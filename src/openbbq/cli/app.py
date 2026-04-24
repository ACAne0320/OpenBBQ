from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from openbbq import __version__
from openbbq.cli.quickstart import DEFAULT_YOUTUBE_QUALITY, write_youtube_subtitle_workflow
from openbbq.config.loader import load_project_config
from openbbq.workflow.diff import diff_artifact_versions
from openbbq.workflow.state import read_effective_workflow_state
from openbbq.domain.base import JsonObject, dump_jsonable, format_pydantic_error
from openbbq.domain.models import ProjectConfig
from openbbq.engine.service import (
    abort_workflow,
    resume_workflow,
    run_workflow,
    unlock_workflow,
)
from openbbq.engine.validation import validate_workflow
from openbbq.errors import OpenBBQError, ValidationError
from openbbq.plugins.registry import PluginRegistry, discover_plugins
from openbbq.runtime.context import build_runtime_context
from openbbq.runtime.doctor import check_workflow
from openbbq.runtime.models import ProviderProfile
from openbbq.runtime.models_assets import faster_whisper_model_status
from openbbq.runtime.secrets import SecretResolver
from openbbq.runtime.settings import (
    load_runtime_settings,
    with_provider_profile,
    write_runtime_settings,
)
from openbbq.storage.models import ArtifactRecord, WorkflowEvent
from openbbq.storage.project_store import ProjectStore

FILE_BACKED_IMPORT_TYPES = frozenset({"audio", "image", "video"})


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    try:
        return _dispatch(args)
    except OpenBBQError as exc:
        _emit_error(exc, json_output=getattr(args, "json_output", False))
        return exc.exit_code


def _build_parser() -> argparse.ArgumentParser:
    global_options = _global_options(defaults=True)
    subcommand_global_options = _global_options(defaults=False)

    parser = argparse.ArgumentParser(prog="openbbq", parents=[global_options])
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", parents=[subcommand_global_options])
    subparsers.add_parser("init", parents=[subcommand_global_options])
    resume = subparsers.add_parser("resume", parents=[subcommand_global_options])
    resume.add_argument("workflow")
    abort = subparsers.add_parser("abort", parents=[subcommand_global_options])
    abort.add_argument("workflow")
    unlock = subparsers.add_parser("unlock", parents=[subcommand_global_options])
    unlock.add_argument("workflow")
    unlock.add_argument("--yes", action="store_true")

    project = subparsers.add_parser("project", parents=[subcommand_global_options])
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_sub.add_parser("list", parents=[subcommand_global_options])
    project_sub.add_parser("info", parents=[subcommand_global_options])

    validate = subparsers.add_parser("validate", parents=[subcommand_global_options])
    validate.add_argument("workflow")

    run = subparsers.add_parser("run", parents=[subcommand_global_options])
    run.add_argument("workflow")
    run.add_argument("--force", action="store_true")
    run.add_argument("--step")

    status = subparsers.add_parser("status", parents=[subcommand_global_options])
    status.add_argument("workflow")

    logs = subparsers.add_parser("logs", parents=[subcommand_global_options])
    logs.add_argument("workflow")

    artifact = subparsers.add_parser("artifact", parents=[subcommand_global_options])
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)
    artifact_list = artifact_sub.add_parser("list", parents=[subcommand_global_options])
    artifact_list.add_argument("--workflow")
    artifact_list.add_argument("--step")
    artifact_list.add_argument("--type", dest="artifact_type")
    artifact_show = artifact_sub.add_parser("show", parents=[subcommand_global_options])
    artifact_show.add_argument("artifact_id")
    artifact_diff = artifact_sub.add_parser("diff", parents=[subcommand_global_options])
    artifact_diff.add_argument("from_version")
    artifact_diff.add_argument("to_version")
    artifact_import = artifact_sub.add_parser("import", parents=[subcommand_global_options])
    artifact_import.add_argument("path")
    artifact_import.add_argument("--type", dest="artifact_type", required=True)
    artifact_import.add_argument("--name", required=True)

    plugin = subparsers.add_parser("plugin", parents=[subcommand_global_options])
    plugin_sub = plugin.add_subparsers(dest="plugin_command", required=True)
    plugin_sub.add_parser("list", parents=[subcommand_global_options])
    plugin_info = plugin_sub.add_parser("info", parents=[subcommand_global_options])
    plugin_info.add_argument("name")

    settings = subparsers.add_parser("settings", parents=[subcommand_global_options])
    settings_sub = settings.add_subparsers(dest="settings_command", required=True)
    settings_sub.add_parser("show", parents=[subcommand_global_options])
    settings_provider = settings_sub.add_parser("set-provider", parents=[subcommand_global_options])
    settings_provider.add_argument("name")
    settings_provider.add_argument("--type", required=True)
    settings_provider.add_argument("--base-url")
    settings_provider.add_argument("--api-key")
    settings_provider.add_argument("--default-chat-model")
    settings_provider.add_argument("--display-name")

    auth = subparsers.add_parser("auth", parents=[subcommand_global_options])
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_set = auth_sub.add_parser("set", parents=[subcommand_global_options])
    auth_set.add_argument("name")
    auth_set.add_argument("--type", default="openai_compatible")
    auth_set.add_argument("--base-url")
    auth_set.add_argument("--api-key-ref")
    auth_set.add_argument("--default-chat-model")
    auth_set.add_argument("--display-name")
    auth_check = auth_sub.add_parser("check", parents=[subcommand_global_options])
    auth_check.add_argument("name")

    secret = subparsers.add_parser("secret", parents=[subcommand_global_options])
    secret_sub = secret.add_subparsers(dest="secret_command", required=True)
    secret_check = secret_sub.add_parser("check", parents=[subcommand_global_options])
    secret_check.add_argument("reference")
    secret_set = secret_sub.add_parser("set", parents=[subcommand_global_options])
    secret_set.add_argument("reference")

    models = subparsers.add_parser("models", parents=[subcommand_global_options])
    models_sub = models.add_subparsers(dest="models_command", required=True)
    models_sub.add_parser("list", parents=[subcommand_global_options])

    doctor = subparsers.add_parser("doctor", parents=[subcommand_global_options])
    doctor.add_argument("--workflow")

    subtitle = subparsers.add_parser("subtitle", parents=[subcommand_global_options])
    subtitle_sub = subtitle.add_subparsers(dest="subtitle_command", required=True)
    subtitle_youtube = subtitle_sub.add_parser("youtube", parents=[subcommand_global_options])
    subtitle_youtube.add_argument("--url", required=True)
    subtitle_youtube.add_argument("--source", required=True)
    subtitle_youtube.add_argument("--target", required=True)
    subtitle_youtube.add_argument("--output", required=True)
    subtitle_youtube.add_argument("--provider", default="openai")
    subtitle_youtube.add_argument("--model")
    subtitle_youtube.add_argument("--asr-model")
    subtitle_youtube.add_argument("--asr-device")
    subtitle_youtube.add_argument("--asr-compute-type")
    subtitle_youtube.add_argument("--quality", default=DEFAULT_YOUTUBE_QUALITY)
    subtitle_youtube.add_argument(
        "--auth",
        choices=("auto", "anonymous", "browser_cookies"),
        default="auto",
    )
    subtitle_youtube.add_argument("--browser")
    subtitle_youtube.add_argument("--browser-profile")
    subtitle_youtube.add_argument("--force", action="store_true")

    return parser


def _global_options(*, defaults: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    if defaults:
        parser.add_argument("--project", default=os.environ.get("OPENBBQ_PROJECT", "."))
        parser.add_argument("--config", default=os.environ.get("OPENBBQ_CONFIG"))
        parser.add_argument("--plugins", action="append", default=[])
        parser.add_argument("--json", action="store_true", dest="json_output")
        parser.add_argument("--verbose", action="store_true")
        parser.add_argument("--debug", action="store_true")
    else:
        parser.add_argument("--project", default=argparse.SUPPRESS)
        parser.add_argument("--config", default=argparse.SUPPRESS)
        parser.add_argument("--plugins", action="append", default=argparse.SUPPRESS)
        parser.add_argument(
            "--json", action="store_true", dest="json_output", default=argparse.SUPPRESS
        )
        parser.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS)
        parser.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    return parser


def _configure_logging(args: argparse.Namespace) -> None:
    logging.getLogger("openbbq").setLevel(_effective_log_level(args))


def _effective_log_level(args: argparse.Namespace) -> int:
    if getattr(args, "debug", False):
        return logging.DEBUG
    env_level = os.environ.get("OPENBBQ_LOG_LEVEL")
    if env_level:
        return getattr(logging, env_level.upper(), logging.WARNING)
    if getattr(args, "verbose", False):
        return logging.INFO
    return logging.WARNING


def _dispatch(args: argparse.Namespace) -> int:
    _configure_logging(args)
    if args.command == "version":
        _emit({"ok": True, "version": __version__}, args.json_output, __version__)
        return 0
    if args.command == "init":
        return _init_project(args)
    if args.command == "resume":
        return _resume(args)
    if args.command == "abort":
        return _abort(args)
    if args.command == "unlock":
        return _unlock(args)
    if args.command == "project":
        if args.project_command == "list":
            return _project_list(args)
        if args.project_command == "info":
            return _project_info(args)
    if args.command == "validate":
        return _validate(args)
    if args.command == "run":
        if args.force and args.step:
            raise OpenBBQError(
                "invalid_command_usage",
                "run --force cannot be combined with --step.",
                2,
            )
        return _run(args)
    if args.command == "status":
        return _status(args)
    if args.command == "logs":
        return _logs(args)
    if args.command == "artifact":
        if args.artifact_command == "diff":
            return _artifact_diff(args)
        if args.artifact_command == "import":
            return _artifact_import(args)
        if args.artifact_command == "list":
            return _artifact_list(args)
        if args.artifact_command == "show":
            return _artifact_show(args)
    if args.command == "plugin":
        if args.plugin_command == "list":
            return _plugin_list(args)
        if args.plugin_command == "info":
            return _plugin_info(args)
    if args.command == "settings":
        if args.settings_command == "show":
            return _settings_show(args)
        if args.settings_command == "set-provider":
            return _settings_set_provider(args)
    if args.command == "auth":
        if args.auth_command == "set":
            return _auth_set(args)
        if args.auth_command == "check":
            return _auth_check(args)
    if args.command == "secret":
        if args.secret_command == "check":
            return _secret_check(args)
        if args.secret_command == "set":
            return _secret_set(args)
    if args.command == "models":
        if args.models_command == "list":
            return _models_list(args)
    if args.command == "doctor":
        return _doctor(args)
    if args.command == "subtitle":
        if args.subtitle_command == "youtube":
            return _subtitle_youtube(args)
    return 2


def _init_project(args: argparse.Namespace) -> int:
    project_root = Path(args.project).expanduser().resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    config_path = (
        Path(args.config).expanduser().resolve() if args.config else project_root / "openbbq.yaml"
    )
    if config_path.exists():
        raise ValidationError(f"Project config already exists: {config_path}", exit_code=1)
    config_path.write_text(
        "version: 1\n\nproject:\n  name: OpenBBQ Project\n\nworkflows: {}\n",
        encoding="utf-8",
    )
    (project_root / ".openbbq" / "artifacts").mkdir(parents=True, exist_ok=True)
    (project_root / ".openbbq" / "state").mkdir(parents=True, exist_ok=True)
    _emit(
        {"ok": True, "config_path": str(config_path)},
        args.json_output,
        f"Initialized {config_path}",
    )
    return 0


def _project_list(args: argparse.Namespace) -> int:
    config = _load_config(args)
    payload = {
        "ok": True,
        "projects": [
            {
                "id": config.project.id,
                "name": config.project.name,
                "root_path": str(config.root_path),
            }
        ],
    }
    _emit(payload, args.json_output, config.project.name)
    return 0


def _project_info(args: argparse.Namespace) -> int:
    config = _load_config(args)
    payload = {
        "ok": True,
        "project": {"id": config.project.id, "name": config.project.name},
        "root_path": str(config.root_path),
        "config_path": str(config.config_path),
        "workflow_count": len(config.workflows),
        "plugin_paths": [str(path) for path in config.plugin_paths],
        "artifact_storage_path": str(config.storage.artifacts),
    }
    _emit(payload, args.json_output, f"{config.project.name}: {len(config.workflows)} workflow(s)")
    return 0


def _validate(args: argparse.Namespace) -> int:
    config, registry = _load_config_and_plugins(args)
    result = validate_workflow(config, registry, args.workflow)
    payload = {"ok": True, "workflow_id": result.workflow_id, "step_count": result.step_count}
    _emit(payload, args.json_output, f"Workflow '{result.workflow_id}' is valid.")
    return 0


def _run(args: argparse.Namespace) -> int:
    config, registry = _load_config_and_plugins(args)
    result = run_workflow(
        config,
        registry,
        args.workflow,
        force=args.force,
        step_id=args.step,
        runtime_context=_runtime_context(),
    )
    payload = {
        "ok": True,
        "workflow_id": result.workflow_id,
        "status": result.status,
        "step_count": result.step_count,
        "artifact_count": result.artifact_count,
    }
    _emit(payload, args.json_output, f"Workflow '{result.workflow_id}' {result.status}.")
    return 0


def _resume(args: argparse.Namespace) -> int:
    config, registry = _load_config_and_plugins(args)
    result = resume_workflow(
        config,
        registry,
        args.workflow,
        runtime_context=_runtime_context(),
    )
    payload = {
        "ok": True,
        "workflow_id": result.workflow_id,
        "status": result.status,
        "step_count": result.step_count,
        "artifact_count": result.artifact_count,
    }
    _emit(payload, args.json_output, f"Workflow '{result.workflow_id}' {result.status}.")
    return 0


def _abort(args: argparse.Namespace) -> int:
    config = _load_config(args)
    result = abort_workflow(config, args.workflow)
    payload = {"ok": True, "workflow_id": args.workflow, "status": result["status"]}
    message = (
        f"Workflow '{args.workflow}' abort requested."
        if result["status"] == "abort_requested"
        else f"Workflow '{args.workflow}' aborted."
    )
    _emit(payload, args.json_output, message)
    return 0


def _unlock(args: argparse.Namespace) -> int:
    if not args.yes:
        if args.json_output:
            raise OpenBBQError(
                "confirmation_required",
                "unlock requires --yes when --json is used.",
                1,
            )
        answer = input(f"Remove stale lock for workflow '{args.workflow}'? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            raise OpenBBQError("unlock_cancelled", "Unlock cancelled.", 1)
    config = _load_config(args)
    result = unlock_workflow(config, args.workflow)
    payload = {"ok": True, **result}
    _emit(
        payload,
        args.json_output,
        f"Unlocked workflow '{args.workflow}' stale lock from PID {result['pid']}.",
    )
    return 0


def _status(args: argparse.Namespace) -> int:
    config = _load_config(args)
    workflow = config.workflows.get(args.workflow)
    if workflow is None:
        raise ValidationError(f"Workflow '{args.workflow}' is not defined.")
    store = _project_store(config)
    state = read_effective_workflow_state(store, workflow)
    payload = {"ok": True, **dump_jsonable(state)}
    _emit(payload, args.json_output, f"{args.workflow}: {state.get('status')}")
    return 0


def _logs(args: argparse.Namespace) -> int:
    config = _load_config(args)
    events = _read_events(_project_store(config), args.workflow)
    payload = {"ok": True, "workflow_id": args.workflow, "events": events}
    _emit(payload, args.json_output, "\n".join(_format_event(event) for event in events))
    return 0


def _artifact_list(args: argparse.Namespace) -> int:
    config = _load_config(args)
    store = _project_store(config)
    artifacts = store.list_artifacts()
    if args.workflow:
        artifacts = [
            artifact
            for artifact in artifacts
            if _artifact_workflow_id(store, artifact) == args.workflow
        ]
    if args.step:
        artifacts = [
            artifact
            for artifact in artifacts
            if artifact.get("created_by_step_id") == args.step
            or artifact.get("name", "").startswith(f"{args.step}.")
        ]
    if args.artifact_type:
        artifacts = [
            artifact for artifact in artifacts if artifact.get("type") == args.artifact_type
        ]
    payload = {"ok": True, "artifacts": artifacts}
    _emit(payload, args.json_output, "\n".join(artifact["id"] for artifact in artifacts))
    return 0


def _artifact_diff(args: argparse.Namespace) -> int:
    config = _load_config(args)
    result = diff_artifact_versions(
        _project_store(config),
        args.from_version,
        args.to_version,
    )
    payload = {"ok": True, **result}
    _emit(payload, args.json_output, result["diff"])
    return 0


def _artifact_import(args: argparse.Namespace) -> int:
    from openbbq.domain.models import ARTIFACT_TYPES

    source = Path(args.path).expanduser().resolve()
    if not source.is_file():
        raise ValidationError(f"Artifact import source is not a file: {source}")
    if args.artifact_type not in ARTIFACT_TYPES:
        raise ValidationError(f"Artifact type '{args.artifact_type}' is not registered.")
    if args.artifact_type not in FILE_BACKED_IMPORT_TYPES:
        allowed = ", ".join(sorted(FILE_BACKED_IMPORT_TYPES))
        raise ValidationError(
            f"Artifact import supports file-backed artifact types only: {allowed}."
        )

    config = _load_config(args)
    artifact, version = _project_store(config).write_artifact_version(
        artifact_type=args.artifact_type,
        name=args.name,
        content=None,
        file_path=source,
        metadata={},
        created_by_step_id=None,
        lineage={"source": "cli_import", "original_path": str(source)},
    )
    payload = {"ok": True, "artifact": artifact.record, "version": version.record}
    _emit(payload, args.json_output, artifact.id)
    return 0


def _artifact_show(args: argparse.Namespace) -> int:
    config = _load_config(args)
    store = _project_store(config)
    artifact = store.read_artifact(args.artifact_id)
    version = store.read_artifact_version(artifact["current_version_id"])
    payload = {
        "ok": True,
        "artifact": artifact,
        "current_version": {
            "record": version.record,
            "content": _jsonable_content(version.content),
        },
    }
    _emit(payload, args.json_output, _jsonable_content(version.content))
    return 0


def _artifact_workflow_id(store: ProjectStore, artifact: ArtifactRecord) -> str | None:
    current_version_id = artifact.get("current_version_id")
    if not isinstance(current_version_id, str):
        return None
    version = store.read_artifact_version(current_version_id)
    workflow_id = version.record.get("lineage", {}).get("workflow_id")
    return workflow_id if isinstance(workflow_id, str) else None


def _latest_workflow_artifact_content(
    store: ProjectStore,
    *,
    workflow_id: str,
    artifact_type: str,
    artifact_name: str,
) -> tuple[ArtifactRecord, Any]:
    matches = []
    for artifact in store.list_artifacts():
        if artifact.get("type") != artifact_type or artifact.get("name") != artifact_name:
            continue
        current_version_id = artifact.get("current_version_id")
        if not isinstance(current_version_id, str):
            continue
        version = store.read_artifact_version(current_version_id)
        if version.record.get("lineage", {}).get("workflow_id") != workflow_id:
            continue
        matches.append((artifact, version))
    if not matches:
        raise OpenBBQError(
            "artifact_not_found",
            f"Workflow '{workflow_id}' did not produce artifact '{artifact_name}'.",
            1,
        )
    matches.sort(key=lambda item: item[0].get("updated_at", ""))
    artifact, version = matches[-1]
    return artifact, version.content


def _default_provider_keyring_reference(name: str) -> str:
    return f"keyring:openbbq/providers/{name}/api_key"


def _plugin_list(args: argparse.Namespace) -> int:
    registry = _load_registry(args)
    plugins = [
        {
            "name": plugin.name,
            "version": plugin.version,
            "runtime": plugin.runtime,
            "manifest_path": str(plugin.manifest_path),
        }
        for plugin in registry.plugins.values()
    ]
    invalid = [
        {"path": str(invalid_plugin.path), "error": invalid_plugin.error}
        for invalid_plugin in registry.invalid_plugins
    ]
    payload = {
        "ok": True,
        "plugins": plugins,
        "invalid_plugins": invalid,
        "warnings": registry.warnings,
    }
    _emit(payload, args.json_output, "\n".join(plugin["name"] for plugin in plugins))
    return 0


def _plugin_info(args: argparse.Namespace) -> int:
    registry = _load_registry(args)
    plugin = registry.plugins.get(args.name)
    if plugin is None:
        raise ValidationError(f"Plugin '{args.name}' was not found.", exit_code=4)
    payload = {
        "ok": True,
        "plugin": {
            "name": plugin.name,
            "version": plugin.version,
            "runtime": plugin.runtime,
            "entrypoint": plugin.entrypoint,
            "manifest_path": str(plugin.manifest_path),
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_artifact_types": tool.input_artifact_types,
                    "output_artifact_types": tool.output_artifact_types,
                    "parameter_schema": tool.parameter_schema,
                    "effects": tool.effects,
                }
                for tool in plugin.tools
            ],
        },
    }
    _emit(payload, args.json_output, plugin.name)
    return 0


def _settings_show(args: argparse.Namespace) -> int:
    settings = load_runtime_settings()
    payload = {"ok": True, "settings": settings.public_dict()}
    _emit(payload, args.json_output, str(settings.config_path))
    return 0


def _settings_set_provider(args: argparse.Namespace) -> int:
    settings = load_runtime_settings()
    try:
        provider = ProviderProfile(
            name=args.name,
            type=args.type,
            base_url=args.base_url,
            api_key=args.api_key,
            default_chat_model=args.default_chat_model,
            display_name=args.display_name,
        )
    except PydanticValidationError as exc:
        raise ValidationError(format_pydantic_error(f"providers.{args.name}", exc)) from exc
    updated = with_provider_profile(settings, provider)
    write_runtime_settings(updated)
    payload = {
        "ok": True,
        "provider": provider.public_dict(),
        "config_path": str(updated.config_path),
    }
    _emit(payload, args.json_output, f"Updated provider '{provider.name}'.")
    return 0


def _auth_set(args: argparse.Namespace) -> int:
    api_key_ref = args.api_key_ref
    stored_secret = False
    if api_key_ref is None:
        api_key_ref = _default_provider_keyring_reference(args.name)
        if args.json_output:
            raise ValidationError("auth set requires --api-key-ref when --json is used.")
        value = getpass.getpass("API key: ")
        SecretResolver().set_secret(api_key_ref, value)
        stored_secret = True

    settings = load_runtime_settings()
    provider = ProviderProfile(
        name=args.name,
        type=args.type,
        base_url=args.base_url,
        api_key=api_key_ref,
        default_chat_model=args.default_chat_model,
        display_name=args.display_name,
    )
    updated = with_provider_profile(settings, provider)
    write_runtime_settings(updated)
    payload = {
        "ok": True,
        "provider": provider.public_dict(),
        "secret_stored": stored_secret,
        "config_path": str(updated.config_path),
    }
    _emit(payload, args.json_output, f"Configured provider '{provider.name}'.")
    return 0


def _auth_check(args: argparse.Namespace) -> int:
    settings = load_runtime_settings()
    provider = settings.providers.get(args.name)
    if provider is None:
        raise ValidationError(f"Provider '{args.name}' is not configured.")
    if provider.api_key is None:
        secret = {
            "reference": None,
            "resolved": False,
            "display": None,
            "value_preview": None,
            "error": f"Provider '{args.name}' does not define an API key reference.",
        }
    else:
        check = SecretResolver().resolve(provider.api_key).public
        secret = {
            "reference": check.reference,
            "resolved": check.resolved,
            "display": check.display,
            "value_preview": check.value_preview,
            "error": check.error,
        }
    payload = {"ok": True, "provider": provider.public_dict(), "secret": secret}
    text = secret["value_preview"] if secret["resolved"] else secret["error"]
    _emit(payload, args.json_output, text)
    return 0


def _secret_check(args: argparse.Namespace) -> int:
    check = SecretResolver().resolve(args.reference).public
    payload = {
        "ok": True,
        "secret": {
            "reference": check.reference,
            "resolved": check.resolved,
            "display": check.display,
            "value_preview": check.value_preview,
            "error": check.error,
        },
    }
    _emit(payload, args.json_output, check.display)
    return 0


def _secret_set(args: argparse.Namespace) -> int:
    if args.json_output:
        raise ValidationError("secret set requires interactive input and cannot run in JSON mode.")
    value = getpass.getpass("Secret value: ")
    SecretResolver().set_secret(args.reference, value)
    _emit({"ok": True, "reference": args.reference}, args.json_output, "Secret stored.")
    return 0


def _models_list(args: argparse.Namespace) -> int:
    settings = load_runtime_settings()
    status = faster_whisper_model_status(settings)
    payload = {"ok": True, "models": [status.public_dict()]}
    _emit(payload, args.json_output, status.public_dict())
    return 0


def _doctor(args: argparse.Namespace) -> int:
    settings = load_runtime_settings()
    if args.workflow:
        config, registry = _load_config_and_plugins(args)
        checks = check_workflow(
            config=config,
            registry=registry,
            workflow_id=args.workflow,
            settings=settings,
        )
    else:
        checks = []
    payload = {
        "ok": all(check.status != "failed" for check in checks),
        "checks": [check.public_dict() for check in checks],
    }
    _emit(payload, args.json_output, "\n".join(check.message for check in checks))
    return 0 if payload["ok"] else 1


def _subtitle_youtube(args: argparse.Namespace) -> int:
    workspace_root = Path(args.project).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    settings = load_runtime_settings()
    faster_whisper = settings.models.faster_whisper
    generated = write_youtube_subtitle_workflow(
        workspace_root=workspace_root,
        url=args.url,
        source_lang=args.source,
        target_lang=args.target,
        provider=args.provider,
        model=args.model,
        asr_model=args.asr_model or faster_whisper.default_model,
        asr_device=args.asr_device or faster_whisper.default_device,
        asr_compute_type=args.asr_compute_type or faster_whisper.default_compute_type,
        quality=args.quality,
        auth=args.auth,
        browser=args.browser,
        browser_profile=args.browser_profile,
    )
    config = load_project_config(
        generated.project_root,
        config_path=generated.config_path,
        extra_plugin_paths=args.plugins,
    )
    registry = discover_plugins(config.plugin_paths)
    store = _project_store(config)
    state = read_effective_workflow_state(store, config.workflows[generated.workflow_id])
    force = state.get("status") == "completed" or (
        args.force and state.get("status") in {"completed", "running"}
    )
    result = run_workflow(
        config,
        registry,
        generated.workflow_id,
        force=force,
        runtime_context=_runtime_context(),
    )
    artifact, content = _latest_workflow_artifact_content(
        store,
        workflow_id=generated.workflow_id,
        artifact_type="subtitle",
        artifact_name="subtitle.subtitle",
    )
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(str(content), encoding="utf-8")
    payload = {
        "ok": True,
        "workflow_id": result.workflow_id,
        "status": result.status,
        "step_count": result.step_count,
        "artifact_count": result.artifact_count,
        "output_path": str(output_path),
        "subtitle_artifact_id": artifact["id"],
        "generated_run_id": generated.run_id,
        "generated_project_root": str(generated.project_root),
        "generated_config_path": str(generated.config_path),
    }
    _emit(payload, args.json_output, f"Wrote {output_path}")
    return 0


def _runtime_context():
    return build_runtime_context(load_runtime_settings())


def _load_config(args: argparse.Namespace):
    return load_project_config(
        Path(args.project),
        config_path=args.config,
        extra_plugin_paths=args.plugins,
    )


def _load_registry(args: argparse.Namespace) -> PluginRegistry:
    config = _load_config(args)
    return discover_plugins(config.plugin_paths)


def _load_config_and_plugins(args: argparse.Namespace):
    config = _load_config(args)
    return config, discover_plugins(config.plugin_paths)


def _project_store(config: ProjectConfig) -> ProjectStore:
    return ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )


def _read_events(store: ProjectStore, workflow_id: str) -> list[WorkflowEvent]:
    events_path = store.state_root / workflow_id / "events.jsonl"
    if not events_path.exists():
        return []
    events: list[WorkflowEvent] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(WorkflowEvent.model_validate(json.loads(line)))
        except (json.JSONDecodeError, PydanticValidationError):
            break
    return events


def _format_event(event: WorkflowEvent) -> str:
    return f"{event.sequence} {event.type} {event.message or ''}".strip()


def _jsonable_content(content: Any) -> Any:
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return content


def _emit(payload: JsonObject, json_output: bool, text: Any) -> None:
    payload = dump_jsonable(payload)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
        return
    if text is not None:
        print(text)


def _emit_error(error: OpenBBQError, json_output: bool) -> None:
    payload = {"ok": False, "error": {"code": error.code, "message": error.message}}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(error.message, file=sys.stderr)

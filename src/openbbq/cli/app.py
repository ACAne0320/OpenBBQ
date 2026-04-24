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
from openbbq.application.artifacts import (
    ArtifactImportRequest,
    diff_artifact_versions as diff_artifact_versions_command,
    import_artifact,
    list_artifacts as list_artifacts_command,
    show_artifact,
)
from openbbq.application.diagnostics import doctor as doctor_command
from openbbq.application.plugins import plugin_info as plugin_info_command
from openbbq.application.plugins import plugin_list as plugin_list_command
from openbbq.application.projects import (
    ProjectInitRequest,
    init_project as init_project_command,
    project_info as project_info_command,
)
from openbbq.application.runtime import (
    AuthSetRequest,
    ProviderSetRequest,
    SecretSetRequest,
    auth_check as auth_check_command,
    auth_set as auth_set_command,
    model_list as model_list_command,
    provider_set as provider_set_command,
    secret_check as secret_check_command,
    secret_set as secret_set_command,
    settings_show as settings_show_command,
)
from openbbq.application.workflows import (
    WorkflowCommandRequest,
    WorkflowRunRequest,
    abort_workflow_command,
    resume_workflow_command,
    run_workflow_command,
    unlock_workflow_command,
    workflow_logs,
    workflow_status,
)
from openbbq.application.quickstart import (
    DEFAULT_YOUTUBE_QUALITY,
    write_local_subtitle_workflow,
    write_youtube_subtitle_workflow,
)
from openbbq.config.loader import load_project_config
from openbbq.domain.base import JsonObject, dump_jsonable
from openbbq.domain.models import ProjectConfig
from openbbq.engine.validation import validate_workflow
from openbbq.errors import OpenBBQError, ValidationError
from openbbq.plugins.registry import PluginRegistry, discover_plugins
from openbbq.runtime.context import build_runtime_context
from openbbq.runtime.settings import load_runtime_settings
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
    subtitle_local = subtitle_sub.add_parser("local", parents=[subcommand_global_options])
    subtitle_local.add_argument("--input", required=True)
    subtitle_local.add_argument("--source", required=True)
    subtitle_local.add_argument("--target", required=True)
    subtitle_local.add_argument("--output", required=True)
    subtitle_local.add_argument("--provider", default="openai")
    subtitle_local.add_argument("--model")
    subtitle_local.add_argument("--asr-model")
    subtitle_local.add_argument("--asr-device")
    subtitle_local.add_argument("--asr-compute-type")
    subtitle_local.add_argument("--force", action="store_true")

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
        if args.subtitle_command == "local":
            return _subtitle_local(args)
        if args.subtitle_command == "youtube":
            return _subtitle_youtube(args)
    return 2


def _init_project(args: argparse.Namespace) -> int:
    result = init_project_command(
        ProjectInitRequest(
            project_root=Path(args.project),
            config_path=Path(args.config) if args.config else None,
        )
    )
    _emit(
        {"ok": True, "config_path": str(result.config_path)},
        args.json_output,
        f"Initialized {result.config_path}",
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
    info = project_info_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
    )
    payload = {
        "ok": True,
        "project": {"id": info.id, "name": info.name},
        "root_path": str(info.root_path),
        "config_path": str(info.config_path),
        "workflow_count": info.workflow_count,
        "plugin_paths": [str(path) for path in info.plugin_paths],
        "artifact_storage_path": str(info.artifact_storage_path),
    }
    _emit(payload, args.json_output, f"{info.name}: {info.workflow_count} workflow(s)")
    return 0


def _validate(args: argparse.Namespace) -> int:
    config, registry = _load_config_and_plugins(args)
    result = validate_workflow(config, registry, args.workflow)
    payload = {"ok": True, "workflow_id": result.workflow_id, "step_count": result.step_count}
    _emit(payload, args.json_output, f"Workflow '{result.workflow_id}' is valid.")
    return 0


def _run(args: argparse.Namespace) -> int:
    result = run_workflow_command(
        WorkflowRunRequest(
            project_root=Path(args.project),
            config_path=Path(args.config) if args.config else None,
            plugin_paths=tuple(Path(path) for path in args.plugins),
            workflow_id=args.workflow,
            force=args.force,
            step_id=args.step,
        )
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
    result = resume_workflow_command(
        WorkflowCommandRequest(
            project_root=Path(args.project),
            config_path=Path(args.config) if args.config else None,
            plugin_paths=tuple(Path(path) for path in args.plugins),
            workflow_id=args.workflow,
        )
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
    result = abort_workflow_command(
        WorkflowCommandRequest(
            project_root=Path(args.project),
            config_path=Path(args.config) if args.config else None,
            plugin_paths=tuple(Path(path) for path in args.plugins),
            workflow_id=args.workflow,
        )
    )
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
    result = unlock_workflow_command(
        WorkflowCommandRequest(
            project_root=Path(args.project),
            config_path=Path(args.config) if args.config else None,
            plugin_paths=tuple(Path(path) for path in args.plugins),
            workflow_id=args.workflow,
        )
    )
    payload = {"ok": True, **result}
    _emit(
        payload,
        args.json_output,
        f"Unlocked workflow '{args.workflow}' stale lock from PID {result['pid']}.",
    )
    return 0


def _status(args: argparse.Namespace) -> int:
    state = workflow_status(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
        workflow_id=args.workflow,
    )
    payload = {"ok": True, **dump_jsonable(state)}
    _emit(payload, args.json_output, f"{args.workflow}: {state.status}")
    return 0


def _logs(args: argparse.Namespace) -> int:
    result = workflow_logs(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
        workflow_id=args.workflow,
    )
    events = list(result.events)
    payload = {"ok": True, "workflow_id": result.workflow_id, "events": events}
    _emit(payload, args.json_output, "\n".join(_format_event(event) for event in events))
    return 0


def _artifact_list(args: argparse.Namespace) -> int:
    artifacts = list_artifacts_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        workflow_id=args.workflow,
        step_id=args.step,
        artifact_type=args.artifact_type,
    )
    payload = {"ok": True, "artifacts": artifacts}
    _emit(payload, args.json_output, "\n".join(artifact.id for artifact in artifacts))
    return 0


def _artifact_diff(args: argparse.Namespace) -> int:
    result = diff_artifact_versions_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        from_version=args.from_version,
        to_version=args.to_version,
    )
    payload = {"ok": True, **result}
    _emit(payload, args.json_output, result["diff"])
    return 0


def _artifact_import(args: argparse.Namespace) -> int:
    result = import_artifact(
        ArtifactImportRequest(
            project_root=Path(args.project),
            config_path=Path(args.config) if args.config else None,
            path=Path(args.path),
            artifact_type=args.artifact_type,
            name=args.name,
        )
    )
    payload = {"ok": True, "artifact": result.artifact, "version": result.version.record}
    _emit(payload, args.json_output, result.artifact.id)
    return 0


def _artifact_show(args: argparse.Namespace) -> int:
    result = show_artifact(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        artifact_id=args.artifact_id,
    )
    payload = {
        "ok": True,
        "artifact": result.artifact,
        "current_version": {
            "record": result.current_version.record,
            "content": _jsonable_content(result.current_version.content),
        },
    }
    _emit(payload, args.json_output, _jsonable_content(result.current_version.content))
    return 0


def _artifact_workflow_id(store: ProjectStore, artifact: ArtifactRecord) -> str | None:
    if artifact.current_version_id is None:
        return None
    version = store.read_artifact_version(artifact.current_version_id)
    workflow_id = version.record.lineage.get("workflow_id")
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
        if artifact.type != artifact_type or artifact.name != artifact_name:
            continue
        if artifact.current_version_id is None:
            continue
        version = store.read_artifact_version(artifact.current_version_id)
        if version.record.lineage.get("workflow_id") != workflow_id:
            continue
        matches.append((artifact, version))
    if not matches:
        raise OpenBBQError(
            "artifact_not_found",
            f"Workflow '{workflow_id}' did not produce artifact '{artifact_name}'.",
            1,
        )
    matches.sort(key=lambda item: item[0].updated_at)
    artifact, version = matches[-1]
    return artifact, version.content


def _plugin_list(args: argparse.Namespace) -> int:
    result = plugin_list_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
    )
    payload = {
        "ok": True,
        "plugins": list(result.plugins),
        "invalid_plugins": list(result.invalid_plugins),
        "warnings": list(result.warnings),
    }
    _emit(payload, args.json_output, "\n".join(plugin["name"] for plugin in result.plugins))
    return 0


def _plugin_info(args: argparse.Namespace) -> int:
    result = plugin_info_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
        plugin_name=args.name,
    )
    payload = {"ok": True, "plugin": result.plugin}
    _emit(payload, args.json_output, result.plugin["name"])
    return 0


def _settings_show(args: argparse.Namespace) -> int:
    result = settings_show_command()
    payload = {"ok": True, "settings": result.settings.public_dict()}
    _emit(payload, args.json_output, str(result.settings.config_path))
    return 0


def _settings_set_provider(args: argparse.Namespace) -> int:
    result = provider_set_command(
        ProviderSetRequest(
            name=args.name,
            type=args.type,
            base_url=args.base_url,
            api_key=args.api_key,
            default_chat_model=args.default_chat_model,
            display_name=args.display_name,
        )
    )
    payload = {
        "ok": True,
        "provider": result.provider.public_dict(),
        "config_path": str(result.config_path),
    }
    _emit(payload, args.json_output, f"Updated provider '{result.provider.name}'.")
    return 0


def _auth_set(args: argparse.Namespace) -> int:
    secret_value = None
    if args.api_key_ref is None:
        if args.json_output:
            raise ValidationError("auth set requires --api-key-ref when --json is used.")
        secret_value = getpass.getpass("API key: ")
    result = auth_set_command(
        AuthSetRequest(
            name=args.name,
            type=args.type,
            base_url=args.base_url,
            api_key_ref=args.api_key_ref,
            secret_value=secret_value,
            default_chat_model=args.default_chat_model,
            display_name=args.display_name,
        )
    )
    payload = {
        "ok": True,
        "provider": result.provider.public_dict(),
        "secret_stored": result.secret_stored,
        "config_path": str(result.config_path),
    }
    _emit(payload, args.json_output, f"Configured provider '{result.provider.name}'.")
    return 0


def _auth_check(args: argparse.Namespace) -> int:
    result = auth_check_command(args.name)
    secret = _secret_payload(result.secret)
    payload = {"ok": True, "provider": result.provider.public_dict(), "secret": secret}
    text = secret["value_preview"] if secret["resolved"] else secret["error"]
    _emit(payload, args.json_output, text)
    return 0


def _secret_check(args: argparse.Namespace) -> int:
    result = secret_check_command(args.reference)
    payload = {"ok": True, "secret": _secret_payload(result.secret)}
    _emit(payload, args.json_output, result.secret.display)
    return 0


def _secret_set(args: argparse.Namespace) -> int:
    if args.json_output:
        raise ValidationError("secret set requires interactive input and cannot run in JSON mode.")
    value = getpass.getpass("Secret value: ")
    secret_set_command(SecretSetRequest(reference=args.reference, value=value))
    _emit({"ok": True, "reference": args.reference}, args.json_output, "Secret stored.")
    return 0


def _models_list(args: argparse.Namespace) -> int:
    result = model_list_command()
    payload = {"ok": True, "models": [model.public_dict() for model in result.models]}
    _emit(payload, args.json_output, result.models[0].public_dict())
    return 0


def _doctor(args: argparse.Namespace) -> int:
    result = doctor_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
        workflow_id=args.workflow,
    )
    payload = {
        "ok": result.ok,
        "checks": [check.public_dict() for check in result.checks],
    }
    _emit(payload, args.json_output, "\n".join(check.message for check in result.checks))
    return 0 if payload["ok"] else 1


def _subtitle_local(args: argparse.Namespace) -> int:
    workspace_root = Path(args.project).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    settings = load_runtime_settings()
    faster_whisper = settings.models.faster_whisper
    generated = write_local_subtitle_workflow(
        workspace_root=workspace_root,
        video_selector="project.art_source_video",
        source_lang=args.source,
        target_lang=args.target,
        provider=args.provider,
        model=args.model,
        asr_model=args.asr_model or faster_whisper.default_model,
        asr_device=args.asr_device or faster_whisper.default_device,
        asr_compute_type=args.asr_compute_type or faster_whisper.default_compute_type,
    )
    imported = import_artifact(
        ArtifactImportRequest(
            project_root=generated.project_root,
            config_path=generated.config_path,
            path=Path(args.input),
            artifact_type="video",
            name="source.video",
        )
    )
    generated = write_local_subtitle_workflow(
        workspace_root=workspace_root,
        video_selector=f"project.{imported.artifact.id}",
        source_lang=args.source,
        target_lang=args.target,
        provider=args.provider,
        model=args.model,
        asr_model=args.asr_model or faster_whisper.default_model,
        asr_device=args.asr_device or faster_whisper.default_device,
        asr_compute_type=args.asr_compute_type or faster_whisper.default_compute_type,
        run_id=generated.run_id,
    )
    config = load_project_config(
        generated.project_root,
        config_path=generated.config_path,
        extra_plugin_paths=args.plugins,
    )
    store = _project_store(config)
    state = workflow_status(
        project_root=generated.project_root,
        config_path=generated.config_path,
        plugin_paths=tuple(Path(path) for path in args.plugins),
        workflow_id=generated.workflow_id,
    )
    force = state.status == "completed" or (args.force and state.status in {"completed", "running"})
    result = run_workflow_command(
        WorkflowRunRequest(
            project_root=generated.project_root,
            config_path=generated.config_path,
            plugin_paths=tuple(Path(path) for path in args.plugins),
            workflow_id=generated.workflow_id,
            force=force,
        )
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
        "source_artifact_id": imported.artifact.id,
        "subtitle_artifact_id": artifact.id,
        "generated_run_id": generated.run_id,
        "generated_project_root": str(generated.project_root),
        "generated_config_path": str(generated.config_path),
    }
    _emit(payload, args.json_output, f"Wrote {output_path}")
    return 0


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
    store = _project_store(config)
    state = workflow_status(
        project_root=generated.project_root,
        config_path=generated.config_path,
        plugin_paths=tuple(Path(path) for path in args.plugins),
        workflow_id=generated.workflow_id,
    )
    force = state.status == "completed" or (args.force and state.status in {"completed", "running"})
    result = run_workflow_command(
        WorkflowRunRequest(
            project_root=generated.project_root,
            config_path=generated.config_path,
            plugin_paths=tuple(Path(path) for path in args.plugins),
            workflow_id=generated.workflow_id,
            force=force,
        )
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
        "subtitle_artifact_id": artifact.id,
        "generated_run_id": generated.run_id,
        "generated_project_root": str(generated.project_root),
        "generated_config_path": str(generated.config_path),
    }
    _emit(payload, args.json_output, f"Wrote {output_path}")
    return 0


def _runtime_context():
    return build_runtime_context(load_runtime_settings())


def _secret_payload(secret) -> dict[str, object]:
    return {
        "reference": secret.reference or None,
        "resolved": secret.resolved,
        "display": secret.display or None,
        "value_preview": secret.value_preview,
        "error": secret.error,
    }


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

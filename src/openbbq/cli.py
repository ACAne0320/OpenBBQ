from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from openbbq import __version__
from openbbq.config import load_project_config
from openbbq.core.workflow.state import read_effective_workflow_state
from openbbq.domain import ProjectConfig
from openbbq.engine import (
    abort_workflow,
    resume_workflow,
    run_workflow,
    unlock_workflow,
    validate_workflow,
)
from openbbq.errors import OpenBBQError, ValidationError
from openbbq.plugins import PluginRegistry, discover_plugins
from openbbq.storage import ProjectStore


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

    plugin = subparsers.add_parser("plugin", parents=[subcommand_global_options])
    plugin_sub = plugin.add_subparsers(dest="plugin_command", required=True)
    plugin_sub.add_parser("list", parents=[subcommand_global_options])
    plugin_info = plugin_sub.add_parser("info", parents=[subcommand_global_options])
    plugin_info.add_argument("name")

    return parser


def _global_options(*, defaults: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    if defaults:
        parser.add_argument("--project", default=".")
        parser.add_argument("--config")
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


def _dispatch(args: argparse.Namespace) -> int:
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
        if args.force or args.step:
            raise _unsupported_slice_2("run --force/--step")
        return _run(args)
    if args.command == "status":
        return _status(args)
    if args.command == "logs":
        return _logs(args)
    if args.command == "artifact":
        if args.artifact_command == "diff":
            raise _unsupported_slice_2("artifact diff")
        if args.artifact_command == "list":
            return _artifact_list(args)
        if args.artifact_command == "show":
            return _artifact_show(args)
    if args.command == "plugin":
        if args.plugin_command == "list":
            return _plugin_list(args)
        if args.plugin_command == "info":
            return _plugin_info(args)
    return 2


def _unsupported_slice_2(feature: str) -> OpenBBQError:
    return OpenBBQError(
        "slice_2_unsupported",
        f"{feature} is not implemented in Slice 2.",
        1,
    )


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
    result = run_workflow(config, registry, args.workflow)
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
    result = resume_workflow(config, registry, args.workflow)
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
    payload = {"ok": True, **state}
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
    artifacts = _project_store(config).list_artifacts()
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


def _read_events(store: ProjectStore, workflow_id: str) -> list[dict[str, Any]]:
    events_path = store.state_root / workflow_id / "events.jsonl"
    if not events_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            break
    return events


def _format_event(event: dict[str, Any]) -> str:
    return f"{event.get('sequence', '?')} {event.get('type', 'event')} {event.get('message', '')}".strip()


def _jsonable_content(content: Any) -> Any:
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return content


def _emit(payload: dict[str, Any], json_output: bool, text: Any) -> None:
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

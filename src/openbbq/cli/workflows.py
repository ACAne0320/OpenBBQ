from __future__ import annotations

import argparse
from pathlib import Path

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
from openbbq.cli.context import load_config_and_plugins
from openbbq.cli.output import emit
from openbbq.engine.validation import validate_workflow
from openbbq.errors import OpenBBQError
from openbbq.storage.models import WorkflowEvent


def register(subparsers, parents) -> None:
    resume = subparsers.add_parser("resume", parents=parents)
    resume.add_argument("workflow")
    abort = subparsers.add_parser("abort", parents=parents)
    abort.add_argument("workflow")
    unlock = subparsers.add_parser("unlock", parents=parents)
    unlock.add_argument("workflow")
    unlock.add_argument("--yes", action="store_true")

    validate = subparsers.add_parser("validate", parents=parents)
    validate.add_argument("workflow")

    run = subparsers.add_parser("run", parents=parents)
    run.add_argument("workflow")
    run.add_argument("--force", action="store_true")
    run.add_argument("--step")

    status = subparsers.add_parser("status", parents=parents)
    status.add_argument("workflow")

    logs = subparsers.add_parser("logs", parents=parents)
    logs.add_argument("workflow")


def dispatch(args: argparse.Namespace) -> int | None:
    if args.command == "resume":
        return _resume(args)
    if args.command == "abort":
        return _abort(args)
    if args.command == "unlock":
        return _unlock(args)
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
    return None


def _validate(args: argparse.Namespace) -> int:
    config, registry = load_config_and_plugins(args)
    result = validate_workflow(config, registry, args.workflow)
    payload = {"ok": True, "workflow_id": result.workflow_id, "step_count": result.step_count}
    emit(payload, args.json_output, f"Workflow '{result.workflow_id}' is valid.")
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
    emit(payload, args.json_output, f"Workflow '{result.workflow_id}' {result.status}.")
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
    emit(payload, args.json_output, f"Workflow '{result.workflow_id}' {result.status}.")
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
    emit(payload, args.json_output, message)
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
    emit(
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
    payload = {"ok": True, **state.model_dump(mode="json")}
    emit(payload, args.json_output, f"{args.workflow}: {state.status}")
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
    emit(payload, args.json_output, "\n".join(_format_event(event) for event in events))
    return 0


def _format_event(event: WorkflowEvent) -> str:
    return f"{event.sequence} {event.type} {event.message or ''}".strip()

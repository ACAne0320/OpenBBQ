from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from pydantic import model_validator

from openbbq.application.workflows import (
    WorkflowCommandRequest,
    WorkflowRunRequest,
    abort_workflow_command,
    resume_workflow_command,
    retry_workflow_checkpoint_command,
    run_workflow_command,
)
from openbbq.application.project_context import load_project_context
from openbbq.domain.base import OpenBBQModel
from openbbq.errors import ExecutionError, OpenBBQError, ValidationError
from openbbq.storage.models import RunErrorRecord, RunRecord
from openbbq.storage.project_store import ProjectStore
from openbbq.storage.runs import list_active_runs, list_runs, read_run, write_run


class RunCreateRequest(OpenBBQModel):
    project_root: Path
    workflow_id: str
    config_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    force: bool = False
    step_id: str | None = None
    created_by: str = "api"

    @model_validator(mode="after")
    def force_without_step_id(self) -> RunCreateRequest:
        if self.force and self.step_id is not None:
            raise ValueError("force cannot be combined with step_id")
        return self


class _RunCommandResult(Protocol):
    status: str


_TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "aborted"})

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="openbbq-run")


def create_run(request: RunCreateRequest, *, execute_inline: bool = False) -> RunRecord:
    context = load_project_context(
        request.project_root,
        config_path=request.config_path,
        plugin_paths=request.plugin_paths,
    )
    workflow = context.config.workflows.get(request.workflow_id)
    if workflow is None:
        raise ValidationError(f"Workflow '{request.workflow_id}' is not defined.")
    store = context.store
    active = list_active_runs(store.state_base, workflow_id=request.workflow_id)
    if active:
        raise ExecutionError(
            f"Workflow '{request.workflow_id}' already has an active run.",
            code="active_run_exists",
            exit_code=1,
        )
    mode = "force_rerun" if request.force else ("step_rerun" if request.step_id else "start")
    run = RunRecord(
        id=_new_run_id(),
        workflow_id=request.workflow_id,
        mode=mode,
        status="queued",
        project_root=request.project_root.expanduser().resolve(),
        config_path=request.config_path,
        plugin_paths=request.plugin_paths,
        latest_event_sequence=store.latest_event_sequence(request.workflow_id),
        created_by=request.created_by,
    )
    write_run(store.state_base, run)
    if execute_inline:
        _execute_run(run.id, request)
    else:
        _EXECUTOR.submit(_execute_run, run.id, request)
    return read_run(store.state_base, run.id)


def get_run(*, project_root: Path, run_id: str, config_path: Path | None = None) -> RunRecord:
    context = load_project_context(project_root, config_path=config_path)
    return read_run(context.store.state_base, run_id)


def list_project_runs(
    *, project_root: Path, config_path: Path | None = None
) -> tuple[RunRecord, ...]:
    context = load_project_context(project_root, config_path=config_path)
    return list_runs(context.store.state_base)


def abort_run(*, project_root: Path, run_id: str, config_path: Path | None = None) -> RunRecord:
    run = get_run(project_root=project_root, run_id=run_id, config_path=config_path)
    abort_workflow_command(
        WorkflowCommandRequest(
            project_root=project_root,
            config_path=run.config_path,
            plugin_paths=run.plugin_paths,
            workflow_id=run.workflow_id,
        )
    )
    return _sync_run_from_workflow_state(project_root=project_root, run_id=run_id, run=run)


def resume_run(
    *,
    project_root: Path,
    run_id: str,
    config_path: Path | None = None,
    execute_inline: bool = True,
) -> RunRecord:
    run = get_run(project_root=project_root, run_id=run_id, config_path=config_path)
    request = RunCreateRequest(
        project_root=project_root,
        config_path=run.config_path,
        plugin_paths=run.plugin_paths,
        workflow_id=run.workflow_id,
        created_by=run.created_by,
    )
    context = load_project_context(project_root, config_path=run.config_path)
    store = context.store
    write_run(
        store.state_base,
        run.model_copy(update={"status": "queued", "completed_at": None, "error": None}),
    )
    if execute_inline:
        _execute_resume(run.id, request)
    else:
        _EXECUTOR.submit(_execute_resume, run.id, request)
    return get_run(project_root=project_root, run_id=run_id, config_path=config_path)


def retry_run_checkpoint(
    *,
    project_root: Path,
    run_id: str,
    config_path: Path | None = None,
    execute_inline: bool = True,
) -> RunRecord:
    run = get_run(project_root=project_root, run_id=run_id, config_path=config_path)
    request = RunCreateRequest(
        project_root=project_root,
        config_path=run.config_path,
        plugin_paths=run.plugin_paths,
        workflow_id=run.workflow_id,
        created_by=run.created_by,
    )
    context = load_project_context(project_root, config_path=run.config_path)
    store = context.store
    write_run(
        store.state_base,
        run.model_copy(update={"status": "queued", "completed_at": None, "error": None}),
    )
    if execute_inline:
        _execute_retry_checkpoint(run.id, request)
    else:
        _EXECUTOR.submit(_execute_retry_checkpoint, run.id, request)
    return get_run(project_root=project_root, run_id=run_id, config_path=config_path)


def _execute_run(run_id: str, request: RunCreateRequest) -> None:
    def command() -> _RunCommandResult:
        return run_workflow_command(
            WorkflowRunRequest(
                project_root=request.project_root,
                config_path=request.config_path,
                plugin_paths=request.plugin_paths,
                workflow_id=request.workflow_id,
                force=request.force,
                step_id=request.step_id,
            )
        )

    _execute_run_lifecycle(run_id, request, command)


def _execute_resume(run_id: str, request: RunCreateRequest) -> None:
    def command() -> _RunCommandResult:
        return resume_workflow_command(
            WorkflowCommandRequest(
                project_root=request.project_root,
                config_path=request.config_path,
                plugin_paths=request.plugin_paths,
                workflow_id=request.workflow_id,
            )
        )

    _execute_run_lifecycle(run_id, request, command, clear_error_on_success=True)


def _execute_retry_checkpoint(run_id: str, request: RunCreateRequest) -> None:
    def command() -> _RunCommandResult:
        return retry_workflow_checkpoint_command(
            WorkflowCommandRequest(
                project_root=request.project_root,
                config_path=request.config_path,
                plugin_paths=request.plugin_paths,
                workflow_id=request.workflow_id,
            )
        )

    _execute_run_lifecycle(run_id, request, command, clear_error_on_success=True)


def _execute_run_lifecycle(
    run_id: str,
    request: RunCreateRequest,
    command: Callable[[], _RunCommandResult],
    *,
    clear_error_on_success: bool = False,
) -> None:
    context = load_project_context(
        request.project_root,
        config_path=request.config_path,
        plugin_paths=request.plugin_paths,
    )
    store = context.store
    run = read_run(store.state_base, run_id)
    write_run(store.state_base, run.model_copy(update={"status": "running", "started_at": _now()}))
    try:
        result = command()
    except OpenBBQError as exc:
        _mark_run_failed(
            store,
            run_id=run_id,
            workflow_id=request.workflow_id,
            code=exc.code,
            message=exc.message,
        )
        return
    except Exception as exc:
        _mark_run_failed(
            store,
            run_id=run_id,
            workflow_id=request.workflow_id,
            code="internal_error",
            message=str(exc),
        )
        return
    update = {
        "status": result.status,
        "completed_at": _now() if result.status in _TERMINAL_RUN_STATUSES else None,
        "latest_event_sequence": store.latest_event_sequence(request.workflow_id),
    }
    if clear_error_on_success:
        update["error"] = None
    completed = read_run(store.state_base, run_id).model_copy(update=update)
    write_run(store.state_base, completed)


def _sync_run_from_workflow_state(*, project_root: Path, run_id: str, run: RunRecord) -> RunRecord:
    from openbbq.application.workflows import workflow_status

    state = workflow_status(
        project_root=project_root,
        config_path=run.config_path,
        plugin_paths=run.plugin_paths,
        workflow_id=run.workflow_id,
    )
    context = load_project_context(project_root, config_path=run.config_path)
    store = context.store
    latest = store.latest_event_sequence(run.workflow_id)
    updated = read_run(store.state_base, run_id).model_copy(
        update={
            "status": state.status,
            "completed_at": _now() if state.status in _TERMINAL_RUN_STATUSES else None,
            "latest_event_sequence": latest,
        }
    )
    return write_run(store.state_base, updated)


def _mark_run_failed(
    store: ProjectStore,
    *,
    run_id: str,
    workflow_id: str,
    code: str,
    message: str,
) -> RunRecord:
    latest = store.latest_event_sequence(workflow_id)
    failed = read_run(store.state_base, run_id).model_copy(
        update={
            "status": "failed",
            "completed_at": _now(),
            "latest_event_sequence": latest,
            "error": RunErrorRecord(code=code, message=message),
        }
    )
    return write_run(store.state_base, failed)


def _new_run_id() -> str:
    return f"run_{uuid4().hex}"


def _now() -> str:
    return datetime.now(UTC).isoformat()

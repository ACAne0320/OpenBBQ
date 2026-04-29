from __future__ import annotations

from openbbq.domain.base import OpenBBQModel
from openbbq.engine.validation import validate_workflow
from openbbq.workflow.aborts import write_abort_request
from openbbq.workflow.execution import (
    execute_workflow_from_resume,
    execute_workflow_from_start,
    execute_workflow_step,
)
from openbbq.workflow.locks import WorkflowLock, unlock_workflow_lock, workflow_lock_path
from openbbq.workflow.rerun import build_artifact_reuse_map, mark_running_step_runs_failed
from openbbq.workflow.state import (
    compute_workflow_config_hash,
    read_effective_workflow_state,
    rebuild_output_bindings,
    require_status,
)
from openbbq.domain.models import ProjectConfig, WorkflowConfig
from openbbq.errors import ExecutionError, ValidationError
from openbbq.plugins.registry import PluginRegistry
from openbbq.runtime.models import RuntimeContext
from openbbq.storage.models import WorkflowState
from openbbq.storage.project_store import ProjectStore


class WorkflowRunResult(OpenBBQModel):
    workflow_id: str
    status: str
    step_count: int
    artifact_count: int


def run_workflow(
    config: ProjectConfig,
    registry: PluginRegistry,
    workflow_id: str,
    *,
    force: bool = False,
    step_id: str | None = None,
    runtime_context: RuntimeContext | None = None,
) -> WorkflowRunResult:
    validate_workflow(config, registry, workflow_id)
    workflow = config.workflows[workflow_id]
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    existing_state = read_effective_workflow_state(store, workflow)
    if force and step_id is not None:
        raise ExecutionError(
            "run --force cannot be combined with run --step.",
            code="invalid_command_usage",
            exit_code=2,
        )
    if step_id is not None:
        result = _run_workflow_step(
            config,
            registry,
            store,
            workflow,
            existing_state,
            step_id,
            runtime_context=runtime_context,
        )
        return WorkflowRunResult(
            workflow_id=result.workflow_id,
            status=result.status,
            step_count=result.step_count,
            artifact_count=result.artifact_count,
        )
    if force:
        result = _force_run_workflow(
            config,
            registry,
            store,
            workflow,
            existing_state,
            runtime_context=runtime_context,
        )
        return WorkflowRunResult(
            workflow_id=result.workflow_id,
            status=result.status,
            step_count=result.step_count,
            artifact_count=result.artifact_count,
        )
    if existing_state.status in {"running", "paused", "completed", "aborted"}:
        raise ExecutionError(
            f"Workflow '{workflow.id}' is {existing_state.status}.",
            code="invalid_workflow_state",
            exit_code=1,
        )

    with WorkflowLock.acquire(store, workflow.id):
        result = execute_workflow_from_start(
            config,
            registry,
            store,
            workflow,
            runtime_context=runtime_context,
        )
    return WorkflowRunResult(
        workflow_id=result.workflow_id,
        status=result.status,
        step_count=result.step_count,
        artifact_count=result.artifact_count,
    )


def _run_workflow_step(
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
    existing_state: WorkflowState,
    step_id: str,
    *,
    runtime_context: RuntimeContext | None = None,
):
    status = existing_state.status
    if status not in {"completed", "failed"}:
        raise ExecutionError(
            f"Workflow '{workflow.id}' is {status}; run --step requires completed or failed.",
            code="invalid_workflow_state",
            exit_code=1,
        )
    if not any(step.id == step_id for step in workflow.steps):
        raise ValidationError(f"Workflow '{workflow.id}' does not define step '{step_id}'.")
    step_run_ids = list(existing_state.step_run_ids)
    with WorkflowLock.acquire(store, workflow.id):
        return execute_workflow_step(
            config=config,
            registry=registry,
            store=store,
            workflow=workflow,
            step_id=step_id,
            step_run_ids=step_run_ids,
            output_bindings=rebuild_output_bindings(store, workflow.id, step_run_ids),
            artifact_reuse=build_artifact_reuse_map(store, workflow.id, step_run_ids),
            runtime_context=runtime_context,
        )


def _force_run_workflow(
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
    existing_state: WorkflowState,
    *,
    runtime_context: RuntimeContext | None = None,
):
    status = existing_state.status
    if status not in {"completed", "running"}:
        raise ExecutionError(
            f"Workflow '{workflow.id}' cannot be force rerun from status {status}.",
            code="invalid_workflow_state",
            exit_code=1,
        )
    step_run_ids = list(existing_state.step_run_ids)
    with WorkflowLock.acquire(store, workflow.id):
        artifact_reuse = build_artifact_reuse_map(store, workflow.id, step_run_ids)
        mark_running_step_runs_failed(store, workflow.id, step_run_ids)
        store.write_workflow_state(
            workflow.id,
            {
                "name": workflow.name,
                "status": "pending",
                "current_step_id": workflow.steps[0].id if workflow.steps else None,
                "config_hash": compute_workflow_config_hash(config, workflow.id),
                "step_run_ids": [],
            },
        )
        return execute_workflow_from_start(
            config,
            registry,
            store,
            workflow,
            artifact_reuse=artifact_reuse,
            runtime_context=runtime_context,
        )


def resume_workflow(
    config: ProjectConfig,
    registry: PluginRegistry,
    workflow_id: str,
    *,
    runtime_context: RuntimeContext | None = None,
) -> WorkflowRunResult:
    validate_workflow(config, registry, workflow_id)
    workflow = config.workflows[workflow_id]
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    state = read_effective_workflow_state(store, workflow)
    require_status(state, "paused", workflow.id)
    current_hash = compute_workflow_config_hash(config, workflow.id)
    if state.config_hash != current_hash:
        raise ValidationError(
            f"Workflow '{workflow.id}' changed while paused; resume is not supported across config edits."
        )
    current_step_id = state.current_step_id
    if not isinstance(current_step_id, str) or not current_step_id:
        raise ExecutionError(
            f"Workflow '{workflow.id}' does not have a resumable step.",
            code="invalid_workflow_state",
            exit_code=1,
        )
    step_run_ids = list(state.step_run_ids)
    with WorkflowLock.acquire(store, workflow.id):
        result = execute_workflow_from_resume(
            config=config,
            registry=registry,
            store=store,
            workflow=workflow,
            current_step_id=current_step_id,
            step_run_ids=step_run_ids,
            output_bindings=rebuild_output_bindings(store, workflow.id, step_run_ids),
            runtime_context=runtime_context,
        )
    return WorkflowRunResult(
        workflow_id=result.workflow_id,
        status=result.status,
        step_count=result.step_count,
        artifact_count=result.artifact_count,
    )


def retry_workflow_checkpoint(
    config: ProjectConfig,
    registry: PluginRegistry,
    workflow_id: str,
    *,
    runtime_context: RuntimeContext | None = None,
) -> WorkflowRunResult:
    validate_workflow(config, registry, workflow_id)
    workflow = config.workflows[workflow_id]
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    state = read_effective_workflow_state(store, workflow)
    require_status(state, "failed", workflow.id)
    current_hash = compute_workflow_config_hash(config, workflow.id)
    if state.config_hash != current_hash:
        raise ValidationError(
            f"Workflow '{workflow.id}' changed after failure; checkpoint retry is not supported across config edits."
        )
    current_step_id = state.current_step_id
    if not isinstance(current_step_id, str) or not current_step_id:
        raise ExecutionError(
            f"Workflow '{workflow.id}' does not have a retryable checkpoint.",
            code="invalid_workflow_state",
            exit_code=1,
        )
    step_run_ids = list(state.step_run_ids)
    with WorkflowLock.acquire(store, workflow.id):
        result = execute_workflow_from_resume(
            config=config,
            registry=registry,
            store=store,
            workflow=workflow,
            current_step_id=current_step_id,
            step_run_ids=step_run_ids,
            output_bindings=rebuild_output_bindings(store, workflow.id, step_run_ids),
            runtime_context=runtime_context,
        )
    return WorkflowRunResult(
        workflow_id=result.workflow_id,
        status=result.status,
        step_count=result.step_count,
        artifact_count=result.artifact_count,
    )


def abort_workflow(config: ProjectConfig, workflow_id: str) -> dict[str, object]:
    workflow = config.workflows.get(workflow_id)
    if workflow is None:
        raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    state = read_effective_workflow_state(store, workflow)
    status = state.status
    if status == "running":
        write_abort_request(store, workflow.id)
        return {"workflow_id": workflow.id, "status": "abort_requested"}
    require_status(state, "paused", workflow.id)
    aborted = store.write_workflow_state(
        workflow.id,
        {
            "name": workflow.name,
            "status": "aborted",
            "current_step_id": state.current_step_id,
            "config_hash": state.config_hash,
            "step_run_ids": list(state.step_run_ids),
        },
    )
    store.append_event(
        workflow.id,
        {"type": "workflow.aborted", "message": f"Workflow '{workflow.id}' aborted."},
    )
    workflow_lock_path(store, workflow.id).unlink(missing_ok=True)
    return aborted.model_dump(mode="json")


def unlock_workflow(config: ProjectConfig, workflow_id: str) -> dict[str, object]:
    workflow = config.workflows.get(workflow_id)
    if workflow is None:
        raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    return unlock_workflow_lock(store, workflow.id)

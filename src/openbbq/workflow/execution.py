from __future__ import annotations

from openbbq.domain.models import ProjectConfig, WorkflowConfig
from openbbq.errors import ExecutionError
from openbbq.plugins.registry import PluginRegistry
from openbbq.runtime.models import RuntimeContext
from openbbq.storage.models import OutputBindings
from openbbq.storage.project_store import ProjectStore
from openbbq.workflow.context import ExecutionContext
from openbbq.workflow.runner import ExecutionResult, run_steps
from openbbq.workflow.state import compute_workflow_config_hash
from openbbq.workflow.transitions import mark_workflow_running


def execute_workflow_from_start(
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
    artifact_reuse: dict[str, str] | None = None,
    runtime_context: RuntimeContext | None = None,
) -> ExecutionResult:
    config_hash = compute_workflow_config_hash(config, workflow.id)
    mark_workflow_running(
        store,
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        current_step_id=workflow.steps[0].id if workflow.steps else None,
        config_hash=config_hash,
        step_run_ids=(),
    )
    store.append_event(
        workflow.id, {"type": "workflow.started", "message": f"Workflow '{workflow.id}' started."}
    )
    return run_steps(
        _context(
            config=config,
            registry=registry,
            store=store,
            workflow=workflow,
            config_hash=config_hash,
            artifact_reuse=artifact_reuse or {},
            runtime_context=runtime_context,
        ),
        start_index=0,
        skip_pause_before_step_id=None,
    )


def execute_workflow_from_resume(
    *,
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
    current_step_id: str,
    step_run_ids: list[str],
    output_bindings: OutputBindings,
    runtime_context: RuntimeContext | None = None,
) -> ExecutionResult:
    start_index = _step_index(workflow, current_step_id)
    config_hash = compute_workflow_config_hash(config, workflow.id)
    mark_workflow_running(
        store,
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        current_step_id=current_step_id,
        config_hash=config_hash,
        step_run_ids=tuple(step_run_ids),
    )
    store.append_event(
        workflow.id,
        {"type": "workflow.resumed", "message": f"Workflow '{workflow.id}' resumed."},
    )
    return run_steps(
        _context(
            config=config,
            registry=registry,
            store=store,
            workflow=workflow,
            config_hash=config_hash,
            step_run_ids=tuple(step_run_ids),
            output_bindings=output_bindings,
            runtime_context=runtime_context,
        ),
        start_index=start_index,
        skip_pause_before_step_id=current_step_id,
    )


def execute_workflow_step(
    *,
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
    step_id: str,
    step_run_ids: list[str],
    output_bindings: OutputBindings,
    artifact_reuse: dict[str, str],
    runtime_context: RuntimeContext | None = None,
) -> ExecutionResult:
    start_index = _step_index(workflow, step_id)
    config_hash = compute_workflow_config_hash(config, workflow.id)
    mark_workflow_running(
        store,
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        current_step_id=step_id,
        config_hash=config_hash,
        step_run_ids=tuple(step_run_ids),
    )
    store.append_event(
        workflow.id,
        {
            "type": "workflow.step_rerun_started",
            "step_id": step_id,
            "message": f"Workflow '{workflow.id}' rerunning step '{step_id}'.",
        },
    )
    return run_steps(
        _context(
            config=config,
            registry=registry,
            store=store,
            workflow=workflow,
            config_hash=config_hash,
            step_run_ids=tuple(step_run_ids),
            output_bindings=output_bindings,
            artifact_reuse=artifact_reuse,
            runtime_context=runtime_context,
        ),
        start_index=start_index,
        end_index=start_index + 1,
        skip_pause_before_step_id=step_id,
    )


def _context(
    *,
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
    config_hash: str,
    step_run_ids: tuple[str, ...] = (),
    output_bindings: OutputBindings | None = None,
    artifact_reuse: dict[str, str] | None = None,
    runtime_context: RuntimeContext | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        config=config,
        registry=registry,
        store=store,
        workflow=workflow,
        config_hash=config_hash,
        runtime_context=runtime_context,
        step_run_ids=step_run_ids,
        output_bindings=output_bindings or {},
        artifact_reuse=artifact_reuse or {},
    )


def _step_index(workflow: WorkflowConfig, step_id: str) -> int:
    for index, step in enumerate(workflow.steps):
        if step.id == step_id:
            return index
    raise ExecutionError(f"Workflow '{workflow.id}' cannot resume unknown step '{step_id}'.")

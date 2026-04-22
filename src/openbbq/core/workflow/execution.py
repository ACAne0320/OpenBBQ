from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from openbbq.core.workflow.aborts import consume_abort_request
from openbbq.core.workflow.bindings import build_plugin_inputs, persist_step_outputs
from openbbq.core.workflow.state import compute_workflow_config_hash
from openbbq.errors import ExecutionError, PluginError, ValidationError
from openbbq.models.workflow import ProjectConfig, WorkflowConfig
from openbbq.plugins import PluginRegistry, execute_plugin_tool
from openbbq.storage import ProjectStore


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    workflow_id: str
    status: str
    step_count: int
    artifact_count: int


def execute_workflow_from_start(
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
    artifact_reuse: dict[str, str] | None = None,
) -> ExecutionResult:
    config_hash = compute_workflow_config_hash(config, workflow.id)
    step_run_ids: list[str] = []
    output_bindings: dict[str, dict[str, Any]] = {}
    store.write_workflow_state(
        workflow.id,
        {
            "name": workflow.name,
            "status": "running",
            "current_step_id": workflow.steps[0].id if workflow.steps else None,
            "config_hash": config_hash,
            "step_run_ids": [],
        },
    )
    store.append_event(
        workflow.id, {"type": "workflow.started", "message": f"Workflow '{workflow.id}' started."}
    )
    return execute_steps(
        config=config,
        registry=registry,
        store=store,
        workflow=workflow,
        start_index=0,
        step_run_ids=step_run_ids,
        output_bindings=output_bindings,
        config_hash=config_hash,
        skip_pause_before_step_id=None,
        artifact_reuse=artifact_reuse or {},
    )


def execute_workflow_from_resume(
    *,
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
    current_step_id: str,
    step_run_ids: list[str],
    output_bindings: dict[str, dict[str, Any]],
) -> ExecutionResult:
    start_index = _step_index(workflow, current_step_id)
    config_hash = compute_workflow_config_hash(config, workflow.id)
    store.write_workflow_state(
        workflow.id,
        {
            "name": workflow.name,
            "status": "running",
            "current_step_id": current_step_id,
            "config_hash": config_hash,
            "step_run_ids": step_run_ids,
        },
    )
    store.append_event(
        workflow.id,
        {"type": "workflow.resumed", "message": f"Workflow '{workflow.id}' resumed."},
    )
    return execute_steps(
        config=config,
        registry=registry,
        store=store,
        workflow=workflow,
        start_index=start_index,
        step_run_ids=step_run_ids,
        output_bindings=output_bindings,
        config_hash=config_hash,
        skip_pause_before_step_id=current_step_id,
        artifact_reuse={},
    )


def execute_steps(
    *,
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
    start_index: int,
    step_run_ids: list[str],
    output_bindings: dict[str, dict[str, Any]],
    config_hash: str,
    skip_pause_before_step_id: str | None = None,
    artifact_reuse: dict[str, str] | None = None,
) -> ExecutionResult:
    for index in range(start_index, len(workflow.steps)):
        step = workflow.steps[index]
        if step.pause_before and step.id != skip_pause_before_step_id:
            store.write_workflow_state(
                workflow.id,
                {
                    "name": workflow.name,
                    "status": "paused",
                    "current_step_id": step.id,
                    "config_hash": config_hash,
                    "step_run_ids": step_run_ids,
                },
            )
            store.append_event(
                workflow.id,
                {
                    "type": "workflow.paused",
                    "step_id": step.id,
                    "message": f"Workflow '{workflow.id}' paused before step '{step.id}'.",
                },
            )
            return ExecutionResult(
                workflow_id=workflow.id,
                status="paused",
                step_count=len(workflow.steps),
                artifact_count=len(output_bindings),
            )

        tool = registry.tools[step.tool_ref]
        plugin = registry.plugins[tool.plugin_name]
        store.append_event(
            workflow.id,
            {
                "type": "step.started",
                "step_id": step.id,
                "message": f"Step '{step.id}' started.",
            },
        )
        plugin_inputs, input_artifact_version_ids = build_plugin_inputs(
            store, step, output_bindings
        )
        step_run = store.write_step_run(
            workflow.id,
            {
                "step_id": step.id,
                "attempt": 1,
                "status": "running",
                "input_artifact_version_ids": input_artifact_version_ids,
                "output_bindings": {},
                "started_at": _timestamp(),
            },
        )
        step_run_ids.append(step_run["id"])
        store.write_workflow_state(
            workflow.id,
            {
                "name": workflow.name,
                "status": "running",
                "current_step_id": step.id,
                "config_hash": config_hash,
                "step_run_ids": step_run_ids,
            },
        )

        request = {
            "project_root": str(config.root_path),
            "workflow_id": workflow.id,
            "step_id": step.id,
            "tool_name": tool.name,
            "parameters": step.parameters,
            "inputs": plugin_inputs,
            "work_dir": str(config.storage.root / "work" / workflow.id / step.id),
        }
        try:
            response = execute_plugin_tool(plugin, tool, request)
            output_bindings_for_step = persist_step_outputs(
                store,
                workflow.id,
                step,
                tool,
                response,
                input_artifact_version_ids,
                artifact_reuse=artifact_reuse,
            )
        except (PluginError, ValidationError) as exc:
            failed = dict(step_run)
            failed["status"] = "failed"
            failed["error"] = {"code": exc.code, "message": exc.message}
            failed["completed_at"] = _timestamp()
            store.write_step_run(workflow.id, failed)
            store.write_workflow_state(
                workflow.id,
                {
                    "name": workflow.name,
                    "status": "failed",
                    "current_step_id": step.id,
                    "config_hash": config_hash,
                    "step_run_ids": step_run_ids,
                },
            )
            store.append_event(
                workflow.id,
                {
                    "type": "step.failed",
                    "step_id": step.id,
                    "message": exc.message,
                },
            )
            raise ExecutionError(exc.message) from exc

        completed = dict(step_run)
        completed["status"] = "completed"
        completed["output_bindings"] = output_bindings_for_step
        completed["completed_at"] = _timestamp()
        store.write_step_run(workflow.id, completed)
        for output_name, binding in output_bindings_for_step.items():
            output_bindings[f"{step.id}.{output_name}"] = binding
        next_step_id = workflow.steps[index + 1].id if index + 1 < len(workflow.steps) else None
        pausing_after = step.pause_after and next_step_id is not None
        store.write_workflow_state(
            workflow.id,
            {
                "name": workflow.name,
                "status": "paused"
                if pausing_after
                else ("running" if next_step_id else "completed"),
                "current_step_id": next_step_id,
                "config_hash": config_hash,
                "step_run_ids": step_run_ids,
            },
        )
        store.append_event(
            workflow.id,
            {
                "type": "step.completed",
                "step_id": step.id,
                "message": f"Step '{step.id}' completed.",
            },
        )
        if next_step_id is not None and consume_abort_request(store, workflow.id):
            store.append_event(
                workflow.id,
                {
                    "type": "workflow.abort_requested",
                    "message": f"Workflow '{workflow.id}' abort requested.",
                },
            )
            store.write_workflow_state(
                workflow.id,
                {
                    "name": workflow.name,
                    "status": "aborted",
                    "current_step_id": next_step_id,
                    "config_hash": config_hash,
                    "step_run_ids": step_run_ids,
                },
            )
            store.append_event(
                workflow.id,
                {"type": "workflow.aborted", "message": f"Workflow '{workflow.id}' aborted."},
            )
            return ExecutionResult(
                workflow_id=workflow.id,
                status="aborted",
                step_count=len(workflow.steps),
                artifact_count=len(output_bindings),
            )
        if pausing_after:
            store.append_event(
                workflow.id,
                {
                    "type": "workflow.paused",
                    "step_id": step.id,
                    "message": f"Workflow '{workflow.id}' paused after step '{step.id}'.",
                },
            )
            return ExecutionResult(
                workflow_id=workflow.id,
                status="paused",
                step_count=len(workflow.steps),
                artifact_count=len(output_bindings),
            )

    store.append_event(
        workflow.id,
        {"type": "workflow.completed", "message": f"Workflow '{workflow.id}' completed."},
    )
    return ExecutionResult(
        workflow_id=workflow.id,
        status="completed",
        step_count=len(workflow.steps),
        artifact_count=len(output_bindings),
    )


def _step_index(workflow: WorkflowConfig, step_id: str) -> int:
    for index, step in enumerate(workflow.steps):
        if step.id == step_id:
            return index
    raise ExecutionError(f"Workflow '{workflow.id}' cannot resume unknown step '{step_id}'.")


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()

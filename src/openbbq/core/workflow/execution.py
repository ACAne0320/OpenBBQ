from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from openbbq.core.workflow.bindings import build_plugin_inputs, persist_step_outputs
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
) -> ExecutionResult:
    step_run_ids: list[str] = []
    output_bindings: dict[str, dict[str, Any]] = {}
    store.write_workflow_state(
        workflow.id,
        {
            "name": workflow.name,
            "status": "running",
            "current_step_id": workflow.steps[0].id if workflow.steps else None,
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
) -> ExecutionResult:
    for index in range(start_index, len(workflow.steps)):
        step = workflow.steps[index]
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
        store.write_workflow_state(
            workflow.id,
            {
                "name": workflow.name,
                "status": "running" if next_step_id else "completed",
                "current_step_id": next_step_id,
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


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()

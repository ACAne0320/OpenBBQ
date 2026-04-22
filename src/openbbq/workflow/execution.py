from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from openbbq.workflow.aborts import consume_abort_request
from openbbq.workflow.bindings import build_plugin_inputs, persist_step_outputs
from openbbq.workflow.state import compute_workflow_config_hash
from openbbq.errors import ExecutionError, PluginError, ValidationError
from openbbq.domain.models import ProjectConfig, WorkflowConfig
from openbbq.plugins.registry import PluginRegistry, execute_plugin_tool
from openbbq.storage.project_store import ProjectStore


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


def execute_workflow_step(
    *,
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
    step_id: str,
    step_run_ids: list[str],
    output_bindings: dict[str, dict[str, Any]],
    artifact_reuse: dict[str, str],
) -> ExecutionResult:
    start_index = _step_index(workflow, step_id)
    config_hash = compute_workflow_config_hash(config, workflow.id)
    store.write_workflow_state(
        workflow.id,
        {
            "name": workflow.name,
            "status": "running",
            "current_step_id": step_id,
            "config_hash": config_hash,
            "step_run_ids": step_run_ids,
        },
    )
    store.append_event(
        workflow.id,
        {
            "type": "workflow.step_rerun_started",
            "step_id": step_id,
            "message": f"Workflow '{workflow.id}' rerunning step '{step_id}'.",
        },
    )
    return execute_steps(
        config=config,
        registry=registry,
        store=store,
        workflow=workflow,
        start_index=start_index,
        end_index=start_index + 1,
        step_run_ids=step_run_ids,
        output_bindings=output_bindings,
        config_hash=config_hash,
        skip_pause_before_step_id=step_id,
        artifact_reuse=artifact_reuse,
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
    end_index: int | None = None,
) -> ExecutionResult:
    final_index = len(workflow.steps) if end_index is None else end_index
    for index in range(start_index, final_index):
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
        attempt = 1
        max_attempts = 1 + (step.max_retries if step.on_error == "retry" else 0)
        output_bindings_for_step: dict[str, dict[str, str]] = {}
        pause_requested = False
        skipped = False
        while True:
            store.append_event(
                workflow.id,
                {
                    "type": "step.started",
                    "step_id": step.id,
                    "attempt": attempt,
                    "message": f"Step '{step.id}' attempt {attempt} started.",
                },
            )
            step_run = store.write_step_run(
                workflow.id,
                {
                    "step_id": step.id,
                    "attempt": attempt,
                    "status": "running",
                    "input_artifact_version_ids": {},
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
            input_artifact_version_ids: dict[str, str] = {}
            try:
                plugin_inputs, input_artifact_version_ids = build_plugin_inputs(
                    store, step, output_bindings
                )
                running = dict(step_run)
                running["input_artifact_version_ids"] = input_artifact_version_ids
                store.write_step_run(workflow.id, running)
                request = {
                    "project_root": str(config.root_path),
                    "workflow_id": workflow.id,
                    "step_id": step.id,
                    "attempt": attempt,
                    "tool_name": tool.name,
                    "parameters": step.parameters,
                    "inputs": plugin_inputs,
                    "work_dir": str(config.storage.root / "work" / workflow.id / step.id),
                }
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
                failed["input_artifact_version_ids"] = input_artifact_version_ids
                failed["error"] = _step_error(
                    exc, step.id, plugin.name, plugin.version, tool.name, attempt
                )
                failed["completed_at"] = _timestamp()
                if step.on_error == "skip":
                    skipped_step = dict(failed)
                    skipped_step["status"] = "skipped"
                    store.write_step_run(workflow.id, skipped_step)
                    store.append_event(
                        workflow.id,
                        {
                            "type": "step.skipped",
                            "step_id": step.id,
                            "attempt": attempt,
                            "message": exc.message,
                        },
                    )
                    skipped = True
                    break
                store.write_step_run(workflow.id, failed)
                store.append_event(
                    workflow.id,
                    {
                        "type": "step.failed",
                        "step_id": step.id,
                        "attempt": attempt,
                        "message": exc.message,
                    },
                )
                if step.on_error == "retry" and attempt < max_attempts:
                    attempt += 1
                    continue
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
                raise ExecutionError(exc.message) from exc

            completed = dict(step_run)
            completed["status"] = "completed"
            completed["input_artifact_version_ids"] = input_artifact_version_ids
            completed["output_bindings"] = output_bindings_for_step
            completed["completed_at"] = _timestamp()
            store.write_step_run(workflow.id, completed)
            pause_requested = response.get("pause_requested") is True
            break

        for output_name, binding in output_bindings_for_step.items():
            output_bindings[f"{step.id}.{output_name}"] = binding
        next_step_id = (
            workflow.steps[index + 1].id
            if index + 1 < len(workflow.steps) and index + 1 < final_index
            else None
        )
        pausing_after = (step.pause_after or pause_requested) and next_step_id is not None
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
        if not skipped:
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


def _step_error(
    error: PluginError | ValidationError,
    step_id: str,
    plugin_name: str,
    plugin_version: str,
    tool_name: str,
    attempt: int,
) -> dict[str, object]:
    return {
        "code": error.code,
        "message": error.message,
        "step_id": step_id,
        "plugin_name": plugin_name,
        "plugin_version": plugin_version,
        "tool_name": tool_name,
        "attempt": attempt,
    }


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()

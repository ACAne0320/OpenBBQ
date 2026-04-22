from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any

from jsonschema import Draft7Validator

from openbbq.domain import ProjectConfig, StepConfig, StepOutput, WorkflowConfig
from openbbq.errors import ExecutionError, PluginError, ValidationError
from openbbq.plugins import PluginRegistry, ToolSpec, execute_plugin_tool
from openbbq.storage import ProjectStore, StoredArtifactVersion

STEP_SELECTOR_PATTERN = re.compile(r"^([a-z0-9_-]+)\.([a-z0-9_-]+)$")


@dataclass(frozen=True, slots=True)
class WorkflowValidationResult:
    workflow_id: str
    step_count: int


@dataclass(frozen=True, slots=True)
class WorkflowRunResult:
    workflow_id: str
    status: str
    step_count: int
    artifact_count: int


def validate_workflow(
    config: ProjectConfig,
    registry: PluginRegistry,
    workflow_id: str,
) -> WorkflowValidationResult:
    workflow = config.workflows.get(workflow_id)
    if workflow is None:
        raise ValidationError(f"Workflow '{workflow_id}' is not defined.")

    step_outputs = _step_outputs_by_id(workflow)
    for step in workflow.steps:
        _validate_slice_1_step_control(step, workflow)
        tool = registry.tools.get(step.tool_ref)
        if tool is None:
            raise ValidationError(f"Step '{step.id}' references unknown tool '{step.tool_ref}'.")
        _validate_parameters(step, tool)
        _validate_step_inputs(step, tool, step_outputs)
        _validate_step_outputs(step, tool)

    return WorkflowValidationResult(workflow_id=workflow.id, step_count=len(workflow.steps))


def run_workflow(
    config: ProjectConfig,
    registry: PluginRegistry,
    workflow_id: str,
) -> WorkflowRunResult:
    validate_workflow(config, registry, workflow_id)
    workflow = config.workflows[workflow_id]
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    existing_state = _read_optional_workflow_state(store, workflow.id)
    if existing_state and existing_state.get("status") == "completed":
        raise ExecutionError(f"Workflow '{workflow.id}' is already completed.")

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

    for index, step in enumerate(workflow.steps):
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
        plugin_inputs, input_artifact_version_ids = _build_plugin_inputs(
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
            output_bindings_for_step = _persist_step_outputs(
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
    return WorkflowRunResult(
        workflow_id=workflow.id,
        status="completed",
        step_count=len(workflow.steps),
        artifact_count=len(output_bindings),
    )


def _validate_slice_1_step_control(step: StepConfig, workflow: WorkflowConfig) -> None:
    if step.pause_before or step.pause_after:
        raise ValidationError(
            f"Step '{step.id}' in workflow '{workflow.id}' uses pause flags, which are not implemented in Slice 1.",
        )
    if step.on_error != "abort" or step.max_retries != 0:
        raise ValidationError(
            f"Step '{step.id}' in workflow '{workflow.id}' uses error recovery that is not implemented in Slice 1.",
        )


def _validate_parameters(step: StepConfig, tool: ToolSpec) -> None:
    validator = Draft7Validator(tool.parameter_schema)
    errors = sorted(validator.iter_errors(step.parameters), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.path)
        location = f"parameters.{path}" if path else "parameters"
        raise ValidationError(
            f"Step '{step.id}' has invalid {location} for tool '{step.tool_ref}': {error.message}",
        )


def _validate_step_inputs(
    step: StepConfig,
    tool: ToolSpec,
    step_outputs: dict[str, dict[str, StepOutput]],
) -> None:
    for input_name, input_value in step.inputs.items():
        selector = _parse_step_selector(input_value)
        if selector is None:
            continue
        selector_step_id, selector_output_name = selector
        output = step_outputs[selector_step_id][selector_output_name]
        if output.type not in tool.input_artifact_types:
            raise ValidationError(
                f"Step '{step.id}' input '{input_name}' references artifact type '{output.type}', "
                f"but tool '{step.tool_ref}' accepts {tool.input_artifact_types}.",
            )


def _validate_step_outputs(step: StepConfig, tool: ToolSpec) -> None:
    allowed_types = set(tool.output_artifact_types)
    for output in step.outputs:
        if output.type not in allowed_types:
            raise ValidationError(
                f"Step '{step.id}' output '{output.name}' has type '{output.type}', "
                f"but tool '{step.tool_ref}' may only produce {tool.output_artifact_types}.",
            )


def _step_outputs_by_id(workflow: WorkflowConfig) -> dict[str, dict[str, StepOutput]]:
    return {step.id: {output.name: output for output in step.outputs} for step in workflow.steps}


def _parse_step_selector(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    match = STEP_SELECTOR_PATTERN.fullmatch(value)
    if match is None or match.group(1) == "project":
        return None
    return match.group(1), match.group(2)


def _build_plugin_inputs(
    store: ProjectStore,
    step: StepConfig,
    output_bindings: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    plugin_inputs: dict[str, dict[str, Any]] = {}
    input_artifact_version_ids: dict[str, str] = {}
    for input_name, input_value in step.inputs.items():
        if isinstance(input_value, str) and input_value.startswith("project."):
            artifact_id = input_value.removeprefix("project.")
            artifact = store.read_artifact(artifact_id)
            version = store.read_artifact_version(artifact["current_version_id"])
            plugin_inputs[input_name] = _artifact_input(artifact, version)
            input_artifact_version_ids[input_value] = version.id
            continue

        selector = _parse_step_selector(input_value)
        if selector is not None:
            binding = output_bindings[input_value]
            artifact = store.read_artifact(binding["artifact_id"])
            version = store.read_artifact_version(binding["artifact_version_id"])
            plugin_inputs[input_name] = _artifact_input(artifact, version)
            input_artifact_version_ids[input_value] = version.id
            continue

        plugin_inputs[input_name] = {"literal": input_value}
    return plugin_inputs, input_artifact_version_ids


def _artifact_input(artifact: dict[str, Any], version: StoredArtifactVersion) -> dict[str, Any]:
    return {
        "artifact_id": artifact["id"],
        "artifact_version_id": version.id,
        "type": artifact["type"],
        "content": version.content,
        "metadata": version.record.get("metadata", {}),
    }


def _persist_step_outputs(
    store: ProjectStore,
    workflow_id: str,
    step: StepConfig,
    tool: ToolSpec,
    response: dict[str, Any],
    input_artifact_version_ids: dict[str, str],
) -> dict[str, dict[str, str]]:
    response_outputs = response.get("outputs")
    if not isinstance(response_outputs, dict):
        raise ValidationError(
            f"Plugin response for step '{step.id}' must include an outputs object."
        )

    bindings: dict[str, dict[str, str]] = {}
    declared_outputs = {output.name: output for output in step.outputs}
    for output_name, output in declared_outputs.items():
        payload = response_outputs.get(output_name)
        if not isinstance(payload, dict):
            raise ValidationError(
                f"Plugin response for step '{step.id}' is missing output '{output_name}'."
            )
        output_type = payload.get("type")
        if output_type != output.type:
            raise ValidationError(
                f"Plugin response for step '{step.id}' output '{output_name}' has type '{output_type}', expected '{output.type}'.",
            )
        if output_type not in tool.output_artifact_types:
            raise ValidationError(
                f"Plugin response for step '{step.id}' output '{output_name}' type '{output_type}' is not allowed.",
            )
        artifact, version = store.write_artifact_version(
            artifact_type=output.type,
            name=f"{step.id}.{output.name}",
            content=payload.get("content"),
            metadata=payload.get("metadata", {}),
            created_by_step_id=step.id,
            lineage={
                "workflow_id": workflow_id,
                "step_id": step.id,
                "tool_ref": step.tool_ref,
                "input_artifact_version_ids": input_artifact_version_ids,
            },
        )
        bindings[output_name] = {
            "artifact_id": artifact.id,
            "artifact_version_id": version.id,
        }
    return bindings


def _read_optional_workflow_state(store: ProjectStore, workflow_id: str) -> dict[str, Any] | None:
    try:
        return store.read_workflow_state(workflow_id)
    except FileNotFoundError:
        return None


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()

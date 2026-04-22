from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft7Validator

from openbbq.core.workflow.bindings import parse_step_selector
from openbbq.core.workflow.execution import execute_workflow_from_start
from openbbq.domain import ProjectConfig, StepConfig, StepOutput, WorkflowConfig
from openbbq.errors import ExecutionError, ValidationError
from openbbq.plugins import PluginRegistry, ToolSpec
from openbbq.storage import ProjectStore


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

    result = execute_workflow_from_start(config, registry, store, workflow)
    return WorkflowRunResult(
        workflow_id=result.workflow_id,
        status=result.status,
        step_count=result.step_count,
        artifact_count=result.artifact_count,
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
        selector = parse_step_selector(input_value)
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


def _read_optional_workflow_state(store: ProjectStore, workflow_id: str) -> dict[str, Any] | None:
    try:
        return store.read_workflow_state(workflow_id)
    except FileNotFoundError:
        return None

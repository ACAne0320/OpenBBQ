from __future__ import annotations

from dataclasses import dataclass

from jsonschema import Draft7Validator

from openbbq.domain.models import ProjectConfig, StepConfig, StepOutput, WorkflowConfig
from openbbq.errors import ValidationError
from openbbq.plugins.registry import PluginRegistry, ToolSpec
from openbbq.workflow.bindings import parse_step_selector


@dataclass(frozen=True, slots=True)
class WorkflowValidationResult:
    workflow_id: str
    step_count: int


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
        _validate_step_control(step, workflow)
        tool = registry.tools.get(step.tool_ref)
        if tool is None:
            raise ValidationError(f"Step '{step.id}' references unknown tool '{step.tool_ref}'.")
        _validate_parameters(step, tool)
        _validate_step_inputs(step, tool, step_outputs)
        _validate_step_outputs(step, tool)

    return WorkflowValidationResult(workflow_id=workflow.id, step_count=len(workflow.steps))


def _validate_step_control(step: StepConfig, workflow: WorkflowConfig) -> None:
    if step.on_error != "retry" and step.max_retries != 0:
        raise ValidationError(
            f"Step '{step.id}' in workflow '{workflow.id}' may only set max_retries with on_error: retry.",
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

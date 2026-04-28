from __future__ import annotations

from openbbq.domain.base import OpenBBQModel
from openbbq.domain.models import StepConfig
from openbbq.errors import PluginError, ValidationError
from openbbq.plugins.payloads import PluginRequest, PluginResponse
from openbbq.plugins.registry import execute_plugin_tool
from openbbq.runtime.redaction import redact_values
from openbbq.storage.models import OutputBindings, StepRunRecord
from openbbq.workflow.bindings import build_plugin_inputs, persist_step_outputs
from openbbq.workflow.context import ExecutionContext
from openbbq.workflow.progress import ProgressReporter
from openbbq.workflow.transitions import mark_step_run_started, mark_workflow_running


class StepAttemptResult(OpenBBQModel):
    step_run: StepRunRecord
    output_bindings: OutputBindings
    input_artifact_version_ids: dict[str, str]
    response: PluginResponse


class StepAttemptExecutionError(Exception):
    def __init__(
        self,
        error: PluginError | ValidationError,
        *,
        step_run: StepRunRecord,
        input_artifact_version_ids: dict[str, str],
    ) -> None:
        super().__init__(error.message)
        self.error = error
        self.step_run = step_run
        self.input_artifact_version_ids = input_artifact_version_ids


def execute_step_attempt(
    context: ExecutionContext,
    *,
    step: StepConfig,
    attempt: int,
) -> StepAttemptResult:
    tool = context.registry.tools[step.tool_ref]
    plugin = context.registry.plugins[tool.plugin_name]
    step_run = mark_step_run_started(
        context.store,
        workflow_id=context.workflow.id,
        step_id=step.id,
        attempt=attempt,
    )
    mark_workflow_running(
        context.store,
        workflow_id=context.workflow.id,
        workflow_name=context.workflow.name,
        current_step_id=step.id,
        config_hash=context.config_hash,
        step_run_ids=(*context.step_run_ids, step_run.id),
    )
    input_artifact_version_ids: dict[str, str] = {}

    def redact_runtime_secrets(message: str) -> str:
        return redact_values(message, context.redaction_values)

    try:
        plugin_inputs, input_artifact_version_ids = build_plugin_inputs(
            context.store, step, context.output_bindings
        )
        running = step_run.model_dump(mode="json")
        running["input_artifact_version_ids"] = input_artifact_version_ids
        step_run = context.store.write_step_run(context.workflow.id, running)
        request = PluginRequest(
            project_root=str(context.config.root_path),
            workflow_id=context.workflow.id,
            step_id=step.id,
            attempt=attempt,
            tool_name=tool.name,
            parameters=step.parameters,
            inputs=plugin_inputs,
            runtime=context.runtime_payload,
            work_dir=str(context.config.storage.root / "work" / context.workflow.id / step.id),
        )
        reporter = ProgressReporter(
            context.store,
            workflow_id=context.workflow.id,
            step_id=step.id,
            attempt=attempt,
        )
        raw_response = execute_plugin_tool(
            plugin,
            tool,
            request,
            redactor=redact_runtime_secrets,
            progress=reporter.report,
        )
        response = (
            raw_response
            if isinstance(raw_response, PluginResponse)
            else PluginResponse.model_validate(raw_response)
        )
        output_bindings = persist_step_outputs(
            context.store,
            context.workflow.id,
            step,
            tool,
            response,
            input_artifact_version_ids,
            artifact_reuse=context.artifact_reuse,
        )
    except (PluginError, ValidationError) as exc:
        raise StepAttemptExecutionError(
            exc,
            step_run=step_run,
            input_artifact_version_ids=input_artifact_version_ids,
        ) from exc

    return StepAttemptResult(
        step_run=step_run,
        output_bindings=output_bindings,
        input_artifact_version_ids=input_artifact_version_ids,
        response=response,
    )

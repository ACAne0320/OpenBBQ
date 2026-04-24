from __future__ import annotations

from openbbq.domain.base import OpenBBQModel
from openbbq.errors import ExecutionError, PluginError, ValidationError
from openbbq.runtime.redaction import redact_values
from openbbq.storage.models import OutputBindings
from openbbq.workflow.aborts import consume_abort_request
from openbbq.workflow.context import ExecutionContext
from openbbq.workflow.events import append_plugin_events
from openbbq.workflow.steps import StepAttemptExecutionError, execute_step_attempt
from openbbq.workflow.transitions import mark_step_run_completed, mark_step_run_failed


class ExecutionResult(OpenBBQModel):
    workflow_id: str
    status: str
    step_count: int
    artifact_count: int


def run_steps(
    context: ExecutionContext,
    *,
    start_index: int,
    end_index: int | None = None,
    skip_pause_before_step_id: str | None = None,
) -> ExecutionResult:
    workflow = context.workflow
    store = context.store
    final_index = len(workflow.steps) if end_index is None else end_index
    step_run_ids = list(context.step_run_ids)
    output_bindings: OutputBindings = dict(context.output_bindings)

    for index in range(start_index, final_index):
        step = workflow.steps[index]
        if step.pause_before and step.id != skip_pause_before_step_id:
            store.write_workflow_state(
                workflow.id,
                {
                    "name": workflow.name,
                    "status": "paused",
                    "current_step_id": step.id,
                    "config_hash": context.config_hash,
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
            return _result(context, "paused", output_bindings)

        tool = context.registry.tools[step.tool_ref]
        plugin = context.registry.plugins[tool.plugin_name]
        attempt = 1
        max_attempts = 1 + (step.max_retries if step.on_error == "retry" else 0)
        output_bindings_for_step: OutputBindings = {}
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
            attempt_context = context.model_copy(
                update={
                    "step_run_ids": tuple(step_run_ids),
                    "output_bindings": output_bindings,
                }
            )
            try:
                attempt_result = execute_step_attempt(
                    attempt_context,
                    step=step,
                    attempt=attempt,
                )
            except StepAttemptExecutionError as exc:
                step_run_ids.append(exc.step_run.id)
                redacted_message = redact_values(
                    exc.error.message,
                    context.redaction_values,
                )
                error = _step_error(
                    exc.error,
                    step.id,
                    plugin.name,
                    plugin.version,
                    tool.name,
                    attempt,
                    message=redacted_message,
                )
                if step.on_error == "skip":
                    mark_step_run_failed(
                        store,
                        workflow_id=workflow.id,
                        step_run=exc.step_run,
                        input_artifact_version_ids=exc.input_artifact_version_ids,
                        error=error,
                        status="skipped",
                    )
                    store.append_event(
                        workflow.id,
                        {
                            "type": "step.skipped",
                            "step_id": step.id,
                            "attempt": attempt,
                            "message": redacted_message,
                        },
                    )
                    skipped = True
                    break

                mark_step_run_failed(
                    store,
                    workflow_id=workflow.id,
                    step_run=exc.step_run,
                    input_artifact_version_ids=exc.input_artifact_version_ids,
                    error=error,
                )
                store.append_event(
                    workflow.id,
                    {
                        "type": "step.failed",
                        "step_id": step.id,
                        "attempt": attempt,
                        "message": redacted_message,
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
                        "config_hash": context.config_hash,
                        "step_run_ids": step_run_ids,
                    },
                )
                raise ExecutionError(redacted_message) from exc.error

            step_run_ids.append(attempt_result.step_run.id)
            mark_step_run_completed(
                store,
                workflow_id=workflow.id,
                step_run=attempt_result.step_run,
                input_artifact_version_ids=attempt_result.input_artifact_version_ids,
                output_bindings=attempt_result.output_bindings,
            )
            append_plugin_events(
                store,
                workflow.id,
                step.id,
                attempt,
                attempt_result.response,
                redaction_values=tuple(context.redaction_values),
            )
            output_bindings_for_step = attempt_result.output_bindings
            pause_requested = attempt_result.response.pause_requested is True
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
                "config_hash": context.config_hash,
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
                    "config_hash": context.config_hash,
                    "step_run_ids": step_run_ids,
                },
            )
            store.append_event(
                workflow.id,
                {"type": "workflow.aborted", "message": f"Workflow '{workflow.id}' aborted."},
            )
            return _result(context, "aborted", output_bindings)
        if pausing_after:
            store.append_event(
                workflow.id,
                {
                    "type": "workflow.paused",
                    "step_id": step.id,
                    "message": f"Workflow '{workflow.id}' paused after step '{step.id}'.",
                },
            )
            return _result(context, "paused", output_bindings)

    store.append_event(
        workflow.id,
        {"type": "workflow.completed", "message": f"Workflow '{workflow.id}' completed."},
    )
    return _result(context, "completed", output_bindings)


def _result(
    context: ExecutionContext,
    status: str,
    output_bindings: OutputBindings,
) -> ExecutionResult:
    return ExecutionResult(
        workflow_id=context.workflow.id,
        status=status,
        step_count=len(context.workflow.steps),
        artifact_count=len(output_bindings),
    )


def _step_error(
    error: PluginError | ValidationError,
    step_id: str,
    plugin_name: str,
    plugin_version: str,
    tool_name: str,
    attempt: int,
    *,
    message: str | None = None,
) -> dict[str, object]:
    return {
        "code": error.code,
        "message": error.message if message is None else message,
        "step_id": step_id,
        "plugin_name": plugin_name,
        "plugin_version": plugin_version,
        "tool_name": tool_name,
        "attempt": attempt,
    }

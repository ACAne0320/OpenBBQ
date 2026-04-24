from __future__ import annotations

from openbbq.domain.base import JsonObject
from openbbq.plugins.payloads import PluginEventPayload, PluginResponse
from openbbq.runtime.redaction import redact_values
from openbbq.storage.models import WorkflowEvent
from openbbq.storage.project_store import ProjectStore


def append_workflow_event(
    store: ProjectStore,
    workflow_id: str,
    event_type: str,
    *,
    message: str | None = None,
    level: str = "info",
    step_id: str | None = None,
    attempt: int | None = None,
    data: JsonObject | None = None,
) -> WorkflowEvent:
    return store.append_event(
        workflow_id,
        {
            "type": event_type,
            "level": level,
            "message": message,
            "step_id": step_id,
            "attempt": attempt,
            "data": data or {},
        },
    )


def append_plugin_events(
    store: ProjectStore,
    workflow_id: str,
    step_id: str,
    attempt: int,
    response: PluginResponse,
    *,
    redaction_values: tuple[str, ...] = (),
) -> None:
    for event in response.events:
        append_plugin_event(
            store,
            workflow_id,
            step_id,
            attempt,
            event,
            redaction_values=redaction_values,
        )


def append_plugin_event(
    store: ProjectStore,
    workflow_id: str,
    step_id: str,
    attempt: int,
    event: PluginEventPayload,
    *,
    redaction_values: tuple[str, ...] = (),
) -> None:
    append_workflow_event(
        store,
        workflow_id,
        "plugin.event",
        level=event.level,
        step_id=step_id,
        attempt=attempt,
        message=redact_values(event.message, redaction_values),
        data=event.data,
    )

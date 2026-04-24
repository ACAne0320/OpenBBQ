from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import Request
from fastapi.responses import StreamingResponse

from openbbq.api.schemas import EventStreamItem
from openbbq.application.workflows import workflow_events
from openbbq.storage.models import WorkflowEvent


def format_sse(event: WorkflowEvent) -> str:
    item = EventStreamItem(event=event)
    return f"id: {event.sequence}\nevent: {event.type}\ndata: {item.model_dump_json()}\n\n"


async def event_stream(
    *,
    request: Request,
    project_root,
    workflow_id: str,
    after_sequence: int,
    config_path=None,
    plugin_paths=(),
    poll_interval_seconds: float = 0.25,
) -> AsyncIterator[str]:
    last_sequence = after_sequence
    while True:
        result = workflow_events(
            project_root=project_root,
            config_path=config_path,
            plugin_paths=plugin_paths,
            workflow_id=workflow_id,
            after_sequence=last_sequence,
        )
        for event in result.events:
            last_sequence = event.sequence
            yield format_sse(event)
        if await request.is_disconnected():
            return
        yield ": heartbeat\n\n"
        await asyncio.sleep(poll_interval_seconds)


def streaming_response(iterator: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(iterator, media_type="text/event-stream")

from __future__ import annotations

from openbbq.domain.base import JsonObject
from openbbq.storage.clock import TimestampProvider, utc_timestamp
from openbbq.storage.database import ProjectDatabase
from openbbq.storage.id_generation import WorkflowEventIdGenerator
from openbbq.storage.models import WorkflowEvent


class EventRepository:
    def __init__(
        self,
        database: ProjectDatabase,
        *,
        id_generator: WorkflowEventIdGenerator,
        timestamp_provider: TimestampProvider = utc_timestamp,
    ) -> None:
        self.database = database
        self.id_generator = id_generator
        self.timestamp_provider = timestamp_provider

    def append_event(self, workflow_id: str, event: JsonObject) -> WorkflowEvent:
        return self.database.append_event(
            workflow_id,
            event,
            generated_id=self.id_generator.workflow_event_id(),
            timestamp=self.timestamp_provider(),
        )

    def read_events(
        self, workflow_id: str, *, after_sequence: int = 0
    ) -> tuple[WorkflowEvent, ...]:
        return self.database.read_events(workflow_id, after_sequence=after_sequence)

    def latest_sequence(self, workflow_id: str) -> int:
        return self.database.latest_event_sequence(workflow_id)

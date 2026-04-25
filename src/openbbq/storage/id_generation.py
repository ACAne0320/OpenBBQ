from __future__ import annotations

from typing import Protocol
from uuid import uuid4


class WorkflowEventIdGenerator(Protocol):
    def workflow_event_id(self) -> str: ...


class StepRunIdGenerator(Protocol):
    def step_run_id(self) -> str: ...


class ArtifactIdGenerator(Protocol):
    def artifact_id(self) -> str: ...

    def artifact_version_id(self) -> str: ...


class IdGenerator:
    def artifact_id(self) -> str:
        return f"art_{uuid4().hex}"

    def artifact_version_id(self) -> str:
        return f"av_{uuid4().hex}"

    def step_run_id(self) -> str:
        return f"sr_{uuid4().hex}"

    def workflow_event_id(self) -> str:
        return f"evt_{uuid4().hex}"

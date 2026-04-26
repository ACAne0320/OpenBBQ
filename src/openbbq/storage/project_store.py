from __future__ import annotations

from pathlib import Path
from typing import Any

from openbbq.domain.base import ArtifactMetadata, JsonObject, LineagePayload
from openbbq.storage.artifact_repository import ArtifactRepository
from openbbq.storage.clock import utc_timestamp
from openbbq.storage.database import ProjectDatabase
from openbbq.storage.event_repository import EventRepository
from openbbq.storage.id_generation import IdGenerator
from openbbq.storage.json_files import write_json_atomic
from openbbq.storage.models import (
    ArtifactRecord,
    ArtifactVersionRecord,
    StoredArtifact,
    StoredArtifactVersion,
    StepRunRecord,
    WorkflowEvent,
    WorkflowState,
)
from openbbq.storage.workflow_repository import WorkflowRepository


class ProjectStore:
    def __init__(
        self,
        root: Path,
        id_generator: IdGenerator | None = None,
        artifacts_root: Path | None = None,
        state_root: Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.id_generator = id_generator or IdGenerator()
        self.artifacts_root = (
            Path(artifacts_root) if artifacts_root is not None else self.root / "artifacts"
        )
        self.state_base = Path(state_root) if state_root is not None else self.root / "state"
        self.state_root = self.state_base / "workflows"
        self.database = ProjectDatabase(self.root / "openbbq.db")
        self.workflow_repository = WorkflowRepository(
            self.database,
            id_generator=self.id_generator,
        )
        self.event_repository = EventRepository(
            self.database,
            id_generator=self.id_generator,
            timestamp_provider=utc_timestamp,
        )
        self.artifact_repository = ArtifactRepository(
            self.database,
            artifacts_root=self.artifacts_root,
            id_generator=self.id_generator,
            timestamp_provider=utc_timestamp,
        )
        self.state_root.mkdir(parents=True, exist_ok=True)

    def write_json_atomic(self, path: Path, data: JsonObject) -> None:
        write_json_atomic(path, data)

    def append_event(self, workflow_id: str, event: JsonObject) -> WorkflowEvent:
        return self.event_repository.append_event(workflow_id, event)

    def read_events(
        self, workflow_id: str, *, after_sequence: int = 0
    ) -> tuple[WorkflowEvent, ...]:
        return self.event_repository.read_events(workflow_id, after_sequence=after_sequence)

    def latest_event_sequence(self, workflow_id: str) -> int:
        return self.event_repository.latest_sequence(workflow_id)

    def write_workflow_state(
        self, workflow_id: str, state: JsonObject | WorkflowState
    ) -> WorkflowState:
        return self.workflow_repository.write_workflow_state(workflow_id, state)

    def read_workflow_state(self, workflow_id: str) -> WorkflowState:
        return self.workflow_repository.read_workflow_state(workflow_id)

    def write_step_run(
        self, workflow_id: str, step_run: JsonObject | StepRunRecord
    ) -> StepRunRecord:
        return self.workflow_repository.write_step_run(workflow_id, step_run)

    def read_step_run(self, workflow_id: str, step_run_id: str) -> StepRunRecord:
        return self.workflow_repository.read_step_run(workflow_id, step_run_id)

    def list_artifacts(self) -> list[ArtifactRecord]:
        return self.artifact_repository.list_artifacts()

    def read_artifact(self, artifact_id: str) -> ArtifactRecord:
        return self.artifact_repository.read_artifact(artifact_id)

    def read_artifact_version(self, version_id: str) -> StoredArtifactVersion:
        return self.artifact_repository.read_artifact_version(version_id)

    def read_artifact_version_record(self, version_id: str) -> ArtifactVersionRecord:
        return self.artifact_repository.read_artifact_version_record(version_id)

    def write_artifact_version(
        self,
        *,
        artifact_type: str,
        name: str,
        content: Any = None,
        file_path: Path | None = None,
        metadata: ArtifactMetadata,
        created_by_step_id: str | None,
        lineage: LineagePayload,
        artifact_id: str | None = None,
    ) -> tuple[StoredArtifact, StoredArtifactVersion]:
        return self.artifact_repository.write_artifact_version(
            artifact_type=artifact_type,
            name=name,
            content=content,
            file_path=file_path,
            metadata=metadata,
            created_by_step_id=created_by_step_id,
            lineage=lineage,
            artifact_id=artifact_id,
        )

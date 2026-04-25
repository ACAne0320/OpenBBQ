from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from openbbq.domain.base import JsonObject
from openbbq.storage.database_records import (
    dump_json,
    dump_nullable_json,
    model_from_optional_row,
    model_from_row,
    record_payload,
    upsert_row,
)
from openbbq.storage.migration_runner import run_schema_migrations, sqlite_database_url
from openbbq.storage.models import (
    ArtifactRecord,
    ArtifactVersionRecord,
    RunRecord,
    StepRunRecord,
    WorkflowEvent,
    WorkflowState,
)
from openbbq.storage.orm import (
    ArtifactRow,
    ArtifactVersionRow,
    RunRow,
    StepRunRow,
    WorkflowEventRow,
    WorkflowStateRow,
)


def create_sqlite_engine(path: Path) -> Engine:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        sqlite_database_url(path),
        future=True,
    )


def project_database_path_from_state_base(state_base: Path) -> Path:
    return Path(state_base).parent / "openbbq.db"


class ProjectDatabase:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.engine = create_sqlite_engine(self.path)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, future=True)
        self.initialize()

    def initialize(self) -> None:
        run_schema_migrations(self.path, "project")

    def write_run(self, run: RunRecord) -> RunRecord:
        payload = record_payload(run)
        with self._session() as session:
            row = upsert_row(session, RunRow, run.id)
            row.workflow_id = run.workflow_id
            row.mode = run.mode
            row.status = run.status
            row.project_root = str(run.project_root)
            row.config_path = str(run.config_path) if run.config_path is not None else None
            row.plugin_paths_json = dump_json(payload["plugin_paths"])
            row.started_at = run.started_at
            row.completed_at = run.completed_at
            row.latest_event_sequence = run.latest_event_sequence
            row.error_json = dump_nullable_json(payload.get("error"))
            row.created_by = run.created_by
            row.record_json = dump_json(payload)
        return run

    def read_run(self, run_id: str) -> RunRecord | None:
        with self._session() as session:
            row = session.get(RunRow, run_id)
            return model_from_optional_row(RunRecord, row)

    def list_runs(self) -> tuple[RunRecord, ...]:
        with self._session() as session:
            rows = session.scalars(select(RunRow).order_by(RunRow.started_at, RunRow.id)).all()
            return tuple(model_from_row(RunRecord, row) for row in rows)

    def write_workflow_state(self, state: WorkflowState) -> WorkflowState:
        payload = record_payload(state)
        with self._session() as session:
            row = upsert_row(session, WorkflowStateRow, state.id)
            row.name = state.name
            row.status = state.status
            row.current_step_id = state.current_step_id
            row.config_hash = state.config_hash
            row.step_run_ids_json = dump_json(payload["step_run_ids"])
            row.record_json = dump_json(payload)
        return state

    def read_workflow_state(self, workflow_id: str) -> WorkflowState | None:
        with self._session() as session:
            row = session.get(WorkflowStateRow, workflow_id)
            return model_from_optional_row(WorkflowState, row)

    def write_step_run(self, step_run: StepRunRecord) -> StepRunRecord:
        payload = record_payload(step_run)
        with self._session() as session:
            row = upsert_row(session, StepRunRow, step_run.id)
            row.workflow_id = step_run.workflow_id
            row.step_id = step_run.step_id
            row.attempt = step_run.attempt
            row.status = step_run.status
            row.input_artifact_version_ids_json = dump_json(payload["input_artifact_version_ids"])
            row.output_bindings_json = dump_json(payload["output_bindings"])
            row.started_at = step_run.started_at
            row.completed_at = step_run.completed_at
            row.error_json = dump_nullable_json(payload.get("error"))
            row.record_json = dump_json(payload)
        return step_run

    def read_step_run(self, workflow_id: str, step_run_id: str) -> StepRunRecord | None:
        with self._session() as session:
            row = session.scalar(
                select(StepRunRow).where(
                    StepRunRow.workflow_id == workflow_id,
                    StepRunRow.id == step_run_id,
                )
            )
            return model_from_optional_row(StepRunRecord, row)

    def append_event(
        self,
        workflow_id: str,
        event: JsonObject,
        *,
        generated_id: str,
        timestamp: str,
    ) -> WorkflowEvent:
        with self._session() as session:
            sequence = (
                session.scalar(
                    select(func.max(WorkflowEventRow.sequence)).where(
                        WorkflowEventRow.workflow_id == workflow_id
                    )
                )
                or 0
            ) + 1
            payload = dict(event)
            payload["workflow_id"] = workflow_id
            payload["sequence"] = sequence
            payload.setdefault("id", generated_id)
            payload.setdefault("created_at", timestamp)
            typed = WorkflowEvent.model_validate(payload)
            self._write_event_in_session(session, typed)
            return typed

    def write_event(self, event: WorkflowEvent) -> WorkflowEvent:
        with self._session() as session:
            self._write_event_in_session(session, event)
        return event

    def read_events(self, workflow_id: str, after_sequence: int = 0) -> tuple[WorkflowEvent, ...]:
        with self._session() as session:
            rows = session.scalars(
                select(WorkflowEventRow)
                .where(
                    WorkflowEventRow.workflow_id == workflow_id,
                    WorkflowEventRow.sequence > after_sequence,
                )
                .order_by(WorkflowEventRow.sequence)
            ).all()
            return tuple(model_from_row(WorkflowEvent, row) for row in rows)

    def latest_event_sequence(self, workflow_id: str) -> int:
        with self._session() as session:
            return (
                session.scalar(
                    select(func.max(WorkflowEventRow.sequence)).where(
                        WorkflowEventRow.workflow_id == workflow_id
                    )
                )
                or 0
            )

    def write_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        payload = record_payload(artifact)
        with self._session() as session:
            row = upsert_row(session, ArtifactRow, artifact.id)
            row.type = artifact.type
            row.name = artifact.name
            row.versions_json = dump_json(payload["versions"])
            row.current_version_id = artifact.current_version_id
            row.created_by_step_id = artifact.created_by_step_id
            row.created_at = artifact.created_at
            row.updated_at = artifact.updated_at
            row.record_json = dump_json(payload)
        return artifact

    def read_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        with self._session() as session:
            row = session.get(ArtifactRow, artifact_id)
            return model_from_optional_row(ArtifactRecord, row)

    def list_artifacts(self) -> tuple[ArtifactRecord, ...]:
        with self._session() as session:
            rows = session.scalars(
                select(ArtifactRow).order_by(ArtifactRow.created_at, ArtifactRow.id)
            ).all()
            return tuple(model_from_row(ArtifactRecord, row) for row in rows)

    def write_artifact_version(self, version: ArtifactVersionRecord) -> ArtifactVersionRecord:
        payload = record_payload(version)
        with self._session() as session:
            row = upsert_row(session, ArtifactVersionRow, version.id)
            row.artifact_id = version.artifact_id
            row.version_number = version.version_number
            row.content_path = str(version.content_path)
            row.content_hash = version.content_hash
            row.content_encoding = version.content_encoding
            row.content_size = version.content_size
            row.metadata_json = dump_json(payload["metadata"])
            row.lineage_json = dump_json(payload["lineage"])
            row.created_at = version.created_at
            row.record_json = dump_json(payload)
        return version

    def read_artifact_version(self, version_id: str) -> ArtifactVersionRecord | None:
        with self._session() as session:
            row = session.get(ArtifactVersionRow, version_id)
            return model_from_optional_row(ArtifactVersionRecord, row)

    def list_artifact_versions(
        self, artifact_id: str | None = None
    ) -> tuple[ArtifactVersionRecord, ...]:
        statement = select(ArtifactVersionRow).order_by(
            ArtifactVersionRow.artifact_id,
            ArtifactVersionRow.version_number,
            ArtifactVersionRow.id,
        )
        if artifact_id is not None:
            statement = statement.where(ArtifactVersionRow.artifact_id == artifact_id)
        with self._session() as session:
            rows = session.scalars(statement).all()
            return tuple(model_from_row(ArtifactVersionRecord, row) for row in rows)

    def _write_event_in_session(self, session: Session, event: WorkflowEvent) -> None:
        payload = record_payload(event)
        row = upsert_row(session, WorkflowEventRow, event.id)
        row.workflow_id = event.workflow_id
        row.sequence = event.sequence
        row.type = event.type
        row.level = event.level
        row.message = event.message
        row.data_json = dump_json(payload["data"])
        row.created_at = event.created_at
        row.step_id = event.step_id
        row.attempt = event.attempt
        row.record_json = dump_json(payload)

    def _session(self) -> AbstractContextManager[Session]:
        return self.session_factory.begin()

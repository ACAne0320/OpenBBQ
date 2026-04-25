from __future__ import annotations

from contextlib import AbstractContextManager
import json
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from openbbq.domain.base import JsonObject
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

RecordT = TypeVar("RecordT")


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
        payload = run.model_dump(mode="json")
        with self._session() as session:
            row = session.get(RunRow, run.id)
            if row is None:
                row = RunRow(id=run.id)
                session.add(row)
            row.workflow_id = run.workflow_id
            row.mode = run.mode
            row.status = run.status
            row.project_root = str(run.project_root)
            row.config_path = str(run.config_path) if run.config_path is not None else None
            row.plugin_paths_json = _json(payload["plugin_paths"])
            row.started_at = run.started_at
            row.completed_at = run.completed_at
            row.latest_event_sequence = run.latest_event_sequence
            row.error_json = _nullable_json(payload.get("error"))
            row.created_by = run.created_by
            row.record_json = _json(payload)
        return run

    def read_run(self, run_id: str) -> RunRecord | None:
        with self._session() as session:
            row = session.get(RunRow, run_id)
            return _model_or_none(RunRecord, row)

    def list_runs(self) -> tuple[RunRecord, ...]:
        with self._session() as session:
            rows = session.scalars(
                select(RunRow).order_by(RunRow.started_at, RunRow.id)
            ).all()
            return tuple(_model(RunRecord, row) for row in rows)

    def write_workflow_state(self, state: WorkflowState) -> WorkflowState:
        payload = state.model_dump(mode="json")
        with self._session() as session:
            row = session.get(WorkflowStateRow, state.id)
            if row is None:
                row = WorkflowStateRow(id=state.id)
                session.add(row)
            row.name = state.name
            row.status = state.status
            row.current_step_id = state.current_step_id
            row.config_hash = state.config_hash
            row.step_run_ids_json = _json(payload["step_run_ids"])
            row.record_json = _json(payload)
        return state

    def read_workflow_state(self, workflow_id: str) -> WorkflowState | None:
        with self._session() as session:
            row = session.get(WorkflowStateRow, workflow_id)
            return _model_or_none(WorkflowState, row)

    def write_step_run(self, step_run: StepRunRecord) -> StepRunRecord:
        payload = step_run.model_dump(mode="json")
        with self._session() as session:
            row = session.get(StepRunRow, step_run.id)
            if row is None:
                row = StepRunRow(id=step_run.id)
                session.add(row)
            row.workflow_id = step_run.workflow_id
            row.step_id = step_run.step_id
            row.attempt = step_run.attempt
            row.status = step_run.status
            row.input_artifact_version_ids_json = _json(
                payload["input_artifact_version_ids"]
            )
            row.output_bindings_json = _json(payload["output_bindings"])
            row.started_at = step_run.started_at
            row.completed_at = step_run.completed_at
            row.error_json = _nullable_json(payload.get("error"))
            row.record_json = _json(payload)
        return step_run

    def read_step_run(self, workflow_id: str, step_run_id: str) -> StepRunRecord | None:
        with self._session() as session:
            row = session.scalar(
                select(StepRunRow).where(
                    StepRunRow.workflow_id == workflow_id,
                    StepRunRow.id == step_run_id,
                )
            )
            return _model_or_none(StepRunRecord, row)

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

    def read_events(
        self, workflow_id: str, after_sequence: int = 0
    ) -> tuple[WorkflowEvent, ...]:
        with self._session() as session:
            rows = session.scalars(
                select(WorkflowEventRow)
                .where(
                    WorkflowEventRow.workflow_id == workflow_id,
                    WorkflowEventRow.sequence > after_sequence,
                )
                .order_by(WorkflowEventRow.sequence)
            ).all()
            return tuple(_model(WorkflowEvent, row) for row in rows)

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
        payload = artifact.model_dump(mode="json")
        with self._session() as session:
            row = session.get(ArtifactRow, artifact.id)
            if row is None:
                row = ArtifactRow(id=artifact.id)
                session.add(row)
            row.type = artifact.type
            row.name = artifact.name
            row.versions_json = _json(payload["versions"])
            row.current_version_id = artifact.current_version_id
            row.created_by_step_id = artifact.created_by_step_id
            row.created_at = artifact.created_at
            row.updated_at = artifact.updated_at
            row.record_json = _json(payload)
        return artifact

    def read_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        with self._session() as session:
            row = session.get(ArtifactRow, artifact_id)
            return _model_or_none(ArtifactRecord, row)

    def list_artifacts(self) -> tuple[ArtifactRecord, ...]:
        with self._session() as session:
            rows = session.scalars(
                select(ArtifactRow).order_by(ArtifactRow.created_at, ArtifactRow.id)
            ).all()
            return tuple(_model(ArtifactRecord, row) for row in rows)

    def write_artifact_version(
        self, version: ArtifactVersionRecord
    ) -> ArtifactVersionRecord:
        payload = version.model_dump(mode="json")
        with self._session() as session:
            row = session.get(ArtifactVersionRow, version.id)
            if row is None:
                row = ArtifactVersionRow(id=version.id)
                session.add(row)
            row.artifact_id = version.artifact_id
            row.version_number = version.version_number
            row.content_path = str(version.content_path)
            row.content_hash = version.content_hash
            row.content_encoding = version.content_encoding
            row.content_size = version.content_size
            row.metadata_json = _json(payload["metadata"])
            row.lineage_json = _json(payload["lineage"])
            row.created_at = version.created_at
            row.record_json = _json(payload)
        return version

    def read_artifact_version(self, version_id: str) -> ArtifactVersionRecord | None:
        with self._session() as session:
            row = session.get(ArtifactVersionRow, version_id)
            return _model_or_none(ArtifactVersionRecord, row)

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
            return tuple(_model(ArtifactVersionRecord, row) for row in rows)

    def _write_event_in_session(self, session: Session, event: WorkflowEvent) -> None:
        payload = event.model_dump(mode="json")
        row = session.get(WorkflowEventRow, event.id)
        if row is None:
            row = WorkflowEventRow(id=event.id)
            session.add(row)
        row.workflow_id = event.workflow_id
        row.sequence = event.sequence
        row.type = event.type
        row.level = event.level
        row.message = event.message
        row.data_json = _json(payload["data"])
        row.created_at = event.created_at
        row.step_id = event.step_id
        row.attempt = event.attempt
        row.record_json = _json(payload)

    def _session(self) -> AbstractContextManager[Session]:
        return self.session_factory.begin()


def _model(model: type[RecordT], row: Any) -> RecordT:
    return model.model_validate(json.loads(row.record_json))  # type: ignore[attr-defined]


def _model_or_none(model: type[RecordT], row: Any | None) -> RecordT | None:
    if row is None:
        return None
    return _model(model, row)


def _nullable_json(value: Any) -> str | None:
    if value is None:
        return None
    return _json(value)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

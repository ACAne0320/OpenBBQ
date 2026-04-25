from __future__ import annotations

from sqlalchemy import Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ProjectBase(DeclarativeBase):
    pass


class UserBase(DeclarativeBase):
    pass


class RunRow(ProjectBase):
    __tablename__ = "runs"
    __table_args__ = (Index("idx_runs_workflow_status", "workflow_id", "status"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    project_root: Mapped[str] = mapped_column(Text, nullable=False)
    config_path: Mapped[str | None] = mapped_column(Text)
    plugin_paths_json: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[str | None] = mapped_column(Text)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_json: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    record_json: Mapped[str] = mapped_column(Text, nullable=False)


class WorkflowStateRow(ProjectBase):
    __tablename__ = "workflow_states"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    current_step_id: Mapped[str | None] = mapped_column(Text)
    config_hash: Mapped[str | None] = mapped_column(Text)
    step_run_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    record_json: Mapped[str] = mapped_column(Text, nullable=False)


class StepRunRow(ProjectBase):
    __tablename__ = "step_runs"
    __table_args__ = (Index("idx_step_runs_workflow", "workflow_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    step_id: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    input_artifact_version_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    output_bindings_json: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[str | None] = mapped_column(Text)
    error_json: Mapped[str | None] = mapped_column(Text)
    record_json: Mapped[str] = mapped_column(Text, nullable=False)


class WorkflowEventRow(ProjectBase):
    __tablename__ = "workflow_events"
    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence", name="uq_workflow_events_workflow_sequence"),
        Index("idx_workflow_events_workflow_sequence", "workflow_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    step_id: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int | None] = mapped_column(Integer)
    record_json: Mapped[str] = mapped_column(Text, nullable=False)


class ArtifactRow(ProjectBase):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    versions_json: Mapped[str] = mapped_column(Text, nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(Text)
    created_by_step_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    record_json: Mapped[str] = mapped_column(Text, nullable=False)


class ArtifactVersionRow(ProjectBase):
    __tablename__ = "artifact_versions"
    __table_args__ = (Index("idx_artifact_versions_artifact", "artifact_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    artifact_id: Mapped[str] = mapped_column(Text, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    content_encoding: Mapped[str] = mapped_column(Text, nullable=False)
    content_size: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    lineage_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    record_json: Mapped[str] = mapped_column(Text, nullable=False)


class UserProviderRow(UserBase):
    __tablename__ = "providers"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    api_key: Mapped[str | None] = mapped_column(Text)
    default_chat_model: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)


class UserCredentialRow(UserBase):
    __tablename__ = "credentials"

    reference: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

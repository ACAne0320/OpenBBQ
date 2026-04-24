from __future__ import annotations

from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import Field

from openbbq.domain.base import (
    ArtifactMetadata,
    JsonObject,
    JsonValue,
    LineagePayload,
    OpenBBQModel,
)

WorkflowStatus: TypeAlias = Literal[
    "pending", "running", "paused", "completed", "failed", "aborted"
]
StepRunStatus: TypeAlias = Literal["running", "completed", "failed", "skipped"]
WorkflowEventLevel: TypeAlias = Literal["debug", "info", "warning", "error"]
RunStatus: TypeAlias = Literal["queued", "running", "paused", "completed", "failed", "aborted"]
RunMode: TypeAlias = Literal["start", "resume", "step_rerun", "force_rerun"]
RunCreator: TypeAlias = Literal["api", "cli", "desktop"]
ArtifactContent: TypeAlias = JsonValue | bytes


class RecordModel(OpenBBQModel):
    pass


class OutputBinding(RecordModel):
    artifact_id: str
    artifact_version_id: str


OutputBindings: TypeAlias = dict[str, OutputBinding]


class StepErrorRecord(RecordModel):
    code: str
    message: str
    step_id: str | None = None
    plugin_name: str | None = None
    plugin_version: str | None = None
    tool_name: str | None = None
    attempt: int | None = None


class WorkflowState(RecordModel):
    id: str
    name: str | None = None
    status: WorkflowStatus
    current_step_id: str | None = None
    config_hash: str | None = None
    step_run_ids: tuple[str, ...] = ()


class StepRunRecord(RecordModel):
    id: str
    workflow_id: str
    step_id: str | None = None
    attempt: int | None = None
    status: StepRunStatus
    input_artifact_version_ids: dict[str, str] = Field(default_factory=dict)
    output_bindings: OutputBindings = Field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None
    error: StepErrorRecord | None = None


class WorkflowEvent(RecordModel):
    id: str
    workflow_id: str
    sequence: int
    type: str
    level: WorkflowEventLevel = "info"
    message: str | None = None
    data: JsonObject = Field(default_factory=dict)
    created_at: str
    step_id: str | None = None
    attempt: int | None = None


class RunErrorRecord(RecordModel):
    code: str
    message: str


class RunRecord(RecordModel):
    id: str
    workflow_id: str
    mode: RunMode
    status: RunStatus
    project_root: Path
    config_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    started_at: str | None = None
    completed_at: str | None = None
    latest_event_sequence: int = 0
    error: RunErrorRecord | None = None
    created_by: RunCreator = "api"


class ArtifactRecord(RecordModel):
    id: str
    type: str
    name: str
    versions: tuple[str, ...] = ()
    current_version_id: str | None = None
    created_by_step_id: str | None = None
    created_at: str
    updated_at: str


class ArtifactVersionRecord(RecordModel):
    id: str
    artifact_id: str
    version_number: int
    content_path: Path
    content_hash: str
    content_encoding: Literal["text", "json", "bytes", "file"]
    content_size: int
    metadata: ArtifactMetadata = Field(default_factory=dict)
    lineage: LineagePayload = Field(default_factory=dict)
    created_at: str


class StoredArtifact(OpenBBQModel):
    record: ArtifactRecord

    @property
    def id(self) -> str:
        return self.record.id


class StoredArtifactVersion(OpenBBQModel):
    record: ArtifactVersionRecord
    content: ArtifactContent | JsonObject

    @property
    def id(self) -> str:
        return self.record.id

    @property
    def artifact_id(self) -> str:
        return self.record.artifact_id


class AbortRequest(RecordModel):
    workflow_id: str
    pid: int
    requested_at: str


class WorkflowLockInfo(OpenBBQModel):
    path: Path
    workflow_id: str
    pid: int | None
    created_at: str | None
    stale: bool

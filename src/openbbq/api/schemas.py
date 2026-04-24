from __future__ import annotations

from pathlib import Path
from typing import Generic, Literal, TypeAlias, TypeVar

from pydantic import Field, model_validator

from openbbq.domain.base import JsonObject, JsonValue, OpenBBQModel
from openbbq.runtime.models import DoctorCheck, ModelAssetStatus, ProviderProfile, RuntimeSettings
from openbbq.storage.models import (
    ArtifactRecord,
    ArtifactVersionRecord,
    WorkflowEvent,
    WorkflowState,
)

T = TypeVar("T")

RunMode: TypeAlias = Literal["start", "resume", "step_rerun", "force_rerun"]
RunStatus: TypeAlias = Literal["queued", "running", "paused", "completed", "failed", "aborted"]
RunCreator: TypeAlias = Literal["api", "cli", "desktop"]


class ApiSuccess(OpenBBQModel, Generic[T]):
    ok: Literal[True] = True
    data: T


class ApiError(OpenBBQModel):
    code: str
    message: str
    details: JsonObject = Field(default_factory=dict)


class ApiErrorResponse(OpenBBQModel):
    ok: Literal[False] = False
    error: ApiError


class HealthData(OpenBBQModel):
    version: str
    pid: int
    project_root: Path | None = None


class ProjectInfoData(OpenBBQModel):
    id: str | None
    name: str
    root_path: Path
    config_path: Path
    workflow_count: int
    plugin_paths: tuple[Path, ...]
    artifact_storage_path: Path
    state_storage_path: Path


class WorkflowStepSummary(OpenBBQModel):
    id: str
    name: str
    tool_ref: str
    outputs: tuple[JsonObject, ...]


class WorkflowSummary(OpenBBQModel):
    id: str
    name: str
    steps: tuple[WorkflowStepSummary, ...]
    state: WorkflowState
    latest_event_sequence: int


class RunCreateRequest(OpenBBQModel):
    project_root: Path
    workflow_id: str
    config_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    force: bool = False
    step_id: str | None = None
    created_by: RunCreator = "api"

    @model_validator(mode="after")
    def force_without_step_id(self) -> RunCreateRequest:
        if self.force and self.step_id is not None:
            raise ValueError("force cannot be combined with step_id")
        return self


class RunError(OpenBBQModel):
    code: str
    message: str


class RunRecord(OpenBBQModel):
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
    error: RunError | None = None
    created_by: RunCreator = "api"


class ArtifactVersionData(OpenBBQModel):
    record: ArtifactVersionRecord
    content: JsonValue | bytes


class ArtifactShowData(OpenBBQModel):
    artifact: ArtifactRecord
    current_version: ArtifactVersionData


class PluginListData(OpenBBQModel):
    plugins: tuple[JsonObject, ...]
    invalid_plugins: tuple[JsonObject, ...]
    warnings: tuple[str, ...]


class RuntimeSettingsData(OpenBBQModel):
    settings: RuntimeSettings


class ProviderData(OpenBBQModel):
    provider: ProviderProfile
    config_path: Path


class ModelListData(OpenBBQModel):
    models: tuple[ModelAssetStatus, ...]


class DoctorData(OpenBBQModel):
    ok: bool
    checks: tuple[DoctorCheck, ...]


class EventStreamItem(OpenBBQModel):
    event: WorkflowEvent

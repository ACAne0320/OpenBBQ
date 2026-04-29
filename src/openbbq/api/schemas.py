from __future__ import annotations

from pathlib import Path
from typing import Generic, Literal, TypeAlias, TypeVar

from pydantic import Field, model_validator

from openbbq.domain.base import JsonObject, JsonValue, OpenBBQModel
from openbbq.domain.models import StepOutput
from openbbq.engine.validation import WorkflowValidationResult
from openbbq.runtime.models import (
    DoctorCheck,
    ModelAssetStatus,
    ModelDownloadJob,
    ProviderModel,
    ProviderProfile,
    RuntimeSettings,
)
from openbbq.storage.models import (
    ArtifactRecord,
    ArtifactVersionRecord,
    QuickstartTaskRecord,
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


class ProjectInitRequest(OpenBBQModel):
    project_root: Path
    config_path: Path | None = None


class ProjectInitData(OpenBBQModel):
    config_path: Path


class WorkflowStepSummary(OpenBBQModel):
    id: str
    name: str
    tool_ref: str
    outputs: tuple[StepOutput, ...]


class WorkflowSummary(OpenBBQModel):
    id: str
    name: str
    steps: tuple[WorkflowStepSummary, ...]
    state: WorkflowState
    latest_event_sequence: int


class WorkflowListData(OpenBBQModel):
    workflows: tuple[WorkflowSummary, ...]


class WorkflowDetailData(OpenBBQModel):
    id: str
    name: str
    steps: tuple[WorkflowStepSummary, ...]
    state: WorkflowState
    latest_event_sequence: int
    validation: WorkflowValidationResult | None = None


class WorkflowEventsData(OpenBBQModel):
    workflow_id: str
    events: tuple[WorkflowEvent, ...]


class RunCreateRequest(OpenBBQModel):
    project_root: Path | None = None
    workflow_id: str | None = None
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


class RunListData(OpenBBQModel):
    runs: tuple[RunRecord, ...]


class QuickstartTaskListData(OpenBBQModel):
    tasks: tuple[QuickstartTaskRecord, ...]


class WorkflowTextParameterData(OpenBBQModel):
    kind: Literal["text"]
    key: str
    label: str
    value: str


class WorkflowSelectParameterData(OpenBBQModel):
    kind: Literal["select"]
    key: str
    label: str
    value: str
    options: tuple[str, ...]


class WorkflowToggleParameterData(OpenBBQModel):
    kind: Literal["toggle"]
    key: str
    label: str
    description: str
    value: bool


WorkflowParameterData: TypeAlias = (
    WorkflowTextParameterData | WorkflowSelectParameterData | WorkflowToggleParameterData
)


class SubtitleWorkflowStepData(OpenBBQModel):
    id: str
    name: str
    tool_ref: str
    summary: str
    status: Literal["locked", "enabled", "disabled"]
    selected: bool | None = None
    inputs: dict[str, str] | None = None
    outputs: tuple[StepOutput, ...] | None = None
    parameters: tuple[WorkflowParameterData, ...]


class SubtitleWorkflowTemplateData(OpenBBQModel):
    template_id: str
    workflow_id: str
    steps: tuple[SubtitleWorkflowStepData, ...]


class WorkflowToolInputData(OpenBBQModel):
    artifact_types: tuple[str, ...]
    required: bool
    multiple: bool


class SubtitleWorkflowToolData(OpenBBQModel):
    tool_ref: str
    name: str
    description: str
    inputs: dict[str, WorkflowToolInputData]
    outputs: tuple[StepOutput, ...]
    parameters: tuple[WorkflowParameterData, ...]


class SubtitleWorkflowToolCatalogData(OpenBBQModel):
    tools: tuple[SubtitleWorkflowToolData, ...]


class SubtitleExtraStepRequest(OpenBBQModel):
    id: str
    name: str
    tool_ref: str
    inputs: dict[str, str]
    outputs: tuple[StepOutput, ...]
    parameters: JsonObject = Field(default_factory=dict)


class ArtifactVersionData(OpenBBQModel):
    record: ArtifactVersionRecord
    content: JsonValue | bytes


class ArtifactShowData(OpenBBQModel):
    artifact: ArtifactRecord
    current_version: ArtifactVersionData


class ArtifactListData(OpenBBQModel):
    artifacts: tuple[ArtifactRecord, ...]


class ArtifactImportData(OpenBBQModel):
    artifact: ArtifactRecord
    version: ArtifactVersionRecord


class ArtifactDiffData(OpenBBQModel):
    from_version: str = Field(alias="from")
    to: str
    format: str
    diff: str


class ArtifactPreviewData(OpenBBQModel):
    version: ArtifactVersionRecord
    content: JsonValue | None
    truncated: bool
    content_encoding: str
    content_size: int


class ArtifactExportRequest(OpenBBQModel):
    path: Path
    config_path: Path | None = None


class ArtifactExportData(OpenBBQModel):
    version_id: str
    path: Path
    bytes_written: int


class ArtifactImportRequest(OpenBBQModel):
    path: Path
    artifact_type: str
    name: str
    config_path: Path | None = None


class PluginListData(OpenBBQModel):
    plugins: tuple[JsonObject, ...]
    invalid_plugins: tuple[JsonObject, ...]
    warnings: tuple[str, ...]


class RuntimeSettingsData(OpenBBQModel):
    settings: RuntimeSettings


class RuntimeDefaultsSetRequest(OpenBBQModel):
    llm_provider: str
    asr_provider: str = "faster-whisper"


class RuntimeSettingsSetData(OpenBBQModel):
    settings: RuntimeSettings
    config_path: Path


class ProviderData(OpenBBQModel):
    provider: ProviderProfile
    config_path: Path


class FasterWhisperSettingsSetRequest(OpenBBQModel):
    cache_dir: Path
    default_model: str
    default_device: str
    default_compute_type: str
    enabled: bool = True


class FasterWhisperDownloadRequest(OpenBBQModel):
    model: str


class ProviderAuthSetRequest(OpenBBQModel):
    type: str = "openai_compatible"
    base_url: str | None = None
    api_key_ref: str | None = None
    secret_value: str | None = None
    default_chat_model: str | None = None
    display_name: str | None = None
    enabled: bool = True


class ProviderSecretValueData(OpenBBQModel):
    value: str


class ProviderConnectionTestRequest(OpenBBQModel):
    provider_name: str | None = None
    base_url: str
    api_key: str | None = None
    model: str


class ProviderConnectionTestData(OpenBBQModel):
    ok: bool
    message: str


class SecretCheckRequest(OpenBBQModel):
    reference: str


class SecretSetRequest(OpenBBQModel):
    reference: str
    value: str


class ModelListData(OpenBBQModel):
    models: tuple[ModelAssetStatus, ...]


class ProviderModelListData(OpenBBQModel):
    models: tuple[ProviderModel, ...]


class FasterWhisperDownloadData(OpenBBQModel):
    job: ModelDownloadJob


class FasterWhisperDownloadStatusData(OpenBBQModel):
    job: ModelDownloadJob


class DoctorData(OpenBBQModel):
    ok: bool
    checks: tuple[DoctorCheck, ...]


class SubtitleLocalJobRequest(OpenBBQModel):
    input_path: Path
    source_lang: str
    target_lang: str
    provider: str | None = None
    model: str | None = None
    asr_model: str | None = None
    asr_device: str | None = None
    asr_compute_type: str | None = None
    correct_transcript: bool = True
    step_order: tuple[str, ...] = ()
    extra_steps: tuple[SubtitleExtraStepRequest, ...] = ()
    output_path: Path | None = None


class SubtitleYouTubeJobRequest(OpenBBQModel):
    url: str
    source_lang: str
    target_lang: str
    provider: str | None = None
    model: str | None = None
    asr_model: str | None = None
    asr_device: str | None = None
    asr_compute_type: str | None = None
    correct_transcript: bool = True
    step_order: tuple[str, ...] = ()
    extra_steps: tuple[SubtitleExtraStepRequest, ...] = ()
    quality: str = "best[ext=mp4][height<=720]/best[height<=720]/best"
    auth: str = "auto"
    browser: str | None = None
    browser_profile: str | None = None
    output_path: Path | None = None


class SubtitleJobData(OpenBBQModel):
    generated_project_root: Path
    generated_config_path: Path
    workflow_id: str
    run_id: str
    output_path: Path | None = None
    source_artifact_id: str | None = None
    provider: str
    model: str | None = None
    asr_model: str
    asr_device: str
    asr_compute_type: str


class EventStreamItem(OpenBBQModel):
    event: WorkflowEvent

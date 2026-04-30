from __future__ import annotations

from pathlib import Path

from pydantic import Field

from openbbq.application.artifacts import ArtifactImportRequest, import_artifact
from openbbq.application.quickstart_workflows import (
    DEFAULT_YOUTUBE_QUALITY,
    GeneratedWorkflow,
    LOCAL_SUBTITLE_TEMPLATE_NAME,
    LOCAL_SUBTITLE_TEMPLATE_PACKAGE,
    LOCAL_SUBTITLE_TEMPLATE_ID,
    LOCAL_SUBTITLE_WORKFLOW_ID,
    YOUTUBE_SUBTITLE_TEMPLATE_NAME,
    YOUTUBE_SUBTITLE_TEMPLATE_PACKAGE,
    YOUTUBE_SUBTITLE_TEMPLATE_ID,
    YOUTUBE_SUBTITLE_WORKFLOW_ID,
    write_local_subtitle_workflow,
    write_youtube_subtitle_workflow,
)
from openbbq.application.runs import RunCreateRequest, create_run
from openbbq.domain.base import JsonObject, OpenBBQModel
from openbbq.errors import ValidationError
from openbbq.runtime.secrets import SecretResolver
from openbbq.runtime.settings import load_runtime_settings

__all__ = (
    "DEFAULT_YOUTUBE_QUALITY",
    "GeneratedWorkflow",
    "LOCAL_SUBTITLE_TEMPLATE_ID",
    "LOCAL_SUBTITLE_TEMPLATE_NAME",
    "LOCAL_SUBTITLE_TEMPLATE_PACKAGE",
    "LOCAL_SUBTITLE_WORKFLOW_ID",
    "LocalSubtitleJobRequest",
    "SubtitleJobResult",
    "YOUTUBE_SUBTITLE_TEMPLATE_ID",
    "YOUTUBE_SUBTITLE_TEMPLATE_NAME",
    "YOUTUBE_SUBTITLE_TEMPLATE_PACKAGE",
    "YOUTUBE_SUBTITLE_WORKFLOW_ID",
    "YouTubeSubtitleJobRequest",
    "create_local_subtitle_job",
    "create_youtube_subtitle_job",
    "resolve_local_subtitle_job_request",
    "resolve_youtube_subtitle_job_request",
    "write_local_subtitle_workflow",
    "write_youtube_subtitle_workflow",
)


class SubtitleJobResult(OpenBBQModel):
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


class LocalSubtitleJobRequest(OpenBBQModel):
    workspace_root: Path
    input_path: Path
    source_lang: str
    target_lang: str
    provider: str | None = None
    model: str | None = None
    asr_model: str | None = None
    asr_device: str | None = None
    asr_compute_type: str | None = None
    correct_transcript: bool = True
    segment_parameters: JsonObject = Field(default_factory=dict)
    step_order: tuple[str, ...] = ()
    extra_steps: tuple[dict, ...] = ()
    output_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    created_by: str = "api"
    execute_inline: bool = False


class YouTubeSubtitleJobRequest(OpenBBQModel):
    workspace_root: Path
    url: str
    source_lang: str
    target_lang: str
    provider: str | None = None
    model: str | None = None
    asr_model: str | None = None
    asr_device: str | None = None
    asr_compute_type: str | None = None
    correct_transcript: bool = True
    segment_parameters: JsonObject = Field(default_factory=dict)
    step_order: tuple[str, ...] = ()
    extra_steps: tuple[dict, ...] = ()
    quality: str = DEFAULT_YOUTUBE_QUALITY
    auth: str = "auto"
    browser: str | None = None
    browser_profile: str | None = None
    output_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    created_by: str = "api"
    execute_inline: bool = False


def create_local_subtitle_job(request: LocalSubtitleJobRequest) -> SubtitleJobResult:
    request = resolve_local_subtitle_job_request(request)
    generated = write_local_subtitle_workflow(
        workspace_root=request.workspace_root,
        video_selector="project.art_source_video",
        source_lang=request.source_lang,
        target_lang=request.target_lang,
        provider=request.provider,
        model=request.model,
        asr_model=request.asr_model,
        asr_device=request.asr_device,
        asr_compute_type=request.asr_compute_type,
        correct_transcript=request.correct_transcript,
        segment_parameters=request.segment_parameters,
        step_order=request.step_order,
        extra_steps=request.extra_steps,
    )
    imported = import_artifact(
        ArtifactImportRequest(
            project_root=generated.project_root,
            config_path=generated.config_path,
            path=request.input_path,
            artifact_type="video",
            name="source.video",
        )
    )
    generated = write_local_subtitle_workflow(
        workspace_root=request.workspace_root,
        video_selector=f"project.{imported.artifact.id}",
        source_lang=request.source_lang,
        target_lang=request.target_lang,
        provider=request.provider,
        model=request.model,
        asr_model=request.asr_model,
        asr_device=request.asr_device,
        asr_compute_type=request.asr_compute_type,
        correct_transcript=request.correct_transcript,
        segment_parameters=request.segment_parameters,
        step_order=request.step_order,
        extra_steps=request.extra_steps,
        run_id=generated.run_id,
    )
    run = create_run(
        RunCreateRequest(
            project_root=generated.project_root,
            config_path=generated.config_path,
            plugin_paths=request.plugin_paths,
            workflow_id=generated.workflow_id,
            created_by=request.created_by,
        ),
        execute_inline=request.execute_inline,
    )
    return SubtitleJobResult(
        generated_project_root=generated.project_root,
        generated_config_path=generated.config_path,
        workflow_id=generated.workflow_id,
        run_id=run.id,
        output_path=request.output_path,
        source_artifact_id=imported.artifact.id,
        provider=request.provider,
        model=request.model,
        asr_model=request.asr_model,
        asr_device=request.asr_device,
        asr_compute_type=request.asr_compute_type,
    )


def resolve_local_subtitle_job_request(
    request: LocalSubtitleJobRequest,
    *,
    validate_provider_auth: bool = True,
) -> LocalSubtitleJobRequest:
    defaults = _runtime_defaults_for_request(
        provider=request.provider,
        model=request.model,
        asr_model=request.asr_model,
        asr_device=request.asr_device,
        asr_compute_type=request.asr_compute_type,
        validate_provider_auth=validate_provider_auth,
    )
    return request.model_copy(
        update={
            "provider": defaults.provider,
            "model": defaults.model,
            "asr_model": defaults.asr_model,
            "asr_device": defaults.asr_device,
            "asr_compute_type": defaults.asr_compute_type,
        }
    )


def create_youtube_subtitle_job(request: YouTubeSubtitleJobRequest) -> SubtitleJobResult:
    request = resolve_youtube_subtitle_job_request(request)
    generated = write_youtube_subtitle_workflow(
        workspace_root=request.workspace_root,
        url=request.url,
        source_lang=request.source_lang,
        target_lang=request.target_lang,
        provider=request.provider,
        model=request.model,
        asr_model=request.asr_model,
        asr_device=request.asr_device,
        asr_compute_type=request.asr_compute_type,
        correct_transcript=request.correct_transcript,
        segment_parameters=request.segment_parameters,
        step_order=request.step_order,
        extra_steps=request.extra_steps,
        quality=request.quality,
        auth=request.auth,
        browser=request.browser,
        browser_profile=request.browser_profile,
    )
    run = create_run(
        RunCreateRequest(
            project_root=generated.project_root,
            config_path=generated.config_path,
            plugin_paths=request.plugin_paths,
            workflow_id=generated.workflow_id,
            created_by=request.created_by,
        ),
        execute_inline=request.execute_inline,
    )
    return SubtitleJobResult(
        generated_project_root=generated.project_root,
        generated_config_path=generated.config_path,
        workflow_id=generated.workflow_id,
        run_id=run.id,
        output_path=request.output_path,
        source_artifact_id=None,
        provider=request.provider,
        model=request.model,
        asr_model=request.asr_model,
        asr_device=request.asr_device,
        asr_compute_type=request.asr_compute_type,
    )


def resolve_youtube_subtitle_job_request(
    request: YouTubeSubtitleJobRequest,
    *,
    validate_provider_auth: bool = True,
) -> YouTubeSubtitleJobRequest:
    defaults = _runtime_defaults_for_request(
        provider=request.provider,
        model=request.model,
        asr_model=request.asr_model,
        asr_device=request.asr_device,
        asr_compute_type=request.asr_compute_type,
        validate_provider_auth=validate_provider_auth,
    )
    return request.model_copy(
        update={
            "provider": defaults.provider,
            "model": defaults.model,
            "asr_model": defaults.asr_model,
            "asr_device": defaults.asr_device,
            "asr_compute_type": defaults.asr_compute_type,
        }
    )


class _ResolvedQuickstartDefaults(OpenBBQModel):
    provider: str
    model: str | None
    asr_model: str
    asr_device: str
    asr_compute_type: str


def _runtime_defaults_for_request(
    *,
    provider: str | None,
    model: str | None,
    asr_model: str | None,
    asr_device: str | None,
    asr_compute_type: str | None,
    validate_provider_auth: bool,
) -> _ResolvedQuickstartDefaults:
    settings = load_runtime_settings()
    provider_name = provider or settings.defaults.llm_provider
    profile = settings.providers.get(provider_name)
    if profile is None:
        raise ValidationError(f"Default LLM provider '{provider_name}' is not configured.")
    if validate_provider_auth:
        _validate_provider_auth(provider_name, profile.api_key)
    if settings.defaults.asr_provider != "faster-whisper":
        raise ValidationError(
            f"Default ASR provider '{settings.defaults.asr_provider}' is not supported by this quickstart."
        )
    if settings.models is None:
        raise ValidationError("Faster Whisper runtime settings are not configured.")
    faster_whisper = settings.models.faster_whisper
    return _ResolvedQuickstartDefaults(
        provider=provider_name,
        model=model or profile.default_chat_model,
        asr_model=asr_model or faster_whisper.default_model,
        asr_device=asr_device or faster_whisper.default_device,
        asr_compute_type=asr_compute_type or faster_whisper.default_compute_type,
    )


def _validate_provider_auth(provider_name: str, api_key: str | None) -> None:
    if api_key is None:
        raise ValidationError(f"Default LLM provider '{provider_name}' does not define an API key.")
    resolved_secret = SecretResolver().resolve(api_key)
    if not resolved_secret.resolved:
        raise ValidationError(
            resolved_secret.public.error
            or f"Default LLM provider '{provider_name}' API key is not resolved."
        )

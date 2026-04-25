from __future__ import annotations

from pathlib import Path

from openbbq.application.artifacts import ArtifactImportRequest, import_artifact
from openbbq.application.quickstart_workflows import (
    DEFAULT_YOUTUBE_QUALITY,
    GeneratedWorkflow,
    LOCAL_SUBTITLE_TEMPLATE_ID,
    LOCAL_SUBTITLE_WORKFLOW_ID,
    YOUTUBE_SUBTITLE_TEMPLATE_ID,
    YOUTUBE_SUBTITLE_WORKFLOW_ID,
    write_local_subtitle_workflow,
    write_youtube_subtitle_workflow,
)
from openbbq.application.runs import RunCreateRequest, create_run
from openbbq.domain.base import OpenBBQModel
from openbbq.runtime.settings import load_runtime_settings

__all__ = (
    "DEFAULT_YOUTUBE_QUALITY",
    "GeneratedWorkflow",
    "LOCAL_SUBTITLE_TEMPLATE_ID",
    "LOCAL_SUBTITLE_WORKFLOW_ID",
    "LocalSubtitleJobRequest",
    "SubtitleJobResult",
    "YOUTUBE_SUBTITLE_TEMPLATE_ID",
    "YOUTUBE_SUBTITLE_WORKFLOW_ID",
    "YouTubeSubtitleJobRequest",
    "create_local_subtitle_job",
    "create_youtube_subtitle_job",
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


class LocalSubtitleJobRequest(OpenBBQModel):
    workspace_root: Path
    input_path: Path
    source_lang: str
    target_lang: str
    provider: str = "openai"
    model: str | None = None
    asr_model: str | None = None
    asr_device: str | None = None
    asr_compute_type: str | None = None
    output_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    created_by: str = "api"
    execute_inline: bool = False


class YouTubeSubtitleJobRequest(OpenBBQModel):
    workspace_root: Path
    url: str
    source_lang: str
    target_lang: str
    provider: str = "openai"
    model: str | None = None
    asr_model: str | None = None
    asr_device: str | None = None
    asr_compute_type: str | None = None
    quality: str = DEFAULT_YOUTUBE_QUALITY
    auth: str = "auto"
    browser: str | None = None
    browser_profile: str | None = None
    output_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    created_by: str = "api"
    execute_inline: bool = False


def create_local_subtitle_job(request: LocalSubtitleJobRequest) -> SubtitleJobResult:
    defaults = _faster_whisper_defaults()
    generated = write_local_subtitle_workflow(
        workspace_root=request.workspace_root,
        video_selector="project.art_source_video",
        source_lang=request.source_lang,
        target_lang=request.target_lang,
        provider=request.provider,
        model=request.model,
        asr_model=request.asr_model or defaults.default_model,
        asr_device=request.asr_device or defaults.default_device,
        asr_compute_type=request.asr_compute_type or defaults.default_compute_type,
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
        asr_model=request.asr_model or defaults.default_model,
        asr_device=request.asr_device or defaults.default_device,
        asr_compute_type=request.asr_compute_type or defaults.default_compute_type,
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
    )


def create_youtube_subtitle_job(request: YouTubeSubtitleJobRequest) -> SubtitleJobResult:
    defaults = _faster_whisper_defaults()
    generated = write_youtube_subtitle_workflow(
        workspace_root=request.workspace_root,
        url=request.url,
        source_lang=request.source_lang,
        target_lang=request.target_lang,
        provider=request.provider,
        model=request.model,
        asr_model=request.asr_model or defaults.default_model,
        asr_device=request.asr_device or defaults.default_device,
        asr_compute_type=request.asr_compute_type or defaults.default_compute_type,
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
    )


def _faster_whisper_defaults():
    settings = load_runtime_settings()
    return settings.models.faster_whisper

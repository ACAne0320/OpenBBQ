from __future__ import annotations

from fastapi import APIRouter, Request

from openbbq.api.schemas import (
    ApiSuccess,
    SubtitleJobData,
    SubtitleLocalJobRequest,
    SubtitleYouTubeJobRequest,
)
from openbbq.application.quickstart import (
    LocalSubtitleJobRequest,
    YouTubeSubtitleJobRequest,
    create_local_subtitle_job,
    create_youtube_subtitle_job,
)
from openbbq.errors import ValidationError

router = APIRouter(tags=["quickstart"])


@router.post("/quickstart/subtitle/local", response_model=ApiSuccess[SubtitleJobData])
def post_local_subtitle_job(
    body: SubtitleLocalJobRequest,
    request: Request,
) -> ApiSuccess[SubtitleJobData]:
    settings = _settings(request)
    result = create_local_subtitle_job(
        LocalSubtitleJobRequest(
            workspace_root=settings.project_root,
            input_path=body.input_path,
            source_lang=body.source_lang,
            target_lang=body.target_lang,
            provider=body.provider,
            model=body.model,
            asr_model=body.asr_model,
            asr_device=body.asr_device,
            asr_compute_type=body.asr_compute_type,
            output_path=body.output_path,
            plugin_paths=settings.plugin_paths,
            created_by="api",
            execute_inline=settings.execute_runs_inline,
        )
    )
    return ApiSuccess(data=SubtitleJobData(**result.model_dump()))


@router.post("/quickstart/subtitle/youtube", response_model=ApiSuccess[SubtitleJobData])
def post_youtube_subtitle_job(
    body: SubtitleYouTubeJobRequest,
    request: Request,
) -> ApiSuccess[SubtitleJobData]:
    settings = _settings(request)
    result = create_youtube_subtitle_job(
        YouTubeSubtitleJobRequest(
            workspace_root=settings.project_root,
            url=body.url,
            source_lang=body.source_lang,
            target_lang=body.target_lang,
            provider=body.provider,
            model=body.model,
            asr_model=body.asr_model,
            asr_device=body.asr_device,
            asr_compute_type=body.asr_compute_type,
            quality=body.quality,
            auth=body.auth,
            browser=body.browser,
            browser_profile=body.browser_profile,
            output_path=body.output_path,
            plugin_paths=settings.plugin_paths,
            created_by="api",
            execute_inline=settings.execute_runs_inline,
        )
    )
    return ApiSuccess(data=SubtitleJobData(**result.model_dump()))


def _settings(request: Request):
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    return settings

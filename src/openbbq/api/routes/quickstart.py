from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request

from openbbq.api.adapters import api_model
from openbbq.api.context import active_project_settings
from openbbq.api.project_refs import register_run_project
from openbbq.api.schemas import (
    ApiSuccess,
    QuickstartTaskListData,
    RemoteVideoFormatListData,
    SubtitleJobData,
    SubtitleLocalJobRequest,
    SubtitleWorkflowTemplateData,
    SubtitleWorkflowToolCatalogData,
    SubtitleYouTubeJobRequest,
)
from openbbq.api.task_history import (
    list_quickstart_tasks,
    record_local_subtitle_job,
    record_youtube_subtitle_job,
    reusable_local_subtitle_job,
    reusable_youtube_subtitle_job,
)
from openbbq.application.quickstart import (
    LocalSubtitleJobRequest,
    YouTubeSubtitleJobRequest,
    create_local_subtitle_job,
    create_youtube_subtitle_job,
    resolve_local_subtitle_job_request,
    resolve_youtube_subtitle_job_request,
)
from openbbq.application.quickstart_workflows import (
    fallback_remote_video_format_options,
    remote_video_format_options,
    subtitle_workflow_template_for_source,
    subtitle_workflow_tool_catalog,
)
from openbbq.config.loader import BUILTIN_PLUGIN_ROOT

router = APIRouter(tags=["quickstart"])


@router.get(
    "/quickstart/subtitle/template",
    response_model=ApiSuccess[SubtitleWorkflowTemplateData],
    response_model_exclude_none=True,
)
def get_subtitle_workflow_template(
    source_kind: Literal["local_file", "remote_url"],
    url: str | None = None,
) -> ApiSuccess[SubtitleWorkflowTemplateData]:
    format_options = _remote_format_options_or_fallback(url) if source_kind == "remote_url" else ()
    template = subtitle_workflow_template_for_source(
        source_kind=source_kind,
        url=url,
        remote_video_format_options=format_options,
    )
    return ApiSuccess(data=SubtitleWorkflowTemplateData(**template))


@router.get(
    "/quickstart/remote-video/formats",
    response_model=ApiSuccess[RemoteVideoFormatListData],
)
def get_remote_video_formats(
    url: str,
    auth: Literal["auto", "anonymous", "browser_cookies"] = "auto",
    browser: str | None = None,
    browser_profile: str | None = None,
) -> ApiSuccess[RemoteVideoFormatListData]:
    try:
        formats = remote_video_format_options(
            url=url,
            auth=auth,
            browser=browser,
            browser_profile=browser_profile,
        )
    except Exception:
        formats = fallback_remote_video_format_options()
    return ApiSuccess(data=RemoteVideoFormatListData(formats=formats))


@router.get(
    "/quickstart/subtitle/tools",
    response_model=ApiSuccess[SubtitleWorkflowToolCatalogData],
)
def get_subtitle_workflow_tools(request: Request) -> ApiSuccess[SubtitleWorkflowToolCatalogData]:
    settings = active_project_settings(request)
    catalog = subtitle_workflow_tool_catalog(
        plugin_paths=(*settings.plugin_paths, BUILTIN_PLUGIN_ROOT)
    )
    return ApiSuccess(data=SubtitleWorkflowToolCatalogData(**catalog))


def _remote_format_options_or_fallback(url: str | None):
    if not url:
        return fallback_remote_video_format_options()
    try:
        return remote_video_format_options(url=url)
    except Exception:
        return fallback_remote_video_format_options()


@router.post("/quickstart/subtitle/local", response_model=ApiSuccess[SubtitleJobData])
def post_local_subtitle_job(
    body: SubtitleLocalJobRequest,
    request: Request,
) -> ApiSuccess[SubtitleJobData]:
    settings = active_project_settings(request)
    job_request = resolve_local_subtitle_job_request(
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
            correct_transcript=body.correct_transcript,
            segment_parameters=body.segment_parameters,
            step_order=body.step_order,
            extra_steps=tuple(step.model_dump(mode="json") for step in body.extra_steps),
            output_path=body.output_path,
            plugin_paths=settings.plugin_paths,
            created_by="api",
            execute_inline=settings.execute_runs_inline,
        ),
        validate_provider_auth=False,
    )
    resolved_body = body.model_copy(update=_runtime_fields(job_request))
    cached = reusable_local_subtitle_job(request, resolved_body)
    if cached is not None:
        register_run_project(
            request,
            run_id=cached.run_id,
            project_root=cached.generated_project_root,
            config_path=cached.generated_config_path,
            plugin_paths=settings.plugin_paths,
        )
        return ApiSuccess(data=api_model(SubtitleJobData, cached))
    result = create_local_subtitle_job(job_request)
    register_run_project(
        request,
        run_id=result.run_id,
        project_root=result.generated_project_root,
        config_path=result.generated_config_path,
        plugin_paths=settings.plugin_paths,
    )
    record_local_subtitle_job(
        request,
        body=resolved_body,
        result=result,
        workspace_root=settings.project_root,
        plugin_paths=settings.plugin_paths,
    )
    return ApiSuccess(data=api_model(SubtitleJobData, result))


@router.post("/quickstart/subtitle/youtube", response_model=ApiSuccess[SubtitleJobData])
def post_youtube_subtitle_job(
    body: SubtitleYouTubeJobRequest,
    request: Request,
) -> ApiSuccess[SubtitleJobData]:
    settings = active_project_settings(request)
    job_request = resolve_youtube_subtitle_job_request(
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
            correct_transcript=body.correct_transcript,
            segment_parameters=body.segment_parameters,
            step_order=body.step_order,
            extra_steps=tuple(step.model_dump(mode="json") for step in body.extra_steps),
            quality=body.quality,
            auth=body.auth,
            browser=body.browser,
            browser_profile=body.browser_profile,
            output_path=body.output_path,
            plugin_paths=settings.plugin_paths,
            created_by="api",
            execute_inline=settings.execute_runs_inline,
        ),
        validate_provider_auth=False,
    )
    resolved_body = body.model_copy(update=_runtime_fields(job_request))
    cached = reusable_youtube_subtitle_job(request, resolved_body)
    if cached is not None:
        register_run_project(
            request,
            run_id=cached.run_id,
            project_root=cached.generated_project_root,
            config_path=cached.generated_config_path,
            plugin_paths=settings.plugin_paths,
        )
        return ApiSuccess(data=api_model(SubtitleJobData, cached))
    result = create_youtube_subtitle_job(job_request)
    register_run_project(
        request,
        run_id=result.run_id,
        project_root=result.generated_project_root,
        config_path=result.generated_config_path,
        plugin_paths=settings.plugin_paths,
    )
    record_youtube_subtitle_job(
        request,
        body=resolved_body,
        result=result,
        workspace_root=settings.project_root,
        plugin_paths=settings.plugin_paths,
    )
    return ApiSuccess(data=api_model(SubtitleJobData, result))


@router.get("/quickstart/tasks", response_model=ApiSuccess[QuickstartTaskListData])
def get_quickstart_tasks(request: Request) -> ApiSuccess[QuickstartTaskListData]:
    return ApiSuccess(data=QuickstartTaskListData(tasks=list_quickstart_tasks(request)))


def _runtime_fields(
    request: LocalSubtitleJobRequest | YouTubeSubtitleJobRequest,
) -> dict[str, str | None]:
    return {
        "provider": request.provider,
        "model": request.model,
        "asr_model": request.asr_model,
        "asr_device": request.asr_device,
        "asr_compute_type": request.asr_compute_type,
    }

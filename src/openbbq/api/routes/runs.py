from __future__ import annotations

from fastapi import APIRouter, Request

from openbbq.api.schemas import ApiSuccess, RunCreateRequest, RunRecord
from openbbq.application.runs import RunCreateRequest as ApplicationRunCreateRequest
from openbbq.application.runs import abort_run, create_run, get_run, resume_run
from openbbq.errors import ValidationError

router = APIRouter(tags=["runs"])


@router.post("/workflows/{workflow_id}/runs", response_model=ApiSuccess[RunRecord])
def create_workflow_run(
    workflow_id: str,
    body: RunCreateRequest,
    request: Request,
) -> ApiSuccess[RunRecord]:
    settings = request.app.state.openbbq_settings
    run = create_run(
        ApplicationRunCreateRequest(
            project_root=body.project_root,
            config_path=body.config_path or settings.config_path,
            plugin_paths=body.plugin_paths or settings.plugin_paths,
            workflow_id=workflow_id,
            force=body.force,
            step_id=body.step_id,
            created_by=body.created_by,
        ),
        execute_inline=settings.execute_runs_inline,
    )
    return ApiSuccess(data=RunRecord(**run.model_dump()))


@router.get("/runs/{run_id}", response_model=ApiSuccess[RunRecord])
def get_run_route(run_id: str, request: Request) -> ApiSuccess[RunRecord]:
    settings = _settings(request)
    run = get_run(project_root=settings.project_root, config_path=settings.config_path, run_id=run_id)
    return ApiSuccess(data=RunRecord(**run.model_dump()))


@router.post("/runs/{run_id}/resume", response_model=ApiSuccess[RunRecord])
def resume_run_route(run_id: str, request: Request) -> ApiSuccess[RunRecord]:
    settings = _settings(request)
    run = resume_run(project_root=settings.project_root, config_path=settings.config_path, run_id=run_id)
    return ApiSuccess(data=RunRecord(**run.model_dump()))


@router.post("/runs/{run_id}/abort", response_model=ApiSuccess[RunRecord])
def abort_run_route(run_id: str, request: Request) -> ApiSuccess[RunRecord]:
    settings = _settings(request)
    run = abort_run(project_root=settings.project_root, config_path=settings.config_path, run_id=run_id)
    return ApiSuccess(data=RunRecord(**run.model_dump()))


def _settings(request: Request):
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    return settings

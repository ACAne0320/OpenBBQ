from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from openbbq.api.adapters import api_model, api_models
from openbbq.api.context import active_project_settings
from openbbq.api.schemas import ApiSuccess, RunCreateRequest, RunListData, RunRecord
from openbbq.application.runs import RunCreateRequest as ApplicationRunCreateRequest
from openbbq.application.runs import abort_run, create_run, get_run, list_project_runs, resume_run
from openbbq.errors import ValidationError

router = APIRouter(tags=["runs"])


@router.post("/workflows/{workflow_id}/runs", response_model=ApiSuccess[RunRecord])
def create_workflow_run(
    workflow_id: str,
    body: RunCreateRequest,
    request: Request,
) -> ApiSuccess[RunRecord]:
    settings = active_project_settings(request)
    if body.workflow_id is not None and body.workflow_id != workflow_id:
        raise ValidationError(
            f"Request workflow_id '{body.workflow_id}' does not match route workflow_id '{workflow_id}'."
        )
    if body.project_root is not None and _resolve_path(body.project_root) != _resolve_path(
        settings.project_root
    ):
        raise ValidationError("Run project_root must match the active API project root.")
    run = create_run(
        ApplicationRunCreateRequest(
            project_root=settings.project_root,
            config_path=body.config_path or settings.config_path,
            plugin_paths=body.plugin_paths or settings.plugin_paths,
            workflow_id=workflow_id,
            force=body.force,
            step_id=body.step_id,
            created_by=body.created_by,
        ),
        execute_inline=settings.execute_runs_inline,
    )
    return ApiSuccess(data=api_model(RunRecord, run))


@router.get("/runs", response_model=ApiSuccess[RunListData])
def list_runs_route(request: Request) -> ApiSuccess[RunListData]:
    settings = active_project_settings(request)
    runs = list_project_runs(project_root=settings.project_root, config_path=settings.config_path)
    return ApiSuccess(data=RunListData(runs=api_models(RunRecord, runs)))


@router.get("/runs/{run_id}", response_model=ApiSuccess[RunRecord])
def get_run_route(run_id: str, request: Request) -> ApiSuccess[RunRecord]:
    settings = active_project_settings(request)
    run = get_run(
        project_root=settings.project_root, config_path=settings.config_path, run_id=run_id
    )
    return ApiSuccess(data=api_model(RunRecord, run))


@router.post("/runs/{run_id}/resume", response_model=ApiSuccess[RunRecord])
def resume_run_route(run_id: str, request: Request) -> ApiSuccess[RunRecord]:
    settings = active_project_settings(request)
    run = resume_run(
        project_root=settings.project_root,
        config_path=settings.config_path,
        run_id=run_id,
        execute_inline=settings.execute_runs_inline,
    )
    return ApiSuccess(data=api_model(RunRecord, run))


@router.post("/runs/{run_id}/abort", response_model=ApiSuccess[RunRecord])
def abort_run_route(run_id: str, request: Request) -> ApiSuccess[RunRecord]:
    settings = active_project_settings(request)
    run = abort_run(
        project_root=settings.project_root, config_path=settings.config_path, run_id=run_id
    )
    return ApiSuccess(data=api_model(RunRecord, run))


def _resolve_path(path: Path) -> Path:
    return path.expanduser().resolve()

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from openbbq.api.adapters import api_model, api_models
from openbbq.api.context import active_project_settings
from openbbq.api.project_refs import (
    find_run_project,
    known_project_references,
    register_run_record,
)
from openbbq.api.schemas import (
    ApiSuccess,
    ArtifactListData,
    RunCreateRequest,
    RunListData,
    RunRecord,
    WorkflowEventsData,
)
from openbbq.api.routes.events import event_stream, streaming_response
from openbbq.application.artifacts import list_artifacts
from openbbq.application.runs import RunCreateRequest as ApplicationRunCreateRequest
from openbbq.application.runs import abort_run, create_run, list_project_runs, resume_run
from openbbq.application.workflows import workflow_events
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
    register_run_record(request, run)
    return ApiSuccess(data=api_model(RunRecord, run))


@router.get("/runs", response_model=ApiSuccess[RunListData])
def list_runs_route(request: Request) -> ApiSuccess[RunListData]:
    runs_by_id = {}
    for reference in known_project_references(request):
        for run in list_project_runs(
            project_root=reference.project_root,
            config_path=reference.config_path,
        ):
            runs_by_id[run.id] = run
    runs = tuple(runs_by_id.values())
    return ApiSuccess(data=RunListData(runs=api_models(RunRecord, runs)))


@router.get("/runs/{run_id}", response_model=ApiSuccess[RunRecord])
def get_run_route(run_id: str, request: Request) -> ApiSuccess[RunRecord]:
    run, _reference = find_run_project(request, run_id)
    return ApiSuccess(data=api_model(RunRecord, run))


@router.post("/runs/{run_id}/resume", response_model=ApiSuccess[RunRecord])
def resume_run_route(run_id: str, request: Request) -> ApiSuccess[RunRecord]:
    settings = active_project_settings(request)
    _existing, reference = find_run_project(request, run_id)
    run = resume_run(
        project_root=reference.project_root,
        config_path=reference.config_path,
        run_id=run_id,
        execute_inline=settings.execute_runs_inline,
    )
    register_run_record(request, run)
    return ApiSuccess(data=api_model(RunRecord, run))


@router.post("/runs/{run_id}/abort", response_model=ApiSuccess[RunRecord])
def abort_run_route(run_id: str, request: Request) -> ApiSuccess[RunRecord]:
    _existing, reference = find_run_project(request, run_id)
    run = abort_run(
        project_root=reference.project_root, config_path=reference.config_path, run_id=run_id
    )
    register_run_record(request, run)
    return ApiSuccess(data=api_model(RunRecord, run))


@router.get("/runs/{run_id}/events", response_model=ApiSuccess[WorkflowEventsData])
def get_run_events(
    run_id: str,
    request: Request,
    after_sequence: int = 0,
) -> ApiSuccess[WorkflowEventsData]:
    run, reference = find_run_project(request, run_id)
    result = workflow_events(
        project_root=reference.project_root,
        config_path=reference.config_path,
        plugin_paths=reference.plugin_paths,
        workflow_id=run.workflow_id,
        after_sequence=after_sequence,
    )
    return ApiSuccess(data=WorkflowEventsData(workflow_id=result.workflow_id, events=result.events))


@router.get("/runs/{run_id}/events/stream")
def stream_run_events(
    run_id: str,
    request: Request,
    after_sequence: int = 0,
):
    run, reference = find_run_project(request, run_id)
    return streaming_response(
        event_stream(
            request=request,
            project_root=reference.project_root,
            workflow_id=run.workflow_id,
            after_sequence=after_sequence,
            config_path=reference.config_path,
            plugin_paths=reference.plugin_paths,
        )
    )


@router.get("/runs/{run_id}/artifacts", response_model=ApiSuccess[ArtifactListData])
def get_run_artifacts(run_id: str, request: Request) -> ApiSuccess[ArtifactListData]:
    run, reference = find_run_project(request, run_id)
    artifacts = list_artifacts(
        project_root=reference.project_root,
        config_path=reference.config_path,
        workflow_id=run.workflow_id,
    )
    return ApiSuccess(data=ArtifactListData(artifacts=tuple(artifacts)))


def _resolve_path(path: Path) -> Path:
    return path.expanduser().resolve()

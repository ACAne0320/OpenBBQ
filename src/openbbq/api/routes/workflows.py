from __future__ import annotations

from fastapi import APIRouter, Request

from openbbq.api.adapters import api_model
from openbbq.api.context import active_project_settings
from openbbq.api.schemas import (
    ApiSuccess,
    WorkflowDetailData,
    WorkflowEventsData,
    WorkflowListData,
    WorkflowStepSummary,
    WorkflowSummary,
)
from openbbq.api.routes.events import event_stream, streaming_response
from openbbq.application.project_context import load_project_context
from openbbq.application.workflows import workflow_events, workflow_status
from openbbq.config.loader import load_project_config
from openbbq.domain.models import WorkflowConfig
from openbbq.engine.validation import WorkflowValidationResult, validate_workflow
from openbbq.errors import ValidationError
from openbbq.plugins.registry import discover_plugins
from openbbq.storage.models import WorkflowState
from openbbq.storage.project_store import ProjectStore
from openbbq.workflow.state import read_effective_workflow_state

router = APIRouter(tags=["workflows"])


@router.get("/workflows", response_model=ApiSuccess[WorkflowListData])
def list_workflows(request: Request) -> ApiSuccess[WorkflowListData]:
    settings = active_project_settings(request)
    context = load_project_context(
        settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
    )
    workflows = tuple(
        _workflow_summary(context.store, workflow) for workflow in context.config.workflows.values()
    )
    return ApiSuccess(data=WorkflowListData(workflows=workflows))


@router.get("/workflows/{workflow_id}", response_model=ApiSuccess[WorkflowDetailData])
def get_workflow(workflow_id: str, request: Request) -> ApiSuccess[WorkflowDetailData]:
    settings = active_project_settings(request)
    context = load_project_context(
        settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
    )
    workflow = context.config.workflows.get(workflow_id)
    if workflow is None:
        raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
    summary = _workflow_summary(context.store, workflow)
    return ApiSuccess(data=api_model(WorkflowDetailData, summary))


@router.post(
    "/workflows/{workflow_id}/validate",
    response_model=ApiSuccess[WorkflowValidationResult],
)
def validate_workflow_route(
    workflow_id: str, request: Request
) -> ApiSuccess[WorkflowValidationResult]:
    settings = active_project_settings(request)
    config = load_project_config(
        settings.project_root,
        config_path=settings.config_path,
        extra_plugin_paths=settings.plugin_paths,
    )
    registry = discover_plugins(config.plugin_paths)
    result = validate_workflow(config, registry, workflow_id)
    return ApiSuccess(data=result)


@router.get("/workflows/{workflow_id}/status", response_model=ApiSuccess[WorkflowState])
def get_workflow_status(workflow_id: str, request: Request) -> ApiSuccess[WorkflowState]:
    settings = active_project_settings(request)
    state = workflow_status(
        project_root=settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
        workflow_id=workflow_id,
    )
    return ApiSuccess(data=state)


@router.get("/workflows/{workflow_id}/events", response_model=ApiSuccess[WorkflowEventsData])
def get_workflow_events(
    workflow_id: str,
    request: Request,
    after_sequence: int = 0,
) -> ApiSuccess[WorkflowEventsData]:
    settings = active_project_settings(request)
    result = workflow_events(
        project_root=settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
        workflow_id=workflow_id,
        after_sequence=after_sequence,
    )
    return ApiSuccess(data=WorkflowEventsData(workflow_id=result.workflow_id, events=result.events))


@router.get("/workflows/{workflow_id}/events/stream")
def stream_workflow_events(
    workflow_id: str,
    request: Request,
    after_sequence: int = 0,
):
    settings = active_project_settings(request)
    return streaming_response(
        event_stream(
            request=request,
            project_root=settings.project_root,
            workflow_id=workflow_id,
            after_sequence=after_sequence,
            config_path=settings.config_path,
            plugin_paths=settings.plugin_paths,
        )
    )


def _workflow_summary(store: ProjectStore, workflow: WorkflowConfig) -> WorkflowSummary:
    state = read_effective_workflow_state(store, workflow)
    return WorkflowSummary(
        id=workflow.id,
        name=workflow.name,
        steps=tuple(
            WorkflowStepSummary(
                id=step.id,
                name=step.name,
                tool_ref=step.tool_ref,
                outputs=step.outputs,
            )
            for step in workflow.steps
        ),
        state=state,
        latest_event_sequence=store.latest_event_sequence(workflow.id),
    )

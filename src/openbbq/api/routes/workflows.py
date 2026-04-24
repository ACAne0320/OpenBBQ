from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from openbbq.api.schemas import ApiSuccess
from openbbq.application.workflows import workflow_events, workflow_status
from openbbq.config.loader import load_project_config
from openbbq.engine.validation import validate_workflow
from openbbq.errors import ValidationError
from openbbq.plugins.registry import discover_plugins
from openbbq.storage.events import latest_event_sequence
from openbbq.storage.project_store import ProjectStore

router = APIRouter(tags=["workflows"])


@router.get("/workflows", response_model=ApiSuccess[dict[str, Any]])
def list_workflows(request: Request) -> ApiSuccess[dict[str, Any]]:
    settings = _settings(request)
    config = load_project_config(
        settings.project_root,
        config_path=settings.config_path,
        extra_plugin_paths=settings.plugin_paths,
    )
    workflows = [
        {"id": workflow.id, "name": workflow.name, "step_count": len(workflow.steps)}
        for workflow in config.workflows.values()
    ]
    return ApiSuccess(data={"workflows": workflows})


@router.get("/workflows/{workflow_id}", response_model=ApiSuccess[dict[str, Any]])
def get_workflow(workflow_id: str, request: Request) -> ApiSuccess[dict[str, Any]]:
    settings = _settings(request)
    config = load_project_config(
        settings.project_root,
        config_path=settings.config_path,
        extra_plugin_paths=settings.plugin_paths,
    )
    workflow = config.workflows.get(workflow_id)
    if workflow is None:
        raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
    return ApiSuccess(
        data={
            "id": workflow.id,
            "name": workflow.name,
            "steps": [step.model_dump(mode="json") for step in workflow.steps],
        }
    )


@router.post("/workflows/{workflow_id}/validate", response_model=ApiSuccess[dict[str, Any]])
def validate_workflow_route(workflow_id: str, request: Request) -> ApiSuccess[dict[str, Any]]:
    settings = _settings(request)
    config = load_project_config(
        settings.project_root,
        config_path=settings.config_path,
        extra_plugin_paths=settings.plugin_paths,
    )
    registry = discover_plugins(config.plugin_paths)
    result = validate_workflow(config, registry, workflow_id)
    return ApiSuccess(data=result.model_dump(mode="json"))


@router.get("/workflows/{workflow_id}/status", response_model=ApiSuccess[dict[str, Any]])
def get_workflow_status(workflow_id: str, request: Request) -> ApiSuccess[dict[str, Any]]:
    settings = _settings(request)
    state = workflow_status(
        project_root=settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
        workflow_id=workflow_id,
    )
    return ApiSuccess(data=state.model_dump(mode="json"))


@router.get("/workflows/{workflow_id}/events", response_model=ApiSuccess[dict[str, Any]])
def get_workflow_events(
    workflow_id: str,
    request: Request,
    after_sequence: int = 0,
) -> ApiSuccess[dict[str, Any]]:
    settings = _settings(request)
    result = workflow_events(
        project_root=settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
        workflow_id=workflow_id,
        after_sequence=after_sequence,
    )
    return ApiSuccess(data=result.model_dump(mode="json"))


def _settings(request: Request):
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    return settings


def _latest_sequence(settings, workflow_id: str) -> int:
    config = load_project_config(
        settings.project_root,
        config_path=settings.config_path,
        extra_plugin_paths=settings.plugin_paths,
    )
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    return latest_event_sequence(store.state_root, workflow_id)

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from openbbq.config.loader import load_project_config
from openbbq.domain.base import OpenBBQModel
from openbbq.engine.service import (
    WorkflowRunResult,
    abort_workflow,
    resume_workflow,
    run_workflow,
    unlock_workflow,
)
from openbbq.errors import ValidationError
from openbbq.plugins.registry import discover_plugins
from openbbq.runtime.context import build_runtime_context
from openbbq.runtime.settings import load_runtime_settings
from openbbq.storage.events import events_path
from openbbq.storage.models import WorkflowEvent, WorkflowState
from openbbq.storage.project_store import ProjectStore
from openbbq.workflow.state import read_effective_workflow_state


class WorkflowRunRequest(OpenBBQModel):
    project_root: Path
    workflow_id: str
    config_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    force: bool = False
    step_id: str | None = None


class WorkflowCommandRequest(OpenBBQModel):
    project_root: Path
    workflow_id: str
    config_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()


class WorkflowLogsResult(OpenBBQModel):
    workflow_id: str
    events: tuple[WorkflowEvent, ...]


def run_workflow_command(request: WorkflowRunRequest) -> WorkflowRunResult:
    config = load_project_config(
        request.project_root,
        config_path=request.config_path,
        extra_plugin_paths=request.plugin_paths,
    )
    registry = discover_plugins(config.plugin_paths)
    return run_workflow(
        config,
        registry,
        request.workflow_id,
        force=request.force,
        step_id=request.step_id,
        runtime_context=build_runtime_context(load_runtime_settings()),
    )


def resume_workflow_command(request: WorkflowCommandRequest) -> WorkflowRunResult:
    config = load_project_config(
        request.project_root,
        config_path=request.config_path,
        extra_plugin_paths=request.plugin_paths,
    )
    registry = discover_plugins(config.plugin_paths)
    return resume_workflow(
        config,
        registry,
        request.workflow_id,
        runtime_context=build_runtime_context(load_runtime_settings()),
    )


def abort_workflow_command(request: WorkflowCommandRequest) -> dict[str, object]:
    config = load_project_config(
        request.project_root,
        config_path=request.config_path,
        extra_plugin_paths=request.plugin_paths,
    )
    return abort_workflow(config, request.workflow_id)


def unlock_workflow_command(request: WorkflowCommandRequest) -> dict[str, object]:
    config = load_project_config(
        request.project_root,
        config_path=request.config_path,
        extra_plugin_paths=request.plugin_paths,
    )
    return unlock_workflow(config, request.workflow_id)


def workflow_status(
    *,
    project_root: Path,
    workflow_id: str,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> WorkflowState:
    config = load_project_config(
        project_root,
        config_path=config_path,
        extra_plugin_paths=plugin_paths,
    )
    workflow = config.workflows.get(workflow_id)
    if workflow is None:
        raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    return read_effective_workflow_state(store, workflow)


def workflow_logs(
    *,
    project_root: Path,
    workflow_id: str,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> WorkflowLogsResult:
    config = load_project_config(
        project_root,
        config_path=config_path,
        extra_plugin_paths=plugin_paths,
    )
    path = events_path(config.storage.state / "workflows", workflow_id)
    if not path.exists():
        return WorkflowLogsResult(workflow_id=workflow_id, events=())
    events: list[WorkflowEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(WorkflowEvent.model_validate(json.loads(line)))
        except (json.JSONDecodeError, PydanticValidationError):
            break
    return WorkflowLogsResult(workflow_id=workflow_id, events=tuple(events))

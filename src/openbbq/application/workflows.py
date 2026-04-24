from __future__ import annotations

from pathlib import Path

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
from openbbq.storage.events import read_events_after
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
    return workflow_events(
        project_root=project_root,
        workflow_id=workflow_id,
        config_path=config_path,
        plugin_paths=plugin_paths,
        after_sequence=0,
    )


def workflow_events(
    *,
    project_root: Path,
    workflow_id: str,
    after_sequence: int = 0,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> WorkflowLogsResult:
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
    return WorkflowLogsResult(
        workflow_id=workflow_id,
        events=read_events_after(store.state_root, workflow_id, after_sequence),
    )

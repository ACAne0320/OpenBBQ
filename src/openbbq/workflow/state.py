from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
from typing import Any, Iterable

from openbbq.errors import ExecutionError
from openbbq.domain.models import ProjectConfig, WorkflowConfig
from openbbq.storage.project_store import ProjectStore


def build_pending_state(workflow: WorkflowConfig) -> dict[str, Any]:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "status": "pending",
        "current_step_id": workflow.steps[0].id if workflow.steps else None,
        "step_run_ids": [],
    }


def read_effective_workflow_state(store: ProjectStore, workflow: WorkflowConfig) -> dict[str, Any]:
    try:
        return store.read_workflow_state(workflow.id)
    except FileNotFoundError:
        return build_pending_state(workflow)


def require_status(state: dict[str, Any], expected: str, workflow_id: str) -> None:
    status = state.get("status")
    if status != expected:
        raise ExecutionError(
            f"Workflow '{workflow_id}' must be {expected}; current status is {status}.",
            code="invalid_workflow_state",
            exit_code=1,
        )


def compute_workflow_config_hash(config: ProjectConfig, workflow_id: str) -> str:
    workflow = config.workflows[workflow_id]
    payload = {
        "version": config.version,
        "workflow_id": workflow_id,
        "workflow": _jsonable(workflow),
        "plugin_paths": [str(path) for path in config.plugin_paths],
    }
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def rebuild_output_bindings(
    store: ProjectStore, workflow_id: str, step_run_ids: Iterable[str]
) -> dict[str, dict[str, str]]:
    bindings: dict[str, dict[str, str]] = {}
    for step_run_id in step_run_ids:
        try:
            step_run = store.read_step_run(workflow_id, step_run_id)
        except FileNotFoundError:
            continue
        if step_run.get("status") != "completed":
            continue
        step_id = step_run["step_id"]
        for output_name, binding in step_run.get("output_bindings", {}).items():
            bindings[f"{step_id}.{output_name}"] = dict(binding)
    return bindings


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value

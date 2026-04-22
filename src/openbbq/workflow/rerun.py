from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from openbbq.storage.project_store import ProjectStore


def build_artifact_reuse_map(
    store: ProjectStore, workflow_id: str, step_run_ids: Iterable[str]
) -> dict[str, str]:
    artifact_ids: dict[str, str] = {}
    for step_run_id in step_run_ids:
        try:
            step_run = store.read_step_run(workflow_id, step_run_id)
        except FileNotFoundError:
            continue
        if step_run.get("status") != "completed":
            continue
        step_id = step_run.get("step_id")
        if not isinstance(step_id, str):
            continue
        for output_name, binding in step_run.get("output_bindings", {}).items():
            artifact_id = _artifact_id(binding)
            if artifact_id is not None:
                artifact_ids[f"{step_id}.{output_name}"] = artifact_id
    return artifact_ids


def mark_running_step_runs_failed(
    store: ProjectStore, workflow_id: str, step_run_ids: Iterable[str]
) -> None:
    for step_run_id in step_run_ids:
        try:
            step_run = store.read_step_run(workflow_id, step_run_id)
        except FileNotFoundError:
            continue
        if step_run.get("status") != "running":
            continue
        failed = dict(step_run)
        failed["status"] = "failed"
        failed["error"] = {
            "code": "engine.crash_recovery",
            "message": "StepRun was still running during crash recovery.",
        }
        failed["completed_at"] = datetime.now(UTC).isoformat()
        store.write_step_run(workflow_id, failed)


def _artifact_id(binding: Any) -> str | None:
    if not isinstance(binding, dict):
        return None
    artifact_id = binding.get("artifact_id")
    return artifact_id if isinstance(artifact_id, str) else None

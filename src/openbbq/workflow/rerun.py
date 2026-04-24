from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable

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
        if step_run.status != "completed":
            continue
        step_id = step_run.step_id
        if not isinstance(step_id, str):
            continue
        for output_name, binding in step_run.output_bindings.items():
            artifact_ids[f"{step_id}.{output_name}"] = binding.artifact_id
    return artifact_ids


def mark_running_step_runs_failed(
    store: ProjectStore, workflow_id: str, step_run_ids: Iterable[str]
) -> None:
    for step_run_id in step_run_ids:
        try:
            step_run = store.read_step_run(workflow_id, step_run_id)
        except FileNotFoundError:
            continue
        if step_run.status != "running":
            continue
        failed = step_run.model_dump(mode="json")
        failed["status"] = "failed"
        failed["error"] = {
            "code": "engine.crash_recovery",
            "message": "StepRun was still running during crash recovery.",
        }
        failed["completed_at"] = datetime.now(UTC).isoformat()
        store.write_step_run(workflow_id, failed)

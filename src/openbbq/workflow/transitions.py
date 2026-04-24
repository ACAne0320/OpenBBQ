from __future__ import annotations

from datetime import UTC, datetime

from openbbq.storage.models import OutputBindings, StepRunRecord, WorkflowState
from openbbq.storage.project_store import ProjectStore


def mark_workflow_running(
    store: ProjectStore,
    *,
    workflow_id: str,
    workflow_name: str,
    current_step_id: str | None,
    config_hash: str,
    step_run_ids: tuple[str, ...],
) -> WorkflowState:
    return store.write_workflow_state(
        workflow_id,
        {
            "name": workflow_name,
            "status": "running",
            "current_step_id": current_step_id,
            "config_hash": config_hash,
            "step_run_ids": list(step_run_ids),
        },
    )


def mark_step_run_started(
    store: ProjectStore,
    *,
    workflow_id: str,
    step_id: str,
    attempt: int,
) -> StepRunRecord:
    return store.write_step_run(
        workflow_id,
        {
            "step_id": step_id,
            "attempt": attempt,
            "status": "running",
            "input_artifact_version_ids": {},
            "output_bindings": {},
            "started_at": _timestamp(),
        },
    )


def mark_step_run_completed(
    store: ProjectStore,
    *,
    workflow_id: str,
    step_run: StepRunRecord,
    input_artifact_version_ids: dict[str, str],
    output_bindings: OutputBindings,
) -> StepRunRecord:
    return store.write_step_run(
        workflow_id,
        {
            **step_run.model_dump(mode="json"),
            "status": "completed",
            "input_artifact_version_ids": input_artifact_version_ids,
            "output_bindings": output_bindings,
            "completed_at": _timestamp(),
        },
    )


def mark_step_run_failed(
    store: ProjectStore,
    *,
    workflow_id: str,
    step_run: StepRunRecord,
    input_artifact_version_ids: dict[str, str],
    error: dict[str, object],
    status: str = "failed",
) -> StepRunRecord:
    return store.write_step_run(
        workflow_id,
        {
            **step_run.model_dump(mode="json"),
            "status": status,
            "input_artifact_version_ids": input_artifact_version_ids,
            "error": error,
            "completed_at": _timestamp(),
        },
    )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()

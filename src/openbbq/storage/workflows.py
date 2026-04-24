from __future__ import annotations

from pathlib import Path
from typing import Protocol

from openbbq.domain.base import JsonObject, dump_jsonable
from openbbq.storage.json_files import read_json_object, write_json_atomic
from openbbq.storage.models import StepRunRecord, WorkflowState


class StepRunIdGenerator(Protocol):
    def step_run_id(self) -> str: ...


def workflow_dir(state_root: Path, workflow_id: str) -> Path:
    return state_root / workflow_id


def write_workflow_state(
    state_root: Path,
    workflow_id: str,
    state: JsonObject | WorkflowState,
) -> WorkflowState:
    state_path = workflow_dir(state_root, workflow_id) / "state.json"
    record = dict(dump_jsonable(state))
    record["id"] = workflow_id
    workflow_state = WorkflowState.model_validate(record)
    write_json_atomic(state_path, workflow_state.model_dump(mode="json"))
    return workflow_state


def read_workflow_state(state_root: Path, workflow_id: str) -> WorkflowState:
    state_path = workflow_dir(state_root, workflow_id) / "state.json"
    if not state_path.exists():
        raise FileNotFoundError(state_path)
    return WorkflowState.model_validate(read_json_object(state_path))


def write_step_run(
    state_root: Path,
    workflow_id: str,
    step_run: JsonObject | StepRunRecord,
    *,
    id_generator: StepRunIdGenerator,
) -> StepRunRecord:
    record = dict(dump_jsonable(step_run))
    record["workflow_id"] = workflow_id
    step_run_id = record.get("id")
    if not step_run_id:
        step_run_id = id_generator.step_run_id()
        record["id"] = step_run_id
    typed = StepRunRecord.model_validate(record)
    path = workflow_dir(state_root, workflow_id) / "step-runs" / f"{step_run_id}.json"
    write_json_atomic(path, typed.model_dump(mode="json"))
    return typed


def read_step_run(state_root: Path, workflow_id: str, step_run_id: str) -> StepRunRecord:
    path = workflow_dir(state_root, workflow_id) / "step-runs" / f"{step_run_id}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return StepRunRecord.model_validate(read_json_object(path))

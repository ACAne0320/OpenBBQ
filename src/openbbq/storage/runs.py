from __future__ import annotations

from pathlib import Path

from openbbq.storage.database import ProjectDatabase, project_database_path_from_state_base
from openbbq.storage.models import RunRecord

ACTIVE_RUN_STATUSES = frozenset({"queued", "running"})


def write_run(state_base: Path, run: RunRecord) -> RunRecord:
    return _database(state_base).write_run(run)


def read_run(state_base: Path, run_id: str) -> RunRecord:
    record = _database(state_base).read_run(run_id)
    if record is None:
        raise FileNotFoundError(f"run not found: {run_id}")
    return record


def list_runs(state_base: Path) -> tuple[RunRecord, ...]:
    return _database(state_base).list_runs()


def list_active_runs(state_base: Path, *, workflow_id: str) -> tuple[RunRecord, ...]:
    return tuple(
        run
        for run in list_runs(state_base)
        if run.workflow_id == workflow_id and run.status in ACTIVE_RUN_STATUSES
    )


def _database(state_base: Path) -> ProjectDatabase:
    return ProjectDatabase(project_database_path_from_state_base(state_base))

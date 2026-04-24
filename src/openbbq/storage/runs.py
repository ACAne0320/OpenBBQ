from __future__ import annotations

from pathlib import Path

from openbbq.storage.json_files import read_json_object, write_json_atomic
from openbbq.storage.models import RunRecord

ACTIVE_RUN_STATUSES = frozenset({"queued", "running"})


def runs_dir(state_base: Path) -> Path:
    return state_base / "runs"


def run_path(state_base: Path, run_id: str) -> Path:
    return runs_dir(state_base) / f"{run_id}.json"


def write_run(state_base: Path, run: RunRecord) -> RunRecord:
    write_json_atomic(run_path(state_base, run.id), run.model_dump(mode="json"))
    return run


def read_run(state_base: Path, run_id: str) -> RunRecord:
    path = run_path(state_base, run_id)
    if not path.exists():
        raise FileNotFoundError(path)
    return RunRecord.model_validate(read_json_object(path))


def list_runs(state_base: Path) -> tuple[RunRecord, ...]:
    directory = runs_dir(state_base)
    if not directory.exists():
        return ()
    runs = [
        RunRecord.model_validate(read_json_object(path))
        for path in sorted(directory.glob("*.json"), key=lambda item: item.name)
    ]
    return tuple(sorted(runs, key=lambda run: (run.started_at or "", run.id)))


def list_active_runs(state_base: Path, *, workflow_id: str) -> tuple[RunRecord, ...]:
    return tuple(
        run
        for run in list_runs(state_base)
        if run.workflow_id == workflow_id and run.status in ACTIVE_RUN_STATUSES
    )

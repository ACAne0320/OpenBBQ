import sqlite3

from openbbq.storage.models import RunRecord
from openbbq.storage.runs import list_active_runs, read_run, write_run


def test_write_read_and_list_active_runs(tmp_path):
    state_root = tmp_path / ".openbbq" / "state"
    record = RunRecord(
        id="run_1",
        workflow_id="demo",
        mode="start",
        status="queued",
        project_root=tmp_path,
        latest_event_sequence=0,
        created_by="api",
    )

    written = write_run(state_root, record)
    loaded = read_run(state_root, "run_1")
    active = list_active_runs(state_root, workflow_id="demo")

    assert written == record
    assert loaded == record
    assert [run.id for run in active] == ["run_1"]


def test_run_records_are_written_to_project_sqlite_database(tmp_path):
    state_root = tmp_path / ".openbbq" / "state"
    record = RunRecord(
        id="run_sqlite",
        workflow_id="demo",
        mode="start",
        status="running",
        project_root=tmp_path,
        latest_event_sequence=3,
        created_by="desktop",
    )

    write_run(state_root, record)

    db_path = tmp_path / ".openbbq" / "openbbq.db"
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "select id, workflow_id, status, latest_event_sequence, created_by from runs"
        ).fetchone()
    assert row == ("run_sqlite", "demo", "running", 3, "desktop")

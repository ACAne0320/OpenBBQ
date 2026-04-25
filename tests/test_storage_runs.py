import json
import sqlite3

import pytest

from openbbq.errors import RunNotFoundError
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


def test_read_missing_run_raises_domain_not_found_error(tmp_path):
    state_root = tmp_path / ".openbbq" / "state"

    with pytest.raises(RunNotFoundError) as exc:
        read_run(state_root, "missing")

    assert exc.value.code == "run_not_found"
    assert exc.value.message == "run not found: missing"
    assert exc.value.exit_code == 6


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


def test_run_record_json_preserves_paths_and_plugin_path_order(tmp_path):
    state_root = tmp_path / ".openbbq" / "state"
    config_path = tmp_path / "openbbq.yaml"
    plugins_a = tmp_path / "plugins-a"
    plugins_b = tmp_path / "plugins-b"
    record = RunRecord(
        id="run_json",
        workflow_id="demo",
        mode="start",
        status="running",
        project_root=tmp_path,
        config_path=config_path,
        plugin_paths=(plugins_a, plugins_b),
        latest_event_sequence=3,
        created_by="desktop",
    )

    write_run(state_root, record)

    db_path = tmp_path / ".openbbq" / "openbbq.db"
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "select plugin_paths_json, record_json from runs where id = ?",
            ("run_json",),
        ).fetchone()

    assert json.loads(row[0]) == [str(plugins_a), str(plugins_b)]
    payload = json.loads(row[1])
    assert payload["project_root"] == str(tmp_path)
    assert payload["config_path"] == str(config_path)
    assert payload["plugin_paths"] == [str(plugins_a), str(plugins_b)]

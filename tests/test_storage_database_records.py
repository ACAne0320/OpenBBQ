import json
import sqlite3

from sqlalchemy.orm import sessionmaker

from openbbq.runtime.user_db import UserRuntimeDatabase
from openbbq.storage.database import ProjectDatabase
from openbbq.storage.database_records import (
    dump_json,
    dump_nullable_json,
    model_from_row,
    record_payload,
    upsert_row,
)
from openbbq.storage.models import WorkflowState
from openbbq.storage.orm import WorkflowStateRow
from openbbq.storage.project_store import ProjectStore


def _sqlite_table_names(path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {
            row[0]
            for row in connection.execute("select name from sqlite_master where type = 'table'")
        }


def test_database_record_helpers_dump_deterministic_json() -> None:
    assert dump_json({"z": "值", "a": [2, 1]}) == '{"a":[2,1],"z":"值"}'
    assert dump_nullable_json(None) is None
    assert dump_nullable_json({"b": 1}) == '{"b":1}'


def test_database_record_helpers_dump_model_payload() -> None:
    state = WorkflowState(
        id="demo",
        name="Demo",
        status="running",
        current_step_id="seed",
        config_hash="abc",
        step_run_ids=("sr_1",),
    )

    assert record_payload(state) == {
        "id": "demo",
        "name": "Demo",
        "status": "running",
        "current_step_id": "seed",
        "config_hash": "abc",
        "step_run_ids": ["sr_1"],
    }


def test_database_record_helpers_upsert_and_model_from_row(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / ".openbbq" / "openbbq.db")
    session_factory = sessionmaker(database.engine, expire_on_commit=False, future=True)
    state = WorkflowState(id="demo", status="running", step_run_ids=("sr_1",))
    payload = record_payload(state)

    with session_factory.begin() as session:
        row = upsert_row(session, WorkflowStateRow, state.id)
        row.name = state.name
        row.status = state.status
        row.current_step_id = state.current_step_id
        row.config_hash = state.config_hash
        row.step_run_ids_json = dump_json(payload["step_run_ids"])
        row.record_json = dump_json(payload)

        same_row = upsert_row(session, WorkflowStateRow, state.id)
        same_row.status = "completed"

    with session_factory.begin() as session:
        row = session.get(WorkflowStateRow, state.id)
        assert row is not None
        assert row.status == "completed"
        assert json.loads(row.record_json) == payload
        assert model_from_row(WorkflowState, row) == state


def test_project_database_initializes_with_alembic_without_user_tables(tmp_path):
    path = tmp_path / ".openbbq" / "openbbq.db"

    ProjectDatabase(path)

    table_names = _sqlite_table_names(path)
    assert "alembic_version" in table_names
    assert {"runs", "workflow_states", "step_runs", "workflow_events"} <= table_names
    assert {"providers", "credentials"}.isdisjoint(table_names)


def test_user_runtime_database_initializes_with_alembic_without_project_tables(tmp_path):
    path = tmp_path / "openbbq.db"

    UserRuntimeDatabase(path)

    table_names = _sqlite_table_names(path)
    assert "alembic_version" in table_names
    assert {"providers", "credentials"} <= table_names
    assert {"runs", "workflow_states", "step_runs", "workflow_events"}.isdisjoint(table_names)


def test_project_sqlite_records_workflow_state_step_run_event_and_artifact(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    state = store.write_workflow_state("text-demo", {"status": "running"})
    step_run = store.write_step_run("text-demo", {"id": "sr_sqlite", "status": "running"})
    event = store.append_event("text-demo", {"type": "workflow.started"})
    artifact, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello",
        metadata={"lang": "en"},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo", "step_id": "seed"},
    )

    with sqlite3.connect(tmp_path / ".openbbq" / "openbbq.db") as connection:
        workflow_row = connection.execute(
            "select id, status from workflow_states where id = ?", (state.id,)
        ).fetchone()
        step_run_row = connection.execute(
            "select id, workflow_id, status from step_runs where id = ?", (step_run.id,)
        ).fetchone()
        event_row = connection.execute(
            "select id, workflow_id, sequence, type from workflow_events where id = ?",
            (event.id,),
        ).fetchone()
        artifact_row = connection.execute(
            "select id, type, name, current_version_id from artifacts where id = ?",
            (artifact.id,),
        ).fetchone()
        version_row = connection.execute(
            "select id, artifact_id, content_encoding from artifact_versions where id = ?",
            (version.id,),
        ).fetchone()

    assert workflow_row == ("text-demo", "running")
    assert step_run_row == ("sr_sqlite", "text-demo", "running")
    assert event_row == (event.id, "text-demo", 1, "workflow.started")
    assert artifact_row == (artifact.id, "text", "seed.text", version.id)
    assert version_row == (version.id, artifact.id, "text")


def test_project_database_updates_existing_workflow_state_row(tmp_path):
    database = ProjectDatabase(tmp_path / ".openbbq" / "openbbq.db")

    database.write_workflow_state(WorkflowState(id="demo", status="running"))
    database.write_workflow_state(
        WorkflowState(id="demo", status="completed", step_run_ids=("sr_1",))
    )

    with sqlite3.connect(tmp_path / ".openbbq" / "openbbq.db") as connection:
        rows = connection.execute(
            "select status, step_run_ids_json, record_json from workflow_states where id = ?",
            ("demo",),
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "completed"
    assert json.loads(rows[0][1]) == ["sr_1"]
    assert json.loads(rows[0][2])["step_run_ids"] == ["sr_1"]

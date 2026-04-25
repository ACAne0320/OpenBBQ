import json
import sqlite3
from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from openbbq.runtime.user_db import UserRuntimeDatabase
from openbbq.storage.artifact_content import ArtifactContentStore
from openbbq.storage.artifact_repository import ArtifactRepository
from openbbq.storage.database import ProjectDatabase
from openbbq.storage.database_records import (
    dump_json,
    dump_nullable_json,
    model_from_row,
    record_payload,
    upsert_row,
)
from openbbq.storage.event_repository import EventRepository
from openbbq.storage.models import ArtifactRecord, OutputBinding, WorkflowState
from openbbq.storage.orm import WorkflowStateRow
from openbbq.storage.project_store import ProjectStore
from openbbq.storage.workflow_repository import WorkflowRepository


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


def test_artifact_content_store_round_trips_json_text_bytes_and_files(tmp_path):
    store = ArtifactContentStore()
    source = tmp_path / "source.bin"
    source.write_bytes(b"file-body")

    json_content = store.write_content(tmp_path / "json" / "content", {"hello": "openbbq"})
    text_content = store.write_content(tmp_path / "text" / "content", "hello")
    bytes_content = store.write_content(tmp_path / "bytes" / "content", b"bytes")
    file_content = store.copy_file(tmp_path / "file" / "content", source)

    assert json_content.encoding == "json"
    assert store.read_content(json_content.path, json_content.encoding, json_content.size) == {
        "hello": "openbbq"
    }
    assert (
        store.read_content(text_content.path, text_content.encoding, text_content.size) == "hello"
    )
    assert (
        store.read_content(bytes_content.path, bytes_content.encoding, bytes_content.size)
        == b"bytes"
    )
    assert store.read_content(file_content.path, file_content.encoding, file_content.size) == {
        "file_path": file_content.path,
        "size": 9,
        "sha256": file_content.sha256,
    }


def test_storage_repositories_round_trip_without_project_store(tmp_path):
    class FixedIds:
        def artifact_id(self) -> str:
            return "art_repo"

        def artifact_version_id(self) -> str:
            return "av_repo"

        def step_run_id(self) -> str:
            return "sr_repo"

        def workflow_event_id(self) -> str:
            return "evt_repo"

    database = ProjectDatabase(tmp_path / ".openbbq" / "openbbq.db")
    ids = FixedIds()

    def timestamp() -> str:
        return "2026-04-25T00:00:00+00:00"

    workflow_repo = WorkflowRepository(database, id_generator=ids)
    event_repo = EventRepository(database, id_generator=ids, timestamp_provider=timestamp)
    artifact_repo = ArtifactRepository(
        database,
        artifacts_root=tmp_path / ".openbbq" / "artifacts",
        id_generator=ids,
        timestamp_provider=timestamp,
    )

    state = workflow_repo.write_workflow_state("demo", {"status": "running"})
    step_run = workflow_repo.write_step_run("demo", {"status": "running"})
    event = event_repo.append_event("demo", {"type": "workflow.started"})
    artifact, version = artifact_repo.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "demo"},
    )

    assert workflow_repo.read_workflow_state("demo") == state
    assert workflow_repo.read_step_run("demo", "sr_repo") == step_run
    assert event_repo.read_events("demo") == (event,)
    assert event_repo.latest_sequence("demo") == 1
    assert artifact_repo.read_artifact(artifact.id) == artifact.record
    assert artifact_repo.read_artifact_version(version.id).content == "hello"


def test_write_artifact_version_round_trip(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    artifact, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello openbbq",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo"},
    )
    loaded = store.read_artifact_version(version.id)
    assert loaded.content == "hello openbbq"
    assert loaded.record.artifact_id == artifact.id


def test_event_readers_return_typed_events_after_sequence(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    first = store.append_event("demo", {"type": "workflow.started"})
    second = store.append_event("demo", {"type": "workflow.completed"})

    assert [event.id for event in store.read_events("demo")] == [
        first.id,
        second.id,
    ]
    assert [event.id for event in store.read_events("demo", after_sequence=1)] == [second.id]
    assert store.latest_event_sequence("demo") == 2


def test_artifact_version_supports_direct_database_lookup_without_json_index(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    artifact, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo", "step_id": "seed"},
    )

    index_path = tmp_path / ".openbbq" / "artifacts" / "index.json"
    assert not index_path.exists()
    assert store.read_artifact_version(version.id).record.artifact_id == artifact.id


def test_artifact_metadata_is_not_written_to_legacy_json_files(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    artifact, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo", "step_id": "seed"},
    )

    artifact_dir = tmp_path / ".openbbq" / "artifacts" / artifact.id
    version_dir = artifact_dir / "versions" / f"1-{version.id}"

    assert not (tmp_path / ".openbbq" / "artifacts" / "index.json").exists()
    assert not (artifact_dir / "artifact.json").exists()
    assert not (version_dir / "version.json").exists()
    assert (version_dir / "content").is_file()
    assert store.read_artifact(artifact.id).id == artifact.id


def test_storage_models_dump_to_current_json_shape(tmp_path):
    state = WorkflowState(
        id="text-demo",
        name="Text Demo",
        status="running",
        current_step_id="seed",
        config_hash="abc",
        step_run_ids=("sr_1",),
    )

    assert state.model_dump(mode="json") == {
        "id": "text-demo",
        "name": "Text Demo",
        "status": "running",
        "current_step_id": "seed",
        "config_hash": "abc",
        "step_run_ids": ["sr_1"],
    }


def test_output_binding_is_typed():
    binding = OutputBinding(artifact_id="art_1", artifact_version_id="av_1")

    assert binding.artifact_id == "art_1"
    assert binding.model_dump(mode="json") == {
        "artifact_id": "art_1",
        "artifact_version_id": "av_1",
    }


def test_artifact_record_versions_are_tuple_for_internal_use():
    artifact = ArtifactRecord(
        id="art_1",
        type="text",
        name="seed.text",
        versions=["av_1"],
        current_version_id="av_1",
        created_by_step_id="seed",
        created_at="2026-04-24T00:00:00+00:00",
        updated_at="2026-04-24T00:00:00+00:00",
    )

    assert artifact.versions == ("av_1",)


def test_workflow_state_step_run_and_events_round_trip(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    state = store.write_workflow_state(
        "text-demo", {"status": "running", "current_step_id": "seed"}
    )
    assert store.read_workflow_state("text-demo") == state

    step_run = store.write_step_run("text-demo", {"id": "sr_1", "status": "running"})
    assert step_run.id == "sr_1"
    assert store.read_step_run("text-demo", "sr_1").workflow_id == "text-demo"

    event1 = store.append_event("text-demo", {"type": "workflow.started", "message": "started"})
    event2 = store.append_event(
        "text-demo",
        {
            "type": "workflow.completed",
            "message": "done",
            "created_at": "2026-04-22T01:02:03+00:00",
        },
    )
    assert event1.sequence == 1
    assert event2.sequence == 2
    assert datetime.fromisoformat(event1.created_at).tzinfo is not None
    assert store.read_events("text-demo")[1].created_at == "2026-04-22T01:02:03+00:00"


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


def test_project_store_keeps_facts_in_database_not_legacy_json_files(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    store.write_workflow_state("text-demo", {"status": "running"})
    step_run = store.write_step_run("text-demo", {"id": "sr_sqlite", "status": "running"})
    event = store.append_event("text-demo", {"type": "workflow.started"})
    artifact, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello",
        metadata={"source": "sqlite"},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo"},
    )

    workflow_dir = tmp_path / ".openbbq" / "state" / "workflows" / "text-demo"
    version_dir = tmp_path / ".openbbq" / "artifacts" / artifact.id / "versions" / f"1-{version.id}"

    assert store.read_workflow_state("text-demo").status == "running"
    assert store.read_step_run("text-demo", "sr_sqlite").status == "running"
    assert [loaded.id for loaded in store.read_events("text-demo")] == [event.id]
    assert store.read_artifact(artifact.id).name == "seed.text"
    assert store.read_artifact_version(version.id).record.metadata == {"source": "sqlite"}
    assert not (workflow_dir / "state.json").exists()
    assert not (workflow_dir / "step-runs" / f"{step_run.id}.json").exists()
    assert not (workflow_dir / "events.jsonl").exists()
    assert not (tmp_path / ".openbbq" / "artifacts" / artifact.id / "artifact.json").exists()
    assert not (version_dir / "version.json").exists()


def test_write_workflow_state_overrides_conflicting_id(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    state = store.write_workflow_state("text-demo", {"id": "wrong-workflow", "status": "running"})

    assert state.id == "text-demo"
    assert store.read_workflow_state("text-demo").id == "text-demo"


def test_write_step_run_overrides_conflicting_workflow_id(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    step_run = store.write_step_run(
        "text-demo",
        {"id": "sr_2", "workflow_id": "wrong-workflow", "status": "running"},
    )

    assert step_run.workflow_id == "text-demo"
    assert store.read_step_run("text-demo", "sr_2").workflow_id == "text-demo"


def test_id_generator_injection_is_used_for_persisted_ids(tmp_path):
    class FixedIds:
        def artifact_id(self) -> str:
            return "art_fixed"

        def artifact_version_id(self) -> str:
            return "av_fixed"

        def step_run_id(self) -> str:
            return "sr_fixed"

        def workflow_event_id(self) -> str:
            return "evt_fixed"

    store = ProjectStore(tmp_path / ".openbbq", id_generator=FixedIds())

    artifact, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello openbbq",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo"},
    )
    step_run = store.write_step_run("text-demo", {"status": "running"})
    event = store.append_event("text-demo", {"type": "workflow.started", "message": "started"})

    assert artifact.id == "art_fixed"
    assert version.id == "av_fixed"
    assert step_run.id == "sr_fixed"
    assert event.id == "evt_fixed"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("hello openbbq", "hello openbbq"),
        ({"hello": "openbbq"}, {"hello": "openbbq"}),
        (b"hello openbbq", b"hello openbbq"),
    ],
)
def test_write_artifact_version_round_trips_content_types(tmp_path, content, expected):
    store = ProjectStore(tmp_path / ".openbbq")

    artifact, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content=content,
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo"},
    )

    loaded = store.read_artifact_version(version.id)
    assert loaded.content == expected
    assert loaded.record.artifact_id == artifact.id


def test_list_artifacts_and_read_artifact(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    artifact, _ = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello openbbq",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo"},
    )

    artifacts = store.list_artifacts()
    assert [record.name for record in artifacts] == ["seed.text"]
    assert store.read_artifact(artifact.id).current_version_id is not None

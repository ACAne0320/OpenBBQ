import json
from datetime import datetime

import pytest

from openbbq.storage import ProjectStore


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
    assert loaded.record["artifact_id"] == artifact.id


def test_workflow_state_step_run_and_events_round_trip(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    state = store.write_workflow_state(
        "text-demo", {"status": "running", "current_step_id": "seed"}
    )
    assert store.read_workflow_state("text-demo") == state

    step_run = store.write_step_run("text-demo", {"id": "sr_1", "status": "running"})
    assert step_run["id"] == "sr_1"
    step_run_path = (
        tmp_path / ".openbbq" / "state" / "workflows" / "text-demo" / "step-runs" / "sr_1.json"
    )
    assert json.loads(step_run_path.read_text(encoding="utf-8"))["workflow_id"] == "text-demo"

    event1 = store.append_event("text-demo", {"type": "workflow.started", "message": "started"})
    event2 = store.append_event(
        "text-demo",
        {
            "type": "workflow.completed",
            "message": "done",
            "created_at": "2026-04-22T01:02:03+00:00",
        },
    )
    assert event1["sequence"] == 1
    assert event2["sequence"] == 2
    assert datetime.fromisoformat(event1["created_at"]).tzinfo is not None
    assert (
        json.loads(
            (tmp_path / ".openbbq" / "state" / "workflows" / "text-demo" / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[1]
        )["created_at"]
        == "2026-04-22T01:02:03+00:00"
    )


def test_append_event_recovers_trailing_partial_jsonl_line(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    events_path = tmp_path / ".openbbq" / "state" / "workflows" / "text-demo" / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(
        '{"id":"evt_1","sequence":1,"workflow_id":"text-demo","type":"workflow.started"}\n'
        '{"id":"evt_partial","sequence":',
        encoding="utf-8",
    )

    event = store.append_event("text-demo", {"type": "workflow.completed", "message": "done"})

    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["type"] == "workflow.started"
    assert json.loads(lines[1])["sequence"] == 2
    assert json.loads(lines[1])["type"] == "workflow.completed"
    assert event["sequence"] == 2


def test_append_event_preserves_valid_final_jsonl_line_without_newline(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    events_path = tmp_path / ".openbbq" / "state" / "workflows" / "text-demo" / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(
        '{"id":"evt_1","sequence":1,"workflow_id":"text-demo","type":"workflow.started"}',
        encoding="utf-8",
    )

    event = store.append_event("text-demo", {"type": "workflow.completed", "message": "done"})

    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["type"] == "workflow.started"
    assert json.loads(lines[1])["sequence"] == 2
    assert event["sequence"] == 2


def test_write_workflow_state_overrides_conflicting_id(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    state = store.write_workflow_state("text-demo", {"id": "wrong-workflow", "status": "running"})

    assert state["id"] == "text-demo"
    persisted = json.loads(
        (tmp_path / ".openbbq" / "state" / "workflows" / "text-demo" / "state.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted["id"] == "text-demo"


def test_write_step_run_overrides_conflicting_workflow_id(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    step_run = store.write_step_run(
        "text-demo",
        {"id": "sr_2", "workflow_id": "wrong-workflow", "status": "running"},
    )

    assert step_run["workflow_id"] == "text-demo"
    persisted = json.loads(
        (
            tmp_path / ".openbbq" / "state" / "workflows" / "text-demo" / "step-runs" / "sr_2.json"
        ).read_text(encoding="utf-8")
    )
    assert persisted["workflow_id"] == "text-demo"


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
    assert step_run["id"] == "sr_fixed"
    assert event["id"] == "evt_fixed"


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
    assert loaded.record["artifact_id"] == artifact.id


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
    assert [record["name"] for record in artifacts] == ["seed.text"]
    assert store.read_artifact(artifact.id)["current_version_id"] is not None

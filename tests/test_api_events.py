from pathlib import Path

from fastapi.testclient import TestClient

from openbbq.api.app import ApiAppSettings, create_app
from openbbq.api.routes.events import format_sse
from openbbq.storage.models import WorkflowEvent


def write_project(tmp_path, fixture_name: str) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path(f"tests/fixtures/projects/{fixture_name}/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )
    return project


def test_format_sse_serializes_pydantic_event():
    event = WorkflowEvent(
        id="evt_1",
        workflow_id="demo",
        sequence=1,
        type="workflow.started",
        created_at="2026-04-25T00:00:00+00:00",
    )

    rendered = format_sse(event)

    assert rendered.startswith("id: 1\n")
    assert "event: workflow.started\n" in rendered
    assert '"workflow_id":"demo"' in rendered


def test_events_history_route_replays_after_sequence(tmp_path):
    project = write_project(tmp_path, "text-basic")
    client = TestClient(
        create_app(
            ApiAppSettings(project_root=project, token="token", execute_runs_inline=True)
        )
    )
    headers = {"Authorization": "Bearer token"}
    client.post(
        "/workflows/text-demo/runs",
        headers=headers,
        json={"project_root": str(project), "workflow_id": "text-demo"},
    )

    response = client.get("/workflows/text-demo/events?after_sequence=1", headers=headers)

    assert response.status_code == 200
    assert all(event["sequence"] > 1 for event in response.json()["data"]["events"])

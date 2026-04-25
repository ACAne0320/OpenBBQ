from openbbq.api.routes.events import format_sse
from openbbq.storage.models import WorkflowEvent
from tests.helpers import authed_client, write_project_fixture


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
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project)
    client.post(
        "/workflows/text-demo/runs",
        headers=headers,
        json={"project_root": str(project), "workflow_id": "text-demo"},
    )

    response = client.get("/workflows/text-demo/events?after_sequence=1", headers=headers)

    assert response.status_code == 200
    assert all(event["sequence"] > 1 for event in response.json()["data"]["events"])

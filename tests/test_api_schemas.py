from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from openbbq.api.schemas import (
    ApiError,
    ApiErrorResponse,
    ApiSuccess,
    ArtifactImportData,
    ArtifactListData,
    HealthData,
    RunCreateRequest,
    RunRecord,
    WorkflowEventsData,
    WorkflowListData,
    WorkflowSummary,
)
from openbbq.storage.models import (
    ArtifactRecord,
    ArtifactVersionRecord,
    WorkflowEvent,
    WorkflowState,
)


def test_api_success_envelope_validates_payload():
    response = ApiSuccess[HealthData](
        data=HealthData(version="0.1.0", pid=123, project_root=Path("/tmp/project"))
    )

    assert response.model_dump(mode="json") == {
        "ok": True,
        "data": {
            "version": "0.1.0",
            "pid": 123,
            "project_root": "/tmp/project",
        },
    }


def test_api_error_response_includes_details():
    response = ApiErrorResponse(
        error=ApiError(
            code="validation_error",
            message="Project config is invalid.",
            details={"field": "project.name"},
        )
    )

    assert response.ok is False
    assert response.error.details == {"field": "project.name"}


def test_run_create_request_rejects_force_with_step_id():
    with pytest.raises(PydanticValidationError, match="force cannot be combined"):
        RunCreateRequest(
            project_root=Path("/tmp/project"),
            workflow_id="demo",
            force=True,
            step_id="translate",
        )


def test_run_record_uses_known_statuses():
    record = RunRecord(
        id="run_abc",
        workflow_id="demo",
        mode="start",
        status="queued",
        project_root=Path("/tmp/project"),
        latest_event_sequence=0,
        created_by="api",
    )

    assert record.status == "queued"


def test_workflow_list_data_serializes_state_and_events():
    state = WorkflowState(id="demo", name="Demo", status="pending")
    summary = WorkflowSummary(
        id="demo",
        name="Demo",
        steps=(),
        state=state,
        latest_event_sequence=3,
    )
    event = WorkflowEvent(
        id="evt_1",
        workflow_id="demo",
        sequence=3,
        type="workflow.completed",
        created_at="2026-04-25T00:00:00+00:00",
    )

    workflows = WorkflowListData(workflows=(summary,))
    events = WorkflowEventsData(workflow_id="demo", events=(event,))

    assert workflows.model_dump(mode="json")["workflows"][0]["state"]["status"] == "pending"
    assert events.model_dump(mode="json")["events"][0]["sequence"] == 3


def test_artifact_api_data_serializes_records(tmp_path):
    artifact = ArtifactRecord(
        id="art_1",
        type="text",
        name="demo.text",
        versions=("ver_1",),
        current_version_id="ver_1",
        created_at="2026-04-25T00:00:00+00:00",
        updated_at="2026-04-25T00:00:00+00:00",
    )
    version = ArtifactVersionRecord(
        id="ver_1",
        artifact_id="art_1",
        version_number=1,
        content_path=tmp_path / "content",
        content_hash="abc",
        content_encoding="text",
        content_size=5,
        created_at="2026-04-25T00:00:00+00:00",
    )

    listed = ArtifactListData(artifacts=(artifact,))
    imported = ArtifactImportData(artifact=artifact, version=version)

    assert listed.model_dump(mode="json")["artifacts"][0]["id"] == "art_1"
    assert imported.model_dump(mode="json")["version"]["content_path"].endswith("content")

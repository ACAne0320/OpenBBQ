from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from openbbq.api.schemas import (
    ApiError,
    ApiErrorResponse,
    ApiSuccess,
    HealthData,
    RunCreateRequest,
    RunRecord,
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

from openbbq.application.workflows import (
    WorkflowRunRequest,
    run_workflow_command,
    workflow_events,
    workflow_status,
)
from tests.helpers import write_project_fixture


def test_workflow_application_service_runs_and_reports_status(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")

    result = run_workflow_command(WorkflowRunRequest(project_root=project, workflow_id="text-demo"))
    status = workflow_status(project_root=project, workflow_id="text-demo")

    assert result.status == "completed"
    assert status.status == "completed"


def test_workflow_events_returns_events_after_sequence(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    run_workflow_command(WorkflowRunRequest(project_root=project, workflow_id="text-demo"))

    result = workflow_events(project_root=project, workflow_id="text-demo", after_sequence=1)

    assert result.workflow_id == "text-demo"
    assert all(event.sequence > 1 for event in result.events)

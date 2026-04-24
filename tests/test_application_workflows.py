from pathlib import Path

from openbbq.application.workflows import (
    WorkflowRunRequest,
    run_workflow_command,
    workflow_events,
    workflow_status,
)


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


def test_workflow_application_service_runs_and_reports_status(tmp_path):
    project = write_project(tmp_path, "text-basic")

    result = run_workflow_command(WorkflowRunRequest(project_root=project, workflow_id="text-demo"))
    status = workflow_status(project_root=project, workflow_id="text-demo")

    assert result.status == "completed"
    assert status.status == "completed"


def test_workflow_events_returns_events_after_sequence(tmp_path):
    project = write_project(tmp_path, "text-basic")
    run_workflow_command(WorkflowRunRequest(project_root=project, workflow_id="text-demo"))

    result = workflow_events(project_root=project, workflow_id="text-demo", after_sequence=1)

    assert result.workflow_id == "text-demo"
    assert all(event.sequence > 1 for event in result.events)

from pathlib import Path

from openbbq.application.runs import RunCreateRequest, abort_run, create_run, get_run, resume_run
from openbbq.application.workflows import workflow_status


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


def test_create_run_executes_workflow_with_sync_executor(tmp_path):
    project = write_project(tmp_path, "text-basic")

    created = create_run(
        RunCreateRequest(project_root=project, workflow_id="text-demo"),
        execute_inline=True,
    )
    loaded = get_run(project_root=project, run_id=created.id)

    assert created.workflow_id == "text-demo"
    assert loaded.status == "completed"
    assert loaded.latest_event_sequence > 0


def test_resume_run_updates_run_record_to_final_workflow_status(tmp_path):
    project = write_project(tmp_path, "text-pause")

    created = create_run(
        RunCreateRequest(project_root=project, workflow_id="text-demo"),
        execute_inline=True,
    )
    resumed = resume_run(project_root=project, run_id=created.id)
    loaded = get_run(project_root=project, run_id=created.id)

    assert workflow_status(project_root=project, workflow_id="text-demo").status == "completed"
    assert resumed.status == "completed"
    assert loaded.status == "completed"
    assert loaded.completed_at is not None
    assert loaded.latest_event_sequence > created.latest_event_sequence


def test_abort_paused_run_updates_run_record_to_aborted(tmp_path):
    project = write_project(tmp_path, "text-pause")

    created = create_run(
        RunCreateRequest(project_root=project, workflow_id="text-demo"),
        execute_inline=True,
    )
    aborted = abort_run(project_root=project, run_id=created.id)
    loaded = get_run(project_root=project, run_id=created.id)

    assert workflow_status(project_root=project, workflow_id="text-demo").status == "aborted"
    assert aborted.status == "aborted"
    assert loaded.status == "aborted"
    assert loaded.completed_at is not None
    assert loaded.latest_event_sequence > created.latest_event_sequence

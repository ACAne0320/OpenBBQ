from pathlib import Path

from openbbq.application.runs import RunCreateRequest, create_run, get_run


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

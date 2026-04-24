import json
from pathlib import Path

from openbbq.cli.app import main
from openbbq.workflow.locks import workflow_lock_path
from openbbq.storage.project_store import ProjectStore


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


def test_cli_run_status_resume_control_flow(tmp_path, capsys):
    project = write_project(tmp_path, "text-pause")

    assert main(["--project", str(project), "--json", "run", "text-demo"]) == 0
    run_payload = json.loads(capsys.readouterr().out)
    assert run_payload["status"] == "paused"

    assert main(["--project", str(project), "--json", "status", "text-demo"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["status"] == "paused"
    assert status_payload["current_step_id"] == "uppercase"

    assert main(["--project", str(project), "--json", "resume", "text-demo"]) == 0
    resume_payload = json.loads(capsys.readouterr().out)
    assert resume_payload["status"] == "completed"


def test_cli_abort_paused_workflow_and_reject_resume(tmp_path, capsys):
    project = write_project(tmp_path, "text-pause")

    assert main(["--project", str(project), "--json", "run", "text-demo"]) == 0
    capsys.readouterr()
    assert main(["--project", str(project), "--json", "abort", "text-demo"]) == 0
    abort_payload = json.loads(capsys.readouterr().out)
    assert abort_payload["status"] == "aborted"

    assert main(["--project", str(project), "--json", "resume", "text-demo"]) == 1
    error_payload = json.loads(capsys.readouterr().out)
    assert error_payload["ok"] is False
    assert error_payload["error"]["code"] == "invalid_workflow_state"


def test_cli_unlock_stale_lock_with_yes(tmp_path, capsys):
    project = write_project(tmp_path, "text-basic")
    store = ProjectStore(project / ".openbbq")
    lock_path = workflow_lock_path(store, "text-demo")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text('{"pid":999999999,"workflow_id":"text-demo"}', encoding="utf-8")

    code = main(["--project", str(project), "--json", "unlock", "text-demo", "--yes"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "workflow_id": "text-demo",
        "unlocked": True,
        "pid": 999999999,
        "stale": True,
    }
    assert not lock_path.exists()


def test_cli_abort_running_workflow_writes_request(tmp_path, capsys):
    from openbbq.workflow.aborts import abort_request_path

    project = write_project(tmp_path, "text-basic")
    store = ProjectStore(project / ".openbbq")
    store.write_workflow_state(
        "text-demo",
        {
            "name": "Text Demo",
            "status": "running",
            "current_step_id": "uppercase",
            "step_run_ids": [],
        },
    )

    code = main(["--project", str(project), "--json", "abort", "text-demo"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "workflow_id": "text-demo",
        "status": "abort_requested",
    }
    assert abort_request_path(store, "text-demo").exists()
    assert store.read_workflow_state("text-demo").status == "running"


def test_cli_run_force_reruns_completed_workflow(tmp_path, capsys):
    project = write_project(tmp_path, "text-basic")

    assert main(["--project", str(project), "--json", "run", "text-demo"]) == 0
    capsys.readouterr()
    code = main(["--project", str(project), "--json", "run", "text-demo", "--force"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["workflow_id"] == "text-demo"
    assert payload["status"] == "completed"
    store = ProjectStore(project / ".openbbq")
    assert [len(artifact.versions) for artifact in store.list_artifacts()] == [2, 2]


def test_cli_run_step_reruns_one_step(tmp_path, capsys):
    project = write_project(tmp_path, "text-basic")

    assert main(["--project", str(project), "--json", "run", "text-demo"]) == 0
    capsys.readouterr()
    code = main(["--project", str(project), "--json", "run", "text-demo", "--step", "seed"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["workflow_id"] == "text-demo"
    assert payload["status"] == "completed"
    store = ProjectStore(project / ".openbbq")
    assert [len(artifact.versions) for artifact in store.list_artifacts()] == [2, 1]

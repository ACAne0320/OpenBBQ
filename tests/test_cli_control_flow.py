import json
from pathlib import Path

from openbbq.cli import main


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

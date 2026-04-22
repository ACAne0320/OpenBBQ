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


def test_phase1_scenario_a_run_to_completion_and_inspect(tmp_path, capsys):
    project = write_project(tmp_path, "text-basic")

    assert main(["--project", str(project), "--json", "validate", "text-demo"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert main(["--project", str(project), "--json", "plugin", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["plugins"][0]["name"] == "mock_text"

    assert main(["--project", str(project), "--json", "run", "text-demo"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"

    assert main(["--project", str(project), "--json", "status", "text-demo"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"

    assert main(["--project", str(project), "--json", "artifact", "list"]) == 0
    artifacts = json.loads(capsys.readouterr().out)["artifacts"]
    assert [artifact["name"] for artifact in artifacts] == ["seed.text", "uppercase.text"]

    assert main(["--project", str(project), "--json", "artifact", "show", artifacts[-1]["id"]]) == 0
    assert json.loads(capsys.readouterr().out)["current_version"]["content"] == "HELLO OPENBBQ"

    assert main(["--project", str(project), "--json", "run", "text-demo"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_workflow_state"


def test_phase1_scenario_b_pause_status_resume(tmp_path, capsys):
    project = write_project(tmp_path, "text-pause")

    assert main(["--project", str(project), "--json", "run", "text-demo"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "paused"

    assert main(["--project", str(project), "--json", "status", "text-demo"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["status"] == "paused"
    assert status["current_step_id"] == "uppercase"

    assert main(["--project", str(project), "--json", "resume", "text-demo"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"

    assert main(["--project", str(project), "--json", "artifact", "list"]) == 0
    artifacts = json.loads(capsys.readouterr().out)["artifacts"]
    assert [artifact["name"] for artifact in artifacts] == ["seed.text", "uppercase.text"]


def test_phase1_scenario_c_abort_paused_workflow(tmp_path, capsys):
    project = write_project(tmp_path, "text-pause")

    assert main(["--project", str(project), "--json", "run", "text-demo"]) == 0
    capsys.readouterr()

    assert main(["--project", str(project), "--json", "abort", "text-demo"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "aborted"

    assert main(["--project", str(project), "--json", "status", "text-demo"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "aborted"

    assert main(["--project", str(project), "--json", "resume", "text-demo"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_workflow_state"

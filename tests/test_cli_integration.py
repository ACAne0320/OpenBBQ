import json
from pathlib import Path

from openbbq.cli.app import main


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


def test_validate_json_success(tmp_path, capsys):
    project = write_project(tmp_path, "text-basic")

    code = main(["--project", str(project), "--json", "validate", "text-demo"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["workflow_id"] == "text-demo"
    assert payload["step_count"] == 2


def test_validate_json_failure(tmp_path, capsys):
    project = write_project(tmp_path, "text-basic")

    code = main(["--project", str(project), "--json", "validate", "missing"])

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "validation_error"


def test_run_status_logs_and_artifact_show(tmp_path, capsys):
    project = write_project(tmp_path, "text-basic")

    assert main(["--project", str(project), "run", "text-demo"]) == 0
    capsys.readouterr()
    assert main(["--project", str(project), "--json", "status", "text-demo"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["status"] == "completed"

    assert main(["--project", str(project), "--json", "logs", "text-demo"]) == 0
    logs = json.loads(capsys.readouterr().out)
    assert logs["ok"] is True
    assert logs["events"][0]["type"] == "workflow.started"

    assert main(["--project", str(project), "--json", "artifact", "list"]) == 0
    artifact_list = json.loads(capsys.readouterr().out)
    assert [artifact["name"] for artifact in artifact_list["artifacts"]] == [
        "seed.text",
        "uppercase.text",
    ]

    artifact_id = artifact_list["artifacts"][-1]["id"]
    assert main(["--project", str(project), "--json", "artifact", "show", artifact_id]) == 0
    artifact = json.loads(capsys.readouterr().out)
    assert artifact["artifact"]["name"] == "uppercase.text"
    assert artifact["current_version"]["content"] == "HELLO OPENBBQ"


def test_status_before_first_run_reports_pending(tmp_path, capsys):
    project = write_project(tmp_path, "text-basic")

    code = main(["--project", str(project), "--json", "status", "text-demo"])

    assert code == 0
    status = json.loads(capsys.readouterr().out)
    assert status["ok"] is True
    assert status["id"] == "text-demo"
    assert status["status"] == "pending"
    assert status["current_step_id"] == "seed"
    assert status["step_run_ids"] == []


def test_status_rejects_unknown_workflow(tmp_path, capsys):
    project = write_project(tmp_path, "text-basic")

    code = main(["--project", str(project), "--json", "status", "missing"])

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "validation_error"
    assert "missing" in payload["error"]["message"]


def test_project_and_plugin_info(tmp_path, capsys):
    project = write_project(tmp_path, "text-basic")

    assert main(["--project", str(project), "--json", "project", "info"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["project"]["name"] == "Text Basic"
    assert info["workflow_count"] == 1

    assert main(["--project", str(project), "--json", "plugin", "list"]) == 0
    plugins = json.loads(capsys.readouterr().out)
    assert plugins["plugins"][0]["name"] == "mock_text"

    assert main(["--project", str(project), "--json", "plugin", "info", "mock_text"]) == 0
    plugin = json.loads(capsys.readouterr().out)
    assert [tool["name"] for tool in plugin["plugin"]["tools"]] == [
        "echo",
        "uppercase",
        "glossary_replace",
        "translate",
        "subtitle_export",
        "flaky_echo",
        "always_fail",
    ]

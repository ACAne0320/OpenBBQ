from pathlib import Path

import pytest

from openbbq.config import load_project_config
from openbbq.engine import run_workflow
from openbbq.errors import ExecutionError
from openbbq.plugins import discover_plugins
from openbbq.storage import ProjectStore


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


def test_run_text_workflow_to_completion(tmp_path):
    project = write_project(tmp_path, "text-basic")
    config = load_project_config(project)

    result = run_workflow(config, discover_plugins(config.plugin_paths), "text-demo")

    assert result.status == "completed"
    store = ProjectStore(project / ".openbbq")
    artifacts = store.list_artifacts()
    assert [artifact["name"] for artifact in artifacts] == ["seed.text", "uppercase.text"]
    latest = store.read_artifact_version(artifacts[-1]["current_version_id"])
    assert latest.content == "HELLO OPENBBQ"

    state = store.read_workflow_state("text-demo")
    assert state["status"] == "completed"
    assert len(state["step_run_ids"]) == 2


def test_run_rejects_completed_workflow(tmp_path):
    project = write_project(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    run_workflow(config, registry, "text-demo")

    with pytest.raises(ExecutionError, match="completed"):
        run_workflow(config, registry, "text-demo")

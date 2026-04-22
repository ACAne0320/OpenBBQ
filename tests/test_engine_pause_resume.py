from pathlib import Path

import pytest

from openbbq.config import load_project_config
from openbbq.engine import resume_workflow, run_workflow
from openbbq.errors import ExecutionError, ValidationError
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


def test_run_pauses_before_step_and_resume_completes(tmp_path):
    project = write_project(tmp_path, "text-pause")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)

    paused = run_workflow(config, registry, "text-demo")

    assert paused.status == "paused"
    store = ProjectStore(project / ".openbbq")
    state = store.read_workflow_state("text-demo")
    assert state["status"] == "paused"
    assert state["current_step_id"] == "uppercase"
    assert len(state["step_run_ids"]) == 1
    assert store.read_step_run("text-demo", state["step_run_ids"][0])["step_id"] == "seed"

    resumed = resume_workflow(config, registry, "text-demo")

    assert resumed.status == "completed"
    artifacts = store.list_artifacts()
    assert [artifact["name"] for artifact in artifacts] == ["seed.text", "uppercase.text"]
    latest = store.read_artifact_version(artifacts[-1]["current_version_id"])
    assert latest.content == "HELLO OPENBBQ"


def test_resume_rejects_non_paused_workflow(tmp_path):
    project = write_project(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    run_workflow(config, registry, "text-demo")

    with pytest.raises(ExecutionError, match="paused"):
        resume_workflow(config, registry, "text-demo")


def test_resume_rejects_config_drift(tmp_path):
    project = write_project(tmp_path, "text-pause")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    run_workflow(config, registry, "text-demo")
    config_path = project / "openbbq.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("hello openbbq", "changed"),
        encoding="utf-8",
    )
    drifted_config = load_project_config(project)
    drifted_registry = discover_plugins(drifted_config.plugin_paths)

    with pytest.raises(ValidationError, match="changed while paused"):
        resume_workflow(drifted_config, drifted_registry, "text-demo")


def test_run_rejects_paused_workflow_without_force(tmp_path):
    project = write_project(tmp_path, "text-pause")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    run_workflow(config, registry, "text-demo")

    with pytest.raises(ExecutionError, match="paused") as exc:
        run_workflow(config, registry, "text-demo")

    assert exc.value.exit_code == 1

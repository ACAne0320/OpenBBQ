import pytest

from openbbq.config.loader import load_project_config
from openbbq.engine.service import run_workflow
from openbbq.errors import ExecutionError
from openbbq.plugins.registry import discover_plugins
from openbbq.storage.project_store import ProjectStore
from tests.helpers import write_project_fixture


def test_run_text_workflow_to_completion(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    config = load_project_config(project)

    result = run_workflow(config, discover_plugins(config.plugin_paths), "text-demo")

    assert result.status == "completed"
    store = ProjectStore(project / ".openbbq")
    artifacts = store.list_artifacts()
    assert [artifact.name for artifact in artifacts] == ["seed.text", "uppercase.text"]
    assert artifacts[-1].current_version_id is not None
    latest = store.read_artifact_version(artifacts[-1].current_version_id)
    assert latest.content == "HELLO OPENBBQ"

    state = store.read_workflow_state("text-demo")
    assert state.status == "completed"
    assert len(state.step_run_ids) == 2
    events = store.read_events("text-demo")
    assert [event.type for event in events] == [
        "workflow.started",
        "step.started",
        "step.completed",
        "step.started",
        "step.completed",
        "workflow.completed",
    ]


def test_run_rejects_completed_workflow(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    run_workflow(config, registry, "text-demo")

    with pytest.raises(ExecutionError, match="completed"):
        run_workflow(config, registry, "text-demo")


def test_run_respects_custom_storage_paths(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    config_path = project / "openbbq.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "storage:\n  root: .openbbq\n",
            "storage:\n"
            "  root: runtime-root\n"
            "  artifacts: artifact-store\n"
            "  state: workflow-state\n",
        ),
        encoding="utf-8",
    )
    config = load_project_config(project)

    run_workflow(config, discover_plugins(config.plugin_paths), "text-demo")

    assert (project / "artifact-store").is_dir()
    assert (project / "runtime-root" / "openbbq.db").is_file()
    assert not (project / "workflow-state" / "workflows" / "text-demo" / "state.json").exists()
    assert not (project / "runtime-root" / "artifacts").exists()

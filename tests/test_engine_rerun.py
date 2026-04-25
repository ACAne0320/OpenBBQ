import pytest

from openbbq.config.loader import load_project_config
from openbbq.engine.service import run_workflow
from openbbq.errors import ExecutionError
from openbbq.plugins.registry import discover_plugins
from openbbq.storage.project_store import ProjectStore
from tests.helpers import write_project_fixture


def test_force_rerun_completed_workflow_reuses_artifact_ids_and_appends_versions(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    run_workflow(config, registry, "text-demo")
    store = ProjectStore(project / ".openbbq")
    first_artifacts = store.list_artifacts()
    first_ids = [artifact.id for artifact in first_artifacts]
    first_versions = [artifact.current_version_id for artifact in first_artifacts]

    result = run_workflow(config, registry, "text-demo", force=True)

    assert result.status == "completed"
    second_artifacts = store.list_artifacts()
    assert [artifact.id for artifact in second_artifacts] == first_ids
    assert [artifact.name for artifact in second_artifacts] == ["seed.text", "uppercase.text"]
    assert [artifact.current_version_id for artifact in second_artifacts] != first_versions
    assert [len(artifact.versions) for artifact in second_artifacts] == [2, 2]
    state = store.read_workflow_state("text-demo")
    assert state.status == "completed"
    assert len(state.step_run_ids) == 2


def test_force_rerun_crash_recovered_running_marks_dangling_step_run_failed(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    store = ProjectStore(project / ".openbbq")
    store.write_step_run(
        "text-demo",
        {
            "id": "sr_dangling",
            "step_id": "seed",
            "attempt": 1,
            "status": "running",
            "input_artifact_version_ids": {},
            "output_bindings": {},
        },
    )
    store.write_workflow_state(
        "text-demo",
        {
            "name": "Text Demo",
            "status": "running",
            "current_step_id": "seed",
            "step_run_ids": ["sr_dangling"],
        },
    )

    result = run_workflow(config, registry, "text-demo", force=True)

    assert result.status == "completed"
    dangling = store.read_step_run("text-demo", "sr_dangling")
    assert dangling.status == "failed"
    assert dangling.error is not None
    assert dangling.error.code == "engine.crash_recovery"
    assert store.read_workflow_state("text-demo").status == "completed"


def test_step_rerun_completed_workflow_updates_only_target_step_outputs(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    run_workflow(config, registry, "text-demo")
    store = ProjectStore(project / ".openbbq")
    first_artifacts = {artifact.name: artifact for artifact in store.list_artifacts()}

    result = run_workflow(config, registry, "text-demo", step_id="seed")

    assert result.status == "completed"
    second_artifacts = {artifact.name: artifact for artifact in store.list_artifacts()}
    assert second_artifacts["seed.text"].id == first_artifacts["seed.text"].id
    assert second_artifacts["uppercase.text"].id == first_artifacts["uppercase.text"].id
    assert len(second_artifacts["seed.text"].versions) == 2
    assert len(second_artifacts["uppercase.text"].versions) == 1
    assert (
        second_artifacts["seed.text"].current_version_id
        != first_artifacts["seed.text"].current_version_id
    )
    assert (
        second_artifacts["uppercase.text"].current_version_id
        == first_artifacts["uppercase.text"].current_version_id
    )
    state = store.read_workflow_state("text-demo")
    assert state.status == "completed"
    assert len(state.step_run_ids) == 3


def test_step_rerun_rejects_paused_workflow(tmp_path):
    project = write_project_fixture(tmp_path, "text-pause")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    run_workflow(config, registry, "text-demo")

    with pytest.raises(ExecutionError, match="paused"):
        run_workflow(config, registry, "text-demo", step_id="uppercase")

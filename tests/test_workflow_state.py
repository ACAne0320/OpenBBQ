from pathlib import Path

import pytest

from openbbq.config.loader import load_project_config
from openbbq.workflow.state import (
    build_pending_state,
    compute_workflow_config_hash,
    read_effective_workflow_state,
    rebuild_output_bindings,
    require_status,
)
from openbbq.errors import ExecutionError
from openbbq.storage.project_store import ProjectStore


def test_build_pending_state_for_missing_workflow_state():
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    workflow = config.workflows["text-demo"]

    state = build_pending_state(workflow)

    assert state["id"] == "text-demo"
    assert state["status"] == "pending"
    assert state["current_step_id"] == "seed"
    assert state["step_run_ids"] == []


def test_read_effective_workflow_state_returns_pending_when_missing(tmp_path):
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    workflow = config.workflows["text-demo"]
    store = ProjectStore(tmp_path / ".openbbq")

    state = read_effective_workflow_state(store, workflow)

    assert state["status"] == "pending"
    assert state["current_step_id"] == "seed"


def test_compute_workflow_config_hash_changes_when_step_parameters_change(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = Path("tests/fixtures/projects/text-basic/openbbq.yaml").read_text(encoding="utf-8")
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )
    first = load_project_config(project)
    config_path = project / "openbbq.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("hello openbbq", "changed"),
        encoding="utf-8",
    )
    second = load_project_config(project)

    assert compute_workflow_config_hash(first, "text-demo") != compute_workflow_config_hash(
        second, "text-demo"
    )


def test_require_status_rejects_unexpected_status():
    with pytest.raises(ExecutionError, match="paused") as exc:
        require_status({"status": "completed"}, "paused", "text-demo")

    assert exc.value.exit_code == 1


def test_rebuild_output_bindings_uses_completed_step_runs(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    _, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello openbbq",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo"},
    )
    step_run = store.write_step_run(
        "text-demo",
        {
            "step_id": "seed",
            "attempt": 1,
            "status": "completed",
            "output_bindings": {
                "text": {
                    "artifact_id": version.artifact_id,
                    "artifact_version_id": version.id,
                }
            },
        },
    )

    bindings = rebuild_output_bindings(store, "text-demo", [step_run["id"]])

    assert bindings["seed.text"]["artifact_version_id"] == version.id

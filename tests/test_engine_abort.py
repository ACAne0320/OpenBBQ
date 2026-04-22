import json
from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.engine.service import abort_workflow, run_workflow
from openbbq.plugins.registry import discover_plugins
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


def read_events(store: ProjectStore, workflow_id: str) -> list[dict]:
    events_path = store.state_root / workflow_id / "events.jsonl"
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_abort_running_workflow_writes_request_without_state_transition(tmp_path):
    from openbbq.workflow import aborts

    project = write_project(tmp_path, "text-basic")
    config = load_project_config(project)
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

    result = abort_workflow(config, "text-demo")

    assert result["status"] == "abort_requested"
    assert aborts.abort_request_path(store, "text-demo").exists()
    assert store.read_workflow_state("text-demo")["status"] == "running"


def test_run_processes_abort_request_between_steps(tmp_path):
    from openbbq.workflow import aborts

    project = write_project(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    store = ProjectStore(project / ".openbbq")
    aborts.write_abort_request(store, "text-demo")

    result = run_workflow(config, registry, "text-demo")

    assert result.status == "aborted"
    assert not aborts.abort_request_path(store, "text-demo").exists()
    state = store.read_workflow_state("text-demo")
    assert state["status"] == "aborted"
    assert state["current_step_id"] == "uppercase"
    assert [artifact["name"] for artifact in store.list_artifacts()] == ["seed.text"]
    assert [event["type"] for event in read_events(store, "text-demo")] == [
        "workflow.started",
        "step.started",
        "step.completed",
        "workflow.abort_requested",
        "workflow.aborted",
    ]

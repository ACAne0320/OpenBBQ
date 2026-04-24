import json
from pathlib import Path

import pytest

from openbbq.config.loader import load_project_config
from openbbq.engine.service import run_workflow
from openbbq.errors import ExecutionError
from openbbq.plugins.registry import discover_plugins
from openbbq.runtime.models import RuntimeContext
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


def test_runtime_context_is_passed_to_plugin_request_without_persistence(
    tmp_path,
    monkeypatch,
):
    from openbbq.workflow import execution

    captured = {}

    def fake_execute_plugin_tool(plugin, tool, request, redactor=None):
        captured["runtime"] = request.runtime
        return {
            "outputs": {
                "text": {
                    "type": "text",
                    "content": "hello",
                    "metadata": {},
                }
            }
        }

    monkeypatch.setattr(execution, "execute_plugin_tool", fake_execute_plugin_tool)
    project = write_project(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    context = RuntimeContext(redaction_values=("sk-secret",))

    result = run_workflow(config, registry, "text-demo", runtime_context=context)

    assert result.status == "completed"
    assert captured["runtime"] == context.request_payload()
    store = ProjectStore(project / ".openbbq")
    state = store.read_workflow_state("text-demo")
    step_run = store.read_step_run("text-demo", state.step_run_ids[0])
    assert not hasattr(step_run, "runtime")


def test_plugin_error_is_redacted_before_state_and_cli_error(tmp_path, monkeypatch):
    from openbbq.workflow import execution

    def fake_execute_plugin_tool(plugin, tool, request, redactor=None):
        raise execution.PluginError(redactor("failed with sk-secret"))

    monkeypatch.setattr(execution, "execute_plugin_tool", fake_execute_plugin_tool)
    project = write_project(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    context = RuntimeContext(redaction_values=("sk-secret",))

    with pytest.raises(ExecutionError) as exc:
        run_workflow(config, registry, "text-demo", runtime_context=context)

    assert "sk-secret" not in exc.value.message
    assert "[REDACTED]" in exc.value.message
    store = ProjectStore(project / ".openbbq")
    state = store.read_workflow_state("text-demo")
    step_run = store.read_step_run("text-demo", state.step_run_ids[0])
    assert step_run.error is not None
    assert "sk-secret" not in step_run.error.message


def test_plugin_events_are_wrapped_and_redacted(tmp_path, monkeypatch):
    from openbbq.workflow import execution

    def fake_execute_plugin_tool(plugin, tool, request, redactor=None):
        return {
            "outputs": {
                "text": {
                    "type": "text",
                    "content": "hello",
                    "metadata": {},
                }
            },
            "events": [
                {
                    "level": "warning",
                    "message": "provider returned sk-secret",
                    "data": {"provider": "test"},
                }
            ],
        }

    monkeypatch.setattr(execution, "execute_plugin_tool", fake_execute_plugin_tool)
    project = write_project(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    context = RuntimeContext(redaction_values=("sk-secret",))

    result = run_workflow(config, registry, "text-demo", runtime_context=context)

    assert result.status == "completed"
    events = [
        json.loads(line)
        for line in (project / ".openbbq/state/workflows/text-demo/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    plugin_events = [event for event in events if event["type"] == "plugin.event"]
    assert plugin_events[0]["level"] == "warning"
    assert plugin_events[0]["message"] == "provider returned [REDACTED]"
    assert plugin_events[0]["data"] == {"provider": "test"}

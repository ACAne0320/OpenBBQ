import json

import pytest

from openbbq.config.loader import load_project_config
from openbbq.engine.service import run_workflow
from openbbq.errors import ExecutionError
from openbbq.plugins.registry import discover_plugins
from openbbq.runtime.models import RuntimeContext
from openbbq.storage.project_store import ProjectStore
from tests.helpers import write_project_fixture


def test_runtime_context_is_passed_to_plugin_request_without_persistence(
    tmp_path,
    monkeypatch,
):
    from openbbq.workflow import steps

    captured = {}

    def fake_execute_plugin_tool(plugin, tool, request, redactor=None, progress=None):
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

    monkeypatch.setattr(steps, "execute_plugin_tool", fake_execute_plugin_tool)
    project = write_project_fixture(tmp_path, "text-basic")
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
    from openbbq.errors import PluginError
    from openbbq.workflow import steps

    def fake_execute_plugin_tool(plugin, tool, request, redactor=None, progress=None):
        raise PluginError(redactor("failed with sk-secret"))

    monkeypatch.setattr(steps, "execute_plugin_tool", fake_execute_plugin_tool)
    project = write_project_fixture(tmp_path, "text-basic")
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
    from openbbq.workflow import steps

    def fake_execute_plugin_tool(plugin, tool, request, redactor=None, progress=None):
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

    monkeypatch.setattr(steps, "execute_plugin_tool", fake_execute_plugin_tool)
    project = write_project_fixture(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    context = RuntimeContext(redaction_values=("sk-secret",))

    result = run_workflow(config, registry, "text-demo", runtime_context=context)

    assert result.status == "completed"
    store = ProjectStore(project / ".openbbq")
    plugin_events = [
        event for event in store.read_events("text-demo") if event.type == "plugin.event"
    ]
    assert plugin_events[0].level == "warning"
    assert plugin_events[0].message == "provider returned [REDACTED]"
    assert plugin_events[0].data == {"provider": "test"}


def test_workflow_progress_events_are_redacted_and_tolerate_invalid_percent(
    tmp_path,
    monkeypatch,
):
    from openbbq.workflow import steps

    def fake_execute_plugin_tool(plugin, tool, request, redactor=None, progress=None):
        assert progress is not None
        progress(
            phase="demo",
            label="provider sk-secret",
            percent="not-a-number",
            unit="items",
        )
        return {
            "outputs": {
                "text": {
                    "type": "text",
                    "content": "hello",
                    "metadata": {},
                }
            }
        }

    monkeypatch.setattr(steps, "execute_plugin_tool", fake_execute_plugin_tool)
    project = write_project_fixture(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    context = RuntimeContext(redaction_values=("sk-secret",))

    result = run_workflow(config, registry, "text-demo", runtime_context=context)

    assert result.status == "completed"
    store = ProjectStore(project / ".openbbq")
    fake_progress_events = [
        event
        for event in store.read_events("text-demo")
        if event.type == "step.progress"
        and event.data["progress"]["phase"] == "demo"
        and event.data["progress"]["label"] == "provider [REDACTED]"
    ]
    assert fake_progress_events
    for progress_event in fake_progress_events:
        assert progress_event.data["progress"]["percent"] == 0
        assert "sk-secret" not in (progress_event.message or "")
        assert "sk-secret" not in json.dumps(progress_event.data, sort_keys=True)

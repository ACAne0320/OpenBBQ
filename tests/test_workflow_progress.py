from pathlib import Path

from openbbq.plugins.execution import execute_plugin_tool
from openbbq.plugins.models import PluginSpec, ToolSpec
from openbbq.plugins.payloads import PluginRequest
from openbbq.storage.project_store import ProjectStore
from openbbq.workflow.progress import ProgressReporter


def test_progress_reporter_appends_clamped_step_progress_events(tmp_path: Path):
    store = ProjectStore(tmp_path / ".openbbq")
    reporter = ProgressReporter(
        store,
        workflow_id="demo",
        step_id="transcribe",
        attempt=1,
        min_percent_delta=1,
    )

    reporter.report(
        phase="asr_parse",
        label="ASR parsing",
        percent=-10,
        current=0,
        total=100,
        unit="seconds",
    )
    reporter.report(
        phase="asr_parse",
        label="ASR parsing",
        percent=42.4,
        current=42.4,
        total=100,
        unit="seconds",
    )
    reporter.report(
        phase="asr_parse",
        label="ASR parsing",
        percent=42.8,
        current=42.8,
        total=100,
        unit="seconds",
    )
    reporter.report(
        phase="asr_parse",
        label="ASR parsing",
        percent=120,
        current=100,
        total=100,
        unit="seconds",
    )

    events = store.read_events("demo")
    assert [event.type for event in events] == [
        "step.progress",
        "step.progress",
        "step.progress",
    ]
    assert [event.data["progress"]["percent"] for event in events] == [0, 42.4, 100]
    assert events[1].message == "ASR parsing 42%"
    assert events[1].step_id == "transcribe"
    assert events[1].attempt == 1


def test_progress_reporter_always_emits_phase_changes(tmp_path: Path):
    store = ProjectStore(tmp_path / ".openbbq")
    reporter = ProgressReporter(store, workflow_id="demo", step_id="download", attempt=1)

    reporter.report(phase="resolve", label="Resolve metadata", percent=5)
    reporter.report(phase="download", label="Download video", percent=5)

    events = store.read_events("demo")
    assert [event.data["progress"]["phase"] for event in events] == [
        "resolve",
        "download",
    ]


def _plugin(tmp_path: Path, source: str) -> PluginSpec:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text(source, encoding="utf-8")
    manifest_path = plugin_dir / "openbbq.plugin.toml"
    manifest_path.write_text("name = 'demo'\nversion = '1.0.0'\n", encoding="utf-8")
    return PluginSpec(
        name="demo",
        version="1.0.0",
        runtime="python",
        manifest_path=manifest_path,
        entrypoint="plugin:run",
    )


def _tool() -> ToolSpec:
    return ToolSpec(
        plugin_name="demo",
        name="demo",
        description="Demo tool.",
        input_artifact_types=[],
        output_artifact_types=["text"],
        parameter_schema={},
        effects=[],
        manifest_path=Path("openbbq.plugin.toml"),
    )


def _request(tmp_path: Path) -> PluginRequest:
    return PluginRequest(
        project_root=str(tmp_path),
        workflow_id="demo",
        step_id="step",
        attempt=1,
        tool_name="demo",
        parameters={},
        inputs={},
        work_dir=str(tmp_path / "work"),
    )


def test_execute_plugin_tool_passes_progress_callback_when_entrypoint_accepts_it(
    tmp_path: Path,
):
    plugin = _plugin(
        tmp_path,
        """
def run(request, progress=None):
    progress(phase="demo", label="Demo", percent=37)
    return {"outputs": {"out": {"type": "text", "content": "ok"}}}
""",
    )
    calls = []

    execute_plugin_tool(
        plugin,
        _tool(),
        _request(tmp_path),
        progress=lambda **payload: calls.append(payload),
    )

    assert calls == [{"phase": "demo", "label": "Demo", "percent": 37}]


def test_execute_plugin_tool_keeps_one_argument_plugins_compatible(tmp_path: Path):
    plugin = _plugin(
        tmp_path,
        """
def run(request):
    return {"outputs": {"out": {"type": "text", "content": "ok"}}}
""",
    )

    response = execute_plugin_tool(
        plugin,
        _tool(),
        _request(tmp_path),
        progress=lambda **payload: None,
    )

    assert response.outputs["out"].content == "ok"

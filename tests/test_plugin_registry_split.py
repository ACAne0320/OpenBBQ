from pathlib import Path
from textwrap import dedent
import importlib

import pytest

from openbbq.errors import PluginError
from openbbq.plugins.payloads import PluginRequest


PLUGIN_MODULES = (
    "openbbq.plugins.models",
    "openbbq.plugins.manifests",
    "openbbq.plugins.discovery",
    "openbbq.plugins.execution",
    "openbbq.plugins.registry",
)


def test_plugin_split_modules_are_importable():
    for module_name in PLUGIN_MODULES:
        importlib.import_module(module_name)


def test_registry_public_exports_remain_compatible():
    registry = importlib.import_module("openbbq.plugins.registry")
    models = importlib.import_module("openbbq.plugins.models")
    discovery = importlib.import_module("openbbq.plugins.discovery")
    execution = importlib.import_module("openbbq.plugins.execution")

    assert registry.ToolSpec is models.ToolSpec
    assert registry.PluginSpec is models.PluginSpec
    assert registry.InvalidPlugin is models.InvalidPlugin
    assert registry.PluginRegistry is models.PluginRegistry
    assert registry.discover_plugins is discovery.discover_plugins
    assert registry.execute_plugin_tool is execution.execute_plugin_tool


def test_manifest_parser_builds_plugin_spec_without_discovery(tmp_path):
    manifests = importlib.import_module("openbbq.plugins.manifests")
    models = importlib.import_module("openbbq.plugins.models")
    manifest_path = tmp_path / "openbbq.plugin.toml"

    plugin = manifests.parse_plugin_manifest(manifest_path, _manifest("demo", "echo"))

    assert isinstance(plugin, models.PluginSpec)
    assert plugin.name == "demo"
    assert plugin.manifest_path == manifest_path
    assert [tool.name for tool in plugin.tools] == ["echo"]
    assert plugin.tools[0].outputs["text"].artifact_type == "text"


def test_discovery_module_preserves_duplicate_warning(tmp_path):
    discovery = importlib.import_module("openbbq.plugins.discovery")
    first = _write_plugin(tmp_path / "first", _manifest_text("duplicate", "echo"))
    second = _write_plugin(tmp_path / "second", _manifest_text("duplicate", "echo"))

    registry = discovery.discover_plugins([first, second])

    assert list(registry.plugins) == ["duplicate"]
    assert registry.plugins["duplicate"].manifest_path == first / "openbbq.plugin.toml"
    assert registry.warnings == [
        "Duplicate plugin 'duplicate' at "
        f"{second / 'openbbq.plugin.toml'} ignored in favor of "
        f"{first / 'openbbq.plugin.toml'}."
    ]


def test_execution_module_preserves_plugin_error_redaction(tmp_path):
    discovery = importlib.import_module("openbbq.plugins.discovery")
    execution = importlib.import_module("openbbq.plugins.execution")
    plugin_dir = _write_plugin(
        tmp_path / "boom",
        _manifest_text("boom", "explode"),
        """
        def run(request):
            raise RuntimeError("secret failure")
        """,
    )
    registry = discovery.discover_plugins([plugin_dir])
    plugin = registry.plugins["boom"]
    tool = registry.tools["boom.explode"]
    request = PluginRequest(
        project_root=str(tmp_path),
        workflow_id="workflow",
        step_id="step",
        attempt=1,
        tool_name=tool.name,
        parameters={},
        inputs={},
        runtime={},
        work_dir=str(tmp_path / "work"),
    )

    with pytest.raises(PluginError) as exc:
        execution.execute_plugin_tool(
            plugin,
            tool,
            request,
            redactor=lambda message: message.replace("secret", "[REDACTED]"),
        )

    assert exc.value.message == "Plugin 'boom' tool 'explode' failed: [REDACTED] failure"


def test_execution_module_includes_underlying_exception_cause(tmp_path):
    discovery = importlib.import_module("openbbq.plugins.discovery")
    execution = importlib.import_module("openbbq.plugins.execution")
    plugin_dir = _write_plugin(
        tmp_path / "boom",
        _manifest_text("boom", "explode"),
        """
        def run(request):
            try:
                raise TimeoutError("read timed out")
            except TimeoutError as exc:
                raise RuntimeError("Connection error.") from exc
        """,
    )
    registry = discovery.discover_plugins([plugin_dir])
    plugin = registry.plugins["boom"]
    tool = registry.tools["boom.explode"]
    request = PluginRequest(
        project_root=str(tmp_path),
        workflow_id="workflow",
        step_id="step",
        attempt=1,
        tool_name=tool.name,
        parameters={},
        inputs={},
        runtime={},
        work_dir=str(tmp_path / "work"),
    )

    with pytest.raises(PluginError) as exc:
        execution.execute_plugin_tool(plugin, tool, request)

    assert exc.value.message == (
        "Plugin 'boom' tool 'explode' failed: Connection error. "
        "(caused by TimeoutError: read timed out)"
    )


def _manifest(plugin_name: str, tool_name: str) -> dict[str, object]:
    return {
        "name": plugin_name,
        "version": "0.1.0",
        "runtime": "python",
        "entrypoint": "plugin:run",
        "tools": [
            {
                "name": tool_name,
                "description": "Echo text.",
                "effects": [],
                "parameter_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                },
                "outputs": {
                    "text": {
                        "artifact_type": "text",
                        "description": "Echoed text.",
                    }
                },
            }
        ],
    }


def _manifest_text(plugin_name: str, tool_name: str) -> str:
    return f"""
        name = "{plugin_name}"
        version = "0.1.0"
        runtime = "python"
        entrypoint = "plugin:run"

        [[tools]]
        name = "{tool_name}"
        description = "Echo text."
        effects = []

        [tools.parameter_schema]
        type = "object"
        additionalProperties = false
        properties = {{}}

        [tools.outputs.text]
        artifact_type = "text"
        description = "Echoed text."
        """


def _write_plugin(directory: Path, manifest: str, plugin_py: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "openbbq.plugin.toml").write_text(dedent(manifest).lstrip(), encoding="utf-8")
    if plugin_py is not None:
        (directory / "plugin.py").write_text(dedent(plugin_py).lstrip(), encoding="utf-8")
    return directory

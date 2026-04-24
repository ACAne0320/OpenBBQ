from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError as PydanticValidationError

from openbbq.config.loader import load_project_config
from openbbq.plugins.registry import PluginRegistry, ToolSpec, discover_plugins


def _write_plugin(directory: Path, manifest: str, plugin_py: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "openbbq.plugin.toml").write_text(dedent(manifest).lstrip())
    if plugin_py is not None:
        (directory / "plugin.py").write_text(dedent(plugin_py).lstrip())
    return directory


def test_discovers_mock_text_tools_without_importing_plugin_code():
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    registry = discover_plugins(config.plugin_paths)
    assert "mock_text.uppercase" in registry.tools
    assert registry.tools["mock_text.uppercase"].output_artifact_types == ["text"]


def test_manifest_v2_declares_named_input_and_output_specs(tmp_path):
    plugin_dir = tmp_path / "plugins" / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "openbbq.plugin.toml").write_text(
        """
name = "demo"
version = "0.1.0"
runtime = "python"
entrypoint = "plugin:run"
manifest_version = 2

[[tools]]
name = "copy"
description = "Copy text."
effects = []

[tools.parameter_schema]
type = "object"
additionalProperties = false
properties = {}

[tools.inputs.text]
artifact_types = ["text"]
required = true
description = "Source text."

[tools.outputs.text]
artifact_type = "text"
description = "Copied text."
""",
        encoding="utf-8",
    )

    registry = discover_plugins([tmp_path / "plugins"])
    tool = registry.tools["demo.copy"]

    assert tool.inputs["text"].artifact_types == ("text",)
    assert tool.inputs["text"].required is True
    assert tool.outputs["text"].artifact_type == "text"


def test_tool_spec_rejects_non_object_parameter_schema(tmp_path):
    with pytest.raises(PydanticValidationError) as exc:
        ToolSpec(
            plugin_name="demo",
            name="echo",
            description="Echo text.",
            input_artifact_types=[],
            output_artifact_types=["text"],
            parameter_schema=[],
            effects=[],
            manifest_path=tmp_path / "openbbq.plugin.toml",
        )

    assert "parameter_schema" in str(exc.value)


def test_plugin_registry_defaults_to_empty_collections():
    registry = PluginRegistry()

    assert registry.plugins == {}
    assert registry.tools == {}
    assert registry.invalid_plugins == []
    assert registry.warnings == []


def test_discovers_plugin_roots_and_child_directories(tmp_path):
    direct = _write_plugin(
        tmp_path / "direct-plugin",
        """
        name = "direct"
        version = "0.1.0"
        runtime = "python"
        entrypoint = "plugin:run"

        [[tools]]
        name = "echo"
        description = "Echo text."
        effects = []

        [tools.parameter_schema]
        type = "object"
        additionalProperties = false
        properties = {}

        [tools.outputs.text]
        artifact_type = "text"
        description = "Echoed text."
        """,
    )
    _write_plugin(
        tmp_path / "bundle" / "child-plugin",
        """
        name = "child"
        version = "0.1.0"
        runtime = "python"
        entrypoint = "pkg.plugin:run"

        [[tools]]
        name = "echo"
        description = "Echo text."
        effects = []

        [tools.parameter_schema]
        type = "object"
        additionalProperties = false
        properties = {}

        [tools.outputs.text]
        artifact_type = "text"
        description = "Echoed text."
        """,
    )

    registry = discover_plugins([direct, tmp_path / "bundle"])

    assert "direct.echo" in registry.tools
    assert "child.echo" in registry.tools


def test_discovers_without_importing_plugin_code(tmp_path):
    plugin_dir = _write_plugin(
        tmp_path / "sentinel-plugin",
        """
        name = "sentinel"
        version = "0.1.0"
        runtime = "python"
        entrypoint = "plugin:run"

        [[tools]]
        name = "echo"
        description = "Echo text."
        effects = []

        [tools.parameter_schema]
        type = "object"
        additionalProperties = false
        properties = {}

        [tools.outputs.text]
        artifact_type = "text"
        description = "Echoed text."
        """,
        plugin_py="""
        raise AssertionError("plugin.py should not be imported during discovery")
        """,
    )

    registry = discover_plugins([plugin_dir])

    assert "sentinel.echo" in registry.tools


@pytest.mark.parametrize(
    ("manifest", "expected_error"),
    [
        (
            """
            name = "bad-semver"
            version = "1.0"
            runtime = "python"
            entrypoint = "plugin:run"

            [[tools]]
            name = "echo"
            description = "Echo text."
            effects = []

            [tools.parameter_schema]
            type = "object"
            additionalProperties = false
            properties = {}
            """,
            "semantic version",
        ),
        (
            """
            name = "bad-runtime"
            version = "0.1.0"
            runtime = "ruby"
            entrypoint = "plugin:run"

            [[tools]]
            name = "echo"
            description = "Echo text."
            effects = []

            [tools.parameter_schema]
            type = "object"
            additionalProperties = false
            properties = {}
            """,
            "unsupported runtime",
        ),
        (
            """
            name = "bad-entrypoint"
            version = "0.1.0"
            runtime = "python"
            entrypoint = "pkg..plugin:run"

            [[tools]]
            name = "echo"
            description = "Echo text."
            effects = []

            [tools.parameter_schema]
            type = "object"
            additionalProperties = false
            properties = {}
            """,
            "entrypoint",
        ),
        (
            """
            name = "duplicate-tools"
            version = "0.1.0"
            runtime = "python"
            entrypoint = "plugin:run"

            [[tools]]
            name = "echo"
            description = "Echo text."
            effects = []

            [tools.parameter_schema]
            type = "object"
            additionalProperties = false
            properties = {}

            [tools.outputs.text]
            artifact_type = "text"
            description = "Echoed text."

            [[tools]]
            name = "echo"
            description = "Echo text again."
            effects = []

            [tools.parameter_schema]
            type = "object"
            additionalProperties = false
            properties = {}

            [tools.outputs.text]
            artifact_type = "text"
            description = "Echoed text."
            """,
            "duplicate tool name",
        ),
        (
            """
            name = "empty-output-types"
            version = "0.1.0"
            runtime = "python"
            entrypoint = "plugin:run"

            [[tools]]
            name = "echo"
            description = "Echo text."
            effects = []

            [tools.parameter_schema]
            type = "object"
            additionalProperties = false
            properties = {}
            """,
            "outputs",
        ),
        (
            """
            name = "bad-schema"
            version = "0.1.0"
            runtime = "python"
            entrypoint = "plugin:run"

            [[tools]]
            name = "echo"
            description = "Echo text."
            effects = []

            [tools.parameter_schema]
            type = 123
            additionalProperties = false
            properties = {}

            [tools.outputs.text]
            artifact_type = "text"
            description = "Echoed text."
            """,
            "parameter_schema",
        ),
    ],
)
def test_reports_invalid_manifest_reasons(manifest: str, expected_error: str, tmp_path):
    plugin_dir = _write_plugin(tmp_path / "invalid-plugin", manifest)

    registry = discover_plugins([plugin_dir])

    assert registry.tools == {}
    assert registry.invalid_plugins[0].path == plugin_dir / "openbbq.plugin.toml"
    assert expected_error in registry.invalid_plugins[0].error.lower()


def test_reports_schema_error_details(tmp_path):
    plugin_dir = _write_plugin(
        tmp_path / "schema-plugin",
        """
        name = "schema-detail"
        version = "0.1.0"
        runtime = "python"
        entrypoint = "plugin:run"

        [[tools]]
        name = "echo"
        description = "Echo text."
        effects = []

        [tools.parameter_schema]
        type = 123
        additionalProperties = false
        properties = {}

        [tools.outputs.text]
        artifact_type = "text"
        description = "Echoed text."
        """,
    )

    registry = discover_plugins([plugin_dir])

    assert "parameter_schema" in registry.invalid_plugins[0].error
    assert "type" in registry.invalid_plugins[0].error.lower()

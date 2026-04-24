from __future__ import annotations

from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.domain.base import JsonObject, OpenBBQModel
from openbbq.errors import ValidationError
from openbbq.plugins.registry import discover_plugins


class PluginListResult(OpenBBQModel):
    plugins: tuple[JsonObject, ...]
    invalid_plugins: tuple[JsonObject, ...]
    warnings: tuple[str, ...]


class PluginInfoResult(OpenBBQModel):
    plugin: JsonObject


def plugin_list(
    *,
    project_root: Path,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> PluginListResult:
    config = load_project_config(
        project_root,
        config_path=config_path,
        extra_plugin_paths=plugin_paths,
    )
    registry = discover_plugins(config.plugin_paths)
    return PluginListResult(
        plugins=tuple(
            {
                "name": plugin.name,
                "version": plugin.version,
                "runtime": plugin.runtime,
                "manifest_path": str(plugin.manifest_path),
            }
            for plugin in registry.plugins.values()
        ),
        invalid_plugins=tuple(
            {"path": str(invalid.path), "error": invalid.error}
            for invalid in registry.invalid_plugins
        ),
        warnings=tuple(registry.warnings),
    )


def plugin_info(
    *,
    project_root: Path,
    plugin_name: str,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> PluginInfoResult:
    config = load_project_config(
        project_root,
        config_path=config_path,
        extra_plugin_paths=plugin_paths,
    )
    registry = discover_plugins(config.plugin_paths)
    plugin = registry.plugins.get(plugin_name)
    if plugin is None:
        raise ValidationError(f"Plugin '{plugin_name}' was not found.", exit_code=4)
    return PluginInfoResult(
        plugin={
            "name": plugin.name,
            "version": plugin.version,
            "runtime": plugin.runtime,
            "entrypoint": plugin.entrypoint,
            "manifest_path": str(plugin.manifest_path),
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_artifact_types": tool.input_artifact_types,
                    "output_artifact_types": tool.output_artifact_types,
                    "inputs": {
                        name: spec.model_dump(mode="json") for name, spec in tool.inputs.items()
                    },
                    "outputs": {
                        name: spec.model_dump(mode="json") for name, spec in tool.outputs.items()
                    },
                    "runtime_requirements": tool.runtime_requirements.model_dump(mode="json"),
                    "ui": tool.ui.model_dump(mode="json"),
                    "parameter_schema": tool.parameter_schema,
                    "effects": tool.effects,
                }
                for tool in plugin.tools
            ],
        }
    )

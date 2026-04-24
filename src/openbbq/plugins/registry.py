from __future__ import annotations

from collections.abc import Iterable
import importlib
import importlib.util
from pathlib import Path
import re
from types import ModuleType
from typing import Any
from uuid import uuid4

import tomllib
from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError
from pydantic import Field, field_validator
from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import JsonObject, OpenBBQModel, format_pydantic_error
from openbbq.errors import PluginError


SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$",
)
PYTHON_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
ENTRYPOINT_PATTERN = re.compile(
    rf"^{PYTHON_IDENTIFIER}(?:\.{PYTHON_IDENTIFIER})*:{PYTHON_IDENTIFIER}$",
)


class ToolSpec(OpenBBQModel):
    plugin_name: str
    name: str
    description: str
    input_artifact_types: list[str]
    output_artifact_types: list[str]
    parameter_schema: JsonObject
    effects: list[str]
    manifest_path: Path

    @field_validator("plugin_name", "name", "description")
    @classmethod
    def nonempty_string(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("input_artifact_types", "output_artifact_types", "effects")
    @classmethod
    def list_of_strings(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) for item in value):
            raise ValueError("must be a list of strings")
        return value

    @field_validator("output_artifact_types")
    @classmethod
    def nonempty_output_types(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("must not be empty")
        return value


class PluginSpec(OpenBBQModel):
    name: str
    version: str
    runtime: str
    entrypoint: str
    manifest_path: Path
    tools: tuple[ToolSpec, ...] = ()


class InvalidPlugin(OpenBBQModel):
    path: Path
    error: str


class PluginRegistry(OpenBBQModel):
    plugins: dict[str, PluginSpec] = Field(default_factory=dict)
    tools: dict[str, ToolSpec] = Field(default_factory=dict)
    invalid_plugins: list[InvalidPlugin] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def discover_plugins(plugin_paths: Iterable[Path | str]) -> PluginRegistry:
    registry = PluginRegistry()
    seen_manifests: set[Path] = set()

    for raw_path in plugin_paths:
        path = Path(raw_path)
        for manifest_path in _candidate_manifests(path):
            if manifest_path in seen_manifests:
                continue
            seen_manifests.add(manifest_path)
            _load_manifest(manifest_path, registry)

    return registry


def execute_plugin_tool(
    plugin: PluginSpec,
    tool: ToolSpec,
    request: dict[str, Any],
    redactor=None,
) -> dict[str, Any]:
    module_name, function_name = plugin.entrypoint.split(":", 1)
    module_path = plugin.manifest_path.parent / f"{module_name.replace('.', '/')}.py"
    if not module_path.is_file():
        raise PluginError(
            f"Plugin entrypoint module '{module_name}' was not found at {module_path}."
        )

    module = _load_plugin_module(plugin, module_path)
    entrypoint = getattr(module, function_name, None)
    if not callable(entrypoint):
        raise PluginError(
            f"Plugin '{plugin.name}' entrypoint '{plugin.entrypoint}' does not resolve to a callable.",
        )
    try:
        response = entrypoint(request)
    except Exception as exc:
        message = f"Plugin '{plugin.name}' tool '{tool.name}' failed: {exc}"
        if redactor is not None:
            message = redactor(message)
        raise PluginError(message) from exc
    if not isinstance(response, dict):
        raise PluginError(
            f"Plugin '{plugin.name}' tool '{tool.name}' returned a non-object response."
        )
    return response


def _load_plugin_module(plugin: PluginSpec, module_path: Path) -> ModuleType:
    builtin_module_name = _builtin_module_name(module_path)
    if builtin_module_name is not None:
        try:
            return importlib.import_module(builtin_module_name)
        except Exception as exc:
            raise PluginError(f"Plugin module '{module_path}' failed to import: {exc}") from exc

    unique_name = f"_openbbq_plugin_{plugin.name}_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(unique_name, module_path)
    if spec is None or spec.loader is None:
        raise PluginError(f"Plugin module '{module_path}' could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise PluginError(f"Plugin module '{module_path}' failed to import: {exc}") from exc
    return module


def _builtin_module_name(module_path: Path) -> str | None:
    try:
        from openbbq import builtin_plugins
    except ImportError:
        return None

    builtin_root_raw = getattr(builtin_plugins, "__file__", None)
    if builtin_root_raw is None:
        return None
    builtin_root = Path(builtin_root_raw).resolve().parent
    resolved_module = module_path.resolve()
    try:
        relative_module = resolved_module.relative_to(builtin_root).with_suffix("")
    except ValueError:
        return None
    return "openbbq.builtin_plugins." + ".".join(relative_module.parts)


def _candidate_manifests(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.name == "openbbq.plugin.toml" else []

    if not path.is_dir():
        return []

    direct_manifest = path / "openbbq.plugin.toml"
    if direct_manifest.is_file():
        return [direct_manifest]

    manifests: list[Path] = []
    for child in sorted(path.iterdir()):
        if child.is_dir():
            manifest = child / "openbbq.plugin.toml"
            if manifest.is_file():
                manifests.append(manifest)
    return manifests


def _load_manifest(manifest_path: Path, registry: PluginRegistry) -> None:
    try:
        with manifest_path.open("rb") as handle:
            manifest = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        registry.invalid_plugins.append(InvalidPlugin(path=manifest_path, error=str(exc)))
        return

    try:
        plugin = _parse_plugin_manifest(manifest_path, manifest)
    except ValueError as exc:
        registry.invalid_plugins.append(InvalidPlugin(path=manifest_path, error=str(exc)))
        return

    if plugin.name in registry.plugins:
        registry.warnings.append(
            f"Duplicate plugin '{plugin.name}' at {manifest_path} ignored in favor of "
            f"{registry.plugins[plugin.name].manifest_path}.",
        )
        return

    registry.plugins[plugin.name] = plugin
    for tool in plugin.tools:
        registry.tools[f"{plugin.name}.{tool.name}"] = tool


def _parse_plugin_manifest(manifest_path: Path, manifest: Any) -> PluginSpec:
    if not isinstance(manifest, dict):
        raise ValueError("Plugin manifest must contain a TOML table.")

    name = _require_nonempty_string(manifest.get("name"), "name")
    version = _require_nonempty_string(manifest.get("version"), "version")
    runtime = _require_nonempty_string(manifest.get("runtime"), "runtime")
    entrypoint = _require_nonempty_string(manifest.get("entrypoint"), "entrypoint")

    if not SEMVER_PATTERN.fullmatch(version):
        raise ValueError(f"Invalid semantic version '{version}'.")
    if runtime != "python":
        raise ValueError(f"Unsupported runtime '{runtime}'.")
    if not ENTRYPOINT_PATTERN.fullmatch(entrypoint):
        raise ValueError(f"Invalid entrypoint '{entrypoint}'.")

    tools_raw = manifest.get("tools")
    if not isinstance(tools_raw, list) or not tools_raw:
        raise ValueError("Plugin manifest must define at least one tool.")

    tools: list[ToolSpec] = []
    seen_tool_names: set[str] = set()
    for index, tool_raw in enumerate(tools_raw):
        tool = _parse_tool_manifest(manifest_path, name, index, tool_raw)
        if tool.name in seen_tool_names:
            raise ValueError(f"Duplicate tool name '{tool.name}' in plugin '{name}'.")
        seen_tool_names.add(tool.name)
        tools.append(tool)

    try:
        return PluginSpec(
            name=name,
            version=version,
            runtime=runtime,
            entrypoint=entrypoint,
            manifest_path=manifest_path,
            tools=tuple(tools),
        )
    except PydanticValidationError as exc:
        raise ValueError(format_pydantic_error("plugin manifest", exc)) from exc


def _parse_tool_manifest(
    manifest_path: Path, plugin_name: str, index: int, tool_raw: Any
) -> ToolSpec:
    if not isinstance(tool_raw, dict):
        raise ValueError(f"Tool entry {index} in plugin '{plugin_name}' must be a table.")

    name = _require_nonempty_string(tool_raw.get("name"), f"tools[{index}].name")
    description = _require_nonempty_string(
        tool_raw.get("description"), f"tools[{index}].description"
    )
    input_artifact_types = _require_string_list(
        tool_raw.get("input_artifact_types"),
        f"tools[{index}].input_artifact_types",
    )
    output_artifact_types = _require_string_list(
        tool_raw.get("output_artifact_types"),
        f"tools[{index}].output_artifact_types",
    )
    if not output_artifact_types:
        raise ValueError(f"tools[{index}].output_artifact_types must not be empty.")
    effects = _require_string_list(tool_raw.get("effects"), f"tools[{index}].effects")

    schema = tool_raw.get("parameter_schema")
    if not isinstance(schema, dict):
        raise ValueError(f"tools[{index}].parameter_schema must be a table.")
    try:
        tool = ToolSpec(
            plugin_name=plugin_name,
            name=name,
            description=description,
            input_artifact_types=input_artifact_types,
            output_artifact_types=output_artifact_types,
            parameter_schema=schema,
            effects=effects,
            manifest_path=manifest_path,
        )
    except PydanticValidationError as exc:
        raise ValueError(format_pydantic_error(f"tools[{index}]", exc)) from exc

    try:
        Draft7Validator.check_schema(tool.parameter_schema)
    except SchemaError as exc:
        raise ValueError(_format_schema_error(index, exc)) from exc

    return tool


def _require_nonempty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Plugin manifest field '{field_name}' must be a non-empty string.")
    return value


def _require_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"Plugin manifest field '{field_name}' must be a list of strings.")
    if any(not isinstance(item, str) for item in value):
        raise ValueError(f"Plugin manifest field '{field_name}' must be a list of strings.")
    return list(value)


def _format_schema_error(index: int, exc: SchemaError) -> str:
    details = [f"tools[{index}].parameter_schema is not a valid JSON Schema: {exc.message}"]
    schema_path = getattr(exc, "schema_path", None)
    if schema_path:
        details.append(f"schema path: {'/'.join(str(part) for part in schema_path)}")
    return " (" + ", ".join(details) + ")"

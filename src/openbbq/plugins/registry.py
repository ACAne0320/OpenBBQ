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
from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import format_pydantic_error
from openbbq.errors import PluginError
from openbbq.plugins.contracts import (
    RuntimeRequirementSpec,
    ToolInputSpec,
    ToolOutputSpec,
    ToolUiSpec,
)
from openbbq.plugins.models import InvalidPlugin, PluginRegistry, PluginSpec, ToolSpec
from openbbq.plugins.payloads import PluginRequest, PluginResponse


SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$",
)
PYTHON_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
ENTRYPOINT_PATTERN = re.compile(
    rf"^{PYTHON_IDENTIFIER}(?:\.{PYTHON_IDENTIFIER})*:{PYTHON_IDENTIFIER}$",
)


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
    request: PluginRequest,
    redactor=None,
) -> PluginResponse:
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
        response = entrypoint(request.model_dump(mode="json"))
    except Exception as exc:
        message = f"Plugin '{plugin.name}' tool '{tool.name}' failed: {exc}"
        if redactor is not None:
            message = redactor(message)
        raise PluginError(message) from exc
    if not isinstance(response, dict):
        raise PluginError(
            f"Plugin '{plugin.name}' tool '{tool.name}' returned a non-object response."
        )
    try:
        return PluginResponse.model_validate(response)
    except PydanticValidationError as exc:
        raise PluginError(
            f"Plugin '{plugin.name}' tool '{tool.name}' returned an invalid response: "
            f"{format_pydantic_error('response', exc)}"
        ) from exc


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
    effects = _require_string_list(tool_raw.get("effects"), f"tools[{index}].effects")

    schema = tool_raw.get("parameter_schema")
    if not isinstance(schema, dict):
        raise ValueError(f"tools[{index}].parameter_schema must be a table.")
    inputs = _parse_tool_inputs(tool_raw.get("inputs", {}), plugin_name, index)
    outputs = _parse_tool_outputs(tool_raw.get("outputs", {}), plugin_name, index)
    if not outputs:
        raise ValueError(f"tools[{index}].outputs must define at least one output.")
    input_artifact_types = sorted(
        {artifact_type for spec in inputs.values() for artifact_type in spec.artifact_types}
    )
    output_artifact_types = [spec.artifact_type for spec in outputs.values()]
    runtime_requirements = _parse_tool_runtime_requirements(
        tool_raw.get("runtime_requirements", {}), index
    )
    ui = _parse_tool_ui(tool_raw.get("ui", {}), index)
    try:
        tool = ToolSpec(
            plugin_name=plugin_name,
            name=name,
            description=description,
            input_artifact_types=input_artifact_types,
            output_artifact_types=output_artifact_types,
            inputs=inputs,
            outputs=outputs,
            runtime_requirements=runtime_requirements,
            ui=ui,
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


def _parse_tool_inputs(value: Any, plugin_name: str, index: int) -> dict[str, ToolInputSpec]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"tools[{index}].inputs in plugin '{plugin_name}' must be a table.")
    parsed: dict[str, ToolInputSpec] = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"tools[{index}].inputs contains an invalid input name.")
        if not isinstance(raw, dict):
            raise ValueError(f"tools[{index}].inputs.{name} must be a table.")
        try:
            parsed[name] = ToolInputSpec.model_validate(raw)
        except PydanticValidationError as exc:
            raise ValueError(format_pydantic_error(f"tools[{index}].inputs.{name}", exc)) from exc
    return parsed


def _parse_tool_outputs(value: Any, plugin_name: str, index: int) -> dict[str, ToolOutputSpec]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"tools[{index}].outputs in plugin '{plugin_name}' must be a table.")
    parsed: dict[str, ToolOutputSpec] = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"tools[{index}].outputs contains an invalid output name.")
        if not isinstance(raw, dict):
            raise ValueError(f"tools[{index}].outputs.{name} must be a table.")
        try:
            parsed[name] = ToolOutputSpec.model_validate(raw)
        except PydanticValidationError as exc:
            raise ValueError(format_pydantic_error(f"tools[{index}].outputs.{name}", exc)) from exc
    return parsed


def _parse_tool_runtime_requirements(value: Any, index: int) -> RuntimeRequirementSpec:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError(f"tools[{index}].runtime_requirements must be a table.")
    try:
        return RuntimeRequirementSpec.model_validate(value)
    except PydanticValidationError as exc:
        raise ValueError(
            format_pydantic_error(f"tools[{index}].runtime_requirements", exc)
        ) from exc


def _parse_tool_ui(value: Any, index: int) -> ToolUiSpec:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError(f"tools[{index}].ui must be a table.")
    try:
        return ToolUiSpec.model_validate(value)
    except PydanticValidationError as exc:
        raise ValueError(format_pydantic_error(f"tools[{index}].ui", exc)) from exc


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

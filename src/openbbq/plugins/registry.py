from __future__ import annotations

from collections.abc import Iterable
import importlib
import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import tomllib
from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import format_pydantic_error
from openbbq.errors import PluginError
from openbbq.plugins.manifests import parse_plugin_manifest
from openbbq.plugins.models import InvalidPlugin, PluginRegistry, PluginSpec, ToolSpec
from openbbq.plugins.payloads import PluginRequest, PluginResponse


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
        plugin = parse_plugin_manifest(manifest_path, manifest)
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

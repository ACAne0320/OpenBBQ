from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import tomllib

from openbbq.plugins.manifests import parse_plugin_manifest
from openbbq.plugins.models import InvalidPlugin, PluginRegistry


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

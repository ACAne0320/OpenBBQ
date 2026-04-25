from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
import os

from openbbq.config.raw import optional_mapping
from openbbq.domain.base import JsonObject
from openbbq.errors import ValidationError

DEFAULT_STORAGE_ROOT = Path(".openbbq")
DEFAULT_CONFIG_NAME = "openbbq.yaml"
BUILTIN_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "builtin_plugins"


def resolve_config_path(project_root: Path, config_path: Path | str | None) -> Path:
    if config_path is None:
        return (project_root / DEFAULT_CONFIG_NAME).resolve()
    path = Path(config_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def resolve_project_path(project_root: Path, value: Path | str, field_path: str) -> Path:
    try:
        path = Path(value).expanduser()
    except (TypeError, ValueError, OSError) as exc:
        raise ValidationError(
            f"{field_path} must be a string path relative to the project root."
        ) from exc
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def load_plugin_paths(
    project_root: Path, raw_config: JsonObject, env: Mapping[str, str]
) -> list[Path]:
    config_plugins = optional_mapping(raw_config.get("plugins"), "plugins")
    config_paths = config_plugins.get("paths", [])
    if not isinstance(config_paths, list):
        raise ValidationError("plugins.paths must be a list when provided.")

    env_paths_raw = env.get("OPENBBQ_PLUGIN_PATH", "")
    env_paths = [path for path in env_paths_raw.split(os.pathsep) if path]
    return normalize_plugin_paths(project_root, env_paths + config_paths, "plugins.paths")


def normalize_plugin_paths(
    project_root: Path, paths: Iterable[Path | str], field_path: str
) -> list[Path]:
    normalized: list[Path] = []
    seen: set[Path] = set()
    for index, raw_path in enumerate(paths):
        path = resolve_project_path(project_root, raw_path, f"{field_path}[{index}]")
        if path not in seen:
            seen.add(path)
            normalized.append(path)
    return normalized


def merge_paths(preferred: Iterable[Path], fallback: Iterable[Path]) -> list[Path]:
    merged: list[Path] = []
    seen: set[Path] = set()
    for path in list(preferred) + list(fallback):
        if path not in seen:
            seen.add(path)
            merged.append(path)
    return merged

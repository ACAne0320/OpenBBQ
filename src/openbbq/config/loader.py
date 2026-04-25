from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
import os

from openbbq.config.paths import (
    BUILTIN_PLUGIN_ROOT,
    DEFAULT_CONFIG_NAME,
    DEFAULT_STORAGE_ROOT,
    load_plugin_paths as _load_plugin_paths,
    merge_paths as _merge_paths,
    normalize_plugin_paths as _normalize_plugin_paths,
    resolve_config_path as _resolve_config_path,
    resolve_project_path as _resolve_path,
)
from openbbq.config.raw import (
    build_model as _build_model,
    load_yaml_mapping as _load_yaml_mapping,
    optional_mapping as _optional_mapping,
    require_mapping as _require_mapping,
    require_nonempty_string as _require_nonempty_string,
)
from openbbq.config.workflows import build_workflows
from openbbq.domain.models import (
    PluginConfig,
    ProjectConfig,
    ProjectMetadata,
    StorageConfig,
)
from openbbq.errors import ValidationError

__all__ = [
    "BUILTIN_PLUGIN_ROOT",
    "DEFAULT_CONFIG_NAME",
    "DEFAULT_STORAGE_ROOT",
    "load_project_config",
]


def load_project_config(
    project_root: Path | str,
    config_path: Path | str | None = None,
    extra_plugin_paths: Iterable[Path | str] | None = None,
    env: Mapping[str, str] | None = None,
) -> ProjectConfig:
    env = os.environ if env is None else env
    root_path = Path(project_root).expanduser().resolve()
    resolved_config_path = _resolve_config_path(root_path, config_path)
    raw_config = _load_yaml_mapping(resolved_config_path)

    version = raw_config.get("version")
    if type(version) is not int or version != 1:
        raise ValidationError("Project config version must be 1.")

    project_raw = _require_mapping(raw_config.get("project"), "project")
    project_name = _require_nonempty_string(project_raw.get("name"), "project.name")
    project_id = project_raw.get("id")
    if project_id is not None:
        project_id = _require_nonempty_string(project_id, "project.id")

    storage_raw = _optional_mapping(raw_config.get("storage"), "storage")
    storage_root = _resolve_path(
        root_path, storage_raw.get("root", DEFAULT_STORAGE_ROOT), "storage.root"
    )
    artifacts_path = _resolve_path(
        root_path,
        storage_raw.get("artifacts", storage_root / "artifacts"),
        "storage.artifacts",
    )
    state_path = _resolve_path(
        root_path, storage_raw.get("state", storage_root / "state"), "storage.state"
    )
    storage = _build_model(
        StorageConfig,
        "storage",
        root=storage_root,
        artifacts=artifacts_path,
        state=state_path,
    )

    config_plugin_paths = _load_plugin_paths(root_path, raw_config, env)
    cli_plugin_paths = _normalize_plugin_paths(
        root_path, extra_plugin_paths or [], "extra_plugin_paths"
    )
    plugin_paths = _merge_paths(
        cli_plugin_paths, _merge_paths(config_plugin_paths, [BUILTIN_PLUGIN_ROOT])
    )
    plugins = _build_model(PluginConfig, "plugins", paths=tuple(plugin_paths))

    workflows = build_workflows(raw_config)

    project = _build_model(ProjectMetadata, "project", id=project_id, name=project_name)
    return _build_model(
        ProjectConfig,
        "project config",
        version=1,
        root_path=root_path,
        config_path=resolved_config_path,
        project=project,
        storage=storage,
        plugins=plugins,
        workflows=workflows,
    )

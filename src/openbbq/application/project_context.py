from __future__ import annotations

from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.domain.base import OpenBBQModel
from openbbq.domain.models import ProjectConfig
from openbbq.storage.project_store import ProjectStore


class ProjectContext(OpenBBQModel):
    config: ProjectConfig
    store: ProjectStore


def project_store_from_config(config: ProjectConfig) -> ProjectStore:
    return ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )


def load_project_context(
    project_root: Path,
    *,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> ProjectContext:
    config = load_project_config(
        project_root,
        config_path=config_path,
        extra_plugin_paths=plugin_paths,
    )
    return ProjectContext(config=config, store=project_store_from_config(config))

from __future__ import annotations

from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.domain.base import OpenBBQModel
from openbbq.errors import ValidationError


class ProjectInitRequest(OpenBBQModel):
    project_root: Path
    config_path: Path | None = None


class ProjectInitResult(OpenBBQModel):
    config_path: Path


class ProjectInfoResult(OpenBBQModel):
    id: str | None
    name: str
    root_path: Path
    config_path: Path
    workflow_count: int
    plugin_paths: tuple[Path, ...]
    artifact_storage_path: Path
    state_storage_path: Path


def init_project(request: ProjectInitRequest) -> ProjectInitResult:
    project_root = request.project_root.expanduser().resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    config_path = (
        request.config_path.expanduser().resolve()
        if request.config_path is not None
        else project_root / "openbbq.yaml"
    )
    if config_path.exists():
        raise ValidationError(f"Project config already exists: {config_path}", exit_code=1)
    config_path.write_text(
        "version: 1\n\nproject:\n  name: OpenBBQ Project\n\nworkflows: {}\n",
        encoding="utf-8",
    )
    (project_root / ".openbbq" / "artifacts").mkdir(parents=True, exist_ok=True)
    (project_root / ".openbbq" / "state").mkdir(parents=True, exist_ok=True)
    return ProjectInitResult(config_path=config_path)


def project_info(
    *,
    project_root: Path,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> ProjectInfoResult:
    config = load_project_config(
        project_root,
        config_path=config_path,
        extra_plugin_paths=plugin_paths,
    )
    return ProjectInfoResult(
        id=config.project.id,
        name=config.project.name,
        root_path=config.root_path,
        config_path=config.config_path,
        workflow_count=len(config.workflows),
        plugin_paths=config.plugin_paths,
        artifact_storage_path=config.storage.artifacts,
        state_storage_path=config.storage.state,
    )

from __future__ import annotations

from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.domain.base import OpenBBQModel
from openbbq.plugins.registry import discover_plugins
from openbbq.runtime.doctor import check_settings, check_workflow
from openbbq.runtime.models import DoctorCheck
from openbbq.runtime.settings import load_runtime_settings


class DoctorResult(OpenBBQModel):
    ok: bool
    checks: tuple[DoctorCheck, ...]


def doctor(
    *,
    project_root: Path,
    workflow_id: str | None = None,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> DoctorResult:
    settings = load_runtime_settings()
    if workflow_id is None:
        checks = tuple(check_settings(settings=settings))
    else:
        config = load_project_config(
            project_root,
            config_path=config_path,
            extra_plugin_paths=plugin_paths,
        )
        registry = discover_plugins(config.plugin_paths)
        checks = tuple(
            check_workflow(
                config=config,
                registry=registry,
                workflow_id=workflow_id,
                settings=settings,
            )
        )
    return DoctorResult(ok=all(check.status != "failed" for check in checks), checks=checks)

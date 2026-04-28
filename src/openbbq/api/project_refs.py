from __future__ import annotations

from pathlib import Path

from fastapi import Request

from openbbq.api.context import active_project_settings
from openbbq.api.user_database import user_runtime_database
from openbbq.application.runs import get_run
from openbbq.domain.base import OpenBBQModel
from openbbq.errors import OpenBBQError, RunNotFoundError
from openbbq.storage.models import RunRecord

_RUN_PROJECT_REFS_KEY = "openbbq_run_project_refs"


class ApiProjectReference(OpenBBQModel):
    project_root: Path
    config_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()


def active_project_reference(request: Request) -> ApiProjectReference:
    settings = active_project_settings(request)
    return ApiProjectReference(
        project_root=settings.project_root,
        config_path=settings.config_path,
        plugin_paths=settings.plugin_paths,
    )


def set_active_project(
    request: Request,
    *,
    project_root: Path,
    config_path: Path | None,
) -> None:
    settings = request.app.state.openbbq_settings
    request.app.state.openbbq_settings = settings.model_copy(
        update={
            "project_root": project_root.expanduser().resolve(),
            "config_path": config_path.expanduser().resolve() if config_path else None,
        }
    )
    _run_project_refs(request).clear()


def register_run_project(
    request: Request,
    *,
    run_id: str,
    project_root: Path,
    config_path: Path | None,
    plugin_paths: tuple[Path, ...] = (),
) -> None:
    _run_project_refs(request)[run_id] = ApiProjectReference(
        project_root=project_root.expanduser().resolve(),
        config_path=config_path.expanduser().resolve() if config_path else None,
        plugin_paths=tuple(path.expanduser().resolve() for path in plugin_paths),
    )


def register_run_record(request: Request, run: RunRecord) -> None:
    register_run_project(
        request,
        run_id=run.id,
        project_root=run.project_root,
        config_path=run.config_path,
        plugin_paths=run.plugin_paths,
    )


def known_project_references(request: Request) -> tuple[ApiProjectReference, ...]:
    references = [
        *_run_project_refs(request).values(),
        *_quickstart_history_project_references(request),
        active_project_reference(request),
    ]
    seen: set[tuple[Path, Path | None]] = set()
    unique: list[ApiProjectReference] = []
    for reference in references:
        key = (
            reference.project_root.expanduser().resolve(),
            reference.config_path.expanduser().resolve() if reference.config_path else None,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(reference)
    return tuple(unique)


def find_run_project(request: Request, run_id: str) -> tuple[RunRecord, ApiProjectReference]:
    for reference in known_project_references(request):
        try:
            run = get_run(
                project_root=reference.project_root,
                config_path=reference.config_path,
                run_id=run_id,
            )
        except OpenBBQError:
            continue
        run_reference = ApiProjectReference(
            project_root=run.project_root,
            config_path=run.config_path or reference.config_path,
            plugin_paths=run.plugin_paths or reference.plugin_paths,
        )
        register_run_record(request, run)
        return run, run_reference
    raise RunNotFoundError(f"run not found: {run_id}")


def _run_project_refs(request: Request) -> dict[str, ApiProjectReference]:
    if not hasattr(request.app.state, _RUN_PROJECT_REFS_KEY):
        setattr(request.app.state, _RUN_PROJECT_REFS_KEY, {})
    return getattr(request.app.state, _RUN_PROJECT_REFS_KEY)


def _quickstart_history_project_references(request: Request) -> tuple[ApiProjectReference, ...]:
    database = user_runtime_database(request)
    return tuple(
        ApiProjectReference(
            project_root=task.generated_project_root,
            config_path=task.generated_config_path,
            plugin_paths=task.plugin_paths,
        )
        for task in database.list_quickstart_tasks()
    )

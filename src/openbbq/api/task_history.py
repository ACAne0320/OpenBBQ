from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import Request

from openbbq.api.schemas import SubtitleLocalJobRequest, SubtitleYouTubeJobRequest
from openbbq.api.user_database import user_runtime_database
from openbbq.application.quickstart import SubtitleJobResult
from openbbq.application.runs import get_run
from openbbq.errors import OpenBBQError
from openbbq.runtime.user_db import UserRuntimeDatabase
from openbbq.storage.models import QuickstartTaskRecord, RunRecord


def reusable_local_subtitle_job(
    request: Request, body: SubtitleLocalJobRequest
) -> SubtitleJobResult | None:
    return _reusable_task_result(request, _local_cache_key(body))


def reusable_youtube_subtitle_job(
    request: Request, body: SubtitleYouTubeJobRequest
) -> SubtitleJobResult | None:
    return _reusable_task_result(request, _youtube_cache_key(body))


def record_local_subtitle_job(
    request: Request,
    *,
    body: SubtitleLocalJobRequest,
    result: SubtitleJobResult,
    workspace_root: Path,
    plugin_paths: tuple[Path, ...],
) -> QuickstartTaskRecord:
    source_path = body.input_path.expanduser()
    source_uri = str(source_path.resolve()) if source_path.exists() else str(source_path)
    return _record_quickstart_job(
        request,
        result=result,
        workspace_root=workspace_root,
        plugin_paths=plugin_paths,
        source_kind="local_file",
        source_uri=source_uri,
        source_summary=source_path.name,
        source_lang=body.source_lang,
        target_lang=body.target_lang,
        provider=result.provider,
        model=result.model,
        asr_model=result.asr_model,
        asr_device=result.asr_device,
        asr_compute_type=result.asr_compute_type,
        quality=None,
        auth=None,
        browser=None,
        browser_profile=None,
        cache_key=_local_cache_key(body),
    )


def record_youtube_subtitle_job(
    request: Request,
    *,
    body: SubtitleYouTubeJobRequest,
    result: SubtitleJobResult,
    workspace_root: Path,
    plugin_paths: tuple[Path, ...],
) -> QuickstartTaskRecord:
    return _record_quickstart_job(
        request,
        result=result,
        workspace_root=workspace_root,
        plugin_paths=plugin_paths,
        source_kind="remote_url",
        source_uri=body.url.strip(),
        source_summary=body.url.strip(),
        source_lang=body.source_lang,
        target_lang=body.target_lang,
        provider=result.provider,
        model=result.model,
        asr_model=result.asr_model,
        asr_device=result.asr_device,
        asr_compute_type=result.asr_compute_type,
        quality=body.quality,
        auth=body.auth,
        browser=body.browser,
        browser_profile=body.browser_profile,
        cache_key=_youtube_cache_key(body),
    )


def list_quickstart_tasks(request: Request) -> tuple[QuickstartTaskRecord, ...]:
    database = user_runtime_database(request)
    tasks = database.list_quickstart_tasks()
    return tuple(_sync_task_from_project_run(database, task) for task in tasks)


def sync_quickstart_task_for_run(request: Request, run: RunRecord) -> None:
    database = user_runtime_database(request)
    task = database.read_quickstart_task(run.id)
    if task is not None:
        _sync_task_with_run(database, task, run)


def _reusable_task_result(request: Request, cache_key: str) -> SubtitleJobResult | None:
    database = user_runtime_database(request)
    for task in database.find_quickstart_tasks_by_cache_key(cache_key):
        if task.status == "aborted":
            continue
        try:
            run = get_run(
                project_root=task.generated_project_root,
                config_path=task.generated_config_path,
                run_id=task.run_id,
            )
        except OpenBBQError:
            continue
        task = _sync_task_with_run(database, task, run)
        return _job_result_from_task(task)
    return None


def _record_quickstart_job(
    request: Request,
    *,
    result: SubtitleJobResult,
    workspace_root: Path,
    plugin_paths: tuple[Path, ...],
    source_kind: str,
    source_uri: str,
    source_summary: str,
    source_lang: str,
    target_lang: str,
    provider: str,
    model: str | None,
    asr_model: str | None,
    asr_device: str | None,
    asr_compute_type: str | None,
    quality: str | None,
    auth: str | None,
    browser: str | None,
    browser_profile: str | None,
    cache_key: str,
) -> QuickstartTaskRecord:
    database = user_runtime_database(request)
    existing = database.read_quickstart_task(result.run_id)
    now = _now()
    run = _read_result_run(result)
    task = QuickstartTaskRecord(
        id=existing.id if existing is not None else f"task_{result.run_id}",
        run_id=result.run_id,
        workflow_id=result.workflow_id,
        workspace_root=workspace_root.expanduser().resolve(),
        generated_project_root=result.generated_project_root.expanduser().resolve(),
        generated_config_path=result.generated_config_path.expanduser().resolve(),
        plugin_paths=tuple(path.expanduser().resolve() for path in plugin_paths),
        source_kind=source_kind,  # type: ignore[arg-type]
        source_uri=source_uri,
        source_summary=source_summary,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=provider,
        model=model,
        asr_model=asr_model,
        asr_device=asr_device,
        asr_compute_type=asr_compute_type,
        quality=quality,
        auth=auth,
        browser=browser,
        browser_profile=browser_profile,
        output_path=result.output_path,
        source_artifact_id=result.source_artifact_id,
        cache_key=cache_key,
        status=run.status if run is not None else "queued",
        created_at=existing.created_at if existing is not None else now,
        updated_at=now,
        completed_at=run.completed_at if run is not None else None,
        error=run.error if run is not None else None,
    )
    return database.upsert_quickstart_task(task)


def _sync_task_from_project_run(
    database: UserRuntimeDatabase, task: QuickstartTaskRecord
) -> QuickstartTaskRecord:
    try:
        run = get_run(
            project_root=task.generated_project_root,
            config_path=task.generated_config_path,
            run_id=task.run_id,
        )
    except OpenBBQError:
        return task
    return _sync_task_with_run(database, task, run)


def _sync_task_with_run(
    database: UserRuntimeDatabase, task: QuickstartTaskRecord, run: RunRecord
) -> QuickstartTaskRecord:
    update = {
        "status": run.status,
        "completed_at": run.completed_at,
        "error": run.error,
    }
    if (
        task.status == run.status
        and task.completed_at == run.completed_at
        and task.error == run.error
    ):
        return task
    update["updated_at"] = _now()
    updated = task.model_copy(update=update)
    return database.upsert_quickstart_task(updated)


def _read_result_run(result: SubtitleJobResult) -> RunRecord | None:
    try:
        return get_run(
            project_root=result.generated_project_root,
            config_path=result.generated_config_path,
            run_id=result.run_id,
        )
    except OpenBBQError:
        return None


def _job_result_from_task(task: QuickstartTaskRecord) -> SubtitleJobResult:
    return SubtitleJobResult(
        generated_project_root=task.generated_project_root,
        generated_config_path=task.generated_config_path,
        workflow_id=task.workflow_id,
        run_id=task.run_id,
        output_path=task.output_path,
        source_artifact_id=task.source_artifact_id,
        provider=task.provider,
        model=task.model,
        asr_model=task.asr_model,
        asr_device=task.asr_device,
        asr_compute_type=task.asr_compute_type,
    )


def _local_cache_key(body: SubtitleLocalJobRequest) -> str:
    path = body.input_path.expanduser()
    fingerprint: dict[str, Any] = {"path": str(path.resolve()) if path.exists() else str(path)}
    try:
        stat = path.stat()
    except OSError:
        pass
    else:
        fingerprint["size"] = stat.st_size
        fingerprint["mtime_ns"] = stat.st_mtime_ns
    return _cache_key(
        {
            "template": "local-subtitle",
            "source": fingerprint,
            "settings": _common_settings(body),
        }
    )


def _youtube_cache_key(body: SubtitleYouTubeJobRequest) -> str:
    return _cache_key(
        {
            "template": "youtube-subtitle",
            "source": {"url": body.url.strip()},
            "settings": {
                **_common_settings(body),
                "quality": body.quality,
                "auth": body.auth,
                "browser": body.browser,
                "browser_profile": body.browser_profile,
            },
        }
    )


def _common_settings(body: SubtitleLocalJobRequest | SubtitleYouTubeJobRequest) -> dict[str, Any]:
    return {
        "source_lang": body.source_lang,
        "target_lang": body.target_lang,
        "provider": body.provider,
        "model": body.model,
        "asr_model": body.asr_model,
        "asr_device": body.asr_device,
        "asr_compute_type": body.asr_compute_type,
        "correct_transcript": body.correct_transcript,
        "step_order": body.step_order,
        "extra_steps": [step.model_dump(mode="json") for step in body.extra_steps],
    }


def _cache_key(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()

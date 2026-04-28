from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from openbbq.errors import ValidationError
from openbbq.runtime.models import ModelAssetStatus, ModelDownloadJob

ProgressCallback = Callable[..., None]
ModelDownloadWorker = Callable[[ProgressCallback], ModelAssetStatus]


class ModelDownloadJobManager:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="openbbq-model-download",
        )
        self._jobs: dict[str, ModelDownloadJob] = {}
        self._active_by_model: dict[tuple[str, str], str] = {}
        self._lock = Lock()

    def start(
        self,
        *,
        provider: str,
        model: str,
        worker: ModelDownloadWorker,
    ) -> ModelDownloadJob:
        key = (provider, model)
        with self._lock:
            existing_id = self._active_by_model.get(key)
            if existing_id is not None:
                existing = self._jobs[existing_id]
                if existing.status in {"queued", "running"}:
                    return existing.model_copy(deep=True)

            job = ModelDownloadJob(
                job_id=uuid4().hex,
                provider=provider,
                model=model,
                status="running",
                started_at=_now(),
            )
            self._jobs[job.job_id] = job
            self._active_by_model[key] = job.job_id

        self._executor.submit(self._run, job.job_id, worker)
        return self.get(job.job_id)

    def get(self, job_id: str) -> ModelDownloadJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ValidationError(f"Model download job '{job_id}' was not found.")
            return job.model_copy(deep=True)

    def update_progress(
        self,
        job_id: str,
        *,
        percent: float,
        current_bytes: int | None = None,
        total_bytes: int | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            self._jobs[job_id] = job.model_copy(
                update={
                    "status": "running",
                    "percent": max(0, min(100, percent)),
                    "current_bytes": current_bytes,
                    "total_bytes": total_bytes,
                }
            )

    def _run(self, job_id: str, worker: ModelDownloadWorker) -> None:
        try:
            self.update_progress(job_id, percent=0)
            model_status = worker(lambda **payload: self.update_progress(job_id, **payload))
            self._complete(job_id, model_status)
        except Exception as exc:
            self._fail(job_id, str(exc))

    def _complete(self, job_id: str, model_status: ModelAssetStatus) -> None:
        with self._lock:
            job = self._jobs[job_id]
            self._jobs[job_id] = job.model_copy(
                update={
                    "status": "completed",
                    "percent": 100,
                    "completed_at": _now(),
                    "model_status": model_status,
                }
            )

    def _fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            self._jobs[job_id] = job.model_copy(
                update={
                    "status": "failed",
                    "error": error,
                    "completed_at": _now(),
                }
            )


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


model_download_jobs = ModelDownloadJobManager()

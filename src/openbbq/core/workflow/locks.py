from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from types import TracebackType

from openbbq.errors import ExecutionError
from openbbq.storage import ProjectStore


def workflow_lock_path(store: ProjectStore, workflow_id: str) -> Path:
    return store.state_root / f"{workflow_id}.lock"


@dataclass(frozen=True, slots=True)
class WorkflowLock:
    path: Path

    @classmethod
    def acquire(cls, store: ProjectStore, workflow_id: str) -> WorkflowLock:
        path = workflow_lock_path(store, workflow_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "workflow_id": workflow_id,
            "pid": os.getpid(),
            "created_at": datetime.now(UTC).isoformat(),
        }
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(path, flags, 0o644)
        except FileExistsError as exc:
            raise ExecutionError(
                f"Workflow '{workflow_id}' is locked.",
                code="workflow_locked",
                exit_code=1,
            ) from exc
        try:
            data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        return cls(path=path)

    def release(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            return

    def __enter__(self) -> WorkflowLock:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()

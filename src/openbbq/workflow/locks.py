from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from types import TracebackType

from openbbq.errors import ExecutionError
from openbbq.storage.models import WorkflowLockInfo
from openbbq.storage.project_store import ProjectStore


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
            raise _existing_lock_error(store, workflow_id) from exc
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


def read_workflow_lock(store: ProjectStore, workflow_id: str) -> WorkflowLockInfo:
    path = workflow_lock_path(store, workflow_id)
    if not path.exists():
        raise ExecutionError(
            f"Workflow '{workflow_id}' does not have a lock file.",
            code="workflow_lock_missing",
            exit_code=1,
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    pid = payload.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int):
        pid = None
    recorded_workflow_id = payload.get("workflow_id")
    if not isinstance(recorded_workflow_id, str) or not recorded_workflow_id:
        recorded_workflow_id = workflow_id
    created_at = payload.get("created_at")
    if not isinstance(created_at, str):
        created_at = None
    return WorkflowLockInfo(
        path=path,
        workflow_id=recorded_workflow_id,
        pid=pid,
        created_at=created_at,
        stale=not _pid_is_alive(pid),
    )


def unlock_workflow_lock(store: ProjectStore, workflow_id: str) -> dict[str, object]:
    info = read_workflow_lock(store, workflow_id)
    if not info.stale:
        raise ExecutionError(
            f"Workflow '{workflow_id}' lock is held by live PID {info.pid}.",
            code="workflow_locked",
            exit_code=1,
        )
    info.path.unlink()
    return {
        "workflow_id": workflow_id,
        "unlocked": True,
        "pid": info.pid,
        "stale": True,
    }


def _existing_lock_error(store: ProjectStore, workflow_id: str) -> ExecutionError:
    info = read_workflow_lock(store, workflow_id)
    if info.stale:
        pid_text = "unknown PID" if info.pid is None else f"PID {info.pid}"
        return ExecutionError(
            f"Workflow '{workflow_id}' has a stale lock held by {pid_text}. "
            f"Run 'openbbq unlock {workflow_id}' before retrying.",
            code="workflow_stale_lock",
            exit_code=1,
        )
    return ExecutionError(
        f"Workflow '{workflow_id}' is locked by PID {info.pid}.",
        code="workflow_locked",
        exit_code=1,
    )


def _pid_is_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_pid_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_pid_is_alive(pid: int) -> bool:
    import ctypes

    error_access_denied = 5
    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == error_access_denied
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)

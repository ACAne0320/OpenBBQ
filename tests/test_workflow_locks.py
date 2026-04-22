import json
import os

import pytest

from openbbq.core.workflow import locks
from openbbq.core.workflow.locks import WorkflowLock, workflow_lock_path
from openbbq.errors import ExecutionError
from openbbq.storage import ProjectStore


def test_workflow_lock_creates_pid_file_and_releases(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    lock_path = workflow_lock_path(store, "text-demo")
    with WorkflowLock.acquire(store, "text-demo") as lock:
        assert lock.path == lock_path
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert isinstance(payload["pid"], int)
        assert payload["workflow_id"] == "text-demo"

    assert not lock_path.exists()


def test_workflow_lock_rejects_existing_lock(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    lock_path = workflow_lock_path(store, "text-demo")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({"pid": os.getpid(), "workflow_id": "text-demo"}),
        encoding="utf-8",
    )

    with pytest.raises(ExecutionError, match="locked") as exc:
        WorkflowLock.acquire(store, "text-demo")

    assert exc.value.exit_code == 1


def test_workflow_lock_reports_stale_lock_with_unlock_guidance(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    lock_path = workflow_lock_path(store, "text-demo")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text('{"pid":999999999,"workflow_id":"text-demo"}', encoding="utf-8")

    with pytest.raises(ExecutionError, match="stale") as exc:
        WorkflowLock.acquire(store, "text-demo")

    assert exc.value.code == "workflow_stale_lock"
    assert exc.value.exit_code == 1
    assert "999999999" in exc.value.message
    assert "openbbq unlock text-demo" in exc.value.message


def test_unlock_workflow_removes_stale_lock_without_changing_state(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    store.write_workflow_state(
        "text-demo",
        {
            "name": "Text Demo",
            "status": "running",
            "current_step_id": "seed",
            "step_run_ids": [],
        },
    )
    lock_path = workflow_lock_path(store, "text-demo")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text('{"pid":999999999,"workflow_id":"text-demo"}', encoding="utf-8")

    result = locks.unlock_workflow_lock(store, "text-demo")

    assert result == {
        "workflow_id": "text-demo",
        "unlocked": True,
        "pid": 999999999,
        "stale": True,
    }
    assert not lock_path.exists()
    assert store.read_workflow_state("text-demo")["status"] == "running"

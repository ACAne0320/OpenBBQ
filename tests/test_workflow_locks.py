import json

import pytest

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
    lock_path.write_text('{"pid":123,"workflow_id":"text-demo"}', encoding="utf-8")

    with pytest.raises(ExecutionError, match="locked") as exc:
        WorkflowLock.acquire(store, "text-demo")

    assert exc.value.exit_code == 1

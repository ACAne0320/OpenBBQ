from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path

from openbbq.storage.models import AbortRequest
from openbbq.storage.project_store import ProjectStore


def abort_request_path(store: ProjectStore, workflow_id: str) -> Path:
    return store.state_root / f"{workflow_id}.abort_requested"


def write_abort_request(store: ProjectStore, workflow_id: str) -> AbortRequest:
    payload = AbortRequest(
        workflow_id=workflow_id,
        pid=os.getpid(),
        requested_at=datetime.now(UTC).isoformat(),
    )
    store.write_json_atomic(abort_request_path(store, workflow_id), payload)
    return payload


def consume_abort_request(store: ProjectStore, workflow_id: str) -> bool:
    path = abort_request_path(store, workflow_id)
    if not path.exists():
        return False
    path.unlink()
    return True

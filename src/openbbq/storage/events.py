from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from openbbq.domain.base import JsonObject
from openbbq.storage.json_files import fsync_parent
from openbbq.storage.models import WorkflowEvent


class WorkflowEventIdGenerator(Protocol):
    def workflow_event_id(self) -> str: ...


def events_path(state_root: Path, workflow_id: str) -> Path:
    return state_root / workflow_id / "events.jsonl"


def append_event(
    state_root: Path,
    workflow_id: str,
    event: JsonObject,
    *,
    id_generator: WorkflowEventIdGenerator,
    timestamp: str,
) -> WorkflowEvent:
    path = events_path(state_root, workflow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    truncate_trailing_partial_jsonl_line(path)
    record = dict(event)
    record["workflow_id"] = workflow_id
    record["sequence"] = next_event_sequence(path)
    record.setdefault("id", id_generator.workflow_event_id())
    record.setdefault("created_at", timestamp)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    fsync_parent(path.parent)
    return WorkflowEvent.model_validate(record)


def next_event_sequence(path: Path) -> int:
    last_sequence = 0
    if not path.exists():
        return 1
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                break
            sequence = record.get("sequence")
            if isinstance(sequence, int):
                last_sequence = sequence
    return last_sequence + 1


def truncate_trailing_partial_jsonl_line(path: Path) -> None:
    if not path.exists():
        return
    data = path.read_bytes()
    if not data or data.endswith(b"\n"):
        return
    cutoff = data.rfind(b"\n")
    trailing_line = data if cutoff == -1 else data[cutoff + 1 :]
    try:
        json.loads(trailing_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        new_size = 0 if cutoff == -1 else cutoff + 1
    else:
        with path.open("ab") as handle:
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        fsync_parent(path.parent)
        return
    with path.open("rb+") as handle:
        handle.truncate(new_size)
        handle.flush()
        os.fsync(handle.fileno())
    fsync_parent(path.parent)

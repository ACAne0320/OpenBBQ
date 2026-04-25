# Storage Database Helper Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract repeated project database record mechanics into a focused helper module while preserving storage behavior.

**Architecture:** Keep `openbbq.storage.database.ProjectDatabase` as the public repository facade. Add `openbbq.storage.database_records` for deterministic JSON serialization, Pydantic record payload dumping, row upsert, and row-to-record reconstruction. Keep each write method's record-specific SQLAlchemy column assignments visible in `database.py`.

**Tech Stack:** Python 3.11, Pydantic v2, SQLAlchemy 2, SQLite, pytest, Ruff, uv.

---

## File Structure

- Create `src/openbbq/storage/database_records.py`
  - Internal helpers for storage record payloads, deterministic JSON strings,
    nullable JSON strings, row upsert, and `record_json` reconstruction.
- Modify `src/openbbq/storage/database.py`
  - Replace duplicated local helper functions and inline row creation blocks
    with calls to `database_records.py`.
- Modify `tests/test_storage.py`
  - Add focused characterization tests for helper behavior and database upsert
    semantics.
- Modify `tests/test_storage_runs.py`
  - Add a focused run `record_json` characterization test.
- Modify `tests/test_package_layout.py`
  - Add import coverage for `openbbq.storage.database_records`.
- Modify `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`
  - Mark the storage database helper cleanup complete after verification.

---

### Task 1: Add Database Record Helpers And Tests

**Files:**
- Create: `src/openbbq/storage/database_records.py`
- Modify: `tests/test_storage.py`
- Modify: `tests/test_package_layout.py`

- [ ] **Step 1: Add imports and helper tests**

Modify `tests/test_storage.py` imports:

```python
import json
import sqlite3
from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from openbbq.runtime.user_db import UserRuntimeDatabase
from openbbq.storage.artifact_content import ArtifactContentStore
from openbbq.storage.artifact_repository import ArtifactRepository
from openbbq.storage.database import ProjectDatabase
from openbbq.storage.database_records import (
    dump_json,
    dump_nullable_json,
    model_from_row,
    record_payload,
    upsert_row,
)
from openbbq.storage.event_repository import EventRepository
from openbbq.storage.models import ArtifactRecord, OutputBinding, WorkflowState
from openbbq.storage.orm import WorkflowStateRow
from openbbq.storage.project_store import ProjectStore
from openbbq.storage.workflow_repository import WorkflowRepository
```

Add these tests after `_sqlite_table_names()`:

```python
def test_database_record_helpers_dump_deterministic_json() -> None:
    assert dump_json({"z": "值", "a": [2, 1]}) == '{"a":[2,1],"z":"值"}'
    assert dump_nullable_json(None) is None
    assert dump_nullable_json({"b": 1}) == '{"b":1}'


def test_database_record_helpers_dump_model_payload() -> None:
    state = WorkflowState(
        id="demo",
        name="Demo",
        status="running",
        current_step_id="seed",
        config_hash="abc",
        step_run_ids=("sr_1",),
    )

    assert record_payload(state) == {
        "id": "demo",
        "name": "Demo",
        "status": "running",
        "current_step_id": "seed",
        "config_hash": "abc",
        "step_run_ids": ["sr_1"],
    }


def test_database_record_helpers_upsert_and_model_from_row(tmp_path) -> None:
    database = ProjectDatabase(tmp_path / ".openbbq" / "openbbq.db")
    session_factory = sessionmaker(database.engine, expire_on_commit=False, future=True)
    state = WorkflowState(id="demo", status="running", step_run_ids=("sr_1",))
    payload = record_payload(state)

    with session_factory.begin() as session:
        row = upsert_row(session, WorkflowStateRow, state.id)
        row.name = state.name
        row.status = state.status
        row.current_step_id = state.current_step_id
        row.config_hash = state.config_hash
        row.step_run_ids_json = dump_json(payload["step_run_ids"])
        row.record_json = dump_json(payload)

        same_row = upsert_row(session, WorkflowStateRow, state.id)
        same_row.status = "completed"

    with session_factory.begin() as session:
        row = session.get(WorkflowStateRow, state.id)
        assert row is not None
        assert row.status == "completed"
        assert model_from_row(WorkflowState, row) == state
```

Modify `tests/test_package_layout.py` by adding this string to
`test_database_model_modules_are_importable()`:

```python
        "openbbq.storage.database_records",
```

- [ ] **Step 2: Run the helper tests and confirm they fail**

Run:

```bash
uv run pytest tests/test_storage.py::test_database_record_helpers_dump_deterministic_json tests/test_storage.py::test_database_record_helpers_dump_model_payload tests/test_storage.py::test_database_record_helpers_upsert_and_model_from_row tests/test_package_layout.py::test_database_model_modules_are_importable -q
```

Expected: fail because `openbbq.storage.database_records` does not exist.

- [ ] **Step 3: Create `database_records.py`**

Create `src/openbbq/storage/database_records.py`:

```python
from __future__ import annotations

import json
from typing import Any, Protocol, TypeVar

from sqlalchemy.orm import Session

from openbbq.domain.base import JsonObject
from openbbq.storage.models import RecordModel

RecordT = TypeVar("RecordT", bound=RecordModel)
RowT = TypeVar("RowT")


class RecordJsonRow(Protocol):
    record_json: str


def record_payload(record: RecordModel) -> JsonObject:
    return record.model_dump(mode="json")


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dump_nullable_json(value: Any) -> str | None:
    if value is None:
        return None
    return dump_json(value)


def model_from_row(model_type: type[RecordT], row: RecordJsonRow) -> RecordT:
    return model_type.model_validate(json.loads(row.record_json))


def model_from_optional_row(
    model_type: type[RecordT], row: RecordJsonRow | None
) -> RecordT | None:
    if row is None:
        return None
    return model_from_row(model_type, row)


def upsert_row(session: Session, row_type: type[RowT], row_id: str) -> RowT:
    row = session.get(row_type, row_id)
    if row is None:
        row = row_type(id=row_id)  # type: ignore[call-arg]
        session.add(row)
    return row
```

- [ ] **Step 4: Run the helper tests and confirm they pass**

Run:

```bash
uv run pytest tests/test_storage.py::test_database_record_helpers_dump_deterministic_json tests/test_storage.py::test_database_record_helpers_dump_model_payload tests/test_storage.py::test_database_record_helpers_upsert_and_model_from_row tests/test_package_layout.py::test_database_model_modules_are_importable -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/storage/database_records.py tests/test_storage.py tests/test_package_layout.py
git commit -m "refactor: Add storage database record helpers"
```

---

### Task 2: Migrate ProjectDatabase To Helpers

**Files:**
- Modify: `src/openbbq/storage/database.py`
- Modify: `tests/test_storage.py`
- Modify: `tests/test_storage_runs.py`

- [ ] **Step 1: Add database behavior characterization tests**

Add this test after
`test_project_sqlite_records_workflow_state_step_run_event_and_artifact()` in
`tests/test_storage.py`:

```python
def test_project_database_updates_existing_workflow_state_row(tmp_path):
    database = ProjectDatabase(tmp_path / ".openbbq" / "openbbq.db")

    database.write_workflow_state(WorkflowState(id="demo", status="running"))
    database.write_workflow_state(
        WorkflowState(id="demo", status="completed", step_run_ids=("sr_1",))
    )

    with sqlite3.connect(tmp_path / ".openbbq" / "openbbq.db") as connection:
        rows = connection.execute(
            "select status, step_run_ids_json, record_json from workflow_states where id = ?",
            ("demo",),
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "completed"
    assert json.loads(rows[0][1]) == ["sr_1"]
    assert json.loads(rows[0][2])["step_run_ids"] == ["sr_1"]
```

Modify `tests/test_storage_runs.py` imports:

```python
import json
import sqlite3

from openbbq.storage.models import RunRecord
from openbbq.storage.runs import list_active_runs, read_run, write_run
```

Add this test after `test_run_records_are_written_to_project_sqlite_database()`:

```python
def test_run_record_json_preserves_paths_and_plugin_path_order(tmp_path):
    state_root = tmp_path / ".openbbq" / "state"
    config_path = tmp_path / "openbbq.yaml"
    plugins_a = tmp_path / "plugins-a"
    plugins_b = tmp_path / "plugins-b"
    record = RunRecord(
        id="run_json",
        workflow_id="demo",
        mode="start",
        status="running",
        project_root=tmp_path,
        config_path=config_path,
        plugin_paths=(plugins_a, plugins_b),
        latest_event_sequence=3,
        created_by="desktop",
    )

    write_run(state_root, record)

    db_path = tmp_path / ".openbbq" / "openbbq.db"
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "select plugin_paths_json, record_json from runs where id = ?",
            ("run_json",),
        ).fetchone()

    assert json.loads(row[0]) == [str(plugins_a), str(plugins_b)]
    payload = json.loads(row[1])
    assert payload["project_root"] == str(tmp_path)
    assert payload["config_path"] == str(config_path)
    assert payload["plugin_paths"] == [str(plugins_a), str(plugins_b)]
```

- [ ] **Step 2: Run the new characterization tests**

Run:

```bash
uv run pytest tests/test_storage.py::test_project_database_updates_existing_workflow_state_row tests/test_storage_runs.py::test_run_record_json_preserves_paths_and_plugin_path_order -q
```

Expected: pass before the refactor, proving current behavior.

- [ ] **Step 3: Refactor `database.py` to use helpers**

In `src/openbbq/storage/database.py`:

- Remove local imports of `json`, `Any`, and `TypeVar`.
- Import the helper functions from `openbbq.storage.database_records`.
- Replace every `record.model_dump(mode="json")` call with `record_payload(record)`.
- Replace every `session.get(...); if row is None: ...` block with `upsert_row(session, RowType, record.id)`.
- Replace `_json(...)` with `dump_json(...)`.
- Replace `_nullable_json(...)` with `dump_nullable_json(...)`.
- Replace `_model(...)` with `model_from_row(...)`.
- Replace `_model_or_none(...)` with `model_from_optional_row(...)`.
- Delete the local `_model`, `_model_or_none`, `_nullable_json`, and `_json` helper functions.

The final imports should include:

```python
from openbbq.storage.database_records import (
    dump_json,
    dump_nullable_json,
    model_from_optional_row,
    model_from_row,
    record_payload,
    upsert_row,
)
```

- [ ] **Step 4: Run targeted storage tests**

Run:

```bash
uv run pytest tests/test_storage.py tests/test_storage_runs.py tests/test_package_layout.py::test_database_model_modules_are_importable -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/storage/database.py tests/test_storage.py tests/test_storage_runs.py
git commit -m "refactor: Use storage database record helpers"
```

---

### Task 3: Verify And Close Audit Item

**Files:**
- Modify: `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`

- [ ] **Step 1: Update audit closure status**

Move `P2: Storage database repository repeats serialization and upsert patterns`
from `Remaining` to `Done` and describe the helper module:

```markdown
- **P2: Storage database repository repeats serialization and upsert patterns**
  - Completed by extracting deterministic JSON serialization, nullable JSON
    serialization, row upsert, and record-json reconstruction into
    `src/openbbq/storage/database_records.py`, while keeping
    `ProjectDatabase` record-specific queries and column assignments explicit.
```

Remove the same item from the `Remaining` list.

Change the first execution strategy item from storage cleanup to the next item:

```markdown
1. **Large test module split**
```

Change the `## Next slice` paragraph to:

```markdown
The next implementation slice should be **Large test module split**. It should
split only files where failure locality clearly improves, starting with storage
tests that now cover both repository behavior and extracted database helpers.
```

- [ ] **Step 2: Run final verification in the worktree**

Run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Expected: all commands pass.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md
git commit -m "docs: Track storage database cleanup completion"
```


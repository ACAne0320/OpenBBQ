# Run Lifecycle Executor Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the duplicated start/resume run execution lifecycle into one private helper while preserving public run behavior.

**Architecture:** Keep `openbbq.application.runs` as the owner of run record lifecycle updates. `_execute_run()` and `_execute_resume()` remain the private executor entry points, but each builds a workflow command closure and delegates shared state transition, command execution, failure marking, and final status writing to `_execute_run_lifecycle()`.

**Tech Stack:** Python 3.11, Pydantic v2 models, `collections.abc.Callable`, `typing.Protocol`, pytest, Ruff.

---

## File Structure

- Modify: `src/openbbq/application/runs.py`
  - Add a small private protocol for command results with a `status` attribute.
  - Add `_TERMINAL_RUN_STATUSES`.
  - Add `_execute_run_lifecycle(...)`.
  - Convert `_execute_run()` and `_execute_resume()` into thin wrappers.
- Modify: `tests/test_application_runs.py`
  - Add focused characterization coverage for domain `OpenBBQError` preservation.

Do not modify API route schemas, CLI behavior, storage schema, workflow command functions, or engine execution.

---

### Task 1: Add characterization coverage for domain execution errors

**Files:**
- Modify: `tests/test_application_runs.py`

- [ ] **Step 1: Add the `ExecutionError` import**

Update the imports at the top of `tests/test_application_runs.py` to include:

```python
from openbbq.errors import ExecutionError
```

The import block should become:

```python
from openbbq.application.runs import RunCreateRequest, abort_run, create_run, get_run, resume_run
from openbbq.application.workflows import workflow_status
from openbbq.errors import ExecutionError
from tests.helpers import write_project_fixture
```

- [ ] **Step 2: Add a characterization test for `OpenBBQError` preservation**

Add this test after `test_create_run_records_unexpected_exception_as_failed`:

```python
def test_create_run_records_openbbq_error_code_and_message(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")

    def fail_with_domain_error(*args, **kwargs):
        raise ExecutionError(
            "workflow cannot start",
            code="invalid_workflow_state",
            exit_code=1,
        )

    monkeypatch.setattr("openbbq.application.runs.run_workflow_command", fail_with_domain_error)

    created = create_run(
        RunCreateRequest(project_root=project, workflow_id="text-demo"),
        execute_inline=True,
    )
    loaded = get_run(project_root=project, run_id=created.id)

    assert loaded.status == "failed"
    assert loaded.error is not None
    assert loaded.error.code == "invalid_workflow_state"
    assert loaded.error.message == "workflow cannot start"
```

This is a characterization test for existing behavior, so it should pass before the refactor.

- [ ] **Step 3: Run the new focused test**

Run:

```bash
uv run pytest tests/test_application_runs.py::test_create_run_records_openbbq_error_code_and_message -q
```

Expected: PASS.

- [ ] **Step 4: Run the application run tests**

Run:

```bash
uv run pytest tests/test_application_runs.py -q
```

Expected: PASS.

- [ ] **Step 5: Run focused lint and formatting checks**

Run:

```bash
uv run ruff check tests/test_application_runs.py
uv run ruff format --check tests/test_application_runs.py
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit the characterization test**

Run:

```bash
git add tests/test_application_runs.py
git commit -m "test: Cover run lifecycle domain errors"
```

---

### Task 2: Extract the private run lifecycle executor

**Files:**
- Modify: `src/openbbq/application/runs.py`
- Test: `tests/test_application_runs.py`

- [ ] **Step 1: Add typing imports**

In `src/openbbq/application/runs.py`, add these imports:

```python
from collections.abc import Callable
from typing import Protocol
```

The top import section should start like this:

```python
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4
```

- [ ] **Step 2: Add the private command result protocol and terminal status constant**

Add this block after the `RunCreateRequest` class and before `_EXECUTOR`:

```python
class _RunCommandResult(Protocol):
    status: str


_TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "aborted"})
```

- [ ] **Step 3: Replace `_execute_run()` with a thin wrapper**

Replace the existing `_execute_run()` implementation with:

```python
def _execute_run(run_id: str, request: RunCreateRequest) -> None:
    def command() -> _RunCommandResult:
        return run_workflow_command(
            WorkflowRunRequest(
                project_root=request.project_root,
                config_path=request.config_path,
                plugin_paths=request.plugin_paths,
                workflow_id=request.workflow_id,
                force=request.force,
                step_id=request.step_id,
            )
        )

    _execute_run_lifecycle(run_id, request, command)
```

- [ ] **Step 4: Replace `_execute_resume()` with a thin wrapper**

Replace the existing `_execute_resume()` implementation with:

```python
def _execute_resume(run_id: str, request: RunCreateRequest) -> None:
    def command() -> _RunCommandResult:
        return resume_workflow_command(
            WorkflowCommandRequest(
                project_root=request.project_root,
                config_path=request.config_path,
                plugin_paths=request.plugin_paths,
                workflow_id=request.workflow_id,
            )
        )

    _execute_run_lifecycle(run_id, request, command, clear_error_on_success=True)
```

- [ ] **Step 5: Add `_execute_run_lifecycle()`**

Add this helper immediately after `_execute_resume()` and before `_sync_run_from_workflow_state()`:

```python
def _execute_run_lifecycle(
    run_id: str,
    request: RunCreateRequest,
    command: Callable[[], _RunCommandResult],
    *,
    clear_error_on_success: bool = False,
) -> None:
    context = load_project_context(
        request.project_root,
        config_path=request.config_path,
        plugin_paths=request.plugin_paths,
    )
    store = context.store
    run = read_run(store.state_base, run_id)
    write_run(store.state_base, run.model_copy(update={"status": "running", "started_at": _now()}))
    try:
        result = command()
    except OpenBBQError as exc:
        _mark_run_failed(
            store,
            run_id=run_id,
            workflow_id=request.workflow_id,
            code=exc.code,
            message=exc.message,
        )
        return
    except Exception as exc:
        _mark_run_failed(
            store,
            run_id=run_id,
            workflow_id=request.workflow_id,
            code="internal_error",
            message=str(exc),
        )
        return

    update = {
        "status": result.status,
        "completed_at": _now() if result.status in _TERMINAL_RUN_STATUSES else None,
        "latest_event_sequence": store.latest_event_sequence(request.workflow_id),
    }
    if clear_error_on_success:
        update["error"] = None
    completed = read_run(store.state_base, run_id).model_copy(update=update)
    write_run(store.state_base, completed)
```

- [ ] **Step 6: Reuse `_TERMINAL_RUN_STATUSES` in `_sync_run_from_workflow_state()`**

In `_sync_run_from_workflow_state()`, replace:

```python
"completed_at": _now() if state.status in {"completed", "failed", "aborted"} else None,
```

with:

```python
"completed_at": _now() if state.status in _TERMINAL_RUN_STATUSES else None,
```

- [ ] **Step 7: Run focused run tests**

Run:

```bash
uv run pytest tests/test_application_runs.py -q
```

Expected: PASS.

- [ ] **Step 8: Run API run route tests**

Run:

```bash
uv run pytest tests/test_api_workflows_artifacts_runs.py -q
```

Expected: PASS.

- [ ] **Step 9: Run focused lint and formatting checks**

Run:

```bash
uv run ruff check src/openbbq/application/runs.py tests/test_application_runs.py
uv run ruff format --check src/openbbq/application/runs.py tests/test_application_runs.py
```

Expected: both commands exit 0.

- [ ] **Step 10: Commit lifecycle extraction**

Run:

```bash
git add src/openbbq/application/runs.py tests/test_application_runs.py
git commit -m "refactor: Extract run lifecycle executor"
```

---

### Task 3: Adoption scan and full verification

**Files:**
- Verify: `src/openbbq/application/runs.py`
- Verify: `tests/test_application_runs.py`

- [ ] **Step 1: Scan the private execution helpers**

Run:

```bash
rg -n "def _execute_run\\(|def _execute_resume\\(|def _execute_run_lifecycle\\(|except OpenBBQError|except Exception as exc|completed_at" src/openbbq/application/runs.py
```

Expected:

- `def _execute_run(` appears once.
- `def _execute_resume(` appears once.
- `def _execute_run_lifecycle(` appears once.
- `except OpenBBQError` appears only inside `_execute_run_lifecycle()`.
- `except Exception as exc` appears only inside `_execute_run_lifecycle()`.
- `completed_at` updates use `_TERMINAL_RUN_STATUSES` in `_execute_run_lifecycle()` and `_sync_run_from_workflow_state()`.

- [ ] **Step 2: Run focused run tests**

Run:

```bash
uv run pytest tests/test_application_runs.py -q
```

Expected: PASS.

- [ ] **Step 3: Run API run route tests**

Run:

```bash
uv run pytest tests/test_api_workflows_artifacts_runs.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full test suite**

Run:

```bash
uv run pytest
```

Expected: PASS.

- [ ] **Step 5: Run full lint and formatting checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit final verification cleanups if needed**

If Step 1 through Step 5 required any code changes, commit them:

```bash
git add src/openbbq/application/runs.py tests/test_application_runs.py
git commit -m "refactor: Finish run lifecycle cleanup"
```

If no files changed after Task 2, do not create an empty commit.

---

## Plan Self-Review

- Spec coverage: Task 1 adds focused behavior coverage for domain `OpenBBQError` preservation. Task 2 extracts `_execute_run_lifecycle()` while keeping `_execute_run()` and `_execute_resume()` as executor entry points. Task 3 performs the required scans and final verification.
- Completeness scan: The plan has concrete file paths, commands, expected results, and code snippets for all code changes.
- Type consistency: The private helper is consistently named `_execute_run_lifecycle()`. The command result protocol is `_RunCommandResult`, and command callables use `Callable[[], _RunCommandResult]`.
- Behavior preservation: The plan keeps public run functions, executor submit targets, error conversion, terminal status `completed_at`, and latest event sequence updates unchanged.

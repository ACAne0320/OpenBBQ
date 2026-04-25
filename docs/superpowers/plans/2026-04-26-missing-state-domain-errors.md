# Missing-State Domain Errors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace domain missing-state `FileNotFoundError` paths with explicit OpenBBQ not-found errors while preserving recoverable workflow behavior.

**Architecture:** Add a `NotFoundError` domain base and specific run/workflow-state/step-run subclasses. Update storage repositories to raise them, workflow internals to catch them, and API error status mapping to return 404 from the domain base.

**Tech Stack:** Python 3.11, FastAPI, pytest, Ruff, uv.

---

## File Structure

- Modify `src/openbbq/errors.py`
  - Add `NotFoundError`, `RunNotFoundError`,
    `WorkflowStateNotFoundError`, and `StepRunNotFoundError`.
  - Make `ArtifactNotFoundError` inherit from `NotFoundError`.
- Modify `src/openbbq/storage/runs.py`
  - Raise `RunNotFoundError` for missing runs.
- Modify `src/openbbq/storage/workflow_repository.py`
  - Raise `WorkflowStateNotFoundError` and `StepRunNotFoundError`.
- Modify `src/openbbq/workflow/state.py`
  - Catch workflow/step-run domain errors instead of `FileNotFoundError`.
- Modify `src/openbbq/workflow/rerun.py`
  - Catch `StepRunNotFoundError` instead of `FileNotFoundError`.
- Modify `src/openbbq/api/errors.py`
  - Map `NotFoundError` subclasses to HTTP 404.
  - Remove the generic `FileNotFoundError` handler.
- Modify tests:
  - `tests/test_storage_runs.py`
  - `tests/test_storage_repositories.py`
  - `tests/test_workflow_state.py`
  - `tests/test_api_workflows_artifacts_runs.py`
  - `tests/test_package_layout.py`
- Modify `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`
  only in the audit closure task.

---

### Task 1: Add Domain Not-Found Errors And Storage Tests

**Files:**
- Modify: `src/openbbq/errors.py`
- Modify: `src/openbbq/storage/runs.py`
- Modify: `src/openbbq/storage/workflow_repository.py`
- Modify: `tests/test_storage_runs.py`
- Modify: `tests/test_storage_repositories.py`
- Modify: `tests/test_package_layout.py`

- [ ] **Step 1: Add failing tests for domain not-found errors**

Modify `tests/test_storage_runs.py` imports:

```python
from openbbq.errors import RunNotFoundError
```

Add this test after `test_write_read_and_list_active_runs()`:

```python
def test_read_missing_run_raises_domain_not_found_error(tmp_path):
    state_root = tmp_path / ".openbbq" / "state"

    with pytest.raises(RunNotFoundError) as exc:
        read_run(state_root, "missing")

    assert exc.value.code == "run_not_found"
    assert exc.value.message == "run not found: missing"
    assert exc.value.exit_code == 6
```

Also add `import pytest` to `tests/test_storage_runs.py`.

Modify `tests/test_storage_repositories.py` imports:

```python
from openbbq.errors import StepRunNotFoundError, WorkflowStateNotFoundError
```

Add this test after `test_storage_repositories_round_trip_without_project_store()`:

```python
def test_workflow_repository_missing_records_raise_domain_not_found_errors(tmp_path):
    database = ProjectDatabase(tmp_path / ".openbbq" / "openbbq.db")
    repository = WorkflowRepository(database, id_generator=object())

    with pytest.raises(WorkflowStateNotFoundError) as workflow_exc:
        repository.read_workflow_state("missing-workflow")
    assert workflow_exc.value.code == "workflow_state_not_found"
    assert workflow_exc.value.message == "workflow state not found: missing-workflow"

    with pytest.raises(StepRunNotFoundError) as step_exc:
        repository.read_step_run("demo", "missing-step-run")
    assert step_exc.value.code == "step_run_not_found"
    assert step_exc.value.message == "step run not found: missing-step-run"
```

Modify `tests/test_package_layout.py` by adding:

```python
def test_domain_not_found_errors_share_base_class() -> None:
    from openbbq.errors import (
        ArtifactNotFoundError,
        NotFoundError,
        RunNotFoundError,
        StepRunNotFoundError,
        WorkflowStateNotFoundError,
    )

    assert issubclass(ArtifactNotFoundError, NotFoundError)
    assert RunNotFoundError("missing").code == "run_not_found"
    assert WorkflowStateNotFoundError("missing").code == "workflow_state_not_found"
    assert StepRunNotFoundError("missing").code == "step_run_not_found"
```

- [ ] **Step 2: Run the new storage tests and confirm they fail**

Run:

```bash
uv run pytest tests/test_storage_runs.py::test_read_missing_run_raises_domain_not_found_error tests/test_storage_repositories.py::test_workflow_repository_missing_records_raise_domain_not_found_errors tests/test_package_layout.py::test_domain_not_found_errors_share_base_class -q
```

Expected: fail because the new error classes do not exist yet.

- [ ] **Step 3: Implement domain error classes**

Modify `src/openbbq/errors.py`:

```python
class NotFoundError(OpenBBQError):
    def __init__(self, message: str, code: str = "not_found", exit_code: int = 6) -> None:
        super().__init__(code, message, exit_code)


class ArtifactNotFoundError(NotFoundError):
    def __init__(self, message: str, code: str = "artifact_not_found", exit_code: int = 6) -> None:
        super().__init__(message, code, exit_code)


class RunNotFoundError(NotFoundError):
    def __init__(self, message: str, code: str = "run_not_found", exit_code: int = 6) -> None:
        super().__init__(message, code, exit_code)


class WorkflowStateNotFoundError(NotFoundError):
    def __init__(
        self, message: str, code: str = "workflow_state_not_found", exit_code: int = 6
    ) -> None:
        super().__init__(message, code, exit_code)


class StepRunNotFoundError(NotFoundError):
    def __init__(
        self, message: str, code: str = "step_run_not_found", exit_code: int = 6
    ) -> None:
        super().__init__(message, code, exit_code)
```

Replace the old `ArtifactNotFoundError(OpenBBQError)` class with the subclass
above.

- [ ] **Step 4: Replace storage raises**

Modify `src/openbbq/storage/runs.py`:

```python
from openbbq.errors import RunNotFoundError
...
        raise RunNotFoundError(f"run not found: {run_id}")
```

Modify `src/openbbq/storage/workflow_repository.py`:

```python
from openbbq.errors import StepRunNotFoundError, WorkflowStateNotFoundError
...
            raise WorkflowStateNotFoundError(f"workflow state not found: {workflow_id}")
...
            raise StepRunNotFoundError(f"step run not found: {step_run_id}")
```

- [ ] **Step 5: Run targeted tests**

Run:

```bash
uv run pytest tests/test_storage_runs.py tests/test_storage_repositories.py tests/test_package_layout.py::test_domain_not_found_errors_share_base_class -q
uv run ruff check src/openbbq/errors.py src/openbbq/storage/runs.py src/openbbq/storage/workflow_repository.py tests/test_storage_runs.py tests/test_storage_repositories.py tests/test_package_layout.py
uv run ruff format --check src/openbbq/errors.py src/openbbq/storage/runs.py src/openbbq/storage/workflow_repository.py tests/test_storage_runs.py tests/test_storage_repositories.py tests/test_package_layout.py
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/openbbq/errors.py src/openbbq/storage/runs.py src/openbbq/storage/workflow_repository.py tests/test_storage_runs.py tests/test_storage_repositories.py tests/test_package_layout.py
git commit -m "refactor: Add domain not-found storage errors"
```

---

### Task 2: Update Workflow And API Boundaries

**Files:**
- Modify: `src/openbbq/workflow/state.py`
- Modify: `src/openbbq/workflow/rerun.py`
- Modify: `src/openbbq/api/errors.py`
- Modify: `tests/test_workflow_state.py`
- Modify: `tests/test_api_workflows_artifacts_runs.py`

- [ ] **Step 1: Add behavior tests for recoverable workflow misses and API codes**

Modify `tests/test_workflow_state.py` imports:

```python
from openbbq.errors import ExecutionError, StepRunNotFoundError
```

Add this test after `test_rebuild_output_bindings_uses_completed_step_runs()`:

```python
def test_rebuild_output_bindings_ignores_missing_historical_step_runs(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    bindings = rebuild_output_bindings(store, "text-demo", ["missing-step-run"])

    assert bindings == {}
```

Modify `tests/test_api_workflows_artifacts_runs.py`:

Change `test_missing_run_uses_api_not_found_envelope()` expected error code to
`run_not_found`.

Add this test after it:

```python
def test_missing_artifact_uses_artifact_not_found_envelope(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project, raise_server_exceptions=False)

    response = client.get("/artifacts/missing", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "artifact_not_found"
    assert response.json()["error"]["message"] == "artifact not found: missing"
```

- [ ] **Step 2: Run tests before implementation**

Run:

```bash
uv run pytest tests/test_workflow_state.py::test_rebuild_output_bindings_ignores_missing_historical_step_runs tests/test_api_workflows_artifacts_runs.py::test_missing_run_uses_api_not_found_envelope tests/test_api_workflows_artifacts_runs.py::test_missing_artifact_uses_artifact_not_found_envelope -q
```

Expected: workflow and missing artifact behavior should pass after Task 1;
missing run API code should fail until API mapping uses the domain error code.

- [ ] **Step 3: Update workflow catches**

Modify `src/openbbq/workflow/state.py`:

```python
from openbbq.errors import ExecutionError, StepRunNotFoundError, WorkflowStateNotFoundError
...
    except WorkflowStateNotFoundError:
        return build_pending_state(workflow)
...
        except StepRunNotFoundError:
            continue
```

Modify `src/openbbq/workflow/rerun.py`:

```python
from openbbq.errors import StepRunNotFoundError
...
        except StepRunNotFoundError:
            continue
```

for both catch blocks.

- [ ] **Step 4: Update API error mapping**

Modify `src/openbbq/api/errors.py`:

- Import `NotFoundError`:

```python
from openbbq.errors import NotFoundError, OpenBBQError
```

- Delete the `@app.exception_handler(FileNotFoundError)` handler.
- Change `_status_code()`:

```python
    if isinstance(error, NotFoundError):
        return 404
```

Remove the previous `if error.code == "artifact_not_found"` check because the
base class covers it.

- [ ] **Step 5: Run targeted tests and search for leftover domain catches**

Run:

```bash
uv run pytest tests/test_workflow_state.py tests/test_api_workflows_artifacts_runs.py -q
rg -n "except FileNotFoundError|raise FileNotFoundError|@app.exception_handler\\(FileNotFoundError\\)" src/openbbq/storage src/openbbq/workflow src/openbbq/api
uv run ruff check src/openbbq/workflow/state.py src/openbbq/workflow/rerun.py src/openbbq/api/errors.py tests/test_workflow_state.py tests/test_api_workflows_artifacts_runs.py
uv run ruff format --check src/openbbq/workflow/state.py src/openbbq/workflow/rerun.py src/openbbq/api/errors.py tests/test_workflow_state.py tests/test_api_workflows_artifacts_runs.py
```

Expected: tests and Ruff pass. The `rg` command may still show
`workflow/locks.py` because it intentionally handles real lock-file absence;
it should not show storage run/workflow repository or API handler matches.

- [ ] **Step 6: Commit**

```bash
git add src/openbbq/workflow/state.py src/openbbq/workflow/rerun.py src/openbbq/api/errors.py tests/test_workflow_state.py tests/test_api_workflows_artifacts_runs.py
git commit -m "refactor: Use domain not-found workflow errors"
```

---

### Task 3: Verify And Close Audit Item

**Files:**
- Modify: `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`

- [ ] **Step 1: Update audit closure status**

Move `P3: File-not-found and missing-state errors are not uniformly
domain-specific` from `Remaining` to `Done` with this text:

```markdown
- **P3: File-not-found and missing-state errors are not uniformly
  domain-specific**
  - Completed by adding a `NotFoundError` domain base plus run, workflow-state,
    and step-run not-found subclasses; updating storage repositories to raise
    domain errors; updating workflow recovery paths to catch domain errors; and
    mapping API 404 responses from domain not-found errors instead of generic
    `FileNotFoundError`.
```

Change `### Remaining` to state that no audit items remain.

Change `## Execution strategy` to state that all audit cleanup slices are
complete.

Change `## Next slice` to:

```markdown
No code-quality audit cleanup slices remain. The backend is ready for the final
pre-desktop verification gate.
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
git commit -m "docs: Track missing-state error cleanup completion"
```


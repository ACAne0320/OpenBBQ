# Project Context Helper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize repeated application-layer project config and `ProjectStore` construction without changing CLI/API behavior.

**Architecture:** Add a small `openbbq.application.project_context` module that owns the conversion from a loaded `ProjectConfig` to a correctly rooted `ProjectStore`, plus a request-style loader for application services. Migrate application/API call sites that already need both config and store. Leave CLI helpers and engine internals for later plans so this slice stays behavioral-preserving and easy to review.

**Tech Stack:** Python, Pydantic-based OpenBBQ models, pytest, Ruff.

---

## File structure

- Create: `src/openbbq/application/project_context.py`
  - Defines `ProjectContext`, `project_store_from_config()`, and `load_project_context()`.
- Create: `tests/test_application_project_context.py`
  - Covers the helper's storage-root and plugin-path behavior.
- Modify: `src/openbbq/application/artifacts.py`
  - Replaces local `_store(config)` and repeated config/store construction with the shared helper.
- Modify: `src/openbbq/application/workflows.py`
  - Replaces repeated config/store construction in status and event read paths with the shared helper.
- Modify: `src/openbbq/api/routes/workflows.py`
  - Replaces route-local `_store(config)` with the shared helper.
- Modify: `src/openbbq/application/runs.py`
  - Replaces repeated config/store construction in run lifecycle paths with the shared helper.

Out of scope for this plan:

- `src/openbbq/cli/app.py`, because CLI command extraction is a separate audit item.
- `src/openbbq/engine/service.py` and `src/openbbq/engine/validation.py`, because the engine should keep explicit store construction until application boundaries are cleaner.
- Config-only call sites such as `application/plugins.py`, `application/projects.py`, and `application/diagnostics.py`; they do not need a `ProjectStore` on every path.

### Task 1: Add project context helper tests

**Files:**
- Create: `tests/test_application_project_context.py`

- [ ] **Step 1: Write tests for store-root construction and plugin-path loading**

Create `tests/test_application_project_context.py` with this content:

```python
from pathlib import Path

from openbbq.application.project_context import (
    load_project_context,
    project_store_from_config,
)
from openbbq.config.loader import load_project_config
from tests.helpers import write_project_fixture


def test_project_store_from_config_uses_configured_storage_roots(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    config_path = project / "openbbq.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "storage:\n  root: .openbbq\n",
            "storage:\n"
            "  root: runtime-root\n"
            "  artifacts: artifact-store\n"
            "  state: workflow-state\n",
        ),
        encoding="utf-8",
    )
    config = load_project_config(project)

    store = project_store_from_config(config)

    assert store.root == project / "runtime-root"
    assert store.artifacts_root == project / "artifact-store"
    assert store.state_base == project / "workflow-state"


def test_load_project_context_applies_extra_plugin_paths(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    extra_plugins = tmp_path / "extra-plugins"
    extra_plugins.mkdir()

    context = load_project_context(project, plugin_paths=(extra_plugins,))

    assert context.config.root_path == project
    assert context.config.plugin_paths[-1] == extra_plugins
    assert context.store.root == project / ".openbbq"
```

- [ ] **Step 2: Run the new tests and verify they fail because the helper module does not exist**

Run:

```bash
uv run pytest tests/test_application_project_context.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'openbbq.application.project_context'`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_application_project_context.py
git commit -m "test: Cover application project context helper"
```

### Task 2: Implement the project context helper

**Files:**
- Create: `src/openbbq/application/project_context.py`
- Test: `tests/test_application_project_context.py`

- [ ] **Step 1: Create `src/openbbq/application/project_context.py`**

Create `src/openbbq/application/project_context.py` with this content:

```python
from __future__ import annotations

from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.domain.base import OpenBBQModel
from openbbq.domain.models import ProjectConfig
from openbbq.storage.project_store import ProjectStore


class ProjectContext(OpenBBQModel):
    config: ProjectConfig
    store: ProjectStore


def project_store_from_config(config: ProjectConfig) -> ProjectStore:
    return ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )


def load_project_context(
    project_root: Path,
    *,
    config_path: Path | None = None,
    plugin_paths: tuple[Path, ...] = (),
) -> ProjectContext:
    config = load_project_config(
        project_root,
        config_path=config_path,
        extra_plugin_paths=plugin_paths,
    )
    return ProjectContext(config=config, store=project_store_from_config(config))
```

- [ ] **Step 2: Run the helper tests and verify they pass**

Run:

```bash
uv run pytest tests/test_application_project_context.py -q
```

Expected: PASS, `2 passed`.

- [ ] **Step 3: Run Ruff on the helper files**

Run:

```bash
uv run ruff check src/openbbq/application/project_context.py tests/test_application_project_context.py
uv run ruff format --check src/openbbq/application/project_context.py tests/test_application_project_context.py
```

Expected: both commands PASS.

- [ ] **Step 4: Commit the helper implementation**

```bash
git add src/openbbq/application/project_context.py tests/test_application_project_context.py
git commit -m "refactor: Add application project context helper"
```

### Task 3: Migrate artifact application service

**Files:**
- Modify: `src/openbbq/application/artifacts.py`
- Test: `tests/test_application_artifacts.py`
- Test: `tests/test_api_workflows_artifacts_runs.py`

- [ ] **Step 1: Update imports in `src/openbbq/application/artifacts.py`**

Remove these imports:

```python
from openbbq.config.loader import load_project_config
from openbbq.domain.models import ARTIFACT_TYPES, ProjectConfig
from openbbq.storage.project_store import ProjectStore
```

Add this import:

```python
from openbbq.application.project_context import load_project_context
```

Keep `ARTIFACT_TYPES` by changing the domain import to:

```python
from openbbq.domain.models import ARTIFACT_TYPES
```

- [ ] **Step 2: Replace config/store construction in artifact functions**

In `import_artifact`, replace:

```python
config = load_project_config(request.project_root, config_path=request.config_path)
artifact, version = _store(config).write_artifact_version(
```

with:

```python
context = load_project_context(request.project_root, config_path=request.config_path)
artifact, version = context.store.write_artifact_version(
```

In `list_artifacts`, replace:

```python
config = load_project_config(project_root, config_path=config_path)
store = _store(config)
```

with:

```python
context = load_project_context(project_root, config_path=config_path)
store = context.store
```

In `show_artifact`, replace:

```python
config = load_project_config(project_root, config_path=config_path)
store = _store(config)
```

with:

```python
context = load_project_context(project_root, config_path=config_path)
store = context.store
```

In `show_artifact_version`, replace:

```python
config = load_project_config(project_root, config_path=config_path)
return _store(config).read_artifact_version(version_id)
```

with:

```python
context = load_project_context(project_root, config_path=config_path)
return context.store.read_artifact_version(version_id)
```

In `diff_artifact_versions`, replace:

```python
config = load_project_config(project_root, config_path=config_path)
return diff_versions(_store(config), from_version, to_version)
```

with:

```python
context = load_project_context(project_root, config_path=config_path)
return diff_versions(context.store, from_version, to_version)
```

Delete the private `_store(config: ProjectConfig) -> ProjectStore` function entirely.

- [ ] **Step 3: Run artifact service and route tests**

Run:

```bash
uv run pytest tests/test_application_project_context.py tests/test_application_artifacts.py tests/test_api_workflows_artifacts_runs.py -q
```

Expected: PASS.

- [ ] **Step 4: Run Ruff on touched files**

Run:

```bash
uv run ruff check src/openbbq/application/artifacts.py src/openbbq/application/project_context.py tests/test_application_project_context.py tests/test_application_artifacts.py tests/test_api_workflows_artifacts_runs.py
uv run ruff format --check src/openbbq/application/artifacts.py src/openbbq/application/project_context.py tests/test_application_project_context.py tests/test_application_artifacts.py tests/test_api_workflows_artifacts_runs.py
```

Expected: both commands PASS.

- [ ] **Step 5: Commit the artifact migration**

```bash
git add src/openbbq/application/artifacts.py
git commit -m "refactor: Use project context in artifact service"
```

### Task 4: Migrate workflow application service and API workflow route

**Files:**
- Modify: `src/openbbq/application/workflows.py`
- Modify: `src/openbbq/api/routes/workflows.py`
- Test: `tests/test_application_workflows.py`
- Test: `tests/test_api_workflows_artifacts_runs.py`
- Test: `tests/test_api_events.py`

- [ ] **Step 1: Update imports in `src/openbbq/application/workflows.py`**

Remove:

```python
from openbbq.storage.project_store import ProjectStore
```

Add:

```python
from openbbq.application.project_context import load_project_context
```

Keep the existing `from openbbq.config.loader import load_project_config` import in this file for command functions that only need config plus plugin discovery.

- [ ] **Step 2: Replace store construction in `workflow_status`**

Inside `workflow_status`, replace:

```python
config = load_project_config(
    project_root,
    config_path=config_path,
    extra_plugin_paths=plugin_paths,
)
workflow = config.workflows.get(workflow_id)
if workflow is None:
    raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
store = ProjectStore(
    config.storage.root,
    artifacts_root=config.storage.artifacts,
    state_root=config.storage.state,
)
return read_effective_workflow_state(store, workflow)
```

with:

```python
context = load_project_context(
    project_root,
    config_path=config_path,
    plugin_paths=plugin_paths,
)
workflow = context.config.workflows.get(workflow_id)
if workflow is None:
    raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
return read_effective_workflow_state(context.store, workflow)
```

- [ ] **Step 3: Replace store construction in `workflow_events`**

Inside `workflow_events`, replace:

```python
config = load_project_config(
    project_root,
    config_path=config_path,
    extra_plugin_paths=plugin_paths,
)
workflow = config.workflows.get(workflow_id)
if workflow is None:
    raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
store = ProjectStore(
    config.storage.root,
    artifacts_root=config.storage.artifacts,
    state_root=config.storage.state,
)
return WorkflowLogsResult(
    workflow_id=workflow_id,
    events=store.read_events(workflow_id, after_sequence=after_sequence),
)
```

with:

```python
context = load_project_context(
    project_root,
    config_path=config_path,
    plugin_paths=plugin_paths,
)
workflow = context.config.workflows.get(workflow_id)
if workflow is None:
    raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
return WorkflowLogsResult(
    workflow_id=workflow_id,
    events=context.store.read_events(workflow_id, after_sequence=after_sequence),
)
```

- [ ] **Step 4: Update imports in `src/openbbq/api/routes/workflows.py`**

Remove:

```python
from openbbq.domain.models import ProjectConfig, WorkflowConfig
```

Add:

```python
from openbbq.application.project_context import load_project_context
from openbbq.domain.models import WorkflowConfig
```

Keep the existing `from openbbq.config.loader import load_project_config` import in this route for the validate endpoint, which does not need a store. Keep the existing `from openbbq.storage.project_store import ProjectStore` import because `_workflow_summary` still accepts a store argument.

- [ ] **Step 5: Replace list/detail route context loading**

In `list_workflows`, replace:

```python
config = load_project_config(
    settings.project_root,
    config_path=settings.config_path,
    extra_plugin_paths=settings.plugin_paths,
)
store = _store(config)
workflows = tuple(_workflow_summary(store, workflow) for workflow in config.workflows.values())
```

with:

```python
context = load_project_context(
    settings.project_root,
    config_path=settings.config_path,
    plugin_paths=settings.plugin_paths,
)
workflows = tuple(
    _workflow_summary(context.store, workflow)
    for workflow in context.config.workflows.values()
)
```

In `get_workflow`, replace:

```python
config = load_project_config(
    settings.project_root,
    config_path=settings.config_path,
    extra_plugin_paths=settings.plugin_paths,
)
workflow = config.workflows.get(workflow_id)
if workflow is None:
    raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
summary = _workflow_summary(_store(config), workflow)
```

with:

```python
context = load_project_context(
    settings.project_root,
    config_path=settings.config_path,
    plugin_paths=settings.plugin_paths,
)
workflow = context.config.workflows.get(workflow_id)
if workflow is None:
    raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
summary = _workflow_summary(context.store, workflow)
```

Delete the private `_store(config: ProjectConfig) -> ProjectStore` function entirely.

- [ ] **Step 6: Run workflow service and API tests**

Run:

```bash
uv run pytest tests/test_application_project_context.py tests/test_application_workflows.py tests/test_api_workflows_artifacts_runs.py tests/test_api_events.py -q
```

Expected: PASS.

- [ ] **Step 7: Run Ruff on touched files**

Run:

```bash
uv run ruff check src/openbbq/application/workflows.py src/openbbq/api/routes/workflows.py src/openbbq/application/project_context.py tests/test_application_project_context.py tests/test_application_workflows.py tests/test_api_workflows_artifacts_runs.py tests/test_api_events.py
uv run ruff format --check src/openbbq/application/workflows.py src/openbbq/api/routes/workflows.py src/openbbq/application/project_context.py tests/test_application_project_context.py tests/test_application_workflows.py tests/test_api_workflows_artifacts_runs.py tests/test_api_events.py
```

Expected: both commands PASS.

- [ ] **Step 8: Commit the workflow migration**

```bash
git add src/openbbq/application/workflows.py src/openbbq/api/routes/workflows.py
git commit -m "refactor: Use project context in workflow services"
```

### Task 5: Migrate run application service

**Files:**
- Modify: `src/openbbq/application/runs.py`
- Test: `tests/test_application_runs.py`
- Test: `tests/test_api_workflows_artifacts_runs.py`

- [ ] **Step 1: Update imports in `src/openbbq/application/runs.py`**

Remove:

```python
from openbbq.config.loader import load_project_config
from openbbq.storage.project_store import ProjectStore
```

Add:

```python
from openbbq.application.project_context import load_project_context
from openbbq.storage.project_store import ProjectStore
```

Keep `ProjectStore` because `_mark_run_failed` accepts a store argument.

- [ ] **Step 2: Replace config/store construction in `create_run`**

Replace:

```python
config = load_project_config(
    request.project_root,
    config_path=request.config_path,
    extra_plugin_paths=request.plugin_paths,
)
workflow = config.workflows.get(request.workflow_id)
if workflow is None:
    raise ValidationError(f"Workflow '{request.workflow_id}' is not defined.")
store = ProjectStore(
    config.storage.root,
    artifacts_root=config.storage.artifacts,
    state_root=config.storage.state,
)
```

with:

```python
context = load_project_context(
    request.project_root,
    config_path=request.config_path,
    plugin_paths=request.plugin_paths,
)
workflow = context.config.workflows.get(request.workflow_id)
if workflow is None:
    raise ValidationError(f"Workflow '{request.workflow_id}' is not defined.")
store = context.store
```

- [ ] **Step 3: Replace config/store construction in read/list/resume paths**

In `get_run`, replace the body with:

```python
context = load_project_context(project_root, config_path=config_path)
return read_run(context.store.state_base, run_id)
```

In `list_project_runs`, replace the body with:

```python
context = load_project_context(project_root, config_path=config_path)
return list_runs(context.store.state_base)
```

In `resume_run`, replace:

```python
config = load_project_config(project_root, config_path=run.config_path)
store = ProjectStore(
    config.storage.root,
    artifacts_root=config.storage.artifacts,
    state_root=config.storage.state,
)
```

with:

```python
context = load_project_context(project_root, config_path=run.config_path)
store = context.store
```

- [ ] **Step 4: Replace config/store construction in `_execute_run` and `_execute_resume`**

At the start of `_execute_run`, replace:

```python
config = load_project_config(
    request.project_root,
    config_path=request.config_path,
    extra_plugin_paths=request.plugin_paths,
)
store = ProjectStore(
    config.storage.root,
    artifacts_root=config.storage.artifacts,
    state_root=config.storage.state,
)
```

with:

```python
context = load_project_context(
    request.project_root,
    config_path=request.config_path,
    plugin_paths=request.plugin_paths,
)
store = context.store
```

At the start of `_execute_resume`, make the same replacement.

- [ ] **Step 5: Replace config/store construction in `_sync_run_from_workflow_state`**

Replace:

```python
config = load_project_config(project_root, config_path=run.config_path)
store = ProjectStore(
    config.storage.root,
    artifacts_root=config.storage.artifacts,
    state_root=config.storage.state,
)
```

with:

```python
context = load_project_context(project_root, config_path=run.config_path)
store = context.store
```

- [ ] **Step 6: Run run service and API tests**

Run:

```bash
uv run pytest tests/test_application_project_context.py tests/test_application_runs.py tests/test_api_workflows_artifacts_runs.py -q
```

Expected: PASS.

- [ ] **Step 7: Run Ruff on touched files**

Run:

```bash
uv run ruff check src/openbbq/application/runs.py src/openbbq/application/project_context.py tests/test_application_project_context.py tests/test_application_runs.py tests/test_api_workflows_artifacts_runs.py
uv run ruff format --check src/openbbq/application/runs.py src/openbbq/application/project_context.py tests/test_application_project_context.py tests/test_application_runs.py tests/test_api_workflows_artifacts_runs.py
```

Expected: both commands PASS.

- [ ] **Step 8: Commit the runs migration**

```bash
git add src/openbbq/application/runs.py
git commit -m "refactor: Use project context in run service"
```

### Task 6: Verify helper adoption and full suite

**Files:**
- Verify: `src/openbbq/application/**/*.py`
- Verify: `src/openbbq/api/routes/workflows.py`
- Verify: `tests/**/*.py`

- [ ] **Step 1: Scan for remaining duplicated config/store construction in the migrated scope**

Run:

```bash
rg -n "load_project_config\\(|ProjectStore\\(|def _store\\(" src/openbbq/application src/openbbq/api/routes/workflows.py
```

Expected:

- `src/openbbq/application/project_context.py` contains the shared helper.
- `src/openbbq/application/workflows.py`, `src/openbbq/api/routes/workflows.py`, `src/openbbq/application/plugins.py`, `src/openbbq/application/projects.py`, and `src/openbbq/application/diagnostics.py` may still call `load_project_config` where they only need config.
- No `_store(` helper remains in `src/openbbq/application/artifacts.py` or `src/openbbq/api/routes/workflows.py`.
- `src/openbbq/application/runs.py` and `src/openbbq/application/artifacts.py` should not import `load_project_config` directly.

- [ ] **Step 2: Run full lint and format checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: both commands PASS.

- [ ] **Step 3: Run full test suite**

Run:

```bash
uv run pytest
```

Expected: PASS.

- [ ] **Step 4: Commit verification cleanup only if needed**

If Step 1 finds an accidental leftover in the migrated scope, remove it, rerun Steps 1-3, then commit:

```bash
git add src/openbbq/application src/openbbq/api/routes/workflows.py
git commit -m "refactor: Finish project context adoption"
```

If Steps 1-3 pass with no edits, do not create an empty commit.

## Plan self-review checklist

- Spec coverage: This plan implements the audit register item "Repeated project context construction" for the application/API boundary.
- Scope control: CLI and engine internals remain out of scope for later plans.
- Type consistency: The helper functions are named consistently as `project_store_from_config()` and `load_project_context()`.
- Behavior preservation: The helper uses the same `load_project_config(..., extra_plugin_paths=...)` and `ProjectStore(config.storage.root, artifacts_root=config.storage.artifacts, state_root=config.storage.state)` construction already present in the codebase.

# API Route Adapter Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize repeated API active-project validation and one-to-one response schema adaptation without changing endpoint behavior.

**Architecture:** Add two small API-only modules: `openbbq.api.context` owns request-to-active-project settings validation, and `openbbq.api.adapters` owns intentional Pydantic model-to-schema adaptation. Route modules keep business orchestration and custom response assembly, but stop repeating shared glue.

**Tech Stack:** Python 3.11, FastAPI/Starlette `Request`, Pydantic v2 models through `OpenBBQModel`, pytest, Ruff.

---

## File Structure

- Create: `src/openbbq/api/context.py`
  - Exposes `active_project_settings(request)` for routes that require an active API project.
  - Uses `TYPE_CHECKING` for `ApiAppSettings` to avoid a circular import with `openbbq.api.app`, which imports route modules at import time.
- Create: `src/openbbq/api/adapters.py`
  - Exposes `api_model()` and `api_models()` for one-to-one `OpenBBQModel` adaptation into API schemas.
- Create: `tests/test_api_context_adapters.py`
  - Covers the new helpers directly.
- Modify: `src/openbbq/api/routes/runs.py`
  - Uses `active_project_settings()`, `api_model()`, and `api_models()`.
- Modify: `src/openbbq/api/routes/quickstart.py`
  - Uses `active_project_settings()` and `api_model()`.
- Modify: `src/openbbq/api/routes/artifacts.py`
  - Uses `active_project_settings()` and `api_model()` for one-to-one preview/export mappings.
- Modify: `src/openbbq/api/routes/workflows.py`
  - Uses `active_project_settings()` and `api_model()` for workflow detail mapping.
- Modify: `src/openbbq/api/routes/projects.py`
  - Uses `active_project_settings()` and `api_model()`.
- Modify: `src/openbbq/api/routes/plugins.py`
  - Uses `active_project_settings()` and `api_model()`.
- Modify: `src/openbbq/api/routes/runtime.py`
  - Uses `active_project_settings()` for `/doctor`.

Do not modify application services, storage models, API schema fields, route paths, HTTP status mapping, or authentication behavior.

---

### Task 1: Add failing helper tests

**Files:**
- Create: `tests/test_api_context_adapters.py`

- [ ] **Step 1: Create direct tests for context and adapter helpers**

Create `tests/test_api_context_adapters.py` with this content:

```python
from pathlib import Path

import pytest
from fastapi import FastAPI, Request

from openbbq.api.adapters import api_model, api_models
from openbbq.api.app import ApiAppSettings
from openbbq.api.context import active_project_settings
from openbbq.api.schemas import ProjectInitData
from openbbq.domain.base import OpenBBQModel
from openbbq.errors import ValidationError


class SourceModel(OpenBBQModel):
    config_path: Path


def test_active_project_settings_returns_configured_settings(tmp_path):
    settings = ApiAppSettings(project_root=tmp_path, token="token")
    request = _request_for_settings(settings)

    result = active_project_settings(request)

    assert result is settings
    assert result.project_root == tmp_path


def test_active_project_settings_requires_project_root():
    request = _request_for_settings(ApiAppSettings(token="token"))

    with pytest.raises(
        ValidationError,
        match="API sidecar does not have an active project root.",
    ):
        active_project_settings(request)


def test_api_model_adapts_matching_openbbq_models(tmp_path):
    source = SourceModel(config_path=tmp_path / "openbbq.yaml")

    result = api_model(ProjectInitData, source)

    assert isinstance(result, ProjectInitData)
    assert result.config_path == tmp_path / "openbbq.yaml"


def test_api_models_returns_tuple_of_adapted_models(tmp_path):
    first = SourceModel(config_path=tmp_path / "one.yaml")
    second = SourceModel(config_path=tmp_path / "two.yaml")

    result = api_models(ProjectInitData, (first, second))

    assert isinstance(result, tuple)
    assert result == (
        ProjectInitData(config_path=tmp_path / "one.yaml"),
        ProjectInitData(config_path=tmp_path / "two.yaml"),
    )


def _request_for_settings(settings: ApiAppSettings) -> Request:
    app = FastAPI()
    app.state.openbbq_settings = settings
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": "/",
            "headers": [],
        }
    )
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
uv run pytest tests/test_api_context_adapters.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'openbbq.api.adapters'` or `ModuleNotFoundError: No module named 'openbbq.api.context'`.

- [ ] **Step 3: Commit the failing tests**

Run:

```bash
git add tests/test_api_context_adapters.py
git commit -m "test: Cover API context and adapter helpers"
```

---

### Task 2: Implement shared API helpers

**Files:**
- Create: `src/openbbq/api/context.py`
- Create: `src/openbbq/api/adapters.py`
- Test: `tests/test_api_context_adapters.py`

- [ ] **Step 1: Add `src/openbbq/api/context.py`**

Create `src/openbbq/api/context.py` with this content:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from openbbq.errors import ValidationError

if TYPE_CHECKING:
    from openbbq.api.app import ApiAppSettings


def active_project_settings(request: Request) -> ApiAppSettings:
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    return settings
```

- [ ] **Step 2: Add `src/openbbq/api/adapters.py`**

Create `src/openbbq/api/adapters.py` with this content:

```python
from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar

from openbbq.domain.base import OpenBBQModel

T = TypeVar("T", bound=OpenBBQModel)


def api_model(schema_type: type[T], value: OpenBBQModel) -> T:
    return schema_type.model_validate(value.model_dump())


def api_models(schema_type: type[T], values: Iterable[OpenBBQModel]) -> tuple[T, ...]:
    return tuple(api_model(schema_type, value) for value in values)
```

- [ ] **Step 3: Run helper tests to verify they pass**

Run:

```bash
uv run pytest tests/test_api_context_adapters.py -q
```

Expected: PASS with 4 tests passing.

- [ ] **Step 4: Run focused lint and formatting checks**

Run:

```bash
uv run ruff check src/openbbq/api/context.py src/openbbq/api/adapters.py tests/test_api_context_adapters.py
uv run ruff format --check src/openbbq/api/context.py src/openbbq/api/adapters.py tests/test_api_context_adapters.py
```

Expected: both commands exit 0.

- [ ] **Step 5: Commit helper implementation**

Run:

```bash
git add src/openbbq/api/context.py src/openbbq/api/adapters.py tests/test_api_context_adapters.py
git commit -m "refactor: Add API route helper modules"
```

---

### Task 3: Migrate run and quickstart routes

**Files:**
- Modify: `src/openbbq/api/routes/runs.py`
- Modify: `src/openbbq/api/routes/quickstart.py`
- Test: `tests/test_api_workflows_artifacts_runs.py`
- Test: `tests/test_api_projects_plugins_runtime.py`

- [ ] **Step 1: Update imports in `src/openbbq/api/routes/runs.py`**

Replace the current imports from `openbbq.api.schemas` and `openbbq.errors` area with these imports:

```python
from pathlib import Path

from fastapi import APIRouter, Request

from openbbq.api.adapters import api_model, api_models
from openbbq.api.context import active_project_settings
from openbbq.api.schemas import ApiSuccess, RunCreateRequest, RunListData, RunRecord
from openbbq.application.runs import RunCreateRequest as ApplicationRunCreateRequest
from openbbq.application.runs import abort_run, create_run, get_run, list_project_runs, resume_run
from openbbq.errors import ValidationError
```

- [ ] **Step 2: Replace settings lookup and run response mappings in `runs.py`**

Use this route body shape for each function:

```python
settings = active_project_settings(request)
```

Use these response mappings:

```python
return ApiSuccess(data=api_model(RunRecord, run))
```

For the list route, use:

```python
return ApiSuccess(data=RunListData(runs=api_models(RunRecord, runs)))
```

Delete the private `_settings(request: Request)` function entirely. Keep `_resolve_path(path: Path) -> Path` unchanged.

- [ ] **Step 3: Update imports in `src/openbbq/api/routes/quickstart.py`**

Replace the route-local validation imports with helper imports:

```python
from fastapi import APIRouter, Request

from openbbq.api.adapters import api_model
from openbbq.api.context import active_project_settings
from openbbq.api.schemas import (
    ApiSuccess,
    SubtitleJobData,
    SubtitleLocalJobRequest,
    SubtitleYouTubeJobRequest,
)
```

Remove `from openbbq.errors import ValidationError`.

- [ ] **Step 4: Replace settings lookup and subtitle response mappings in `quickstart.py`**

Use `active_project_settings(request)` in both route functions. Replace both `SubtitleJobData(**result.model_dump())` calls with:

```python
return ApiSuccess(data=api_model(SubtitleJobData, result))
```

Delete the private `_settings(request: Request)` function entirely.

- [ ] **Step 5: Run focused API tests**

Run:

```bash
uv run pytest tests/test_api_context_adapters.py tests/test_api_workflows_artifacts_runs.py tests/test_api_projects_plugins_runtime.py -q
```

Expected: PASS.

- [ ] **Step 6: Run focused lint and formatting checks**

Run:

```bash
uv run ruff check src/openbbq/api/routes/runs.py src/openbbq/api/routes/quickstart.py src/openbbq/api/adapters.py src/openbbq/api/context.py tests/test_api_context_adapters.py
uv run ruff format --check src/openbbq/api/routes/runs.py src/openbbq/api/routes/quickstart.py src/openbbq/api/adapters.py src/openbbq/api/context.py tests/test_api_context_adapters.py
```

Expected: both commands exit 0.

- [ ] **Step 7: Commit migrated run and quickstart routes**

Run:

```bash
git add src/openbbq/api/routes/runs.py src/openbbq/api/routes/quickstart.py
git commit -m "refactor: Use API helpers in run routes"
```

---

### Task 4: Migrate artifact and workflow routes

**Files:**
- Modify: `src/openbbq/api/routes/artifacts.py`
- Modify: `src/openbbq/api/routes/workflows.py`
- Test: `tests/test_api_workflows_artifacts_runs.py`
- Test: `tests/test_api_events.py`

- [ ] **Step 1: Update imports in `src/openbbq/api/routes/artifacts.py`**

Add:

```python
from openbbq.api.adapters import api_model
from openbbq.api.context import active_project_settings
```

Remove:

```python
from openbbq.errors import ValidationError
```

- [ ] **Step 2: Replace settings lookup and one-to-one mappings in `artifacts.py`**

Use:

```python
settings = active_project_settings(request)
```

Replace preview/export mappings with:

```python
return ApiSuccess(data=api_model(ArtifactPreviewData, preview))
```

and:

```python
return ApiSuccess(data=api_model(ArtifactExportData, result))
```

Delete the private `_settings(request: Request)` function entirely. Keep `_jsonable_content()` unchanged because artifact content normalization is custom response assembly.

- [ ] **Step 3: Update imports in `src/openbbq/api/routes/workflows.py`**

Add:

```python
from openbbq.api.adapters import api_model
from openbbq.api.context import active_project_settings
```

Keep `from openbbq.errors import ValidationError` because missing workflow IDs still raise a route-level validation error.

- [ ] **Step 4: Replace settings lookup and workflow detail mapping in `workflows.py`**

Use `active_project_settings(request)` in every route function that currently calls `_settings(request)`.

Replace:

```python
return ApiSuccess(data=WorkflowDetailData(**summary.model_dump()))
```

with:

```python
return ApiSuccess(data=api_model(WorkflowDetailData, summary))
```

Delete the private `_settings(request: Request)` function entirely. Keep `_workflow_summary()` unchanged.

- [ ] **Step 5: Run focused API tests**

Run:

```bash
uv run pytest tests/test_api_context_adapters.py tests/test_api_workflows_artifacts_runs.py tests/test_api_events.py -q
```

Expected: PASS.

- [ ] **Step 6: Run focused lint and formatting checks**

Run:

```bash
uv run ruff check src/openbbq/api/routes/artifacts.py src/openbbq/api/routes/workflows.py src/openbbq/api/adapters.py src/openbbq/api/context.py tests/test_api_context_adapters.py
uv run ruff format --check src/openbbq/api/routes/artifacts.py src/openbbq/api/routes/workflows.py src/openbbq/api/adapters.py src/openbbq/api/context.py tests/test_api_context_adapters.py
```

Expected: both commands exit 0.

- [ ] **Step 7: Commit migrated artifact and workflow routes**

Run:

```bash
git add src/openbbq/api/routes/artifacts.py src/openbbq/api/routes/workflows.py
git commit -m "refactor: Use API helpers in workflow routes"
```

---

### Task 5: Migrate project, plugin, and doctor routes

**Files:**
- Modify: `src/openbbq/api/routes/projects.py`
- Modify: `src/openbbq/api/routes/plugins.py`
- Modify: `src/openbbq/api/routes/runtime.py`
- Test: `tests/test_api_projects_plugins_runtime.py`

- [ ] **Step 1: Update `src/openbbq/api/routes/projects.py`**

Use these imports:

```python
from fastapi import APIRouter, Request

from openbbq.api.adapters import api_model
from openbbq.api.context import active_project_settings
from openbbq.api.schemas import ApiSuccess, ProjectInfoData, ProjectInitData, ProjectInitRequest
from openbbq.application.projects import ProjectInitRequest as ApplicationProjectInitRequest
from openbbq.application.projects import init_project, project_info
```

Replace result mappings with:

```python
return ApiSuccess(data=api_model(ProjectInitData, result))
```

and:

```python
settings = active_project_settings(request)
...
return ApiSuccess(data=api_model(ProjectInfoData, info))
```

Remove `from openbbq.errors import ValidationError`.

- [ ] **Step 2: Update `src/openbbq/api/routes/plugins.py`**

Use these imports:

```python
from fastapi import APIRouter, Request

from openbbq.api.adapters import api_model
from openbbq.api.context import active_project_settings
from openbbq.api.schemas import ApiSuccess, PluginListData
from openbbq.application.plugins import PluginInfoResult, plugin_info, plugin_list
```

Use `active_project_settings(request)` in both route functions. Replace:

```python
return ApiSuccess(data=PluginListData(**result.model_dump()))
```

with:

```python
return ApiSuccess(data=api_model(PluginListData, result))
```

Remove `from openbbq.errors import ValidationError`.

- [ ] **Step 3: Update `src/openbbq/api/routes/runtime.py`**

Add:

```python
from openbbq.api.context import active_project_settings
```

Remove:

```python
from openbbq.errors import ValidationError
```

In `get_doctor()`, replace the inline app-state validation with:

```python
settings = active_project_settings(request)
```

Keep the explicit `DoctorData(ok=result.ok, checks=result.checks)` construction.

- [ ] **Step 4: Run focused API tests**

Run:

```bash
uv run pytest tests/test_api_context_adapters.py tests/test_api_projects_plugins_runtime.py tests/test_api_server.py tests/test_api_schemas.py -q
```

Expected: PASS.

- [ ] **Step 5: Run focused lint and formatting checks**

Run:

```bash
uv run ruff check src/openbbq/api/routes/projects.py src/openbbq/api/routes/plugins.py src/openbbq/api/routes/runtime.py src/openbbq/api/adapters.py src/openbbq/api/context.py tests/test_api_context_adapters.py
uv run ruff format --check src/openbbq/api/routes/projects.py src/openbbq/api/routes/plugins.py src/openbbq/api/routes/runtime.py src/openbbq/api/adapters.py src/openbbq/api/context.py tests/test_api_context_adapters.py
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit migrated project, plugin, and doctor routes**

Run:

```bash
git add src/openbbq/api/routes/projects.py src/openbbq/api/routes/plugins.py src/openbbq/api/routes/runtime.py
git commit -m "refactor: Use API helpers in project routes"
```

---

### Task 6: Adoption scan and full verification

**Files:**
- Verify: `src/openbbq/api/routes/*.py`
- Verify: `src/openbbq/api/context.py`
- Verify: `src/openbbq/api/adapters.py`
- Verify: `tests/test_api_context_adapters.py`

- [ ] **Step 1: Scan for removed route-local settings helpers**

Run:

```bash
rg -n "def _settings\\(" src/openbbq/api/routes
```

Expected: no output.

- [ ] **Step 2: Scan for remaining model-dump schema rebuilding in routes**

Run:

```bash
rg -n "\\*\\*.*model_dump\\(\\)|model_dump\\(\\)" src/openbbq/api/routes
```

Expected: no output from route files for the one-to-one mappings covered by this plan. If output remains for a custom response path, inspect it and either keep it with a clear reason or replace it with `api_model()`.

- [ ] **Step 3: Confirm application modules do not import API modules**

Run:

```bash
rg -n "openbbq\\.api" src/openbbq/application src/openbbq/storage src/openbbq/engine src/openbbq/workflow src/openbbq/plugins
```

Expected: no output.

- [ ] **Step 4: Run API behavior tests**

Run:

```bash
uv run pytest tests/test_api_context_adapters.py tests/test_api_workflows_artifacts_runs.py tests/test_api_events.py tests/test_api_projects_plugins_runtime.py tests/test_api_server.py tests/test_api_schemas.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run:

```bash
uv run pytest
```

Expected: PASS.

- [ ] **Step 6: Run full lint and formatting checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: both commands exit 0.

- [ ] **Step 7: Commit final verification cleanups if needed**

If Step 1 through Step 6 required any code changes, commit them:

```bash
git add src/openbbq/api tests/test_api_context_adapters.py
git commit -m "refactor: Finish API adapter cleanup"
```

If no files changed after the previous task commits, do not create an empty commit.

---

## Plan Self-Review

- Spec coverage: The plan adds shared active-project settings lookup, shared one-to-one response adapters, migrates the specified route modules, preserves custom response assembly, and includes helper tests plus existing API/full-suite verification.
- Completeness scan: The plan has no incomplete tasks, unintroduced helper names, or unspecified test commands.
- Type consistency: The helper names are consistently `active_project_settings()`, `api_model()`, and `api_models()`. `active_project_settings()` uses `TYPE_CHECKING` for `ApiAppSettings` so route imports do not create a circular dependency through `openbbq.api.app`.

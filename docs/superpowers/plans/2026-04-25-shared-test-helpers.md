# Shared Test Helpers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract repeated fixture-project and authenticated API-client setup from tests into shared helpers while preserving all test behavior.

**Architecture:** Add a small `tests/helpers.py` module for reusable test-only helpers. Migrate only tests that copy canonical fixture projects or create the standard token-authenticated API sidecar client. Leave bespoke `write_project` helpers in place when they construct custom inline projects for a specific test.

**Tech Stack:** Python, pytest, FastAPI `TestClient`, existing OpenBBQ test fixtures.

---

## File structure

- Create: `tests/helpers.py`
  - Owns fixture project copying and standard API client construction for tests.
- Create: `tests/__init__.py`
  - Marks `tests` as an importable package so test modules can use `from tests.helpers import ...` reliably under pytest.
- Create: `tests/test_helpers.py`
  - Verifies helper behavior before migrating existing tests.
- Modify: `tests/test_api_events.py`
  - Use shared fixture project and API client helpers.
- Modify: `tests/test_api_workflows_artifacts_runs.py`
  - Use shared fixture project and API client helpers, including the `raise_server_exceptions=False` case.
- Modify: `tests/test_api_projects_plugins_runtime.py`
  - Use shared fixture project and API client helpers while keeping direct no-project client setup for project init.
- Modify: `tests/test_runtime_engine.py`
  - Use shared fixture project helper.
- Modify: `tests/test_phase1_acceptance.py`
  - Use shared fixture project helper.
- Modify: `tests/test_engine_run_text.py`
  - Use shared fixture project helper.
- Modify: `tests/test_application_workflows.py`
  - Use shared fixture project helper.
- Modify: `tests/test_cli_integration.py`
  - Use shared fixture project helper.
- Modify: `tests/test_application_runs.py`
  - Use shared fixture project helper.
- Modify: `tests/test_engine_abort.py`
  - Use shared fixture project helper.
- Modify: `tests/test_engine_rerun.py`
  - Use shared fixture project helper.
- Modify: `tests/test_cli_control_flow.py`
  - Use shared fixture project helper.
- Modify: `tests/test_engine_pause_resume.py`
  - Use shared fixture project helper.

Do not migrate these helpers in this plan because they create custom inline projects or custom phase-2 fixture projects with test-specific content: `tests/test_artifact_import.py`, `tests/test_artifact_diff.py`, `tests/test_builtin_plugins.py`, `tests/test_phase2_local_video_subtitle.py`, `tests/test_phase2_translation_slice.py`, `tests/test_phase2_asr_correction_segmentation.py`, and `tests/test_phase2_remote_video_slice.py`.

### Task 1: Add tests for shared helpers

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_helpers.py`
- Later create: `tests/helpers.py`

- [ ] **Step 1: Mark the test directory as an importable package**

Create `tests/__init__.py` with this content:

```python
"""Test support package for OpenBBQ."""
```

- [ ] **Step 2: Write failing tests for fixture copying and authenticated API clients**

Create `tests/test_helpers.py` with this content:

```python
from pathlib import Path

from tests.helpers import authed_client, write_project_fixture


def test_write_project_fixture_copies_config_and_rewrites_plugin_path(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")

    config_text = (project / "openbbq.yaml").read_text(encoding="utf-8")

    assert project == tmp_path / "project"
    assert "../../plugins" not in config_text
    assert str((Path(__file__).parent / "fixtures" / "plugins").resolve()) in config_text


def test_authed_client_returns_standard_token_headers(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project)

    response = client.get("/projects/current", headers=headers)

    assert headers == {"Authorization": "Bearer token"}
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Text Basic"
```

- [ ] **Step 3: Run helper tests and verify they fail because the helper module is missing**

Run:

```bash
uv run pytest tests/test_helpers.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tests.helpers'`.

- [ ] **Step 4: Commit the failing helper tests**

```bash
git add tests/__init__.py tests/test_helpers.py
git commit -m "test: Cover shared test helpers"
```

### Task 2: Implement shared helper module

**Files:**
- Create: `tests/helpers.py`
- Test: `tests/test_helpers.py`

- [ ] **Step 1: Create the shared helper module**

Create `tests/helpers.py` with this content:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from openbbq.api.app import ApiAppSettings, create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
PROJECT_FIXTURE_ROOT = FIXTURE_ROOT / "projects"
PLUGIN_FIXTURE_ROOT = FIXTURE_ROOT / "plugins"
DEFAULT_API_TOKEN = "token"


def write_project_fixture(
    tmp_path: Path,
    fixture_name: str,
    *,
    project_dir_name: str = "project",
) -> Path:
    project = tmp_path / project_dir_name
    project.mkdir()
    source = (PROJECT_FIXTURE_ROOT / fixture_name / "openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(PLUGIN_FIXTURE_ROOT.resolve())),
        encoding="utf-8",
    )
    return project


def api_auth_headers(token: str = DEFAULT_API_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def authed_client(
    project: Path,
    *,
    token: str = DEFAULT_API_TOKEN,
    execute_runs_inline: bool = True,
    raise_server_exceptions: bool = True,
    **settings_overrides: Any,
) -> tuple[TestClient, dict[str, str]]:
    settings = ApiAppSettings(
        project_root=project,
        token=token,
        execute_runs_inline=execute_runs_inline,
        **settings_overrides,
    )
    client = TestClient(
        create_app(settings),
        raise_server_exceptions=raise_server_exceptions,
    )
    return client, api_auth_headers(token)
```

- [ ] **Step 2: Run helper tests and verify they pass**

Run:

```bash
uv run pytest tests/test_helpers.py -q
```

Expected: PASS, `2 passed`.

- [ ] **Step 3: Run Ruff on the new helper files**

Run:

```bash
uv run ruff check tests/helpers.py tests/test_helpers.py
uv run ruff format --check tests/helpers.py tests/test_helpers.py
```

Expected: both commands PASS.

- [ ] **Step 4: Commit the helper implementation**

```bash
git add tests/helpers.py tests/test_helpers.py
git commit -m "test: Add shared test helper module"
```

### Task 3: Migrate API tests to shared helpers

**Files:**
- Modify: `tests/test_api_events.py`
- Modify: `tests/test_api_workflows_artifacts_runs.py`
- Modify: `tests/test_api_projects_plugins_runtime.py`
- Test: `tests/test_api_events.py`
- Test: `tests/test_api_workflows_artifacts_runs.py`
- Test: `tests/test_api_projects_plugins_runtime.py`

- [ ] **Step 1: Update `tests/test_api_events.py` imports and setup**

Remove these imports from `tests/test_api_events.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from openbbq.api.app import ApiAppSettings, create_app
```

Add this import:

```python
from tests.helpers import authed_client, write_project_fixture
```

Delete the local `write_project` function. Replace the API setup inside `test_events_history_route_replays_after_sequence` with:

```python
project = write_project_fixture(tmp_path, "text-basic")
client, headers = authed_client(project)
```

- [ ] **Step 2: Update `tests/test_api_workflows_artifacts_runs.py` imports and setup**

Remove these imports from `tests/test_api_workflows_artifacts_runs.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from openbbq.api.app import ApiAppSettings, create_app
```

Add this import:

```python
from tests.helpers import authed_client, write_project_fixture
```

Delete the local `write_project` function. Replace fixture calls:

```python
project = write_project(tmp_path, "text-basic")
```

with:

```python
project = write_project_fixture(tmp_path, "text-basic")
```

Replace the default inline client setup:

```python
client = TestClient(
    create_app(ApiAppSettings(project_root=project, token="token", execute_runs_inline=True))
)
headers = {"Authorization": "Bearer token"}
```

with:

```python
client, headers = authed_client(project)
```

Replace the missing-run client setup:

```python
client = TestClient(
    create_app(ApiAppSettings(project_root=project, token="token")),
    raise_server_exceptions=False,
)
headers = {"Authorization": "Bearer token"}
```

with:

```python
client, headers = authed_client(project, raise_server_exceptions=False)
```

- [ ] **Step 3: Update `tests/test_api_projects_plugins_runtime.py` imports and setup**

Keep these imports because `test_project_init_route_creates_project_config` still creates an app without a project root:

```python
from fastapi.testclient import TestClient

from openbbq.api.app import ApiAppSettings, create_app
```

Add this import:

```python
from tests.helpers import authed_client, write_project_fixture
```

Delete the local `write_project` and `authed_client` functions. Replace calls such as:

```python
project = write_project(tmp_path, "text-basic")
client, headers = authed_client(project)
```

with:

```python
project = write_project_fixture(tmp_path, "text-basic")
client, headers = authed_client(project)
```

- [ ] **Step 4: Run the migrated API tests**

Run:

```bash
uv run pytest tests/test_helpers.py tests/test_api_events.py tests/test_api_workflows_artifacts_runs.py tests/test_api_projects_plugins_runtime.py -q
```

Expected: PASS.

- [ ] **Step 5: Run Ruff on migrated API tests**

Run:

```bash
uv run ruff check tests/helpers.py tests/test_helpers.py tests/test_api_events.py tests/test_api_workflows_artifacts_runs.py tests/test_api_projects_plugins_runtime.py
uv run ruff format --check tests/helpers.py tests/test_helpers.py tests/test_api_events.py tests/test_api_workflows_artifacts_runs.py tests/test_api_projects_plugins_runtime.py
```

Expected: both commands PASS.

- [ ] **Step 6: Commit the API test migration**

```bash
git add tests/helpers.py tests/test_helpers.py tests/test_api_events.py tests/test_api_workflows_artifacts_runs.py tests/test_api_projects_plugins_runtime.py
git commit -m "test: Reuse helpers in API route tests"
```

### Task 4: Migrate engine, application, and CLI tests that copy canonical fixtures

**Files:**
- Modify: `tests/test_runtime_engine.py`
- Modify: `tests/test_phase1_acceptance.py`
- Modify: `tests/test_engine_run_text.py`
- Modify: `tests/test_application_workflows.py`
- Modify: `tests/test_cli_integration.py`
- Modify: `tests/test_application_runs.py`
- Modify: `tests/test_engine_abort.py`
- Modify: `tests/test_engine_rerun.py`
- Modify: `tests/test_cli_control_flow.py`
- Modify: `tests/test_engine_pause_resume.py`

- [ ] **Step 1: Remove local fixture-copy helpers**

In each file listed for this task, delete the local function with this shape:

```python
def write_project(tmp_path, fixture_name: str) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path(f"tests/fixtures/projects/{fixture_name}/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )
    return project
```

- [ ] **Step 2: Add the shared helper import to each migrated file**

Add this import near the other imports in each migrated file:

```python
from tests.helpers import write_project_fixture
```

Remove `from pathlib import Path` from any migrated file where it was only used by the deleted local helper.

- [ ] **Step 3: Replace fixture project calls**

In each migrated file, replace:

```python
project = write_project(tmp_path, "text-basic")
```

with:

```python
project = write_project_fixture(tmp_path, "text-basic")
```

Replace:

```python
project = write_project(tmp_path, "text-pause")
```

with:

```python
project = write_project_fixture(tmp_path, "text-pause")
```

- [ ] **Step 4: Run the migrated non-API tests**

Run:

```bash
uv run pytest \
  tests/test_runtime_engine.py \
  tests/test_phase1_acceptance.py \
  tests/test_engine_run_text.py \
  tests/test_application_workflows.py \
  tests/test_cli_integration.py \
  tests/test_application_runs.py \
  tests/test_engine_abort.py \
  tests/test_engine_rerun.py \
  tests/test_cli_control_flow.py \
  tests/test_engine_pause_resume.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Run Ruff on migrated non-API tests**

Run:

```bash
uv run ruff check \
  tests/test_runtime_engine.py \
  tests/test_phase1_acceptance.py \
  tests/test_engine_run_text.py \
  tests/test_application_workflows.py \
  tests/test_cli_integration.py \
  tests/test_application_runs.py \
  tests/test_engine_abort.py \
  tests/test_engine_rerun.py \
  tests/test_cli_control_flow.py \
  tests/test_engine_pause_resume.py
uv run ruff format --check \
  tests/test_runtime_engine.py \
  tests/test_phase1_acceptance.py \
  tests/test_engine_run_text.py \
  tests/test_application_workflows.py \
  tests/test_cli_integration.py \
  tests/test_application_runs.py \
  tests/test_engine_abort.py \
  tests/test_engine_rerun.py \
  tests/test_cli_control_flow.py \
  tests/test_engine_pause_resume.py
```

Expected: both commands PASS.

- [ ] **Step 6: Commit the non-API test migration**

```bash
git add \
  tests/test_runtime_engine.py \
  tests/test_phase1_acceptance.py \
  tests/test_engine_run_text.py \
  tests/test_application_workflows.py \
  tests/test_cli_integration.py \
  tests/test_application_runs.py \
  tests/test_engine_abort.py \
  tests/test_engine_rerun.py \
  tests/test_cli_control_flow.py \
  tests/test_engine_pause_resume.py
git commit -m "test: Reuse fixture helper in workflow tests"
```

### Task 5: Verify duplicate helper cleanup and full suite

**Files:**
- Verify: `tests/**/*.py`
- Verify: `docs/superpowers/specs/2026-04-25-code-quality-audit-design.md`

- [ ] **Step 1: Confirm only bespoke `write_project` helpers remain**

Run:

```bash
rg -n "^def write_project|^def authed_client" tests
```

Expected output should not include the migrated files. Remaining `write_project` helpers should be limited to tests with custom inline or phase-2 project creation, such as:

```text
tests/test_artifact_import.py
tests/test_artifact_diff.py
tests/test_builtin_plugins.py
tests/test_phase2_local_video_subtitle.py
tests/test_phase2_translation_slice.py
tests/test_phase2_asr_correction_segmentation.py
tests/test_phase2_remote_video_slice.py
```

The shared helpers should appear in:

```text
tests/helpers.py
```

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

Expected: PASS with the same skipped-test count as the baseline unless unrelated environment conditions change.

- [ ] **Step 4: Commit final verification notes if any migration cleanup was needed**

If Step 1 revealed a migrated file still defining a duplicated helper, remove that helper, rerun Steps 1-3, then commit:

```bash
git add tests
git commit -m "test: Finish shared helper migration"
```

If Step 1-3 already pass with no additional edits after Task 4, do not create an empty commit.

## Plan self-review checklist

- Spec coverage: This plan implements the first follow-up item from the audit register, "Extract shared test helpers for project fixtures and API clients."
- Scope control: This plan intentionally does not touch production code, API route helpers, run lifecycle code, CLI splitting, or built-in LLM plugin refactors.
- Type consistency: The plan defines `write_project_fixture`, `api_auth_headers`, and `authed_client` once in `tests/helpers.py` and uses those names consistently.
- Behavior preservation: The helper keeps the same default project directory name, fixture config file, absolute plugin path rewrite, token value, and inline execution default used by the duplicated tests.

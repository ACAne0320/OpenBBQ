# Package Layout Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move OpenBBQ Phase 1 backend code into strict `cli/config/domain/engine/workflow/plugins/storage` subpackages without preserving old flat import paths.

**Architecture:** Keep `domain.models` as the dependency-free model layer, `storage.project_store` as durable persistence, `plugins.registry` as plugin discovery/execution, `workflow.*` as execution helpers, `engine.validation` as reusable validation, `engine.service` as orchestration, and `cli.app` as the command-line edge. Use strict imports from concrete submodules and keep package `__init__.py` files as lightweight markers.

**Tech Stack:** Python 3.11, setuptools package discovery under `src`, pytest, Ruff, uv.

---

## File Structure

- Create `src/openbbq/cli/__init__.py`: package marker with no compatibility re-exports.
- Create `src/openbbq/cli/app.py`: moved CLI parser and command handlers from `src/openbbq/cli.py`.
- Create `src/openbbq/config/__init__.py`: package marker with no compatibility re-exports.
- Create `src/openbbq/config/loader.py`: moved config loading and precedence logic from `src/openbbq/config.py`.
- Create `src/openbbq/domain/__init__.py`: package marker with no compatibility re-exports.
- Create `src/openbbq/domain/models.py`: moved domain dataclasses from `src/openbbq/domain.py` plus workflow model exports formerly in `src/openbbq/models/workflow.py`.
- Create `src/openbbq/engine/__init__.py`: package marker with no compatibility re-exports.
- Create `src/openbbq/engine/service.py`: orchestration functions formerly in `src/openbbq/engine.py`.
- Create `src/openbbq/engine/validation.py`: `WorkflowValidationResult`, `validate_workflow`, and validation helper functions extracted from `src/openbbq/engine.py`.
- Create `src/openbbq/workflow/__init__.py`: package marker with no compatibility re-exports.
- Create `src/openbbq/workflow/*.py`: moved workflow helpers from `src/openbbq/core/workflow/*.py`.
- Create `src/openbbq/plugins/__init__.py`: package marker with no compatibility re-exports.
- Create `src/openbbq/plugins/registry.py`: moved plugin registry, manifest loading, and plugin execution from `src/openbbq/plugins.py`.
- Create `src/openbbq/storage/__init__.py`: package marker with no compatibility re-exports.
- Create `src/openbbq/storage/project_store.py`: moved project persistence classes and helpers from `src/openbbq/storage.py`.
- Modify `pyproject.toml`: change the console script to `openbbq.cli.app:main`.
- Modify `tests/*.py`: update imports to strict submodule paths.
- Create `tests/test_package_layout.py`: import-boundary regression coverage.
- Modify current docs that describe the source tree: `AGENTS.md`, `README.md`, and relevant `docs/phase1/*.md`.
- Remove obsolete source paths after moves: `src/openbbq/cli.py`, `src/openbbq/config.py`, `src/openbbq/domain.py`, `src/openbbq/engine.py`, `src/openbbq/plugins.py`, `src/openbbq/storage.py`, `src/openbbq/core/`, and `src/openbbq/models/`.

## Task 1: Add Import-Boundary Regression Tests

**Files:**
- Create: `tests/test_package_layout.py`

- [ ] **Step 1: Write the failing package layout tests**

Create `tests/test_package_layout.py` with this content:

```python
from __future__ import annotations

import importlib
from pathlib import Path


def test_new_package_modules_are_importable() -> None:
    modules = [
        "openbbq.cli.app",
        "openbbq.config.loader",
        "openbbq.domain.models",
        "openbbq.engine.service",
        "openbbq.engine.validation",
        "openbbq.plugins.registry",
        "openbbq.storage.project_store",
        "openbbq.workflow.aborts",
        "openbbq.workflow.bindings",
        "openbbq.workflow.diff",
        "openbbq.workflow.execution",
        "openbbq.workflow.locks",
        "openbbq.workflow.rerun",
        "openbbq.workflow.state",
    ]

    for module in modules:
        importlib.import_module(module)


def test_obsolete_source_modules_are_removed() -> None:
    root = Path(__file__).resolve().parents[1]
    obsolete_paths = [
        "src/openbbq/cli.py",
        "src/openbbq/config.py",
        "src/openbbq/domain.py",
        "src/openbbq/engine.py",
        "src/openbbq/plugins.py",
        "src/openbbq/storage.py",
        "src/openbbq/core",
        "src/openbbq/models",
    ]

    remaining = [path for path in obsolete_paths if (root / path).exists()]

    assert remaining == []
```

- [ ] **Step 2: Run the new tests to verify RED**

Run:

```bash
uv run pytest tests/test_package_layout.py -q
```

Expected: FAIL because `openbbq.cli.app` does not exist and the old flat source files still exist.

- [ ] **Step 3: Commit the failing tests**

Run:

```bash
git add tests/test_package_layout.py
git commit -m "test: Add package layout boundary checks"
```

## Task 2: Move Files Into Target Packages

**Files:**
- Create: `src/openbbq/cli/__init__.py`
- Create: `src/openbbq/config/__init__.py`
- Create: `src/openbbq/domain/__init__.py`
- Create: `src/openbbq/engine/__init__.py`
- Create: `src/openbbq/workflow/__init__.py`
- Create: `src/openbbq/plugins/__init__.py`
- Create: `src/openbbq/storage/__init__.py`
- Move: `src/openbbq/cli.py` to `src/openbbq/cli/app.py`
- Move: `src/openbbq/config.py` to `src/openbbq/config/loader.py`
- Move: `src/openbbq/domain.py` to `src/openbbq/domain/models.py`
- Move: `src/openbbq/engine.py` to `src/openbbq/engine/service.py`
- Move: `src/openbbq/core/workflow/*.py` to `src/openbbq/workflow/*.py`
- Move: `src/openbbq/plugins.py` to `src/openbbq/plugins/registry.py`
- Move: `src/openbbq/storage.py` to `src/openbbq/storage/project_store.py`
- Remove: `src/openbbq/core/`
- Remove: `src/openbbq/models/`

- [ ] **Step 1: Create target package directories and marker files**

Run:

```bash
mkdir -p src/openbbq/cli src/openbbq/config src/openbbq/domain src/openbbq/engine src/openbbq/workflow src/openbbq/plugins src/openbbq/storage
touch src/openbbq/cli/__init__.py src/openbbq/config/__init__.py src/openbbq/domain/__init__.py src/openbbq/engine/__init__.py src/openbbq/workflow/__init__.py src/openbbq/plugins/__init__.py src/openbbq/storage/__init__.py
```

Expected: directories and marker files exist.

- [ ] **Step 2: Move source files**

Run:

```bash
git mv src/openbbq/cli.py src/openbbq/cli/app.py
git mv src/openbbq/config.py src/openbbq/config/loader.py
git mv src/openbbq/domain.py src/openbbq/domain/models.py
git mv src/openbbq/engine.py src/openbbq/engine/service.py
git mv src/openbbq/core/workflow/aborts.py src/openbbq/workflow/aborts.py
git mv src/openbbq/core/workflow/bindings.py src/openbbq/workflow/bindings.py
git mv src/openbbq/core/workflow/diff.py src/openbbq/workflow/diff.py
git mv src/openbbq/core/workflow/execution.py src/openbbq/workflow/execution.py
git mv src/openbbq/core/workflow/locks.py src/openbbq/workflow/locks.py
git mv src/openbbq/core/workflow/rerun.py src/openbbq/workflow/rerun.py
git mv src/openbbq/core/workflow/state.py src/openbbq/workflow/state.py
git mv src/openbbq/plugins.py src/openbbq/plugins/registry.py
git mv src/openbbq/storage.py src/openbbq/storage/project_store.py
git rm src/openbbq/core/workflow/__init__.py src/openbbq/core/__init__.py src/openbbq/models/workflow.py src/openbbq/models/__init__.py
```

Expected: `git status --short` shows moved files into subpackages and removed old `core`/`models` files.

- [ ] **Step 3: Add workflow model names to `domain.models`**

Confirm `src/openbbq/domain/models.py` includes these names, which were formerly re-exported by `openbbq.models.workflow`:

```python
ProjectConfig
StepConfig
StepOutput
WorkflowConfig
```

Expected: no additional code is required because these dataclasses already lived in `domain.py` before the move.

## Task 3: Extract Engine Validation

**Files:**
- Create: `src/openbbq/engine/validation.py`
- Modify: `src/openbbq/engine/service.py`

- [ ] **Step 1: Move validation dataclass and helpers into `engine.validation`**

Create `src/openbbq/engine/validation.py` by extracting:

```python
from __future__ import annotations

from dataclasses import dataclass

from jsonschema import Draft7Validator

from openbbq.domain.models import ProjectConfig, StepConfig, StepOutput, WorkflowConfig
from openbbq.errors import ValidationError
from openbbq.plugins.registry import PluginRegistry, ToolSpec
from openbbq.workflow.bindings import parse_step_selector


@dataclass(frozen=True, slots=True)
class WorkflowValidationResult:
    workflow_id: str
    step_count: int


def validate_workflow(
    config: ProjectConfig,
    registry: PluginRegistry,
    workflow_id: str,
) -> WorkflowValidationResult:
    workflow = config.workflows.get(workflow_id)
    if workflow is None:
        raise ValidationError(f"Workflow '{workflow_id}' is not defined.")

    step_outputs = _step_outputs_by_id(workflow)
    for step in workflow.steps:
        _validate_step_control(step, workflow)
        tool = registry.tools.get(step.tool_ref)
        if tool is None:
            raise ValidationError(f"Step '{step.id}' references unknown tool '{step.tool_ref}'.")
        _validate_parameters(step, tool)
        _validate_step_inputs(step, tool, step_outputs)
        _validate_step_outputs(step, tool)

    return WorkflowValidationResult(workflow_id=workflow.id, step_count=len(workflow.steps))
```

The private helper functions `_validate_step_control`, `_validate_parameters`, `_validate_step_inputs`, `_validate_step_outputs`, and `_step_outputs_by_id` move unchanged except for their imports.

- [ ] **Step 2: Update `engine.service` to import validation**

Remove validation helper code from `src/openbbq/engine/service.py` and import:

```python
from openbbq.engine.validation import validate_workflow
```

Expected: `engine.service` still defines `WorkflowRunResult`, `run_workflow`, `resume_workflow`, `abort_workflow`, and `unlock_workflow`.

- [ ] **Step 3: Run targeted validation tests**

Run:

```bash
uv run pytest tests/test_engine_validate.py -q
```

Expected: PASS after imports are updated in later tasks; before import updates this may still fail because tests reference old paths.

## Task 4: Update Imports And Entrypoint

**Files:**
- Modify: `src/openbbq/**/*.py`
- Modify: `tests/*.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Replace old imports with strict submodule imports**

Apply these mappings across source and tests:

```text
openbbq.cli -> openbbq.cli.app
openbbq.config -> openbbq.config.loader
openbbq.domain -> openbbq.domain.models
openbbq.engine -> openbbq.engine.service
openbbq.plugins -> openbbq.plugins.registry
openbbq.storage -> openbbq.storage.project_store
openbbq.core.workflow -> openbbq.workflow
openbbq.models.workflow -> openbbq.domain.models
```

Expected examples after replacement:

```python
from openbbq.config.loader import load_project_config
from openbbq.domain.models import ProjectConfig
from openbbq.engine.service import run_workflow
from openbbq.engine.validation import validate_workflow
from openbbq.plugins.registry import discover_plugins
from openbbq.storage.project_store import ProjectStore
from openbbq.workflow.locks import WorkflowLock
```

- [ ] **Step 2: Point validation imports to `engine.validation`**

In tests that only need validation, use:

```python
from openbbq.engine.validation import validate_workflow
```

In CLI code, import validation from `engine.validation` and orchestration from `engine.service`.

- [ ] **Step 3: Update console script**

Change `pyproject.toml`:

```toml
openbbq = "openbbq.cli.app:main"
```

- [ ] **Step 4: Run import-boundary tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_package_layout.py -q
```

Expected: PASS.

## Task 5: Update Current Documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: relevant `docs/phase1/*.md`
- Modify: relevant current Superpowers docs that describe current source paths

- [ ] **Step 1: Update source tree references**

Use:

```bash
rg -n "openbbq\\.(core|models|cli|config|domain|engine|plugins|storage)|src/openbbq|openbbq = \"openbbq\\.cli" AGENTS.md README.md docs/phase1 docs/superpowers/specs/2026-04-22-package-layout-refactor-design.md docs/superpowers/plans/2026-04-22-package-layout-refactor.md
```

Update current documentation so it names the new package layout and entry point.

- [ ] **Step 2: Preserve historical plans as historical records**

Do not rewrite older dated implementation plans solely to change code snippets that were accurate when written. Current docs and the new package-layout design/plan must reflect the new layout.

- [ ] **Step 3: Confirm docs do not describe old paths as current**

Run:

```bash
rg -n "openbbq\\.core\\.workflow|openbbq\\.models\\.workflow|openbbq = \"openbbq\\.cli:main\"" AGENTS.md README.md docs/phase1 docs/superpowers/specs/2026-04-22-package-layout-refactor-design.md docs/superpowers/plans/2026-04-22-package-layout-refactor.md
```

Expected: no matches outside sections explicitly describing the pre-refactor baseline in the approved design.

## Task 6: Full Verification And Commit

**Files:**
- Modify all files changed by Tasks 1-5.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
uv run pytest
```

Expected: all tests pass.

- [ ] **Step 2: Run lint**

Run:

```bash
uv run ruff check .
```

Expected: all checks pass.

- [ ] **Step 3: Run formatting check**

Run:

```bash
uv run ruff format --check .
```

Expected: all files are formatted.

- [ ] **Step 4: Run console script smoke test**

Run:

```bash
uv run openbbq validate text-demo --project tests/fixtures/projects/text-basic
```

Expected: command exits 0 and validates `text-demo`.

- [ ] **Step 5: Inspect import references**

Run:

```bash
rg -n "from openbbq\\.(cli|config|domain|engine|plugins|storage) import|from openbbq\\.core|from openbbq\\.models|import openbbq\\.(cli|config|domain|engine|plugins|storage)" src tests
```

Expected: no matches for old flat imports or removed package paths.

- [ ] **Step 6: Commit implementation**

Run:

```bash
git add AGENTS.md README.md docs pyproject.toml src tests
git commit -m "refactor: Restructure openbbq package layout"
```

Expected: commit succeeds on `feature/package-layout-refactor`.


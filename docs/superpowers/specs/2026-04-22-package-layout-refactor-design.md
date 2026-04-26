# Package Layout Refactor Design

## Goal

Refactor the Phase 1 Python package from flat modules and interim workflow paths into explicit subpackages:

```text
src/openbbq/
  cli/
  config/
  domain/
  engine/
  workflow/
  plugins/
  storage/
```

The package layout should make each backend responsibility easier to find and maintain while preserving the existing CLI behavior and Phase 1 runtime semantics.

## Original Baseline

At the time this design was written, the implementation was functionally
complete for Phase 1, but the source tree still mixed stable package boundaries
with earlier Slice 1 paths:

- `openbbq.cli`, `openbbq.config`, `openbbq.domain`, `openbbq.engine`, `openbbq.plugins`, and `openbbq.storage` are flat modules.
- Workflow internals live under `openbbq.core.workflow`.
- Workflow/domain models are split between `openbbq.domain` and `openbbq.models.workflow`.
- The CLI entry point targets `openbbq.cli:main`.

This worked for incremental delivery, but it makes the long-term architecture less clear than the documented `cli/config/domain/engine/workflow/plugins/storage` package split.

## Scope

This refactor includes:

- moving source files into the approved subpackage layout;
- updating all internal imports, tests, and CLI entry points to strict submodule imports;
- removing obsolete flat module files after their code has moved;
- removing the interim `openbbq.core.workflow` and `openbbq.models` package paths;
- updating documentation references that describe source layout, public examples, or developer commands.

This refactor excludes:

- behavior changes to workflow execution, validation, storage, plugins, or CLI output;
- compatibility shims for old import paths;
- new runtime features;
- large semantic rewrites beyond package-boundary cleanup.

## Target Layout

The approved target layout is:

```text
src/openbbq/
  __init__.py

  cli/
    __init__.py
    app.py

  config/
    __init__.py
    loader.py

  domain/
    __init__.py
    models.py

  engine/
    __init__.py
    service.py
    validation.py

  workflow/
    __init__.py
    aborts.py
    bindings.py
    diff.py
    execution.py
    locks.py
    rerun.py
    state.py

  plugins/
    __init__.py
    registry.py

  storage/
    __init__.py
    project_store.py
```

Package `__init__.py` files should be lightweight package markers. They should not re-export old flat APIs as compatibility shims.

## Module Mapping

Move modules as follows:

| Current path | Target path |
| --- | --- |
| `src/openbbq/cli.py` | `src/openbbq/cli/app.py` |
| `src/openbbq/config.py` | `src/openbbq/config/loader.py` |
| `src/openbbq/domain.py` | `src/openbbq/domain/models.py` |
| `src/openbbq/engine.py` | `src/openbbq/engine/service.py` plus `src/openbbq/engine/validation.py` |
| `src/openbbq/core/workflow/*.py` | `src/openbbq/workflow/*.py` |
| `src/openbbq/models/workflow.py` | merge into `src/openbbq/domain/models.py` |
| `src/openbbq/plugins.py` | `src/openbbq/plugins/registry.py` |
| `src/openbbq/storage.py` | `src/openbbq/storage/project_store.py` |

After the move, delete these obsolete paths:

- `src/openbbq/cli.py`
- `src/openbbq/config.py`
- `src/openbbq/domain.py`
- `src/openbbq/engine.py`
- `src/openbbq/plugins.py`
- `src/openbbq/storage.py`
- `src/openbbq/core/`
- `src/openbbq/models/`

## Import Policy

Use strict submodule imports everywhere. New code and tests should import concrete modules rather than relying on package-level re-exports.

Examples:

```python
from openbbq.cli.app import main
from openbbq.config.loader import load_project_config
from openbbq.domain.models import ProjectConfig, StepConfig, WorkflowConfig
from openbbq.engine.service import run_workflow
from openbbq.engine.validation import validate_workflow
from openbbq.plugins.registry import discover_plugins
from openbbq.storage.project_store import ProjectStore
from openbbq.workflow.locks import WorkflowLock
```

Old imports such as `from openbbq.engine import run_workflow` and `from openbbq.core.workflow.state import get_effective_workflow_state` should be removed from the codebase instead of preserved.

## Engine Split

`openbbq.engine.service` should own orchestration functions such as run, resume, abort, unlock, status, logs, artifact inspection, plugin inspection, and project inspection.

`openbbq.engine.validation` should own workflow validation helpers and the public `validate_workflow` function. The service module may import validation functions, but validation should not import service orchestration to avoid cycles.

This split keeps validation reusable for CLI `validate` without forcing callers through the full execution service.

## Domain Model Consolidation

Move workflow state records, artifact records, plugin records, and project configuration dataclasses into `openbbq.domain.models`.

This removes the temporary distinction between:

- `openbbq.domain` for project/plugin config models;
- `openbbq.models.workflow` for persisted workflow records.

The consolidated model module should remain data-oriented and should not import engine, storage, plugin discovery, or CLI modules.

## CLI Entrypoint

Update `pyproject.toml`:

```toml
[project.scripts]
openbbq = "openbbq.cli.app:main"
```

CLI tests should import `main` from `openbbq.cli.app`.

The user-facing command syntax and exit codes should remain unchanged.

## Documentation Updates

Update repository documentation where it describes source layout or import boundaries:

- `AGENTS.md`
- `README.md`
- relevant `docs/phase1/*.md`
- relevant Superpowers plans/specs if they describe current source paths

Docs should describe the new package layout and avoid referring to `openbbq.core.workflow`, `openbbq.models.workflow`, or flat public facades.

## Test Strategy

The refactor should preserve all existing behavior. Verification should include:

- full test suite: `uv run pytest`;
- lint: `uv run ruff check .`;
- formatting check: `uv run ruff format --check .`;
- CLI smoke command through the console script, for example `uv run openbbq validate text-demo --project tests/fixtures/projects/text-basic`;
- import-boundary coverage that imports the new concrete modules and asserts obsolete source files no longer exist.

Tests should be updated to strict submodule imports rather than testing old compatibility paths.

## Risks And Mitigations

Import cycles are the main technical risk. Keep `domain.models` independent, keep storage dependent only on domain models, keep workflow helpers dependent on domain/storage/plugin contracts, and keep CLI at the outer edge.

Entrypoint regressions are the main user-facing risk. Verify the installed console script with `uv run openbbq ...`, not only direct function imports.

Documentation drift is likely because prior phase documents mention the old paths. Use `rg "openbbq\\.(core|models|engine|cli|config|plugins|storage)" docs README.md AGENTS.md tests src` after implementation and update stale references intentionally.

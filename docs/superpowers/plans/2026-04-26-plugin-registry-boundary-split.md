# Plugin Registry Boundary Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `openbbq.plugins.registry` into focused model, manifest parsing, discovery, and execution modules while preserving the public registry API.

**Architecture:** Keep `src/openbbq/plugins/registry.py` as the compatibility module for existing imports. Move models to `models.py`, manifest parsing to `manifests.py`, plugin path scanning and registry aggregation to `discovery.py`, and module loading/tool invocation to `execution.py`. Existing callers should continue importing from `openbbq.plugins.registry`.

**Tech Stack:** Python 3.11, Pydantic, jsonschema, pytest, Ruff.

---

## File Structure

- Create: `src/openbbq/plugins/models.py`
  - Owns `ToolSpec`, `PluginSpec`, `InvalidPlugin`, and `PluginRegistry`.
- Create: `src/openbbq/plugins/manifests.py`
  - Owns `parse_plugin_manifest()` and private manifest validation helpers.
- Create: `src/openbbq/plugins/discovery.py`
  - Owns `discover_plugins()` and private candidate manifest/file-loading helpers.
- Create: `src/openbbq/plugins/execution.py`
  - Owns `execute_plugin_tool()` and private module loading helpers.
- Modify: `src/openbbq/plugins/registry.py`
  - Re-export the public models and public functions from the new modules.
- Create: `tests/test_plugin_registry_split.py`
  - Covers importability, compatibility exports, direct manifest parsing, duplicate discovery behavior, and execution error redaction.
- Modify: `tests/test_package_layout.py`
  - Adds the new plugin implementation modules to import coverage.
- Modify: `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`
  - Marks the plugin registry split done after implementation and sets the next slice to built-in LLM helper extraction.

Do not change manifest schema, plugin request/response payloads, error messages, registry field names, CLI/API output shapes, or workflow execution behavior.

---

### Task 1: Add plugin registry split characterization tests

**Files:**
- Create: `tests/test_plugin_registry_split.py`

- [ ] **Step 1: Create the test file**

Create `tests/test_plugin_registry_split.py` with this content:

```python
from pathlib import Path
from textwrap import dedent
import importlib

import pytest

from openbbq.errors import PluginError
from openbbq.plugins.payloads import PluginRequest


PLUGIN_MODULES = (
    "openbbq.plugins.models",
    "openbbq.plugins.manifests",
    "openbbq.plugins.discovery",
    "openbbq.plugins.execution",
    "openbbq.plugins.registry",
)


def test_plugin_split_modules_are_importable():
    for module_name in PLUGIN_MODULES:
        importlib.import_module(module_name)


def test_registry_public_exports_remain_compatible():
    registry = importlib.import_module("openbbq.plugins.registry")
    models = importlib.import_module("openbbq.plugins.models")
    discovery = importlib.import_module("openbbq.plugins.discovery")
    execution = importlib.import_module("openbbq.plugins.execution")

    assert registry.ToolSpec is models.ToolSpec
    assert registry.PluginSpec is models.PluginSpec
    assert registry.InvalidPlugin is models.InvalidPlugin
    assert registry.PluginRegistry is models.PluginRegistry
    assert registry.discover_plugins is discovery.discover_plugins
    assert registry.execute_plugin_tool is execution.execute_plugin_tool


def test_manifest_parser_builds_plugin_spec_without_discovery(tmp_path):
    manifests = importlib.import_module("openbbq.plugins.manifests")
    models = importlib.import_module("openbbq.plugins.models")
    manifest_path = tmp_path / "openbbq.plugin.toml"

    plugin = manifests.parse_plugin_manifest(manifest_path, _manifest("demo", "echo"))

    assert isinstance(plugin, models.PluginSpec)
    assert plugin.name == "demo"
    assert plugin.manifest_path == manifest_path
    assert [tool.name for tool in plugin.tools] == ["echo"]
    assert plugin.tools[0].outputs["text"].artifact_type == "text"


def test_discovery_module_preserves_duplicate_warning(tmp_path):
    discovery = importlib.import_module("openbbq.plugins.discovery")
    first = _write_plugin(tmp_path / "first", _manifest_text("duplicate", "echo"))
    second = _write_plugin(tmp_path / "second", _manifest_text("duplicate", "echo"))

    registry = discovery.discover_plugins([first, second])

    assert list(registry.plugins) == ["duplicate"]
    assert registry.plugins["duplicate"].manifest_path == first / "openbbq.plugin.toml"
    assert registry.warnings == [
        "Duplicate plugin 'duplicate' at "
        f"{second / 'openbbq.plugin.toml'} ignored in favor of "
        f"{first / 'openbbq.plugin.toml'}."
    ]


def test_execution_module_preserves_plugin_error_redaction(tmp_path):
    discovery = importlib.import_module("openbbq.plugins.discovery")
    execution = importlib.import_module("openbbq.plugins.execution")
    plugin_dir = _write_plugin(
        tmp_path / "boom",
        _manifest_text("boom", "explode"),
        """
        def run(request):
            raise RuntimeError("secret failure")
        """,
    )
    registry = discovery.discover_plugins([plugin_dir])
    plugin = registry.plugins["boom"]
    tool = registry.tools["boom.explode"]
    request = PluginRequest(
        project_root=str(tmp_path),
        workflow_id="workflow",
        step_id="step",
        attempt=1,
        tool_name=tool.name,
        parameters={},
        inputs={},
        runtime={},
        work_dir=str(tmp_path / "work"),
    )

    with pytest.raises(PluginError) as exc:
        execution.execute_plugin_tool(
            plugin,
            tool,
            request,
            redactor=lambda message: message.replace("secret", "[REDACTED]"),
        )

    assert exc.value.message == "Plugin 'boom' tool 'explode' failed: [REDACTED] failure"


def _manifest(plugin_name: str, tool_name: str) -> dict[str, object]:
    return {
        "name": plugin_name,
        "version": "0.1.0",
        "runtime": "python",
        "entrypoint": "plugin:run",
        "tools": [
            {
                "name": tool_name,
                "description": "Echo text.",
                "effects": [],
                "parameter_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                },
                "outputs": {
                    "text": {
                        "artifact_type": "text",
                        "description": "Echoed text.",
                    }
                },
            }
        ],
    }


def _manifest_text(plugin_name: str, tool_name: str) -> str:
    return f"""
        name = "{plugin_name}"
        version = "0.1.0"
        runtime = "python"
        entrypoint = "plugin:run"

        [[tools]]
        name = "{tool_name}"
        description = "Echo text."
        effects = []

        [tools.parameter_schema]
        type = "object"
        additionalProperties = false
        properties = {{}}

        [tools.outputs.text]
        artifact_type = "text"
        description = "Echoed text."
        """


def _write_plugin(directory: Path, manifest: str, plugin_py: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "openbbq.plugin.toml").write_text(dedent(manifest).lstrip(), encoding="utf-8")
    if plugin_py is not None:
        (directory / "plugin.py").write_text(dedent(plugin_py).lstrip(), encoding="utf-8")
    return directory
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
uv run pytest tests/test_plugin_registry_split.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `openbbq.plugins.models`.

- [ ] **Step 3: Commit the failing characterization tests**

Run:

```bash
git add tests/test_plugin_registry_split.py
git commit -m "test: Cover plugin registry split boundaries"
```

---

### Task 2: Move registry models to `plugins.models`

**Files:**
- Create: `src/openbbq/plugins/models.py`
- Modify: `src/openbbq/plugins/registry.py`
- Test: `tests/test_plugins.py`
- Test: `tests/test_plugin_registry_split.py`

- [ ] **Step 1: Create `src/openbbq/plugins/models.py`**

Move the model declarations from `src/openbbq/plugins/registry.py` into
`src/openbbq/plugins/models.py`:

```python
from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator

from openbbq.domain.base import JsonObject, OpenBBQModel
from openbbq.plugins.contracts import (
    RuntimeRequirementSpec,
    ToolInputSpec,
    ToolOutputSpec,
    ToolUiSpec,
)


class ToolSpec(OpenBBQModel):
    plugin_name: str
    name: str
    description: str
    input_artifact_types: list[str]
    output_artifact_types: list[str]
    inputs: dict[str, ToolInputSpec] = Field(default_factory=dict)
    outputs: dict[str, ToolOutputSpec] = Field(default_factory=dict)
    runtime_requirements: RuntimeRequirementSpec = Field(default_factory=RuntimeRequirementSpec)
    ui: ToolUiSpec = Field(default_factory=ToolUiSpec)
    parameter_schema: JsonObject
    effects: list[str]
    manifest_path: Path

    @field_validator("plugin_name", "name", "description")
    @classmethod
    def nonempty_string(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("input_artifact_types", "output_artifact_types", "effects")
    @classmethod
    def list_of_strings(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) for item in value):
            raise ValueError("must be a list of strings")
        return value

    @field_validator("output_artifact_types")
    @classmethod
    def nonempty_output_types(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("must not be empty")
        return value


class PluginSpec(OpenBBQModel):
    name: str
    version: str
    runtime: str
    entrypoint: str
    manifest_path: Path
    tools: tuple[ToolSpec, ...] = ()


class InvalidPlugin(OpenBBQModel):
    path: Path
    error: str


class PluginRegistry(OpenBBQModel):
    plugins: dict[str, PluginSpec] = Field(default_factory=dict)
    tools: dict[str, ToolSpec] = Field(default_factory=dict)
    invalid_plugins: list[InvalidPlugin] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 2: Update `registry.py` imports and remove duplicate model classes**

In `src/openbbq/plugins/registry.py`:

- remove imports that are now only needed by model declarations:
  - `Field`
  - `field_validator`
  - `OpenBBQModel`
  - `JsonObject`
  - plugin contract model imports
- add:

```python
from openbbq.domain.base import format_pydantic_error
from openbbq.plugins.models import InvalidPlugin, PluginRegistry, PluginSpec, ToolSpec
```

Delete the local definitions of:

- `ToolSpec`
- `PluginSpec`
- `InvalidPlugin`
- `PluginRegistry`

Leave discovery, manifest parsing, and execution helpers in `registry.py` for
this task.

- [ ] **Step 3: Run focused tests**

Run:

```bash
uv run pytest tests/test_plugins.py::test_tool_spec_rejects_non_object_parameter_schema tests/test_plugins.py::test_plugin_registry_defaults_to_empty_collections -q
```

Expected: PASS.

Run:

```bash
uv run pytest tests/test_plugin_registry_split.py::test_plugin_split_modules_are_importable -q
```

Expected: FAIL until `manifests.py`, `discovery.py`, and `execution.py` exist.

- [ ] **Step 4: Run lint and commit**

Run:

```bash
uv run ruff check src/openbbq/plugins tests/test_plugins.py tests/test_plugin_registry_split.py
uv run ruff format --check src/openbbq/plugins tests/test_plugins.py tests/test_plugin_registry_split.py
```

Expected: both commands exit 0.

Commit:

```bash
git add src/openbbq/plugins tests/test_plugins.py tests/test_plugin_registry_split.py
git commit -m "refactor: Move plugin registry models"
```

---

### Task 3: Move manifest parsing to `plugins.manifests`

**Files:**
- Create: `src/openbbq/plugins/manifests.py`
- Modify: `src/openbbq/plugins/registry.py`
- Test: `tests/test_plugins.py`
- Test: `tests/test_plugin_registry_split.py`

- [ ] **Step 1: Create `src/openbbq/plugins/manifests.py`**

Move these declarations and helpers from `registry.py` into
`src/openbbq/plugins/manifests.py`:

- `SEMVER_PATTERN`
- `PYTHON_IDENTIFIER`
- `ENTRYPOINT_PATTERN`
- `_parse_plugin_manifest()` renamed to public `parse_plugin_manifest()`
- `_parse_tool_manifest()`
- `_parse_tool_inputs()`
- `_parse_tool_outputs()`
- `_parse_tool_runtime_requirements()`
- `_parse_tool_ui()`
- `_require_nonempty_string()`
- `_require_string_list()`
- `_format_schema_error()`

Use this import section:

```python
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import format_pydantic_error
from openbbq.plugins.contracts import (
    RuntimeRequirementSpec,
    ToolInputSpec,
    ToolOutputSpec,
    ToolUiSpec,
)
from openbbq.plugins.models import PluginSpec, ToolSpec
```

When moving `_parse_plugin_manifest()`, rename the function and keep the body
unchanged except the function name:

```python
def parse_plugin_manifest(manifest_path: Path, manifest: Any) -> PluginSpec:
    ...
```

- [ ] **Step 2: Update `registry.py` to call `parse_plugin_manifest()`**

In `src/openbbq/plugins/registry.py`:

- add:

```python
from openbbq.plugins.manifests import parse_plugin_manifest
```

- change `_load_manifest()` from:

```python
plugin = _parse_plugin_manifest(manifest_path, manifest)
```

to:

```python
plugin = parse_plugin_manifest(manifest_path, manifest)
```

- remove the moved constants and helper functions from `registry.py`.

- [ ] **Step 3: Run focused tests**

Run:

```bash
uv run pytest tests/test_plugins.py tests/test_plugin_registry_split.py::test_manifest_parser_builds_plugin_spec_without_discovery -q
```

Expected: all selected tests pass except any `test_plugin_registry_split.py`
tests that still require `openbbq.plugins.discovery` or
`openbbq.plugins.execution` when run as a whole.

- [ ] **Step 4: Run lint and commit**

Run:

```bash
uv run ruff check src/openbbq/plugins tests/test_plugins.py tests/test_plugin_registry_split.py
uv run ruff format --check src/openbbq/plugins tests/test_plugins.py tests/test_plugin_registry_split.py
```

Expected: both commands exit 0.

Commit:

```bash
git add src/openbbq/plugins tests/test_plugins.py tests/test_plugin_registry_split.py
git commit -m "refactor: Move plugin manifest parsing"
```

---

### Task 4: Move discovery to `plugins.discovery`

**Files:**
- Create: `src/openbbq/plugins/discovery.py`
- Modify: `src/openbbq/plugins/registry.py`
- Test: `tests/test_plugins.py`
- Test: `tests/test_plugin_registry_split.py`

- [ ] **Step 1: Create `src/openbbq/plugins/discovery.py`**

Move these functions from `registry.py` into
`src/openbbq/plugins/discovery.py`:

- `discover_plugins()`
- `_candidate_manifests()`
- `_load_manifest()`

Use this import section:

```python
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import tomllib

from openbbq.plugins.manifests import parse_plugin_manifest
from openbbq.plugins.models import InvalidPlugin, PluginRegistry
```

In `_load_manifest()`, call `parse_plugin_manifest()` as introduced in Task 3.
Keep invalid plugin handling, duplicate plugin warning text, manifest path
de-duplication, and tool registration unchanged.

- [ ] **Step 2: Update `registry.py` to re-export discovery**

In `src/openbbq/plugins/registry.py`:

- add:

```python
from openbbq.plugins.discovery import discover_plugins
```

- remove the local `discover_plugins()`, `_candidate_manifests()`, and
  `_load_manifest()` implementations.
- remove now-unused imports from `registry.py`, including `Iterable`, `Path`,
  and `tomllib` if Ruff reports them unused.

- [ ] **Step 3: Run focused tests**

Run:

```bash
uv run pytest tests/test_plugins.py tests/test_plugin_registry_split.py::test_discovery_module_preserves_duplicate_warning -q
```

Expected: all selected tests pass.

Run:

```bash
uv run pytest tests/test_plugin_registry_split.py::test_registry_public_exports_remain_compatible -q
```

Expected: FAIL until `execution.py` exists and `registry.execute_plugin_tool`
is re-exported from that module.

- [ ] **Step 4: Run lint and commit**

Run:

```bash
uv run ruff check src/openbbq/plugins tests/test_plugins.py tests/test_plugin_registry_split.py
uv run ruff format --check src/openbbq/plugins tests/test_plugins.py tests/test_plugin_registry_split.py
```

Expected: both commands exit 0.

Commit:

```bash
git add src/openbbq/plugins tests/test_plugins.py tests/test_plugin_registry_split.py
git commit -m "refactor: Move plugin discovery"
```

---

### Task 5: Move plugin execution to `plugins.execution`

**Files:**
- Create: `src/openbbq/plugins/execution.py`
- Modify: `src/openbbq/plugins/registry.py`
- Test: `tests/test_plugins.py`
- Test: `tests/test_plugin_registry_split.py`
- Test: `tests/test_builtin_plugins.py`
- Test: `tests/test_runtime_engine.py`

- [ ] **Step 1: Create `src/openbbq/plugins/execution.py`**

Move these functions from `registry.py` into
`src/openbbq/plugins/execution.py`:

- `execute_plugin_tool()`
- `_load_plugin_module()`
- `_builtin_module_name()`

Use this import section:

```python
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import format_pydantic_error
from openbbq.errors import PluginError
from openbbq.plugins.models import PluginSpec, ToolSpec
from openbbq.plugins.payloads import PluginRequest, PluginResponse
```

Keep function bodies unchanged, including:

- non-builtin module unique names using `uuid4().hex`;
- builtin module resolution through `openbbq.builtin_plugins`;
- redactor handling for plugin function exceptions;
- `PluginResponse.model_validate()` response validation;
- current `PluginError` message strings.

- [ ] **Step 2: Update `registry.py` to re-export execution**

In `src/openbbq/plugins/registry.py`:

- add:

```python
from openbbq.plugins.execution import execute_plugin_tool
```

- remove local execution and module-loading helpers.
- remove now-unused imports from `registry.py`, including `importlib`,
  `importlib.util`, `ModuleType`, `uuid4`, `PluginError`, `PluginRequest`, and
  `PluginResponse` if Ruff reports them unused.

After this step, `registry.py` should be a compatibility module shaped like:

```python
from __future__ import annotations

from openbbq.plugins.discovery import discover_plugins
from openbbq.plugins.execution import execute_plugin_tool
from openbbq.plugins.models import InvalidPlugin, PluginRegistry, PluginSpec, ToolSpec

__all__ = [
    "InvalidPlugin",
    "PluginRegistry",
    "PluginSpec",
    "ToolSpec",
    "discover_plugins",
    "execute_plugin_tool",
]
```

- [ ] **Step 3: Run focused tests**

Run:

```bash
uv run pytest tests/test_plugin_registry_split.py tests/test_plugins.py -q
```

Expected: PASS.

Run:

```bash
uv run pytest tests/test_builtin_plugins.py tests/test_runtime_engine.py -q
```

Expected: PASS.

- [ ] **Step 4: Run lint and commit**

Run:

```bash
uv run ruff check src/openbbq/plugins tests/test_plugin_registry_split.py tests/test_plugins.py tests/test_builtin_plugins.py tests/test_runtime_engine.py
uv run ruff format --check src/openbbq/plugins tests/test_plugin_registry_split.py tests/test_plugins.py tests/test_builtin_plugins.py tests/test_runtime_engine.py
```

Expected: both commands exit 0.

Commit:

```bash
git add src/openbbq/plugins tests/test_plugin_registry_split.py tests/test_plugins.py tests/test_builtin_plugins.py tests/test_runtime_engine.py
git commit -m "refactor: Move plugin execution"
```

---

### Task 6: Add package import coverage and update audit tracking

**Files:**
- Modify: `tests/test_package_layout.py`
- Modify: `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`
- Test: `tests/test_package_layout.py`

- [ ] **Step 1: Add new plugin modules to package layout import coverage**

In `tests/test_package_layout.py`, add these module names to the `modules` list
in `test_new_package_modules_are_importable`:

```python
        "openbbq.plugins.discovery",
        "openbbq.plugins.execution",
        "openbbq.plugins.manifests",
        "openbbq.plugins.models",
```

- [ ] **Step 2: Update the audit closure tracking spec**

In `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`,
move **P2: Plugin registry has multiple responsibilities in one module** from
the Remaining section to the Done section. Add this bullet under `### Done`:

```markdown
- **P2: Plugin registry has multiple responsibilities in one module**
  - Completed by the plugin registry boundary split into focused model,
    manifest parsing, discovery, and execution modules under
    `src/openbbq/plugins/`, with `src/openbbq/plugins/registry.py` retained as
    the public compatibility module.
```

Remove this bullet from `### Remaining`:

```markdown
- **P2: Plugin registry has multiple responsibilities in one module**
```

In the `## Execution strategy` section, remove the completed
**Plugin registry boundary split** item from the remaining cleanup order and
renumber the remaining items.

In the `## Next slice` section, replace the current text with:

```markdown
The next implementation slice should be **Built-in LLM helper extraction**. It
is the highest-priority remaining P2 audit item and should preserve plugin tool
contracts and deterministic fixture behavior.
```

- [ ] **Step 3: Run focused tests and lint**

Run:

```bash
uv run pytest tests/test_package_layout.py tests/test_plugin_registry_split.py -q
uv run ruff check tests/test_package_layout.py tests/test_plugin_registry_split.py docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md
uv run ruff format --check tests/test_package_layout.py tests/test_plugin_registry_split.py docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md
```

Expected: all commands exit 0.

- [ ] **Step 4: Commit package coverage and tracking update**

Run:

```bash
git add tests/test_package_layout.py docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md tests/test_plugin_registry_split.py
git commit -m "docs: Track plugin registry split completion"
```

---

### Task 7: Focused plugin contract verification

**Files:**
- No planned file changes.

- [ ] **Step 1: Run focused plugin registry and consumer tests**

Run:

```bash
uv run pytest tests/test_plugins.py -q
uv run pytest tests/test_plugin_registry_split.py tests/test_package_layout.py -q
uv run pytest tests/test_application_projects_plugins.py tests/test_cli_integration.py -q
uv run pytest tests/test_builtin_plugins.py tests/test_runtime_engine.py -q
uv run pytest tests/test_engine_validate.py tests/test_workflow_bindings.py -q
```

Expected: every command exits 0.

- [ ] **Step 2: Verify `registry.py` is a compatibility module**

Run:

```bash
wc -l src/openbbq/plugins/registry.py src/openbbq/plugins/*.py
sed -n '1,120p' src/openbbq/plugins/registry.py
```

Expected:

- `src/openbbq/plugins/registry.py` is much smaller than its starting size of
  about 409 lines.
- `registry.py` imports/re-exports public API from `models.py`, `discovery.py`,
  and `execution.py`.
- `registry.py` contains no manifest parsing, path scanning, module loading, or
  execution helper bodies.

- [ ] **Step 3: Check for stale private helper definitions in `registry.py`**

Run:

```bash
rg -n "^def _(candidate_manifests|load_manifest|parse_plugin_manifest|parse_tool_manifest|parse_tool_inputs|parse_tool_outputs|parse_tool_runtime_requirements|parse_tool_ui|require_nonempty_string|require_string_list|format_schema_error|load_plugin_module|builtin_module_name)" src/openbbq/plugins/registry.py
```

Expected: no matches.

- [ ] **Step 4: Check git status**

Run:

```bash
git status -sb
```

Expected: no uncommitted changes.

---

### Task 8: Final verification

**Files:**
- No planned file changes.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
uv run pytest
```

Expected: PASS.

- [ ] **Step 2: Run full lint**

Run:

```bash
uv run ruff check .
```

Expected: PASS.

- [ ] **Step 3: Run full format check**

Run:

```bash
uv run ruff format --check .
```

Expected: PASS with all files already formatted.

- [ ] **Step 4: Inspect final branch state**

Run:

```bash
git status -sb
git log --oneline -10
```

Expected:

- Working tree is clean.
- The branch contains the plugin registry split commits.

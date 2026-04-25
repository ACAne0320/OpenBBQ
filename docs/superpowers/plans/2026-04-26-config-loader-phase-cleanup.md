# Config Loader Phase Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split project config loading into focused raw, path, and workflow phases while preserving `load_project_config()` behavior.

**Architecture:** Keep `openbbq.config.loader` as the stable public facade. Add `openbbq.config.raw` for YAML/raw scalar/model helper behavior, `openbbq.config.paths` for config/storage/plugin path behavior, and `openbbq.config.workflows` for workflow/step/output/input reference construction and validation. Preserve the current config schema, path precedence, error messages, and Pydantic model boundary.

**Tech Stack:** Python 3.11, PyYAML, Pydantic v2, pytest, Ruff, uv.

---

## File Structure

- Create `src/openbbq/config/raw.py`
  - YAML loading and raw value helpers.
  - Shared `build_model()` wrapper for Pydantic validation errors.
- Create `src/openbbq/config/paths.py`
  - Config path, project-relative path, plugin path normalization, plugin path loading, and path merge behavior.
- Create `src/openbbq/config/workflows.py`
  - Workflow, step, output, and input reference parsing and validation.
- Modify `src/openbbq/config/loader.py`
  - Keep only public orchestration and final `ProjectConfig` assembly.
  - Continue exporting `load_project_config()` from the same module.
- Modify `tests/test_config.py`
  - Add focused characterization tests for extracted raw/path/workflow boundaries.
- Modify `tests/test_package_layout.py`
  - Add import coverage for new config modules.
- Modify `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`
  - Mark the config loader cleanup complete after implementation and verification.

---

### Task 1: Extract Raw And Path Helpers

**Files:**
- Create: `src/openbbq/config/raw.py`
- Create: `src/openbbq/config/paths.py`
- Modify: `src/openbbq/config/loader.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_package_layout.py`

- [ ] **Step 1: Write raw/path boundary tests**

Modify the imports at the top of `tests/test_config.py`:

```python
import os
from pathlib import Path

import pytest

from openbbq.config.loader import load_project_config
from openbbq.config.paths import (
    load_plugin_paths,
    merge_paths,
    normalize_plugin_paths,
    resolve_config_path,
    resolve_project_path,
)
from openbbq.config.raw import load_yaml_mapping
from openbbq.errors import ValidationError
```

Add these tests after `test_load_text_basic_defaults()`:

```python
def test_load_yaml_mapping_reports_missing_file(tmp_path):
    missing = tmp_path / "missing.yaml"

    with pytest.raises(ValidationError) as exc:
        load_yaml_mapping(missing)

    assert str(missing) in str(exc.value)
    assert "was not found" in str(exc.value)


def test_load_yaml_mapping_reports_malformed_yaml(tmp_path):
    config = tmp_path / "openbbq.yaml"
    config.write_text("version: [", encoding="utf-8")

    with pytest.raises(ValidationError) as exc:
        load_yaml_mapping(config)

    assert "malformed yaml" in str(exc.value).lower()


def test_load_yaml_mapping_requires_mapping(tmp_path):
    config = tmp_path / "openbbq.yaml"
    config.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(ValidationError) as exc:
        load_yaml_mapping(config)

    assert "yaml mapping" in str(exc.value).lower()


def test_resolve_config_path_defaults_and_resolves_relative_path(tmp_path):
    assert resolve_config_path(tmp_path, None) == (tmp_path / "openbbq.yaml").resolve()
    assert resolve_config_path(tmp_path, "configs/demo.yaml") == (
        tmp_path / "configs/demo.yaml"
    ).resolve()


def test_resolve_project_path_rejects_non_path_value(tmp_path):
    with pytest.raises(ValidationError) as exc:
        resolve_project_path(tmp_path, ["bad"], "storage.root")

    assert "storage.root" in str(exc.value)
    assert "string path" in str(exc.value)


def test_normalize_plugin_paths_deduplicates_after_resolution(tmp_path):
    paths = normalize_plugin_paths(
        tmp_path,
        ["plugins", tmp_path / "plugins", "other"],
        "plugins.paths",
    )

    assert paths == [(tmp_path / "plugins").resolve(), (tmp_path / "other").resolve()]


def test_load_plugin_paths_uses_env_then_config_order(tmp_path):
    raw_config = {"plugins": {"paths": ["./plugins-a"]}}

    paths = load_plugin_paths(
        tmp_path,
        raw_config,
        {"OPENBBQ_PLUGIN_PATH": f"./plugins-b{os.pathsep}./plugins-c"},
    )

    assert [path.name for path in paths] == ["plugins-b", "plugins-c", "plugins-a"]


def test_merge_paths_preserves_preferred_then_fallback_order(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"

    assert merge_paths([first, second], [second, first]) == [first, second]
```

Modify `tests/test_package_layout.py` by adding these module strings to `test_new_package_modules_are_importable`:

```python
        "openbbq.config.paths",
        "openbbq.config.raw",
```

- [ ] **Step 2: Run the raw/path boundary tests and confirm they fail**

Run:

```bash
uv run pytest tests/test_config.py::test_load_yaml_mapping_reports_missing_file tests/test_config.py::test_resolve_config_path_defaults_and_resolves_relative_path tests/test_package_layout.py::test_new_package_modules_are_importable -q
```

Expected: FAIL with `ModuleNotFoundError` because `openbbq.config.raw` and `openbbq.config.paths` do not exist yet.

- [ ] **Step 3: Create `raw.py`**

Create `src/openbbq/config/raw.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

from pydantic import ValidationError as PydanticValidationError
import yaml

from openbbq.domain.base import JsonObject, OpenBBQModel, format_pydantic_error
from openbbq.errors import ValidationError

TModel = TypeVar("TModel", bound=OpenBBQModel)


def load_yaml_mapping(path: Path) -> JsonObject:
    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ValidationError(f"Project config '{path}' was not found.") from exc
    except yaml.YAMLError as exc:
        raise ValidationError(f"Project config '{path}' contains malformed YAML.") from exc
    if not isinstance(raw, dict):
        raise ValidationError(f"Project config '{path}' must contain a YAML mapping.")
    return raw


def build_model(model_type: type[TModel], field_path: str, **values: Any) -> TModel:
    try:
        return model_type(**values)
    except PydanticValidationError as exc:
        raise ValidationError(format_pydantic_error(field_path, exc)) from exc


def require_mapping(value: Any, field_path: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ValidationError(f"{field_path} must be a mapping.")
    return value


def optional_mapping(value: Any, field_path: str) -> JsonObject:
    if value is None:
        return {}
    return require_mapping(value, field_path)


def require_nonempty_string(value: Any, field_path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_path} must be a non-empty string.")
    return value


def require_bool(value: Any, field_path: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{field_path} must be a boolean.")
    return value
```

- [ ] **Step 4: Create `paths.py`**

Create `src/openbbq/config/paths.py`:

```python
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
import os

from openbbq.config.raw import optional_mapping
from openbbq.domain.base import JsonObject
from openbbq.errors import ValidationError

DEFAULT_STORAGE_ROOT = Path(".openbbq")
DEFAULT_CONFIG_NAME = "openbbq.yaml"
BUILTIN_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "builtin_plugins"


def resolve_config_path(project_root: Path, config_path: Path | str | None) -> Path:
    if config_path is None:
        return (project_root / DEFAULT_CONFIG_NAME).resolve()
    path = Path(config_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def resolve_project_path(project_root: Path, value: Path | str, field_path: str) -> Path:
    try:
        path = Path(value).expanduser()
    except (TypeError, ValueError, OSError) as exc:
        raise ValidationError(
            f"{field_path} must be a string path relative to the project root."
        ) from exc
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def load_plugin_paths(
    project_root: Path, raw_config: JsonObject, env: Mapping[str, str]
) -> list[Path]:
    config_plugins = optional_mapping(raw_config.get("plugins"), "plugins")
    config_paths = config_plugins.get("paths", [])
    if not isinstance(config_paths, list):
        raise ValidationError("plugins.paths must be a list when provided.")

    env_paths_raw = env.get("OPENBBQ_PLUGIN_PATH", "")
    env_paths = [path for path in env_paths_raw.split(os.pathsep) if path]
    return normalize_plugin_paths(project_root, env_paths + config_paths, "plugins.paths")


def normalize_plugin_paths(
    project_root: Path, paths: Iterable[Path | str], field_path: str
) -> list[Path]:
    normalized: list[Path] = []
    seen: set[Path] = set()
    for index, raw_path in enumerate(paths):
        path = resolve_project_path(project_root, raw_path, f"{field_path}[{index}]")
        if path not in seen:
            seen.add(path)
            normalized.append(path)
    return normalized


def merge_paths(preferred: Iterable[Path], fallback: Iterable[Path]) -> list[Path]:
    merged: list[Path] = []
    seen: set[Path] = set()
    for path in list(preferred) + list(fallback):
        if path not in seen:
            seen.add(path)
            merged.append(path)
    return merged
```

- [ ] **Step 5: Update `loader.py` to use raw/path helpers**

Modify the imports at the top of `src/openbbq/config/loader.py` to:

```python
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
import os
import re

from openbbq.config.paths import (
    BUILTIN_PLUGIN_ROOT,
    DEFAULT_CONFIG_NAME,
    DEFAULT_STORAGE_ROOT,
    load_plugin_paths as _load_plugin_paths,
    merge_paths as _merge_paths,
    normalize_plugin_paths as _normalize_plugin_paths,
    resolve_config_path as _resolve_config_path,
    resolve_project_path as _resolve_path,
)
from openbbq.config.raw import (
    build_model as _build_model,
    load_yaml_mapping as _load_yaml_mapping,
    optional_mapping as _optional_mapping,
    require_bool as _require_bool,
    require_mapping as _require_mapping,
    require_nonempty_string as _require_nonempty_string,
)
from openbbq.domain.base import PluginInputs
from openbbq.domain.models import (
    ARTIFACT_TYPES,
    PluginConfig,
    ProjectConfig,
    ProjectMetadata,
    StepConfig,
    StepOutput,
    StorageConfig,
    WorkflowConfig,
)
from openbbq.errors import ValidationError

__all__ = [
    "BUILTIN_PLUGIN_ROOT",
    "DEFAULT_CONFIG_NAME",
    "DEFAULT_STORAGE_ROOT",
    "load_project_config",
]
```

Delete these private helper definitions from `loader.py` because they are now imported from `raw.py` or `paths.py`:

- `_load_yaml_mapping`
- `_build_model`
- `_resolve_config_path`
- `_resolve_path`
- `_load_plugin_paths`
- `_normalize_plugin_paths`
- `_merge_paths`
- `_require_mapping`
- `_optional_mapping`
- `_require_nonempty_string`
- `_require_bool`

Leave workflow parsing and `_validate_step_inputs()` in `loader.py` for this task.

- [ ] **Step 6: Run focused config tests**

Run:

```bash
uv run pytest tests/test_config.py tests/test_config_precedence.py tests/test_package_layout.py::test_new_package_modules_are_importable
```

Expected: PASS.

- [ ] **Step 7: Commit raw/path extraction**

Run:

```bash
git add src/openbbq/config/raw.py src/openbbq/config/paths.py src/openbbq/config/loader.py tests/test_config.py tests/test_package_layout.py
git commit -m "refactor: Extract config raw and path helpers"
```

---

### Task 2: Extract Workflow Builder

**Files:**
- Create: `src/openbbq/config/workflows.py`
- Modify: `src/openbbq/config/loader.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_package_layout.py`

- [ ] **Step 1: Write workflow boundary tests**

Add this import to `tests/test_config.py`:

```python
from openbbq.config.workflows import build_workflows
```

Add these tests after `test_rejects_missing_output_selector()`:

```python
def test_build_workflows_rejects_duplicate_step_ids():
    raw_config = {
        "workflows": {
            "demo": {
                "name": "Demo",
                "steps": [
                    {
                        "id": "seed",
                        "name": "Seed",
                        "tool_ref": "x.y",
                        "outputs": [{"name": "out", "type": "text"}],
                    },
                    {
                        "id": "seed",
                        "name": "Duplicate",
                        "tool_ref": "x.y",
                        "outputs": [{"name": "out", "type": "text"}],
                    },
                ],
            }
        }
    }

    with pytest.raises(ValidationError) as exc:
        build_workflows(raw_config)

    assert "duplicate step id" in str(exc.value).lower()


def test_build_workflows_rejects_unregistered_output_type():
    raw_config = {
        "workflows": {
            "demo": {
                "name": "Demo",
                "steps": [
                    {
                        "id": "seed",
                        "name": "Seed",
                        "tool_ref": "x.y",
                        "outputs": [{"name": "out", "type": "unknown"}],
                    }
                ],
            }
        }
    }

    with pytest.raises(ValidationError) as exc:
        build_workflows(raw_config)

    assert "not registered" in str(exc.value).lower()


def test_build_workflows_rejects_forward_input_reference():
    raw_config = {
        "workflows": {
            "demo": {
                "name": "Demo",
                "steps": [
                    {
                        "id": "seed",
                        "name": "Seed",
                        "tool_ref": "x.y",
                        "inputs": {"text": "later.out"},
                        "outputs": [{"name": "out", "type": "text"}],
                    },
                    {
                        "id": "later",
                        "name": "Later",
                        "tool_ref": "x.y",
                        "outputs": [{"name": "out", "type": "text"}],
                    },
                ],
            }
        }
    }

    with pytest.raises(ValidationError) as exc:
        build_workflows(raw_config)

    assert "forward reference" in str(exc.value).lower()
```

Modify `tests/test_package_layout.py` by adding:

```python
        "openbbq.config.workflows",
```

- [ ] **Step 2: Run workflow boundary tests and confirm they fail**

Run:

```bash
uv run pytest tests/test_config.py::test_build_workflows_rejects_duplicate_step_ids tests/test_package_layout.py::test_new_package_modules_are_importable -q
```

Expected: FAIL with `ModuleNotFoundError` because `openbbq.config.workflows` does not exist yet.

- [ ] **Step 3: Create `workflows.py`**

Create `src/openbbq/config/workflows.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
import re

from openbbq.config.raw import (
    build_model,
    optional_mapping,
    require_bool,
    require_mapping,
    require_nonempty_string,
)
from openbbq.domain.base import JsonObject, PluginInputs
from openbbq.domain.models import (
    ARTIFACT_TYPES,
    StepConfig,
    StepOutput,
    WorkflowConfig,
)
from openbbq.errors import ValidationError

WORKFLOW_ID_PATTERN = re.compile(r"^[a-z0-9_-]+$")
STEP_SELECTOR_PATTERN = re.compile(r"^([a-z0-9_-]+)\.([a-z0-9_-]+)$")
VALID_ON_ERROR = {"abort", "retry", "skip"}


def build_workflows(raw_config: JsonObject) -> dict[str, WorkflowConfig]:
    workflows_raw = require_mapping(raw_config.get("workflows"), "workflows")
    workflows: dict[str, WorkflowConfig] = {}
    for workflow_id, workflow_raw in workflows_raw.items():
        workflow_id = require_nonempty_string(workflow_id, "workflows.<workflow_id>")
        _validate_identifier(workflow_id, "workflow id")
        workflow_mapping = require_mapping(workflow_raw, f"workflows.{workflow_id}")
        workflow_name = require_nonempty_string(
            workflow_mapping.get("name"), f"workflows.{workflow_id}.name"
        )
        steps_raw = workflow_mapping.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ValidationError(f"Workflow '{workflow_id}' must define a non-empty steps list.")

        steps: list[StepConfig] = []
        step_ids: list[str] = []
        step_outputs: dict[str, set[str]] = {}
        input_refs: list[tuple[str, int, PluginInputs]] = []
        seen_step_ids: set[str] = set()
        for index, step_raw in enumerate(steps_raw):
            step = _build_step(
                workflow_id=workflow_id,
                index=index,
                step_raw=step_raw,
                seen_step_ids=seen_step_ids,
                input_refs=input_refs,
            )
            steps.append(step)
            step_ids.append(step.id)
            step_outputs[step.id] = {output.name for output in step.outputs}

        step_positions = {step_id: position for position, step_id in enumerate(step_ids)}
        for step_id, step_index, inputs in input_refs:
            _validate_step_inputs(
                inputs, step_id, workflow_id, step_index, step_positions, step_outputs
            )

        workflows[workflow_id] = build_model(
            WorkflowConfig,
            f"workflows.{workflow_id}",
            id=workflow_id,
            name=workflow_name,
            steps=tuple(steps),
        )
    return workflows


def _build_step(
    *,
    workflow_id: str,
    index: int,
    step_raw: object,
    seen_step_ids: set[str],
    input_refs: list[tuple[str, int, PluginInputs]],
) -> StepConfig:
    step_mapping = require_mapping(step_raw, f"workflows.{workflow_id}.steps[{index}]")
    step_id = require_nonempty_string(
        step_mapping.get("id"), f"workflows.{workflow_id}.steps[{index}].id"
    )
    _validate_identifier(step_id, "step id")
    if step_id in seen_step_ids:
        raise ValidationError(
            f"Duplicate step id '{step_id}' in workflow '{workflow_id}'.",
        )
    seen_step_ids.add(step_id)
    step_name = require_nonempty_string(
        step_mapping.get("name"), f"workflows.{workflow_id}.steps[{index}].name"
    )
    tool_ref = require_nonempty_string(
        step_mapping.get("tool_ref"),
        f"workflows.{workflow_id}.steps[{index}].tool_ref",
    )
    inputs = optional_mapping(
        step_mapping.get("inputs"), f"workflows.{workflow_id}.steps[{index}].inputs"
    )
    input_refs.append((step_id, index, inputs))
    parameters = optional_mapping(
        step_mapping.get("parameters"),
        f"workflows.{workflow_id}.steps[{index}].parameters",
    )
    outputs = _build_outputs(workflow_id, index, step_id, step_mapping.get("outputs"))

    on_error = step_mapping.get("on_error", "abort")
    if not isinstance(on_error, str) or on_error not in VALID_ON_ERROR:
        raise ValidationError(
            f"Step '{step_id}' in workflow '{workflow_id}' has invalid on_error '{on_error}'.",
        )

    max_retries = step_mapping.get("max_retries", 0)
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
        raise ValidationError(
            f"Step '{step_id}' in workflow '{workflow_id}' has invalid max_retries '{max_retries}'.",
        )

    pause_before = require_bool(
        step_mapping.get("pause_before", False),
        f"workflows.{workflow_id}.steps[{index}].pause_before",
    )
    pause_after = require_bool(
        step_mapping.get("pause_after", False),
        f"workflows.{workflow_id}.steps[{index}].pause_after",
    )

    return build_model(
        StepConfig,
        f"workflows.{workflow_id}.steps[{index}]",
        id=step_id,
        name=step_name,
        tool_ref=tool_ref,
        inputs=dict(inputs),
        outputs=tuple(outputs),
        parameters=dict(parameters),
        on_error=on_error,
        max_retries=max_retries,
        pause_before=pause_before,
        pause_after=pause_after,
    )


def _build_outputs(
    workflow_id: str,
    step_index: int,
    step_id: str,
    outputs_raw: object,
) -> list[StepOutput]:
    if not isinstance(outputs_raw, list) or not outputs_raw:
        raise ValidationError(
            f"Step '{step_id}' in workflow '{workflow_id}' must define at least one output.",
        )
    outputs: list[StepOutput] = []
    seen_output_names: set[str] = set()
    for output_index, output_raw in enumerate(outputs_raw):
        output_mapping = require_mapping(
            output_raw,
            f"workflows.{workflow_id}.steps[{step_index}].outputs[{output_index}]",
        )
        output_name = require_nonempty_string(
            output_mapping.get("name"),
            f"workflows.{workflow_id}.steps[{step_index}].outputs[{output_index}].name",
        )
        if output_name in seen_output_names:
            raise ValidationError(
                f"Duplicate output name '{output_name}' in step '{step_id}' of workflow '{workflow_id}'.",
            )
        seen_output_names.add(output_name)
        output_type = require_nonempty_string(
            output_mapping.get("type"),
            f"workflows.{workflow_id}.steps[{step_index}].outputs[{output_index}].type",
        )
        if output_type not in ARTIFACT_TYPES:
            raise ValidationError(
                f"Output type '{output_type}' in step '{step_id}' of workflow '{workflow_id}' is not registered.",
            )
        outputs.append(
            build_model(
                StepOutput,
                f"workflows.{workflow_id}.steps[{step_index}].outputs[{output_index}]",
                name=output_name,
                type=output_type,
            )
        )
    return outputs


def _validate_identifier(value: str, label: str) -> None:
    if not WORKFLOW_ID_PATTERN.fullmatch(value):
        raise ValidationError(f"Invalid {label}: '{value}'.")


def _validate_step_inputs(
    inputs: PluginInputs,
    step_id: str,
    workflow_id: str,
    step_index: int,
    step_positions: Mapping[str, int],
    step_outputs: Mapping[str, set[str]],
) -> None:
    for input_name, input_value in inputs.items():
        if not isinstance(input_value, str):
            continue
        selector = STEP_SELECTOR_PATTERN.fullmatch(input_value)
        if selector is None:
            continue
        selector_step_id = selector.group(1)
        if selector_step_id == "project":
            continue
        if selector_step_id == step_id:
            raise ValidationError(
                f"Step '{step_id}' in workflow '{workflow_id}' has a self-reference in input '{input_name}'.",
            )
        selector_position = step_positions.get(selector_step_id)
        if selector_position is None:
            raise ValidationError(
                f"Step '{step_id}' in workflow '{workflow_id}' references unknown step '{selector_step_id}' in input '{input_name}'.",
            )
        if selector_position > step_index:
            raise ValidationError(
                f"Step '{step_id}' in workflow '{workflow_id}' has a forward reference in input '{input_name}'.",
            )
        selector_output_name = selector.group(2)
        declared_outputs = step_outputs.get(selector_step_id, set())
        if selector_output_name not in declared_outputs:
            raise ValidationError(
                f"Step '{step_id}' in workflow '{workflow_id}' references unknown output '{selector_output_name}' on step '{selector_step_id}' in input '{input_name}'.",
            )
```

- [ ] **Step 4: Reduce `loader.py` to orchestration**

Update `src/openbbq/config/loader.py` so the full file is:

```python
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
import os

from openbbq.config.paths import (
    BUILTIN_PLUGIN_ROOT,
    DEFAULT_CONFIG_NAME,
    DEFAULT_STORAGE_ROOT,
    load_plugin_paths,
    merge_paths,
    normalize_plugin_paths,
    resolve_config_path,
    resolve_project_path,
)
from openbbq.config.raw import (
    build_model,
    load_yaml_mapping,
    optional_mapping,
    require_mapping,
    require_nonempty_string,
)
from openbbq.config.workflows import build_workflows
from openbbq.domain.models import (
    PluginConfig,
    ProjectConfig,
    ProjectMetadata,
    StorageConfig,
)
from openbbq.errors import ValidationError

__all__ = [
    "BUILTIN_PLUGIN_ROOT",
    "DEFAULT_CONFIG_NAME",
    "DEFAULT_STORAGE_ROOT",
    "load_project_config",
]


def load_project_config(
    project_root: Path | str,
    config_path: Path | str | None = None,
    extra_plugin_paths: Iterable[Path | str] | None = None,
    env: Mapping[str, str] | None = None,
) -> ProjectConfig:
    env = os.environ if env is None else env
    root_path = Path(project_root).expanduser().resolve()
    resolved_config_path = resolve_config_path(root_path, config_path)
    raw_config = load_yaml_mapping(resolved_config_path)

    version = raw_config.get("version")
    if type(version) is not int or version != 1:
        raise ValidationError("Project config version must be 1.")

    project_raw = require_mapping(raw_config.get("project"), "project")
    project_name = require_nonempty_string(project_raw.get("name"), "project.name")
    project_id = project_raw.get("id")
    if project_id is not None:
        project_id = require_nonempty_string(project_id, "project.id")

    storage_raw = optional_mapping(raw_config.get("storage"), "storage")
    storage_root = resolve_project_path(
        root_path, storage_raw.get("root", DEFAULT_STORAGE_ROOT), "storage.root"
    )
    artifacts_path = resolve_project_path(
        root_path,
        storage_raw.get("artifacts", storage_root / "artifacts"),
        "storage.artifacts",
    )
    state_path = resolve_project_path(
        root_path, storage_raw.get("state", storage_root / "state"), "storage.state"
    )
    storage = build_model(
        StorageConfig,
        "storage",
        root=storage_root,
        artifacts=artifacts_path,
        state=state_path,
    )

    config_plugin_paths = load_plugin_paths(root_path, raw_config, env)
    cli_plugin_paths = normalize_plugin_paths(
        root_path, extra_plugin_paths or [], "extra_plugin_paths"
    )
    plugin_paths = merge_paths(
        cli_plugin_paths, merge_paths(config_plugin_paths, [BUILTIN_PLUGIN_ROOT])
    )
    plugins = build_model(PluginConfig, "plugins", paths=tuple(plugin_paths))

    workflows = build_workflows(raw_config)

    project = build_model(ProjectMetadata, "project", id=project_id, name=project_name)
    return build_model(
        ProjectConfig,
        "project config",
        version=1,
        root_path=root_path,
        config_path=resolved_config_path,
        project=project,
        storage=storage,
        plugins=plugins,
        workflows=workflows,
    )
```

Keep `DEFAULT_CONFIG_NAME`, `DEFAULT_STORAGE_ROOT`, and `BUILTIN_PLUGIN_ROOT` imported into `loader.py` so existing code that imports these constants from `openbbq.config.loader` remains compatible.

- [ ] **Step 5: Run focused config tests**

Run:

```bash
uv run pytest tests/test_config.py tests/test_config_precedence.py tests/test_package_layout.py::test_new_package_modules_are_importable
```

Expected: PASS.

- [ ] **Step 6: Commit workflow extraction**

Run:

```bash
git add src/openbbq/config/workflows.py src/openbbq/config/loader.py tests/test_config.py tests/test_package_layout.py
git commit -m "refactor: Extract config workflow builder"
```

---

### Task 3: Update Audit Tracking And Verify

**Files:**
- Modify: `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`

- [ ] **Step 1: Update audit closure status**

In `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`, add this item to the `### Done` list after the runtime settings item:

```markdown
- **P2: Config loader performs several phases in one file**
  - Completed by splitting YAML/raw helpers into `src/openbbq/config/raw.py`,
    path and plugin path helpers into `src/openbbq/config/paths.py`, and
    workflow/step/input reference construction into
    `src/openbbq/config/workflows.py`, with `src/openbbq/config/loader.py`
    retained as the public `load_project_config()` orchestration facade.
```

Remove this item from the `### Remaining` list:

```markdown
- **P2: Config loader performs several phases in one file**
```

Replace the `## Execution strategy` numbered list with:

```markdown
The remaining cleanup should happen as separate slices, in this order:

1. **Storage database helper cleanup**
   - Add private helpers for JSON serialization and repeated row-to-model
     mapping where SQL shapes are already identical.
   - Avoid hiding record-specific queries behind a premature repository
     abstraction.
2. **Large test module split**
   - Split only files touched by the previous cleanup slices or files where
     failure locality clearly improves.
   - Prefer grouping by plugin family, CLI command group, or storage record
     family.
3. **Typed internal payloads**
   - Add typed internal models only where payloads are transformed repeatedly,
     especially transcript and translation segments.
   - Keep `dict[str, Any]` and JSON-like data at plugin, artifact, and config
     boundaries.
4. **Missing-state domain errors**
   - First add characterization tests for current `FileNotFoundError` and
     missing-state behavior.
   - Then introduce domain-specific errors at application/service boundaries
     where it improves CLI/API consistency.
```

Replace the `## Next slice` paragraph with:

```markdown
The next implementation slice should be **Storage database helper cleanup**.
It should add private helpers for JSON serialization and repeated row-to-model
mapping where SQL shapes are already identical, while avoiding a premature
repository abstraction.
```

- [ ] **Step 2: Run full verification**

Run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Expected:

- `uv run pytest`: PASS with all current tests passing and existing skips only.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS.

- [ ] **Step 3: Commit audit tracking update**

Run:

```bash
git add docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md
git commit -m "docs: Track config loader cleanup completion"
```

---

## Final Review

After all tasks are complete, run:

```bash
git status -sb
git log --oneline -6
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Expected:

- Worktree is clean.
- The latest commits cover raw/path helper extraction, workflow builder extraction, and audit tracking.
- Full test and Ruff verification pass.

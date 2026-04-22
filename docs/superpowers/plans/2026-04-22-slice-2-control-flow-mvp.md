# Slice 2 Control Flow MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Slice 2 control-flow MVP: persisted pause/resume, paused abort, config drift rejection, and basic run/resume locks.

**Architecture:** Keep `openbbq.engine` as the public facade and introduce modular internals under `openbbq.core.workflow`. New code imports workflow model names from `openbbq.models.workflow`, while existing dataclasses remain in `openbbq.domain` for compatibility. The shared execution loop lives in `core.workflow.execution`; state, lock, and artifact binding behavior move into focused modules before feature behavior is added.

**Tech Stack:** Python 3.11, argparse, dataclasses, pathlib, json, hashlib, pytest, Ruff, PyYAML, jsonschema.

---

## File Structure

- Create `src/openbbq/core/__init__.py`: package marker.
- Create `src/openbbq/core/workflow/__init__.py`: workflow core package exports.
- Create `src/openbbq/core/workflow/locks.py`: exclusive lock file helpers.
- Create `src/openbbq/core/workflow/state.py`: workflow state, config hash, and resume binding reconstruction.
- Create `src/openbbq/core/workflow/bindings.py`: plugin input resolution and artifact output persistence.
- Create `src/openbbq/core/workflow/execution.py`: shared run/resume execution loop.
- Create `src/openbbq/models/__init__.py`: model package marker.
- Create `src/openbbq/models/workflow.py`: re-export workflow dataclasses for new code.
- Modify `src/openbbq/engine.py`: keep validation facade, delegate execution, expose `resume_workflow` and `abort_workflow`.
- Modify `src/openbbq/cli.py`: wire `resume` and paused `abort`, keep unsupported guardrails for deferred commands.
- Modify `src/openbbq/storage.py`: add `read_step_run()`, workflow directory/lock path helpers as needed.
- Create `tests/fixtures/projects/text-pause/openbbq.yaml`: canonical pause fixture.
- Modify `tests/test_engine_validate.py`: pause flags are valid after this slice.
- Modify `tests/test_slice2_guardrails.py`: remove `resume`/`abort` unsupported expectations, keep `unlock`, `run --force`, `run --step`, and `artifact diff`.
- Create `tests/test_workflow_locks.py`: lock helper behavior.
- Create `tests/test_workflow_state.py`: config hash and binding reconstruction behavior.
- Create `tests/test_engine_pause_resume.py`: engine-level pause/resume/abort behavior.
- Create `tests/test_cli_control_flow.py`: process-boundary CLI behavior.

## Task 1: Package Boundaries And Pause Fixture

**Files:**
- Create: `src/openbbq/core/__init__.py`
- Create: `src/openbbq/core/workflow/__init__.py`
- Create: `src/openbbq/models/__init__.py`
- Create: `src/openbbq/models/workflow.py`
- Create: `tests/fixtures/projects/text-pause/openbbq.yaml`
- Modify: `tests/test_fixtures.py`

- [ ] **Step 1: Write failing fixture/model tests**

Add this to `tests/test_fixtures.py`:

```python
def test_text_pause_fixture_pauses_before_uppercase():
    project = _load_yaml(FIXTURES / "projects/text-pause/openbbq.yaml")

    steps = project["workflows"]["text-demo"]["steps"]

    assert steps[0]["id"] == "seed"
    assert steps[1]["id"] == "uppercase"
    assert steps[1]["pause_before"] is True
```

Create `tests/test_models.py`:

```python
from openbbq.domain import ProjectConfig as DomainProjectConfig
from openbbq.models.workflow import ProjectConfig


def test_workflow_models_reexport_domain_types():
    assert ProjectConfig is DomainProjectConfig
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_fixtures.py::test_text_pause_fixture_pauses_before_uppercase tests/test_models.py::test_workflow_models_reexport_domain_types -v
```

Expected: FAIL because the fixture and model package do not exist.

- [ ] **Step 3: Add package files and re-export model names**

Create empty package markers:

```python
# src/openbbq/core/__init__.py
```

```python
# src/openbbq/core/workflow/__init__.py
```

```python
# src/openbbq/models/__init__.py
```

Create `src/openbbq/models/workflow.py`:

```python
from __future__ import annotations

from openbbq.domain import ProjectConfig, StepConfig, StepOutput, WorkflowConfig

__all__ = ["ProjectConfig", "StepConfig", "StepOutput", "WorkflowConfig"]
```

- [ ] **Step 4: Add the text-pause fixture**

Create `tests/fixtures/projects/text-pause/openbbq.yaml`:

```yaml
version: 1

project:
  id: text-pause
  name: Text Pause

storage:
  root: .openbbq

plugins:
  paths:
    - ../../plugins/mock-text

workflows:
  text-demo:
    name: Text Demo
    steps:
      - id: seed
        name: Seed Text
        tool_ref: mock_text.echo
        inputs:
          text: "hello openbbq"
        outputs:
          - name: text
            type: text
        parameters: {}
        on_error: abort
        max_retries: 0

      - id: uppercase
        name: Uppercase Text
        tool_ref: mock_text.uppercase
        pause_before: true
        inputs:
          text: seed.text
        outputs:
          - name: text
            type: text
        parameters: {}
        on_error: abort
        max_retries: 0
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_fixtures.py::test_text_pause_fixture_pauses_before_uppercase tests/test_models.py::test_workflow_models_reexport_domain_types -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openbbq/core src/openbbq/models tests/fixtures/projects/text-pause tests/test_fixtures.py tests/test_models.py
git commit -m "feat: Add workflow core package boundaries"
```

## Task 2: Workflow Lock Helpers

**Files:**
- Create: `src/openbbq/core/workflow/locks.py`
- Create: `tests/test_workflow_locks.py`

- [ ] **Step 1: Write failing lock tests**

Create `tests/test_workflow_locks.py`:

```python
import json
from pathlib import Path

import pytest

from openbbq.core.workflow.locks import WorkflowLock, workflow_lock_path
from openbbq.errors import ExecutionError
from openbbq.storage import ProjectStore


def test_workflow_lock_creates_pid_file_and_releases(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    lock_path = workflow_lock_path(store, "text-demo")
    with WorkflowLock.acquire(store, "text-demo") as lock:
        assert lock.path == lock_path
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert isinstance(payload["pid"], int)
        assert payload["workflow_id"] == "text-demo"

    assert not lock_path.exists()


def test_workflow_lock_rejects_existing_lock(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    lock_path = workflow_lock_path(store, "text-demo")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text('{"pid":123,"workflow_id":"text-demo"}', encoding="utf-8")

    with pytest.raises(ExecutionError, match="locked") as exc:
        WorkflowLock.acquire(store, "text-demo")

    assert exc.value.exit_code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_workflow_locks.py -v
```

Expected: FAIL because `openbbq.core.workflow.locks` does not exist.

- [ ] **Step 3: Implement lock helpers**

Create `src/openbbq/core/workflow/locks.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from types import TracebackType

from openbbq.errors import ExecutionError
from openbbq.storage import ProjectStore


def workflow_lock_path(store: ProjectStore, workflow_id: str) -> Path:
    return store.state_root / workflow_id / f"{workflow_id}.lock"


@dataclass(frozen=True, slots=True)
class WorkflowLock:
    path: Path

    @classmethod
    def acquire(cls, store: ProjectStore, workflow_id: str) -> WorkflowLock:
        path = workflow_lock_path(store, workflow_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "workflow_id": workflow_id,
            "pid": os.getpid(),
            "created_at": datetime.now(UTC).isoformat(),
        }
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(path, flags, 0o644)
        except FileExistsError as exc:
            raise ExecutionError(
                f"Workflow '{workflow_id}' is locked.",
                code="workflow_locked",
                exit_code=1,
            ) from exc
        try:
            data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        return cls(path=path)

    def release(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            return

    def __enter__(self) -> WorkflowLock:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_workflow_locks.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/core/workflow/locks.py tests/test_workflow_locks.py
git commit -m "feat: Add workflow lock helpers"
```

## Task 3: Workflow State Helpers And Config Hash

**Files:**
- Create: `src/openbbq/core/workflow/state.py`
- Modify: `src/openbbq/storage.py`
- Create: `tests/test_workflow_state.py`

- [ ] **Step 1: Write failing state tests**

Create `tests/test_workflow_state.py`:

```python
from pathlib import Path

import pytest

from openbbq.config import load_project_config
from openbbq.core.workflow.state import (
    build_pending_state,
    compute_workflow_config_hash,
    read_effective_workflow_state,
    rebuild_output_bindings,
    require_status,
)
from openbbq.errors import ExecutionError
from openbbq.storage import ProjectStore


def test_build_pending_state_for_missing_workflow_state():
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    workflow = config.workflows["text-demo"]

    state = build_pending_state(workflow)

    assert state["id"] == "text-demo"
    assert state["status"] == "pending"
    assert state["current_step_id"] == "seed"
    assert state["step_run_ids"] == []


def test_compute_workflow_config_hash_changes_when_step_parameters_change(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = Path("tests/fixtures/projects/text-basic/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )
    first = load_project_config(project)
    config_path = project / "openbbq.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("hello openbbq", "changed"),
        encoding="utf-8",
    )
    second = load_project_config(project)

    assert compute_workflow_config_hash(first, "text-demo") != compute_workflow_config_hash(
        second, "text-demo"
    )


def test_require_status_rejects_unexpected_status():
    with pytest.raises(ExecutionError, match="paused") as exc:
        require_status({"status": "completed"}, "paused", "text-demo")

    assert exc.value.exit_code == 1


def test_rebuild_output_bindings_uses_completed_step_runs(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    _, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello openbbq",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo"},
    )
    step_run = store.write_step_run(
        "text-demo",
        {
            "step_id": "seed",
            "attempt": 1,
            "status": "completed",
            "output_bindings": {
                "text": {
                    "artifact_id": version.artifact_id,
                    "artifact_version_id": version.id,
                }
            },
        },
    )

    bindings = rebuild_output_bindings(store, "text-demo", [step_run["id"]])

    assert bindings["seed.text"]["artifact_version_id"] == version.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_workflow_state.py -v
```

Expected: FAIL because state helpers and `ProjectStore.read_step_run()` do not exist.

- [ ] **Step 3: Add `ProjectStore.read_step_run`**

Add this public method to `src/openbbq/storage.py` near `write_step_run`:

```python
    def read_step_run(self, workflow_id: str, step_run_id: str) -> dict[str, Any]:
        path = self._workflow_dir(workflow_id) / "step-runs" / f"{step_run_id}.json"
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Implement workflow state helpers**

Create `src/openbbq/core/workflow/state.py`:

```python
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
from typing import Any, Iterable

from openbbq.errors import ExecutionError
from openbbq.models.workflow import ProjectConfig, WorkflowConfig
from openbbq.storage import ProjectStore


def build_pending_state(workflow: WorkflowConfig) -> dict[str, Any]:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "status": "pending",
        "current_step_id": workflow.steps[0].id if workflow.steps else None,
        "step_run_ids": [],
    }


def read_effective_workflow_state(
    store: ProjectStore, workflow: WorkflowConfig
) -> dict[str, Any]:
    try:
        return store.read_workflow_state(workflow.id)
    except FileNotFoundError:
        return build_pending_state(workflow)


def require_status(state: dict[str, Any], expected: str, workflow_id: str) -> None:
    status = state.get("status")
    if status != expected:
        raise ExecutionError(
            f"Workflow '{workflow_id}' must be {expected}; current status is {status}.",
            code="invalid_workflow_state",
            exit_code=1,
        )


def compute_workflow_config_hash(config: ProjectConfig, workflow_id: str) -> str:
    workflow = config.workflows[workflow_id]
    payload = {
        "version": config.version,
        "workflow_id": workflow_id,
        "workflow": _jsonable(workflow),
        "plugin_paths": [str(path) for path in config.plugin_paths],
    }
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def rebuild_output_bindings(
    store: ProjectStore, workflow_id: str, step_run_ids: Iterable[str]
) -> dict[str, dict[str, str]]:
    bindings: dict[str, dict[str, str]] = {}
    for step_run_id in step_run_ids:
        try:
            step_run = store.read_step_run(workflow_id, step_run_id)
        except FileNotFoundError:
            continue
        if step_run.get("status") != "completed":
            continue
        step_id = step_run["step_id"]
        for output_name, binding in step_run.get("output_bindings", {}).items():
            bindings[f"{step_id}.{output_name}"] = dict(binding)
    return bindings


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_workflow_state.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openbbq/storage.py src/openbbq/core/workflow/state.py tests/test_workflow_state.py
git commit -m "feat: Add workflow state helpers"
```

## Task 4: Move Artifact Binding Helpers

**Files:**
- Create: `src/openbbq/core/workflow/bindings.py`
- Modify: `src/openbbq/engine.py`
- Create: `tests/test_workflow_bindings.py`

- [ ] **Step 1: Write failing binding tests**

Create `tests/test_workflow_bindings.py`:

```python
from pathlib import Path

from openbbq.config import load_project_config
from openbbq.core.workflow.bindings import build_plugin_inputs, persist_step_outputs
from openbbq.plugins import discover_plugins
from openbbq.storage import ProjectStore


def test_build_plugin_inputs_resolves_literals_and_artifacts(tmp_path):
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    workflow = config.workflows["text-demo"]
    seed_step = workflow.steps[0]
    uppercase_step = workflow.steps[1]
    store = ProjectStore(tmp_path / ".openbbq")
    artifact, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello openbbq",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo"},
    )

    literal_inputs, literal_versions = build_plugin_inputs(store, seed_step, {})
    artifact_inputs, artifact_versions = build_plugin_inputs(
        store,
        uppercase_step,
        {
            "seed.text": {
                "artifact_id": artifact.id,
                "artifact_version_id": version.id,
            }
        },
    )

    assert literal_inputs["text"] == {"literal": "hello openbbq"}
    assert literal_versions == {}
    assert artifact_inputs["text"]["content"] == "hello openbbq"
    assert artifact_versions == {"seed.text": version.id}


def test_persist_step_outputs_writes_declared_artifact_version(tmp_path):
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    registry = discover_plugins(config.plugin_paths)
    step = config.workflows["text-demo"].steps[0]
    tool = registry.tools[step.tool_ref]
    store = ProjectStore(tmp_path / ".openbbq")

    bindings = persist_step_outputs(
        store,
        "text-demo",
        step,
        tool,
        {"outputs": {"text": {"type": "text", "content": "hello openbbq", "metadata": {}}}},
        {},
    )

    version = store.read_artifact_version(bindings["text"]["artifact_version_id"])
    assert version.content == "hello openbbq"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_workflow_bindings.py -v
```

Expected: FAIL because `openbbq.core.workflow.bindings` does not exist.

- [ ] **Step 3: Move binding code into the new module**

Create `src/openbbq/core/workflow/bindings.py` by moving these helpers out of `engine.py`:

```python
from __future__ import annotations

import re
from typing import Any

from openbbq.errors import ValidationError
from openbbq.models.workflow import StepConfig
from openbbq.plugins import ToolSpec
from openbbq.storage import ProjectStore, StoredArtifactVersion

STEP_SELECTOR_PATTERN = re.compile(r"^([a-z0-9_-]+)\.([a-z0-9_-]+)$")


def parse_step_selector(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    match = STEP_SELECTOR_PATTERN.fullmatch(value)
    if match is None or match.group(1) == "project":
        return None
    return match.group(1), match.group(2)


def build_plugin_inputs(
    store: ProjectStore,
    step: StepConfig,
    output_bindings: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    plugin_inputs: dict[str, dict[str, Any]] = {}
    input_artifact_version_ids: dict[str, str] = {}
    for input_name, input_value in step.inputs.items():
        if isinstance(input_value, str) and input_value.startswith("project."):
            artifact_id = input_value.removeprefix("project.")
            artifact = store.read_artifact(artifact_id)
            version = store.read_artifact_version(artifact["current_version_id"])
            plugin_inputs[input_name] = artifact_input(artifact, version)
            input_artifact_version_ids[input_value] = version.id
            continue

        selector = parse_step_selector(input_value)
        if selector is not None:
            binding = output_bindings[input_value]
            artifact = store.read_artifact(binding["artifact_id"])
            version = store.read_artifact_version(binding["artifact_version_id"])
            plugin_inputs[input_name] = artifact_input(artifact, version)
            input_artifact_version_ids[input_value] = version.id
            continue

        plugin_inputs[input_name] = {"literal": input_value}
    return plugin_inputs, input_artifact_version_ids


def artifact_input(artifact: dict[str, Any], version: StoredArtifactVersion) -> dict[str, Any]:
    return {
        "artifact_id": artifact["id"],
        "artifact_version_id": version.id,
        "type": artifact["type"],
        "content": version.content,
        "metadata": version.record.get("metadata", {}),
    }


def persist_step_outputs(
    store: ProjectStore,
    workflow_id: str,
    step: StepConfig,
    tool: ToolSpec,
    response: dict[str, Any],
    input_artifact_version_ids: dict[str, str],
) -> dict[str, dict[str, str]]:
    response_outputs = response.get("outputs")
    if not isinstance(response_outputs, dict):
        raise ValidationError(
            f"Plugin response for step '{step.id}' must include an outputs object."
        )

    bindings: dict[str, dict[str, str]] = {}
    declared_outputs = {output.name: output for output in step.outputs}
    for output_name, output in declared_outputs.items():
        payload = response_outputs.get(output_name)
        if not isinstance(payload, dict):
            raise ValidationError(
                f"Plugin response for step '{step.id}' is missing output '{output_name}'."
            )
        output_type = payload.get("type")
        if output_type != output.type:
            raise ValidationError(
                f"Plugin response for step '{step.id}' output '{output_name}' has type '{output_type}', expected '{output.type}'."
            )
        if output_type not in tool.output_artifact_types:
            raise ValidationError(
                f"Plugin response for step '{step.id}' output '{output_name}' type '{output_type}' is not allowed."
            )
        artifact, version = store.write_artifact_version(
            artifact_type=output.type,
            name=f"{step.id}.{output.name}",
            content=payload.get("content"),
            metadata=payload.get("metadata", {}),
            created_by_step_id=step.id,
            lineage={
                "workflow_id": workflow_id,
                "step_id": step.id,
                "tool_ref": step.tool_ref,
                "input_artifact_version_ids": input_artifact_version_ids,
            },
        )
        bindings[output_name] = {
            "artifact_id": artifact.id,
            "artifact_version_id": version.id,
        }
    return bindings
```

- [ ] **Step 4: Update `engine.py` imports without changing behavior**

In `src/openbbq/engine.py`, import and use:

```python
from openbbq.core.workflow.bindings import (
    build_plugin_inputs,
    parse_step_selector,
    persist_step_outputs,
)
```

Replace calls:

```python
plugin_inputs, input_artifact_version_ids = build_plugin_inputs(
    store, step, output_bindings
)
output_bindings_for_step = persist_step_outputs(
    store,
    workflow.id,
    step,
    tool,
    response,
    input_artifact_version_ids,
)
selector = parse_step_selector(input_value)
```

Delete the moved private helpers from `engine.py`.

- [ ] **Step 5: Run focused and full tests**

Run:

```bash
uv run pytest tests/test_workflow_bindings.py tests/test_engine_run_text.py tests/test_engine_run_media.py -v
uv run pytest
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openbbq/core/workflow/bindings.py src/openbbq/engine.py tests/test_workflow_bindings.py
git commit -m "refactor: Extract workflow artifact bindings"
```

## Task 5: Extract Shared Execution Loop Without Feature Changes

**Files:**
- Create: `src/openbbq/core/workflow/execution.py`
- Modify: `src/openbbq/engine.py`
- Modify: `tests/test_engine_run_text.py`

- [ ] **Step 1: Write a regression test for unchanged run behavior**

Add this assertion to `test_run_text_workflow_to_completion` in `tests/test_engine_run_text.py`:

```python
    events_path = project / ".openbbq" / "state" / "workflows" / "text-demo" / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert [event["type"] for event in events] == [
        "workflow.started",
        "step.started",
        "step.completed",
        "step.started",
        "step.completed",
        "workflow.completed",
    ]
```

Also add `import json` to the file.

- [ ] **Step 2: Run the regression test before refactor**

Run:

```bash
uv run pytest tests/test_engine_run_text.py::test_run_text_workflow_to_completion -v
```

Expected: PASS before refactor; this locks the behavior that must survive extraction.

- [ ] **Step 3: Create execution result and context types**

Create `src/openbbq/core/workflow/execution.py` with the extracted run loop. Keep behavior equivalent to the current `run_workflow`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from openbbq.core.workflow.bindings import build_plugin_inputs, persist_step_outputs
from openbbq.errors import ExecutionError, PluginError, ValidationError
from openbbq.models.workflow import ProjectConfig, WorkflowConfig
from openbbq.plugins import PluginRegistry, execute_plugin_tool
from openbbq.storage import ProjectStore


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    workflow_id: str
    status: str
    step_count: int
    artifact_count: int


def execute_workflow_from_start(
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
) -> ExecutionResult:
    step_run_ids: list[str] = []
    output_bindings: dict[str, dict[str, Any]] = {}
    store.write_workflow_state(
        workflow.id,
        {
            "name": workflow.name,
            "status": "running",
            "current_step_id": workflow.steps[0].id if workflow.steps else None,
            "step_run_ids": [],
        },
    )
    store.append_event(
        workflow.id, {"type": "workflow.started", "message": f"Workflow '{workflow.id}' started."}
    )
    return execute_steps(
        config=config,
        registry=registry,
        store=store,
        workflow=workflow,
        start_index=0,
        step_run_ids=step_run_ids,
        output_bindings=output_bindings,
    )


def execute_steps(
    *,
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
    start_index: int,
    step_run_ids: list[str],
    output_bindings: dict[str, dict[str, Any]],
) -> ExecutionResult:
    for index in range(start_index, len(workflow.steps)):
        step = workflow.steps[index]
        tool = registry.tools[step.tool_ref]
        plugin = registry.plugins[tool.plugin_name]
        store.append_event(
            workflow.id,
            {
                "type": "step.started",
                "step_id": step.id,
                "message": f"Step '{step.id}' started.",
            },
        )
        plugin_inputs, input_artifact_version_ids = build_plugin_inputs(
            store, step, output_bindings
        )
        step_run = store.write_step_run(
            workflow.id,
            {
                "step_id": step.id,
                "attempt": 1,
                "status": "running",
                "input_artifact_version_ids": input_artifact_version_ids,
                "output_bindings": {},
                "started_at": _timestamp(),
            },
        )
        step_run_ids.append(step_run["id"])
        store.write_workflow_state(
            workflow.id,
            {
                "name": workflow.name,
                "status": "running",
                "current_step_id": step.id,
                "step_run_ids": step_run_ids,
            },
        )

        request = {
            "project_root": str(config.root_path),
            "workflow_id": workflow.id,
            "step_id": step.id,
            "tool_name": tool.name,
            "parameters": step.parameters,
            "inputs": plugin_inputs,
            "work_dir": str(config.storage.root / "work" / workflow.id / step.id),
        }
        try:
            response = execute_plugin_tool(plugin, tool, request)
            output_bindings_for_step = persist_step_outputs(
                store,
                workflow.id,
                step,
                tool,
                response,
                input_artifact_version_ids,
            )
        except (PluginError, ValidationError) as exc:
            failed = dict(step_run)
            failed["status"] = "failed"
            failed["error"] = {"code": exc.code, "message": exc.message}
            failed["completed_at"] = _timestamp()
            store.write_step_run(workflow.id, failed)
            store.write_workflow_state(
                workflow.id,
                {
                    "name": workflow.name,
                    "status": "failed",
                    "current_step_id": step.id,
                    "step_run_ids": step_run_ids,
                },
            )
            store.append_event(
                workflow.id,
                {
                    "type": "step.failed",
                    "step_id": step.id,
                    "message": exc.message,
                },
            )
            raise ExecutionError(exc.message) from exc

        completed = dict(step_run)
        completed["status"] = "completed"
        completed["output_bindings"] = output_bindings_for_step
        completed["completed_at"] = _timestamp()
        store.write_step_run(workflow.id, completed)
        for output_name, binding in output_bindings_for_step.items():
            output_bindings[f"{step.id}.{output_name}"] = binding
        next_step_id = workflow.steps[index + 1].id if index + 1 < len(workflow.steps) else None
        store.write_workflow_state(
            workflow.id,
            {
                "name": workflow.name,
                "status": "running" if next_step_id else "completed",
                "current_step_id": next_step_id,
                "step_run_ids": step_run_ids,
            },
        )
        store.append_event(
            workflow.id,
            {
                "type": "step.completed",
                "step_id": step.id,
                "message": f"Step '{step.id}' completed.",
            },
        )

    store.append_event(
        workflow.id,
        {"type": "workflow.completed", "message": f"Workflow '{workflow.id}' completed."},
    )
    return ExecutionResult(
        workflow_id=workflow.id,
        status="completed",
        step_count=len(workflow.steps),
        artifact_count=len(output_bindings),
    )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()
```

- [ ] **Step 4: Delegate `engine.run_workflow` to the execution module**

Replace the body of `run_workflow` in `src/openbbq/engine.py` after validation/state rejection with:

```python
    result = execute_workflow_from_start(config, registry, store, workflow)
    return WorkflowRunResult(
        workflow_id=result.workflow_id,
        status=result.status,
        step_count=result.step_count,
        artifact_count=result.artifact_count,
    )
```

Import:

```python
from openbbq.core.workflow.execution import execute_workflow_from_start
```

Remove the duplicated run loop from `engine.py`.

- [ ] **Step 5: Run tests to verify behavior is unchanged**

Run:

```bash
uv run pytest tests/test_engine_run_text.py tests/test_engine_run_media.py tests/test_cli_integration.py -v
uv run pytest
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openbbq/core/workflow/execution.py src/openbbq/engine.py tests/test_engine_run_text.py
git commit -m "refactor: Extract workflow execution loop"
```

## Task 6: Remove Slice 1 Pause Rejection

**Files:**
- Modify: `src/openbbq/engine.py`
- Modify: `tests/test_engine_validate.py`

- [ ] **Step 1: Change the validation test expectation**

Replace `test_validate_rejects_slice_1_pause_flags` in `tests/test_engine_validate.py` with:

```python
def test_validate_accepts_pause_flags(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        f"""
version: 1
project:
  name: Pause
plugins:
  paths:
    - {Path.cwd() / "tests/fixtures/plugins/mock-text"}
workflows:
  demo:
    name: Demo
    steps:
      - id: seed
        name: Seed
        tool_ref: mock_text.echo
        pause_before: true
        inputs:
          text: hello
        outputs:
          - name: text
            type: text
""",
        encoding="utf-8",
    )
    config = load_project_config(tmp_path)
    registry = discover_plugins(config.plugin_paths)

    result = validate_workflow(config, registry, "demo")

    assert result.workflow_id == "demo"
    assert result.step_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_engine_validate.py::test_validate_accepts_pause_flags -v
```

Expected: FAIL because `_validate_slice_1_step_control` still rejects pause flags.

- [ ] **Step 3: Update step control validation**

In `src/openbbq/engine.py`, replace `_validate_slice_1_step_control` with `_validate_step_control`:

```python
def _validate_step_control(step: StepConfig, workflow: WorkflowConfig) -> None:
    if step.on_error != "abort" or step.max_retries != 0:
        raise ValidationError(
            f"Step '{step.id}' in workflow '{workflow.id}' uses error recovery that is not implemented in this control-flow MVP.",
        )
```

Update the call in `validate_workflow`:

```python
        _validate_step_control(step, workflow)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_engine_validate.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/engine.py tests/test_engine_validate.py
git commit -m "feat: Accept pause flags in workflow validation"
```

## Task 7: Pause Before And Resume

**Files:**
- Modify: `src/openbbq/core/workflow/execution.py`
- Modify: `src/openbbq/engine.py`
- Create: `tests/test_engine_pause_resume.py`

- [ ] **Step 1: Write failing engine pause/resume tests**

Create `tests/test_engine_pause_resume.py`:

```python
from pathlib import Path

import pytest

from openbbq.config import load_project_config
from openbbq.engine import resume_workflow, run_workflow
from openbbq.errors import ExecutionError, ValidationError
from openbbq.plugins import discover_plugins
from openbbq.storage import ProjectStore


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


def test_run_pauses_before_step_and_resume_completes(tmp_path):
    project = write_project(tmp_path, "text-pause")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)

    paused = run_workflow(config, registry, "text-demo")

    assert paused.status == "paused"
    store = ProjectStore(project / ".openbbq")
    state = store.read_workflow_state("text-demo")
    assert state["status"] == "paused"
    assert state["current_step_id"] == "uppercase"
    assert len(state["step_run_ids"]) == 1
    assert store.read_step_run("text-demo", state["step_run_ids"][0])["step_id"] == "seed"

    resumed = resume_workflow(config, registry, "text-demo")

    assert resumed.status == "completed"
    artifacts = store.list_artifacts()
    assert [artifact["name"] for artifact in artifacts] == ["seed.text", "uppercase.text"]
    latest = store.read_artifact_version(artifacts[-1]["current_version_id"])
    assert latest.content == "HELLO OPENBBQ"


def test_resume_rejects_non_paused_workflow(tmp_path):
    project = write_project(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    run_workflow(config, registry, "text-demo")

    with pytest.raises(ExecutionError, match="paused"):
        resume_workflow(config, registry, "text-demo")


def test_resume_rejects_config_drift(tmp_path):
    project = write_project(tmp_path, "text-pause")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    run_workflow(config, registry, "text-demo")
    config_path = project / "openbbq.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("hello openbbq", "changed"),
        encoding="utf-8",
    )
    drifted_config = load_project_config(project)
    drifted_registry = discover_plugins(drifted_config.plugin_paths)

    with pytest.raises(ValidationError, match="changed while paused"):
        resume_workflow(drifted_config, drifted_registry, "text-demo")


def test_run_rejects_paused_workflow_without_force(tmp_path):
    project = write_project(tmp_path, "text-pause")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    run_workflow(config, registry, "text-demo")

    with pytest.raises(ExecutionError, match="paused") as exc:
        run_workflow(config, registry, "text-demo")

    assert exc.value.exit_code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_engine_pause_resume.py -v
```

Expected: FAIL because `resume_workflow` and pause behavior do not exist.

- [ ] **Step 3: Add execution support for config hash, pause before, and resume start index**

Modify `src/openbbq/core/workflow/execution.py`:

- Add imports:

```python
from openbbq.core.workflow.state import compute_workflow_config_hash
```

- Update `execute_workflow_from_start` so it computes the hash and passes it into `execute_steps`:

```python
def execute_workflow_from_start(
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
) -> ExecutionResult:
    config_hash = compute_workflow_config_hash(config, workflow.id)
    step_run_ids: list[str] = []
    output_bindings: dict[str, dict[str, Any]] = {}
    store.write_workflow_state(
        workflow.id,
        {
            "name": workflow.name,
            "status": "running",
            "current_step_id": workflow.steps[0].id if workflow.steps else None,
            "config_hash": config_hash,
            "step_run_ids": [],
        },
    )
    store.append_event(
        workflow.id, {"type": "workflow.started", "message": f"Workflow '{workflow.id}' started."}
    )
    return execute_steps(
        config=config,
        registry=registry,
        store=store,
        workflow=workflow,
        start_index=0,
        step_run_ids=step_run_ids,
        output_bindings=output_bindings,
        config_hash=config_hash,
        skip_pause_before_step_id=None,
    )
```

- Add `execute_workflow_from_resume`:

```python
def execute_workflow_from_resume(
    *,
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
    current_step_id: str,
    step_run_ids: list[str],
    output_bindings: dict[str, dict[str, Any]],
) -> ExecutionResult:
    start_index = _step_index(workflow, current_step_id)
    store.append_event(
        workflow.id,
        {"type": "workflow.resumed", "message": f"Workflow '{workflow.id}' resumed."},
    )
    return execute_steps(
        config=config,
        registry=registry,
        store=store,
        workflow=workflow,
        start_index=start_index,
        step_run_ids=step_run_ids,
        output_bindings=output_bindings,
        config_hash=compute_workflow_config_hash(config, workflow.id),
        skip_pause_before_step_id=current_step_id,
    )
```

- Add `config_hash` and `skip_pause_before_step_id` to `execute_steps` arguments and include `config_hash` in every workflow state write:

```python
def execute_steps(
    *,
    config: ProjectConfig,
    registry: PluginRegistry,
    store: ProjectStore,
    workflow: WorkflowConfig,
    start_index: int,
    step_run_ids: list[str],
    output_bindings: dict[str, dict[str, Any]],
    config_hash: str,
    skip_pause_before_step_id: str | None = None,
) -> ExecutionResult:
```

`execute_workflow_from_start` must pass `skip_pause_before_step_id=None`. `execute_workflow_from_resume` must pass the resumed `current_step_id` so the step that already caused `pause_before` is executed instead of pausing again.

- At the top of the loop, before `step.started`, add:

```python
        if step.pause_before and step.id != skip_pause_before_step_id:
            store.write_workflow_state(
                workflow.id,
                {
                    "name": workflow.name,
                    "status": "paused",
                    "current_step_id": step.id,
                    "config_hash": config_hash,
                    "step_run_ids": step_run_ids,
                },
            )
            store.append_event(
                workflow.id,
                {
                    "type": "workflow.paused",
                    "step_id": step.id,
                    "message": f"Workflow '{workflow.id}' paused before step '{step.id}'.",
                },
            )
            return ExecutionResult(
                workflow_id=workflow.id,
                status="paused",
                step_count=len(workflow.steps),
                artifact_count=len(output_bindings),
            )
```

- Add `_step_index`:

```python
def _step_index(workflow: WorkflowConfig, step_id: str) -> int:
    for index, step in enumerate(workflow.steps):
        if step.id == step_id:
            return index
    raise ExecutionError(f"Workflow '{workflow.id}' cannot resume unknown step '{step_id}'.")
```

- [ ] **Step 4: Add engine facade for resume**

Modify `src/openbbq/engine.py`:

- Import:

```python
from openbbq.core.workflow.execution import (
    execute_workflow_from_resume,
    execute_workflow_from_start,
)
from openbbq.core.workflow.state import (
    compute_workflow_config_hash,
    read_effective_workflow_state,
    rebuild_output_bindings,
    require_status,
)
```

- Update `run_workflow` to reject non-runnable persisted states before executing:

```python
    existing_state = read_effective_workflow_state(store, workflow)
    if existing_state.get("status") in {"running", "paused", "completed", "aborted"}:
        raise ExecutionError(
            f"Workflow '{workflow.id}' is {existing_state['status']}.",
            code="invalid_workflow_state",
            exit_code=1,
        )
```

- Add `resume_workflow`:

```python
def resume_workflow(
    config: ProjectConfig,
    registry: PluginRegistry,
    workflow_id: str,
) -> WorkflowRunResult:
    validate_workflow(config, registry, workflow_id)
    workflow = config.workflows[workflow_id]
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    state = read_effective_workflow_state(store, workflow)
    require_status(state, "paused", workflow.id)
    current_hash = compute_workflow_config_hash(config, workflow.id)
    if state.get("config_hash") != current_hash:
        raise ValidationError(
            f"Workflow '{workflow.id}' changed while paused; resume is not supported across config edits."
        )
    current_step_id = state.get("current_step_id")
    if not isinstance(current_step_id, str) or not current_step_id:
        raise ExecutionError(f"Workflow '{workflow.id}' does not have a resumable step.")
    step_run_ids = list(state.get("step_run_ids", []))
    result = execute_workflow_from_resume(
        config=config,
        registry=registry,
        store=store,
        workflow=workflow,
        current_step_id=current_step_id,
        step_run_ids=step_run_ids,
        output_bindings=rebuild_output_bindings(store, workflow.id, step_run_ids),
    )
    return WorkflowRunResult(
        workflow_id=result.workflow_id,
        status=result.status,
        step_count=result.step_count,
        artifact_count=result.artifact_count,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_engine_pause_resume.py -v
uv run pytest tests/test_engine_run_text.py tests/test_engine_validate.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openbbq/core/workflow/execution.py src/openbbq/engine.py tests/test_engine_pause_resume.py
git commit -m "feat: Add workflow pause and resume"
```

## Task 8: Basic Lock Integration In Run And Resume

**Files:**
- Modify: `src/openbbq/engine.py`
- Modify: `tests/test_engine_pause_resume.py`

- [ ] **Step 1: Write failing lock integration tests**

Add to `tests/test_engine_pause_resume.py`:

```python
from openbbq.core.workflow.locks import WorkflowLock, workflow_lock_path
```

Add tests:

```python
def test_run_rejects_existing_lock(tmp_path):
    project = write_project(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    store = ProjectStore(project / ".openbbq")
    WorkflowLock.acquire(store, "text-demo")

    with pytest.raises(ExecutionError, match="locked"):
        run_workflow(config, registry, "text-demo")


def test_lock_released_when_workflow_pauses_and_completes(tmp_path):
    project = write_project(tmp_path, "text-pause")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    store = ProjectStore(project / ".openbbq")

    run_workflow(config, registry, "text-demo")
    assert not workflow_lock_path(store, "text-demo").exists()

    resume_workflow(config, registry, "text-demo")
    assert not workflow_lock_path(store, "text-demo").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_engine_pause_resume.py::test_run_rejects_existing_lock tests/test_engine_pause_resume.py::test_lock_released_when_workflow_pauses_and_completes -v
```

Expected: first test FAIL because run does not check locks.

- [ ] **Step 3: Acquire locks in `run_workflow` and `resume_workflow`**

Modify `src/openbbq/engine.py`:

```python
from openbbq.core.workflow.locks import WorkflowLock
```

In `run_workflow`, wrap execution:

```python
    with WorkflowLock.acquire(store, workflow.id):
        result = execute_workflow_from_start(config, registry, store, workflow)
```

In `resume_workflow`, wrap execution:

```python
    with WorkflowLock.acquire(store, workflow.id):
        result = execute_workflow_from_resume(
            config=config,
            registry=registry,
            store=store,
            workflow=workflow,
            current_step_id=current_step_id,
            step_run_ids=step_run_ids,
            output_bindings=rebuild_output_bindings(store, workflow.id, step_run_ids),
        )
```

The context manager releases locks for paused, completed, and failed outcomes because execution is synchronous in this MVP.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_engine_pause_resume.py tests/test_workflow_locks.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/engine.py tests/test_engine_pause_resume.py
git commit -m "feat: Lock workflow run and resume"
```

## Task 9: Pause After Behavior

**Files:**
- Modify: `src/openbbq/core/workflow/execution.py`
- Modify: `tests/test_engine_pause_resume.py`

- [ ] **Step 1: Write failing pause-after test**

Add to `tests/test_engine_pause_resume.py`:

```python
def test_run_pauses_after_step_and_resume_completes(tmp_path):
    project = write_project(tmp_path, "text-basic")
    config_path = project / "openbbq.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "      - id: seed\n",
            "      - id: seed\n        pause_after: true\n",
        ),
        encoding="utf-8",
    )
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)

    paused = run_workflow(config, registry, "text-demo")

    assert paused.status == "paused"
    store = ProjectStore(project / ".openbbq")
    state = store.read_workflow_state("text-demo")
    assert state["status"] == "paused"
    assert state["current_step_id"] == "uppercase"
    artifacts = store.list_artifacts()
    assert [artifact["name"] for artifact in artifacts] == ["seed.text"]

    resumed = resume_workflow(config, registry, "text-demo")

    assert resumed.status == "completed"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_engine_pause_resume.py::test_run_pauses_after_step_and_resume_completes -v
```

Expected: FAIL because pause-after is not implemented.

- [ ] **Step 3: Implement pause-after after step completion**

In `src/openbbq/core/workflow/execution.py`, after appending `step.completed` and after calculating `next_step_id`, add:

```python
        if step.pause_after and next_step_id is not None:
            store.write_workflow_state(
                workflow.id,
                {
                    "name": workflow.name,
                    "status": "paused",
                    "current_step_id": next_step_id,
                    "config_hash": config_hash,
                    "step_run_ids": step_run_ids,
                },
            )
            store.append_event(
                workflow.id,
                {
                    "type": "workflow.paused",
                    "step_id": step.id,
                    "message": f"Workflow '{workflow.id}' paused after step '{step.id}'.",
                },
            )
            return ExecutionResult(
                workflow_id=workflow.id,
                status="paused",
                step_count=len(workflow.steps),
                artifact_count=len(output_bindings),
            )
```

Ensure this block runs before the next loop iteration and after final-step completion handling. If `next_step_id is None`, let the workflow complete.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_engine_pause_resume.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/core/workflow/execution.py tests/test_engine_pause_resume.py
git commit -m "feat: Add pause-after workflow control"
```

## Task 10: Paused Abort Facade

**Files:**
- Modify: `src/openbbq/engine.py`
- Modify: `tests/test_engine_pause_resume.py`

- [ ] **Step 1: Write failing paused abort tests**

Add to `tests/test_engine_pause_resume.py` imports:

```python
from openbbq.engine import abort_workflow, resume_workflow, run_workflow
```

Add tests:

```python
def test_abort_paused_workflow_persists_aborted_and_preserves_artifacts(tmp_path):
    project = write_project(tmp_path, "text-pause")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    run_workflow(config, registry, "text-demo")

    result = abort_workflow(config, "text-demo")

    assert result["status"] == "aborted"
    store = ProjectStore(project / ".openbbq")
    state = store.read_workflow_state("text-demo")
    assert state["status"] == "aborted"
    assert state["current_step_id"] == "uppercase"
    assert [artifact["name"] for artifact in store.list_artifacts()] == ["seed.text"]


def test_resume_rejects_aborted_workflow(tmp_path):
    project = write_project(tmp_path, "text-pause")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    run_workflow(config, registry, "text-demo")
    abort_workflow(config, "text-demo")

    with pytest.raises(ExecutionError, match="paused"):
        resume_workflow(config, registry, "text-demo")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_engine_pause_resume.py::test_abort_paused_workflow_persists_aborted_and_preserves_artifacts tests/test_engine_pause_resume.py::test_resume_rejects_aborted_workflow -v
```

Expected: FAIL because `abort_workflow` does not exist.

- [ ] **Step 3: Implement `abort_workflow`**

Add to `src/openbbq/engine.py`:

```python
from openbbq.core.workflow.locks import workflow_lock_path


def abort_workflow(config: ProjectConfig, workflow_id: str) -> dict[str, object]:
    workflow = config.workflows.get(workflow_id)
    if workflow is None:
        raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    state = read_effective_workflow_state(store, workflow)
    require_status(state, "paused", workflow.id)
    aborted = store.write_workflow_state(
        workflow.id,
        {
            "name": workflow.name,
            "status": "aborted",
            "current_step_id": state.get("current_step_id"),
            "config_hash": state.get("config_hash"),
            "step_run_ids": list(state.get("step_run_ids", [])),
        },
    )
    store.append_event(
        workflow.id,
        {"type": "workflow.aborted", "message": f"Workflow '{workflow.id}' aborted."},
    )
    workflow_lock_path(store, workflow.id).unlink(missing_ok=True)
    return aborted
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_engine_pause_resume.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/engine.py tests/test_engine_pause_resume.py
git commit -m "feat: Add paused workflow abort"
```

## Task 11: CLI Control Flow Commands

**Files:**
- Modify: `src/openbbq/cli.py`
- Modify: `tests/test_slice2_guardrails.py`
- Create: `tests/test_cli_control_flow.py`

- [ ] **Step 1: Write failing CLI control flow tests**

Create `tests/test_cli_control_flow.py`:

```python
import json
from pathlib import Path

from openbbq.cli import main


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


def test_cli_run_status_resume_control_flow(tmp_path, capsys):
    project = write_project(tmp_path, "text-pause")

    assert main(["--project", str(project), "--json", "run", "text-demo"]) == 0
    run_payload = json.loads(capsys.readouterr().out)
    assert run_payload["status"] == "paused"

    assert main(["--project", str(project), "--json", "status", "text-demo"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["status"] == "paused"
    assert status_payload["current_step_id"] == "uppercase"

    assert main(["--project", str(project), "--json", "resume", "text-demo"]) == 0
    resume_payload = json.loads(capsys.readouterr().out)
    assert resume_payload["status"] == "completed"


def test_cli_abort_paused_workflow_and_reject_resume(tmp_path, capsys):
    project = write_project(tmp_path, "text-pause")

    assert main(["--project", str(project), "--json", "run", "text-demo"]) == 0
    capsys.readouterr()
    assert main(["--project", str(project), "--json", "abort", "text-demo"]) == 0
    abort_payload = json.loads(capsys.readouterr().out)
    assert abort_payload["status"] == "aborted"

    assert main(["--project", str(project), "--json", "resume", "text-demo"]) == 1
    error_payload = json.loads(capsys.readouterr().out)
    assert error_payload["ok"] is False
    assert error_payload["error"]["code"] == "invalid_workflow_state"
```

- [ ] **Step 2: Update guardrail tests**

In `tests/test_slice2_guardrails.py`:

- Delete `test_resume_is_clear_slice_2_error`.
- Add:

```python
def test_unlock_is_clear_slice_2_error(capsys):
    code = main(["unlock", "demo"])

    assert code == 1
    assert "not implemented in Slice 1" in capsys.readouterr().err
```

Keep artifact diff, run force, and run step guardrail tests.

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_cli_control_flow.py tests/test_slice2_guardrails.py -v
```

Expected: CLI control flow tests FAIL because `resume` and `abort` still dispatch unsupported errors.

- [ ] **Step 4: Wire CLI commands**

Modify imports in `src/openbbq/cli.py`:

```python
from openbbq.engine import abort_workflow, resume_workflow, run_workflow, validate_workflow
```

Update `_dispatch`:

```python
    if args.command == "resume":
        return _resume(args)
    if args.command == "abort":
        return _abort(args)
    if args.command == "unlock":
        raise _unsupported_slice_2(args.command)
```

Add handlers:

```python
def _resume(args: argparse.Namespace) -> int:
    config, registry = _load_config_and_plugins(args)
    result = resume_workflow(config, registry, args.workflow)
    payload = {
        "ok": True,
        "workflow_id": result.workflow_id,
        "status": result.status,
        "step_count": result.step_count,
        "artifact_count": result.artifact_count,
    }
    _emit(payload, args.json_output, f"Workflow '{result.workflow_id}' {result.status}.")
    return 0


def _abort(args: argparse.Namespace) -> int:
    config = _load_config(args)
    result = abort_workflow(config, args.workflow)
    payload = {"ok": True, "workflow_id": args.workflow, "status": result["status"]}
    _emit(payload, args.json_output, f"Workflow '{args.workflow}' aborted.")
    return 0
```

Update `_run` human output so paused runs do not say completed:

```python
    _emit(payload, args.json_output, f"Workflow '{result.workflow_id}' {result.status}.")
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_cli_control_flow.py tests/test_slice2_guardrails.py tests/test_cli_integration.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openbbq/cli.py tests/test_cli_control_flow.py tests/test_slice2_guardrails.py
git commit -m "feat: Wire pause resume CLI flow"
```

## Task 12: Final Verification And Documentation Check

**Files:**
- Modify only if verification exposes a real issue.

- [ ] **Step 1: Run full verification**

Run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Expected:

- pytest reports all tests passing.
- Ruff check reports no issues.
- Ruff format check reports all files formatted.

- [ ] **Step 2: Run manual CLI smoke flow**

Run:

```bash
tmpdir="$(mktemp -d)"
cp -R tests/fixtures/projects/text-pause "$tmpdir/project"
export PROJECT="$tmpdir/project"
python - <<'PY'
from pathlib import Path
import os
project = Path(os.environ["PROJECT"])
config = project / "openbbq.yaml"
config.write_text(config.read_text().replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")), encoding="utf-8")
PY
```

Then run:

```bash
uv run openbbq --project "$tmpdir/project" --json run text-demo
uv run openbbq --project "$tmpdir/project" --json status text-demo
uv run openbbq --project "$tmpdir/project" --json resume text-demo
uv run openbbq --project "$tmpdir/project" --json status text-demo
```

Expected:

- first run reports `status: "paused"`;
- status reports `current_step_id: "uppercase"`;
- resume reports `status: "completed"`;
- final status reports `status: "completed"`.

- [ ] **Step 3: Inspect git diff**

Run:

```bash
git diff --stat
git status --short
```

Expected: only intended Slice 2 control-flow files changed.

- [ ] **Step 4: Commit any final fixes**

If Step 1 or Step 2 required a real code fix:

```bash
git add <changed-files>
git commit -m "fix: Stabilize slice 2 control flow"
```

If no fixes were needed, do not create an empty commit.

## Self-Review

- Spec coverage: Tasks cover the approved modular package layout, workflow model re-export, state/config hash helpers, lock helpers, artifact binding extraction, shared execution loop, pause-before, pause-after, resume, paused abort, CLI wiring, fixtures, and verification.
- Explicit exclusions: running abort request files, unlock, stale lock recovery, retry/skip, run force, run step, and artifact diff remain outside this plan.
- Type consistency: Public facade uses `WorkflowRunResult` for run/resume and a state dict for abort. Internal execution returns `ExecutionResult`. `ProjectStore.read_step_run()` returns the same dict shape written by `write_step_run()`.
- Placeholder scan: The plan has no unresolved placeholder markers. Each task includes exact files, test code, implementation code or concrete edit instructions, commands, expected outcomes, and commit commands.

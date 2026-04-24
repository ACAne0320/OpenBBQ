# Backend Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden OpenBBQ's working CLI-first backend into a stricter typed application core that can support desktop development without inheriting CLI-era technical debt.

**Architecture:** Strengthen contracts first, then split execution and storage around those contracts, then introduce application services that both CLI and future desktop/API adapters can call. Remove compatibility paths after the new typed contracts cover the existing target workflows.

**Tech Stack:** Python 3.11, Pydantic v2, PyYAML, TOML via `tomllib`, `jsonschema`, pytest, Ruff, local filesystem storage.

---

## Scope Check

The design touches contracts, plugin manifests, execution, storage, services, and built-in plugins. These are related backend-hardening slices for the same desktop-readiness goal. Keep them in one plan, but commit each task separately so a future task can be reverted without losing earlier contract work.

Do not build desktop UI, FastAPI routes, or a worker daemon in this plan.

## File Structure

Create these files:

- `src/openbbq/application/__init__.py`: package marker for adapter-independent application services.
- `src/openbbq/application/artifacts.py`: artifact import, list, show, diff, and export operations.
- `src/openbbq/application/auth.py`: provider auth setup and checks.
- `src/openbbq/application/diagnostics.py`: doctor checks and runtime diagnostics.
- `src/openbbq/application/plugins.py`: plugin list and plugin info operations.
- `src/openbbq/application/projects.py`: project initialization, list, and info operations.
- `src/openbbq/application/runtime.py`: runtime settings operations.
- `src/openbbq/application/workflows.py`: validate, run, resume, abort, unlock, status, logs, and generated workflow operations.
- `src/openbbq/plugins/contracts.py`: plugin manifest v2 models.
- `src/openbbq/storage/json_files.py`: atomic JSON and JSONL primitives.
- `src/openbbq/storage/events.py`: workflow event persistence and JSONL recovery.
- `src/openbbq/storage/artifacts.py`: artifact records, version records, content storage, and artifact index.
- `src/openbbq/storage/workflows.py`: workflow state, step run, lock, and abort request persistence.
- `src/openbbq/workflow/context.py`: execution context object shared by runner and step executor.
- `src/openbbq/workflow/events.py`: workflow event construction, plugin event wrapping, and redaction.
- `src/openbbq/workflow/runner.py`: workflow run loop.
- `src/openbbq/workflow/steps.py`: one-step attempt execution.
- `src/openbbq/workflow/transitions.py`: named workflow and step run state transitions.
- `src/openbbq/builtin_plugins/translation/models.py`: typed translation parameters, segments, and QA issue models.
- `src/openbbq/builtin_plugins/translation/llm_json.py`: shared LLM JSON completion helpers for translation.
- `src/openbbq/builtin_plugins/translation/translate.py`: translation tool implementation.
- `src/openbbq/builtin_plugins/translation/qa.py`: translation QA tool implementation.
- `src/openbbq/builtin_plugins/transcript/models.py`: typed transcript correction and segmentation models.
- `src/openbbq/builtin_plugins/transcript/llm_json.py`: shared LLM JSON completion helpers for transcript correction.
- `src/openbbq/builtin_plugins/transcript/correct.py`: transcript correction tool implementation.
- `src/openbbq/builtin_plugins/transcript/segment.py`: transcript segmentation tool implementation.

Modify these files:

- `docs/phase1/Domain-Model.md`: align persisted event schema with implementation.
- `docs/phase1/Plugin-System.md`: document manifest v2 and plugin response metadata/events.
- `docs/Target-Workflows.md`: remove `llm.translate` alias and legacy provider notes.
- `README.md`: update current CLI examples after provider and plugin contract changes.
- `src/openbbq/domain/base.py`: add strict dump helpers and remove dict-like compatibility assumptions.
- `src/openbbq/domain/models.py`: make mappings immutable or typed records where practical.
- `src/openbbq/storage/models.py`: add event level/data, plugin event payloads, and remove dict-like access.
- `src/openbbq/plugins/payloads.py`: add plugin response metadata and events.
- `src/openbbq/plugins/registry.py`: parse manifest v2 and build typed plugin contracts.
- `src/openbbq/engine/validation.py`: validate named inputs and outputs against plugin contract v2.
- `src/openbbq/workflow/bindings.py`: use named plugin input and output specs.
- `src/openbbq/workflow/execution.py`: shrink to wrappers around the new runner during migration, then remove duplicated logic.
- `src/openbbq/workflow/state.py`: use typed state helpers without dict access.
- `src/openbbq/workflow/rerun.py`: use typed step run and output binding access.
- `src/openbbq/workflow/locks.py`: move persistence calls through `storage.workflows`.
- `src/openbbq/workflow/aborts.py`: move persistence calls through `storage.workflows`.
- `src/openbbq/engine/service.py`: delegate to application/workflow services and typed stores.
- `src/openbbq/runtime/provider.py`: remove implicit legacy environment fallback.
- `src/openbbq/runtime/doctor.py`: check named providers only.
- `src/openbbq/cli/app.py`: keep parser and output adapter; move application behavior out.
- `src/openbbq/cli/quickstart.py`: delegate generated workflow behavior through application services.
- Built-in and fixture `openbbq.plugin.toml` files: migrate from flat allowlists to manifest v2 named slots.
- Fixture `openbbq.yaml` files: update provider and tool alias usage.
- Tests under `tests/`: add focused contract tests and update old compatibility expectations.

## Task 1: Align Workflow Events And Plugin Response Payloads

**Files:**

- Modify: `src/openbbq/storage/models.py`
- Modify: `src/openbbq/plugins/payloads.py`
- Modify: `src/openbbq/storage/project_store.py`
- Modify: `src/openbbq/plugins/registry.py`
- Modify: `src/openbbq/workflow/execution.py`
- Modify: `src/openbbq/workflow/events.py`
- Create: `src/openbbq/workflow/events.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_storage.py`
- Modify: `tests/test_workflow_bindings.py`
- Modify: `tests/test_runtime_engine.py`

- [ ] **Step 1: Write failing model tests for event and plugin response contracts**

Append these tests to `tests/test_models.py`:

```python
from openbbq.plugins.payloads import PluginEventPayload, PluginResponse
from openbbq.storage.models import WorkflowEvent


def test_workflow_event_requires_level_and_data_defaults():
    event = WorkflowEvent(
        id="evt_1",
        workflow_id="text-demo",
        sequence=1,
        type="workflow.started",
        message="started",
        created_at="2026-04-24T00:00:00+00:00",
    )

    assert event.level == "info"
    assert event.data == {}


def test_plugin_response_preserves_metadata_and_events():
    response = PluginResponse.model_validate(
        {
            "outputs": {
                "text": {
                    "type": "text",
                    "content": "HELLO",
                    "metadata": {},
                }
            },
            "metadata": {"duration_ms": 3},
            "events": [
                {
                    "level": "info",
                    "message": "Transform completed",
                    "data": {"input_chars": 5},
                }
            ],
        }
    )

    assert response.metadata == {"duration_ms": 3}
    assert response.events == (
        PluginEventPayload(
            level="info",
            message="Transform completed",
            data={"input_chars": 5},
        ),
    )
```

- [ ] **Step 2: Run the failing contract tests**

Run:

```bash
uv run pytest tests/test_models.py::test_workflow_event_requires_level_and_data_defaults tests/test_models.py::test_plugin_response_preserves_metadata_and_events -q
```

Expected: FAIL because `level`, `data`, `PluginEventPayload`, response `metadata`, and response `events` are not implemented.

- [ ] **Step 3: Extend storage and plugin payload models**

In `src/openbbq/storage/models.py`, replace `WorkflowEvent` with this shape:

```python
WorkflowEventLevel: TypeAlias = Literal["debug", "info", "warning", "error"]


class WorkflowEvent(RecordModel):
    id: str
    workflow_id: str
    sequence: int
    type: str
    level: WorkflowEventLevel = "info"
    message: str | None = None
    data: JsonObject = Field(default_factory=dict)
    created_at: str
    step_id: str | None = None
    attempt: int | None = None
```

In `src/openbbq/plugins/payloads.py`, add:

```python
PluginEventLevel: TypeAlias = Literal["debug", "info", "warning", "error"]


class PluginEventPayload(PluginPayloadModel):
    level: PluginEventLevel = "info"
    message: str
    data: JsonObject = Field(default_factory=dict)
```

Then update `PluginResponse`:

```python
class PluginResponse(PluginPayloadModel):
    outputs: dict[str, PluginOutputPayload]
    metadata: JsonObject = Field(default_factory=dict)
    events: tuple[PluginEventPayload, ...] = ()
    pause_requested: bool = False
```

- [ ] **Step 4: Add plugin event wrapping**

Create `src/openbbq/workflow/events.py`:

```python
from __future__ import annotations

from openbbq.domain.base import JsonObject
from openbbq.plugins.payloads import PluginEventPayload, PluginResponse
from openbbq.runtime.redaction import redact_values
from openbbq.storage.project_store import ProjectStore


def append_workflow_event(
    store: ProjectStore,
    workflow_id: str,
    event_type: str,
    *,
    message: str | None = None,
    level: str = "info",
    step_id: str | None = None,
    attempt: int | None = None,
    data: JsonObject | None = None,
):
    return store.append_event(
        workflow_id,
        {
            "type": event_type,
            "level": level,
            "message": message,
            "step_id": step_id,
            "attempt": attempt,
            "data": data or {},
        },
    )


def append_plugin_events(
    store: ProjectStore,
    workflow_id: str,
    step_id: str,
    attempt: int,
    response: PluginResponse,
    *,
    redaction_values: tuple[str, ...] = (),
) -> None:
    for event in response.events:
        append_plugin_event(
            store,
            workflow_id,
            step_id,
            attempt,
            event,
            redaction_values=redaction_values,
        )


def append_plugin_event(
    store: ProjectStore,
    workflow_id: str,
    step_id: str,
    attempt: int,
    event: PluginEventPayload,
    *,
    redaction_values: tuple[str, ...] = (),
) -> None:
    message = redact_values(event.message, redaction_values)
    append_workflow_event(
        store,
        workflow_id,
        "plugin.event",
        level=event.level,
        step_id=step_id,
        attempt=attempt,
        message=message,
        data=event.data,
    )
```

- [ ] **Step 5: Persist plugin events after a successful step**

In `src/openbbq/workflow/execution.py`, import `append_plugin_events`:

```python
from openbbq.workflow.events import append_plugin_events
```

After `store.write_step_run(workflow.id, completed)` and before setting `pause_requested`, add:

```python
append_plugin_events(
    store,
    workflow.id,
    step.id,
    attempt,
    response,
    redaction_values=tuple(redaction_values),
)
```

- [ ] **Step 6: Add an execution test for plugin events and redaction**

Append to `tests/test_runtime_engine.py`:

```python
def test_plugin_events_are_wrapped_and_redacted(tmp_path, monkeypatch):
    from openbbq.workflow import execution

    def fake_execute_plugin_tool(plugin, tool, request, redactor=None):
        return {
            "outputs": {
                "text": {
                    "type": "text",
                    "content": "hello",
                    "metadata": {},
                }
            },
            "events": [
                {
                    "level": "warning",
                    "message": "provider returned sk-secret",
                    "data": {"provider": "test"},
                }
            ],
        }

    monkeypatch.setattr(execution, "execute_plugin_tool", fake_execute_plugin_tool)
    project = write_project(tmp_path, "text-basic")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    context = RuntimeContext(redaction_values=("sk-secret",))

    result = run_workflow(config, registry, "text-demo", runtime_context=context)

    assert result.status == "completed"
    store = ProjectStore(project / ".openbbq")
    events = [
        json.loads(line)
        for line in (project / ".openbbq/state/workflows/text-demo/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    plugin_events = [event for event in events if event["type"] == "plugin.event"]
    assert plugin_events[0]["level"] == "warning"
    assert plugin_events[0]["message"] == "provider returned [REDACTED]"
    assert plugin_events[0]["data"] == {"provider": "test"}
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run pytest tests/test_models.py tests/test_storage.py tests/test_runtime_engine.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit event contract hardening**

Run:

```bash
git add src/openbbq/storage/models.py src/openbbq/plugins/payloads.py src/openbbq/workflow/events.py src/openbbq/workflow/execution.py tests/test_models.py tests/test_storage.py tests/test_runtime_engine.py
git commit -m "feat: Harden workflow event contracts"
```

## Task 2: Remove Dict-Like Model Access Internally

**Files:**

- Modify: `src/openbbq/storage/models.py`
- Modify: `src/openbbq/plugins/payloads.py`
- Modify: `src/openbbq/workflow/state.py`
- Modify: `src/openbbq/workflow/rerun.py`
- Modify: `src/openbbq/workflow/bindings.py`
- Modify: `src/openbbq/workflow/execution.py`
- Modify: `src/openbbq/engine/service.py`
- Modify: `src/openbbq/cli/app.py`
- Modify: tests that index models as dictionaries.

- [ ] **Step 1: Write tests proving models are not mappings**

Append to `tests/test_models.py`:

```python
from openbbq.storage.models import OutputBinding, WorkflowState


def test_storage_models_do_not_expose_dict_compatibility():
    state = WorkflowState(id="text-demo", status="pending", current_step_id="seed")
    binding = OutputBinding(artifact_id="art_1", artifact_version_id="av_1")

    assert not hasattr(state, "__getitem__")
    assert not hasattr(state, "get")
    assert binding.artifact_id == "art_1"
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
uv run pytest tests/test_models.py::test_storage_models_do_not_expose_dict_compatibility -q
```

Expected: FAIL because `RecordModel` currently exposes `__getitem__` and `get`.

- [ ] **Step 3: Remove dict compatibility from models**

In `src/openbbq/storage/models.py`, replace:

```python
class RecordModel(OpenBBQModel):
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)
```

with:

```python
class RecordModel(OpenBBQModel):
    pass
```

In `src/openbbq/plugins/payloads.py`, replace:

```python
class PluginPayloadModel(OpenBBQModel):
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict):
            return self.model_dump(mode="json", exclude_none=True) == other
        return super().__eq__(other)
```

with:

```python
class PluginPayloadModel(OpenBBQModel):
    pass
```

- [ ] **Step 4: Migrate internal accessors to attributes**

Apply these representative replacements across source and tests:

```python
state.status
state.current_step_id
state.step_run_ids
step_run.id
step_run.status
step_run.step_id
step_run.output_bindings
binding.artifact_id
binding.artifact_version_id
artifact.id
artifact.type
artifact.name
artifact.current_version_id
version.record.lineage
```

For CLI JSON output, use:

```python
payload = {"ok": True, **dump_jsonable(state)}
```

only at adapter boundaries after `dump_jsonable()` converts models to dictionaries.

- [ ] **Step 5: Run focused migration tests**

Run:

```bash
uv run pytest tests/test_models.py tests/test_storage.py tests/test_workflow_state.py tests/test_workflow_bindings.py tests/test_engine_run_text.py tests/test_cli_integration.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit model access cleanup**

Run:

```bash
git add src/openbbq tests
git commit -m "refactor: Remove dict-like model access"
```

## Task 3: Introduce Plugin Manifest V2 With Named Inputs And Outputs

**Files:**

- Create: `src/openbbq/plugins/contracts.py`
- Modify: `src/openbbq/plugins/registry.py`
- Modify: `src/openbbq/engine/validation.py`
- Modify: `src/openbbq/workflow/bindings.py`
- Modify: all `openbbq.plugin.toml` files under `src/openbbq/builtin_plugins/` and `tests/fixtures/plugins/`
- Modify: `docs/phase1/Plugin-System.md`
- Modify: `tests/test_plugins.py`
- Modify: `tests/test_engine_validate.py`
- Modify: `tests/test_fixtures.py`

- [ ] **Step 1: Write failing registry tests for manifest v2**

Append to `tests/test_plugins.py`:

```python
def test_manifest_v2_declares_named_input_and_output_specs(tmp_path):
    plugin_dir = tmp_path / "plugins" / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "openbbq.plugin.toml").write_text(
        """
name = "demo"
version = "0.1.0"
runtime = "python"
entrypoint = "plugin:run"
manifest_version = 2

[[tools]]
name = "copy"
description = "Copy text."
effects = []

[tools.parameter_schema]
type = "object"
additionalProperties = false
properties = {}

[tools.inputs.text]
artifact_types = ["text"]
required = true
description = "Source text."

[tools.outputs.text]
artifact_type = "text"
description = "Copied text."
""",
        encoding="utf-8",
    )

    registry = discover_plugins([tmp_path / "plugins"])
    tool = registry.tools["demo.copy"]

    assert tool.inputs["text"].artifact_types == ("text",)
    assert tool.inputs["text"].required is True
    assert tool.outputs["text"].artifact_type == "text"
```

- [ ] **Step 2: Run the failing registry test**

Run:

```bash
uv run pytest tests/test_plugins.py::test_manifest_v2_declares_named_input_and_output_specs -q
```

Expected: FAIL because manifest v2 models are not implemented.

- [ ] **Step 3: Add plugin contract models**

Create `src/openbbq/plugins/contracts.py`:

```python
from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import Field, field_validator

from openbbq.domain.base import JsonObject, OpenBBQModel
from openbbq.domain.models import ARTIFACT_TYPES

PluginRuntime: TypeAlias = Literal["python"]
PluginEffect: TypeAlias = Literal["network", "reads_files", "writes_files"]


class ToolInputSpec(OpenBBQModel):
    artifact_types: tuple[str, ...]
    required: bool = True
    description: str | None = None
    multiple: bool = False

    @field_validator("artifact_types")
    @classmethod
    def registered_artifact_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("must define at least one artifact type")
        unknown = [artifact_type for artifact_type in value if artifact_type not in ARTIFACT_TYPES]
        if unknown:
            raise ValueError(f"unknown artifact types: {', '.join(sorted(unknown))}")
        return value


class ToolOutputSpec(OpenBBQModel):
    artifact_type: str
    description: str | None = None

    @field_validator("artifact_type")
    @classmethod
    def registered_artifact_type(cls, value: str) -> str:
        if value not in ARTIFACT_TYPES:
            raise ValueError(f"unknown artifact type: {value}")
        return value


class RuntimeRequirementSpec(OpenBBQModel):
    binaries: tuple[str, ...] = ()
    python_extras: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()
    models: tuple[str, ...] = ()


class ToolUiSpec(OpenBBQModel):
    form: JsonObject = Field(default_factory=dict)
    preview: JsonObject = Field(default_factory=dict)


class ToolContract(OpenBBQModel):
    inputs: dict[str, ToolInputSpec] = Field(default_factory=dict)
    outputs: dict[str, ToolOutputSpec]
    runtime_requirements: RuntimeRequirementSpec = Field(default_factory=RuntimeRequirementSpec)
    ui: ToolUiSpec = Field(default_factory=ToolUiSpec)
```

- [ ] **Step 4: Extend `ToolSpec`**

In `src/openbbq/plugins/registry.py`, add fields to `ToolSpec`:

```python
inputs: dict[str, ToolInputSpec] = Field(default_factory=dict)
outputs: dict[str, ToolOutputSpec] = Field(default_factory=dict)
runtime_requirements: RuntimeRequirementSpec = Field(default_factory=RuntimeRequirementSpec)
ui: ToolUiSpec = Field(default_factory=ToolUiSpec)
```

Keep `input_artifact_types` and `output_artifact_types` only during this task so existing manifests still load while v2 tests are developed. The compatibility fields are removed in Task 8.

- [ ] **Step 5: Parse v2 `inputs` and `outputs` tables**

In `_parse_tool_manifest()`, after reading `schema`, parse v2 fields:

```python
inputs = _parse_tool_inputs(tool_raw.get("inputs", {}), plugin_name, index)
outputs = _parse_tool_outputs(tool_raw.get("outputs", {}), plugin_name, index)
if outputs:
    input_artifact_types = sorted(
        {artifact_type for spec in inputs.values() for artifact_type in spec.artifact_types}
    )
    output_artifact_types = [spec.artifact_type for spec in outputs.values()]
```

Add helper functions:

```python
def _parse_tool_inputs(value: Any, plugin_name: str, index: int) -> dict[str, ToolInputSpec]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"tools[{index}].inputs in plugin '{plugin_name}' must be a table.")
    parsed = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"tools[{index}].inputs contains an invalid input name.")
        if not isinstance(raw, dict):
            raise ValueError(f"tools[{index}].inputs.{name} must be a table.")
        parsed[name] = ToolInputSpec.model_validate(raw)
    return parsed


def _parse_tool_outputs(value: Any, plugin_name: str, index: int) -> dict[str, ToolOutputSpec]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"tools[{index}].outputs in plugin '{plugin_name}' must be a table.")
    parsed = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"tools[{index}].outputs contains an invalid output name.")
        if not isinstance(raw, dict):
            raise ValueError(f"tools[{index}].outputs.{name} must be a table.")
        parsed[name] = ToolOutputSpec.model_validate(raw)
    return parsed
```

- [ ] **Step 6: Validate workflow input names against v2 specs**

Append to `tests/test_engine_validate.py`:

```python
def test_validate_rejects_unknown_named_tool_input(tmp_path):
    project = copy_project(tmp_path, "text-basic")
    config_path = project / "openbbq.yaml"
    source = config_path.read_text(encoding="utf-8")
    config_path.write_text(source.replace("text: seed.text", "wrong: seed.text"), encoding="utf-8")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)

    with pytest.raises(ValidationError, match="unknown input 'wrong'"):
        validate_workflow(config, registry, "text-demo")
```

In `src/openbbq/engine/validation.py`, add:

```python
def _validate_named_inputs(step: StepConfig, tool: ToolSpec) -> None:
    if not tool.inputs:
        return
    allowed = set(tool.inputs)
    for input_name in step.inputs:
        if input_name not in allowed:
            raise ValidationError(
                f"Step '{step.id}' input '{input_name}' is not declared by tool '{step.tool_ref}'."
            )
    for input_name, input_spec in tool.inputs.items():
        if input_spec.required and input_name not in step.inputs:
            raise ValidationError(
                f"Step '{step.id}' is missing required input '{input_name}' for tool '{step.tool_ref}'."
            )
```

Call `_validate_named_inputs(step, tool)` before artifact type validation.

- [ ] **Step 7: Migrate fixture and built-in manifests to v2**

For each tool, add named `inputs` and `outputs`. Example for `mock_text.uppercase`:

```toml
manifest_version = 2

[[tools]]
name = "uppercase"
description = "Convert text input to uppercase."
effects = []

[tools.parameter_schema]
type = "object"
additionalProperties = false
properties = {}

[tools.inputs.text]
artifact_types = ["text"]
required = true
description = "Text artifact to transform."

[tools.outputs.text]
artifact_type = "text"
description = "Uppercase text artifact."
```

Use these named slots for built-ins:

- `remote_video.download`: outputs `video`.
- `ffmpeg.extract_audio`: input `video`, output `audio`.
- `faster_whisper.transcribe`: input `audio`, output `transcript`.
- `transcript.correct`: input `transcript`, output `transcript`.
- `transcript.segment`: input `transcript`, output `subtitle_segments`.
- `translation.translate`: input `subtitle_segments`, output `translation`.
- `translation.qa`: input `translation`, output `qa`.
- `subtitle.export`: input `translation`, output `subtitle`.

- [ ] **Step 8: Run plugin and validation suites**

Run:

```bash
uv run pytest tests/test_plugins.py tests/test_engine_validate.py tests/test_fixtures.py tests/test_phase2_contract_regressions.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit manifest v2 support**

Run:

```bash
git add src/openbbq/plugins src/openbbq/engine/validation.py src/openbbq/workflow/bindings.py src/openbbq/builtin_plugins tests docs/phase1/Plugin-System.md
git commit -m "feat: Add named plugin contracts"
```

## Task 4: Split Workflow Execution Into Runner, Step Executor, Transitions, And Event Sink

**Files:**

- Create: `src/openbbq/workflow/context.py`
- Create: `src/openbbq/workflow/runner.py`
- Create: `src/openbbq/workflow/steps.py`
- Create: `src/openbbq/workflow/transitions.py`
- Modify: `src/openbbq/workflow/execution.py`
- Modify: `tests/test_engine_run_text.py`
- Modify: `tests/test_engine_error_policy.py`
- Modify: `tests/test_engine_pause_resume.py`
- Modify: `tests/test_engine_abort.py`

- [ ] **Step 1: Write transition-focused tests**

Create `tests/test_workflow_transitions.py`:

```python
from openbbq.workflow.transitions import (
    mark_step_run_completed,
    mark_step_run_started,
    mark_workflow_running,
)


def test_transition_helpers_write_typed_workflow_and_step_run_records(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")

    state = mark_workflow_running(
        store,
        workflow_id="text-demo",
        workflow_name="Text Demo",
        current_step_id="seed",
        config_hash="abc",
        step_run_ids=(),
    )
    step_run = mark_step_run_started(
        store,
        workflow_id="text-demo",
        step_id="seed",
        attempt=1,
    )
    completed = mark_step_run_completed(
        store,
        workflow_id="text-demo",
        step_run=step_run,
        input_artifact_version_ids={},
        output_bindings={},
    )

    assert state.status == "running"
    assert step_run.status == "running"
    assert completed.status == "completed"
```

Include these imports at the top:

```python
from openbbq.storage.project_store import ProjectStore
```

- [ ] **Step 2: Run the failing transition test**

Run:

```bash
uv run pytest tests/test_workflow_transitions.py -q
```

Expected: FAIL because `workflow.transitions` does not exist.

- [ ] **Step 3: Add execution context model**

Create `src/openbbq/workflow/context.py`:

```python
from __future__ import annotations

from pydantic import Field

from openbbq.domain.base import OpenBBQModel
from openbbq.domain.models import ProjectConfig, WorkflowConfig
from openbbq.plugins.registry import PluginRegistry
from openbbq.runtime.models import RuntimeContext
from openbbq.storage.models import OutputBindings
from openbbq.storage.project_store import ProjectStore


class ExecutionContext(OpenBBQModel):
    config: ProjectConfig
    registry: PluginRegistry
    store: ProjectStore
    workflow: WorkflowConfig
    config_hash: str
    runtime_context: RuntimeContext | None = None
    step_run_ids: tuple[str, ...] = ()
    output_bindings: OutputBindings = Field(default_factory=dict)
    artifact_reuse: dict[str, str] = Field(default_factory=dict)

    @property
    def runtime_payload(self):
        return self.runtime_context.request_payload() if self.runtime_context is not None else {}

    @property
    def redaction_values(self) -> tuple[str, ...]:
        return self.runtime_context.redaction_values if self.runtime_context is not None else ()
```

- [ ] **Step 4: Add transition helpers**

Create `src/openbbq/workflow/transitions.py` with named functions:

```python
from __future__ import annotations

from datetime import UTC, datetime

from openbbq.storage.models import OutputBindings, StepRunRecord, WorkflowState
from openbbq.storage.project_store import ProjectStore


def mark_workflow_running(
    store: ProjectStore,
    *,
    workflow_id: str,
    workflow_name: str,
    current_step_id: str | None,
    config_hash: str,
    step_run_ids: tuple[str, ...],
) -> WorkflowState:
    return store.write_workflow_state(
        workflow_id,
        {
            "name": workflow_name,
            "status": "running",
            "current_step_id": current_step_id,
            "config_hash": config_hash,
            "step_run_ids": list(step_run_ids),
        },
    )


def mark_step_run_started(
    store: ProjectStore,
    *,
    workflow_id: str,
    step_id: str,
    attempt: int,
) -> StepRunRecord:
    return store.write_step_run(
        workflow_id,
        {
            "step_id": step_id,
            "attempt": attempt,
            "status": "running",
            "input_artifact_version_ids": {},
            "output_bindings": {},
            "started_at": _timestamp(),
        },
    )


def mark_step_run_completed(
    store: ProjectStore,
    *,
    workflow_id: str,
    step_run: StepRunRecord,
    input_artifact_version_ids: dict[str, str],
    output_bindings: OutputBindings,
) -> StepRunRecord:
    return store.write_step_run(
        workflow_id,
        {
            **step_run.model_dump(mode="json"),
            "status": "completed",
            "input_artifact_version_ids": input_artifact_version_ids,
            "output_bindings": output_bindings,
            "completed_at": _timestamp(),
        },
    )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()
```

- [ ] **Step 5: Move one-step execution into `workflow.steps`**

Create `src/openbbq/workflow/steps.py` with an `execute_step_attempt()` function that accepts:

```python
def execute_step_attempt(
    context: ExecutionContext,
    *,
    step: StepConfig,
    attempt: int,
) -> StepAttemptResult:
```

Add `StepAttemptResult`:

```python
class StepAttemptResult(OpenBBQModel):
    step_run: StepRunRecord
    output_bindings: OutputBindings
    input_artifact_version_ids: dict[str, str]
    response: PluginResponse
```

Move request construction, `execute_plugin_tool()`, response validation, and `persist_step_outputs()` from `execute_steps()` into this function.

- [ ] **Step 6: Move the run loop into `workflow.runner`**

Create `src/openbbq/workflow/runner.py` with:

```python
def run_steps(
    context: ExecutionContext,
    *,
    start_index: int,
    end_index: int | None = None,
    skip_pause_before_step_id: str | None = None,
) -> ExecutionResult:
```

Move pause-before, retry, skip, pause-after, abort checkpoints, and completion handling from `execute_steps()` into `run_steps()`. Keep event messages identical where tests assert them.

- [ ] **Step 7: Make `workflow.execution` a compatibility wrapper during the split**

In `src/openbbq/workflow/execution.py`, keep public functions:

- `execute_workflow_from_start`;
- `execute_workflow_from_resume`;
- `execute_workflow_step`;
- `ExecutionResult`.

Each public function should construct `ExecutionContext` and call `run_steps()`. Delete the old loop after wrapper tests pass.

- [ ] **Step 8: Run execution suites**

Run:

```bash
uv run pytest tests/test_workflow_transitions.py tests/test_engine_run_text.py tests/test_engine_error_policy.py tests/test_engine_pause_resume.py tests/test_engine_abort.py tests/test_engine_rerun.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit execution split**

Run:

```bash
git add src/openbbq/workflow tests/test_workflow_transitions.py tests/test_engine_run_text.py tests/test_engine_error_policy.py tests/test_engine_pause_resume.py tests/test_engine_abort.py tests/test_engine_rerun.py
git commit -m "refactor: Split workflow execution boundaries"
```

## Task 5: Split Storage And Add Artifact Version Index

**Files:**

- Create: `src/openbbq/storage/json_files.py`
- Create: `src/openbbq/storage/events.py`
- Create: `src/openbbq/storage/artifacts.py`
- Create: `src/openbbq/storage/workflows.py`
- Modify: `src/openbbq/storage/project_store.py`
- Modify: `tests/test_storage.py`
- Modify: `tests/test_file_backed_artifacts.py`
- Modify: `tests/test_artifact_import.py`
- Modify: `tests/test_artifact_diff.py`

- [ ] **Step 1: Add artifact index tests**

Append to `tests/test_storage.py`:

```python
def test_artifact_version_index_supports_direct_lookup(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    artifact, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo", "step_id": "seed"},
    )

    index_path = tmp_path / ".openbbq" / "artifacts" / "index.json"
    assert index_path.exists()
    assert store.read_artifact_version(version.id).record.artifact_id == artifact.id


def test_artifact_index_can_be_rebuilt_from_artifact_records(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    artifact, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo", "step_id": "seed"},
    )
    index_path = tmp_path / ".openbbq" / "artifacts" / "index.json"
    index_path.unlink()

    rebuilt = store.rebuild_artifact_index()

    assert rebuilt.version_paths[version.id].endswith(f"1-{version.id}")
    assert store.read_artifact(artifact.id).id == artifact.id
```

- [ ] **Step 2: Run the failing index tests**

Run:

```bash
uv run pytest tests/test_storage.py::test_artifact_version_index_supports_direct_lookup tests/test_storage.py::test_artifact_index_can_be_rebuilt_from_artifact_records -q
```

Expected: FAIL because the artifact index and rebuild method do not exist.

- [ ] **Step 3: Add JSON file primitives**

Create `src/openbbq/storage/json_files.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from openbbq.domain.base import JsonObject, dump_jsonable


def write_json_atomic(path: Path, data: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dump_jsonable(data), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, prefix=f".{path.name}.", suffix=".tmp") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    temp_path.replace(path)
    fsync_parent(path.parent)


def read_json_object(path: Path) -> JsonObject:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return raw


def fsync_parent(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
```

- [ ] **Step 4: Add artifact index model and writer**

In `src/openbbq/storage/artifacts.py`, define:

```python
from __future__ import annotations

from pathlib import Path

from pydantic import Field

from openbbq.domain.base import OpenBBQModel
from openbbq.storage.json_files import read_json_object, write_json_atomic


class ArtifactIndex(OpenBBQModel):
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    version_paths: dict[str, str] = Field(default_factory=dict)


def index_path(artifacts_root: Path) -> Path:
    return artifacts_root / "index.json"


def read_artifact_index(artifacts_root: Path) -> ArtifactIndex:
    path = index_path(artifacts_root)
    if not path.exists():
        return ArtifactIndex()
    return ArtifactIndex.model_validate(read_json_object(path))


def write_artifact_index(artifacts_root: Path, index: ArtifactIndex) -> None:
    write_json_atomic(index_path(artifacts_root), index.model_dump(mode="json"))
```

- [ ] **Step 5: Update `ProjectStore` to write and use the index**

After writing a new version in `write_artifact_version()`, update:

```python
index = read_artifact_index(self.artifacts_root)
index = index.model_copy(
    update={
        "artifact_paths": {
            **index.artifact_paths,
            artifact["id"]: str(self._artifact_dir(artifact["id"])),
        },
        "version_paths": {
            **index.version_paths,
            version_id: str(version_dir),
        },
    }
)
write_artifact_index(self.artifacts_root, index)
```

In `read_artifact_version()`, first use the index:

```python
index = read_artifact_index(self.artifacts_root)
indexed_path = index.version_paths.get(version_id)
if indexed_path is not None:
    version_path = Path(indexed_path)
else:
    version_path = self._find_version_path(version_id)
```

Add:

```python
def rebuild_artifact_index(self) -> ArtifactIndex:
    artifact_paths: dict[str, str] = {}
    version_paths: dict[str, str] = {}
    for artifact_dir in sorted(self.artifacts_root.iterdir(), key=lambda path: path.name):
        artifact_file = artifact_dir / "artifact.json"
        if not artifact_file.exists():
            continue
        artifact = ArtifactRecord.model_validate(json.loads(artifact_file.read_text(encoding="utf-8")))
        artifact_paths[artifact.id] = str(artifact_dir)
        versions_dir = artifact_dir / "versions"
        if versions_dir.exists():
            for version_dir in sorted(versions_dir.iterdir(), key=lambda path: path.name):
                version_file = version_dir / "version.json"
                if not version_file.exists():
                    continue
                record = ArtifactVersionRecord.model_validate(json.loads(version_file.read_text(encoding="utf-8")))
                version_paths[record.id] = str(version_dir)
    index = ArtifactIndex(artifact_paths=artifact_paths, version_paths=version_paths)
    write_artifact_index(self.artifacts_root, index)
    return index
```

- [ ] **Step 6: Split storage modules without changing public behavior**

Move code from `ProjectStore` into helper modules while keeping `ProjectStore` as a facade for existing callers. The facade should delegate:

- JSON primitives to `storage.json_files`;
- event reads and appends to `storage.events`;
- artifact reads, writes, content, and index to `storage.artifacts`;
- workflow state, step runs, locks, and abort request paths to `storage.workflows`.

Keep method names on `ProjectStore` until application services are migrated.

- [ ] **Step 7: Run storage and artifact suites**

Run:

```bash
uv run pytest tests/test_storage.py tests/test_file_backed_artifacts.py tests/test_artifact_import.py tests/test_artifact_diff.py tests/test_engine_rerun.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit storage split**

Run:

```bash
git add src/openbbq/storage tests/test_storage.py tests/test_file_backed_artifacts.py tests/test_artifact_import.py tests/test_artifact_diff.py tests/test_engine_rerun.py
git commit -m "refactor: Split storage and index artifacts"
```

## Task 6: Introduce Application Services And Slim The CLI

**Files:**

- Create: files under `src/openbbq/application/`
- Modify: `src/openbbq/cli/app.py`
- Modify: `src/openbbq/cli/quickstart.py`
- Modify: `tests/test_cli_integration.py`
- Modify: `tests/test_cli_quickstart.py`
- Modify: `tests/test_runtime_cli.py`
- Create: `tests/test_application_workflows.py`
- Create: `tests/test_application_artifacts.py`

- [ ] **Step 1: Add workflow service tests independent of CLI**

Create `tests/test_application_workflows.py`:

```python
from pathlib import Path

from openbbq.application.workflows import WorkflowRunRequest, run_workflow_command, workflow_status


def write_project(tmp_path, fixture_name: str) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path(f"tests/fixtures/projects/{fixture_name}/openbbq.yaml").read_text(encoding="utf-8")
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )
    return project


def test_workflow_application_service_runs_and_reports_status(tmp_path):
    project = write_project(tmp_path, "text-basic")

    result = run_workflow_command(
        WorkflowRunRequest(project_root=project, workflow_id="text-demo")
    )
    status = workflow_status(project_root=project, workflow_id="text-demo")

    assert result.status == "completed"
    assert status.status == "completed"
```

- [ ] **Step 2: Run the failing application workflow test**

Run:

```bash
uv run pytest tests/test_application_workflows.py -q
```

Expected: FAIL because `openbbq.application.workflows` does not exist.

- [ ] **Step 3: Add workflow application service models and functions**

Create `src/openbbq/application/workflows.py`:

```python
from __future__ import annotations

from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.domain.base import OpenBBQModel
from openbbq.engine.service import abort_workflow, resume_workflow, run_workflow, unlock_workflow
from openbbq.engine.validation import validate_workflow
from openbbq.plugins.registry import discover_plugins
from openbbq.runtime.context import build_runtime_context
from openbbq.runtime.settings import load_runtime_settings
from openbbq.storage.models import WorkflowState
from openbbq.storage.project_store import ProjectStore
from openbbq.workflow.state import read_effective_workflow_state


class WorkflowRunRequest(OpenBBQModel):
    project_root: Path
    workflow_id: str
    config_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    force: bool = False
    step_id: str | None = None


def run_workflow_command(request: WorkflowRunRequest):
    config = load_project_config(
        request.project_root,
        config_path=request.config_path,
        extra_plugin_paths=request.plugin_paths,
    )
    registry = discover_plugins(config.plugin_paths)
    return run_workflow(
        config,
        registry,
        request.workflow_id,
        force=request.force,
        step_id=request.step_id,
        runtime_context=build_runtime_context(load_runtime_settings()),
    )


def workflow_status(*, project_root: Path, workflow_id: str, config_path: Path | None = None) -> WorkflowState:
    config = load_project_config(project_root, config_path=config_path)
    workflow = config.workflows[workflow_id]
    store = ProjectStore(config.storage.root, artifacts_root=config.storage.artifacts, state_root=config.storage.state)
    return read_effective_workflow_state(store, workflow)
```

- [ ] **Step 4: Add artifact service tests**

Create `tests/test_application_artifacts.py`:

```python
from pathlib import Path

from openbbq.application.artifacts import ArtifactImportRequest, import_artifact, list_artifacts


def test_artifact_application_service_imports_file_backed_artifact(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "openbbq.yaml").write_text(
        "version: 1\n\nproject:\n  name: Demo\n\nworkflows:\n  demo:\n    name: Demo\n    steps:\n      - id: seed\n        name: Seed\n        tool_ref: mock_text.echo\n        outputs:\n          - name: text\n            type: text\n",
        encoding="utf-8",
    )
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"media")

    imported = import_artifact(
        ArtifactImportRequest(
            project_root=project,
            path=source,
            artifact_type="video",
            name="source.video",
        )
    )
    artifacts = list_artifacts(project_root=project)

    assert imported.artifact.name == "source.video"
    assert [artifact.name for artifact in artifacts] == ["source.video"]
```

- [ ] **Step 5: Move artifact operations into `application.artifacts`**

Create `src/openbbq/application/artifacts.py`:

```python
from __future__ import annotations

from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.domain.base import OpenBBQModel
from openbbq.domain.models import ARTIFACT_TYPES
from openbbq.errors import ValidationError
from openbbq.storage.models import ArtifactRecord, StoredArtifact, StoredArtifactVersion
from openbbq.storage.project_store import ProjectStore

FILE_BACKED_IMPORT_TYPES = frozenset({"audio", "image", "video"})


class ArtifactImportRequest(OpenBBQModel):
    project_root: Path
    path: Path
    artifact_type: str
    name: str
    config_path: Path | None = None


class ArtifactImportResult(OpenBBQModel):
    artifact: ArtifactRecord
    version: StoredArtifactVersion


def import_artifact(request: ArtifactImportRequest) -> ArtifactImportResult:
    source = request.path.expanduser().resolve()
    if not source.is_file():
        raise ValidationError(f"Artifact import source is not a file: {source}")
    if request.artifact_type not in ARTIFACT_TYPES:
        raise ValidationError(f"Artifact type '{request.artifact_type}' is not registered.")
    if request.artifact_type not in FILE_BACKED_IMPORT_TYPES:
        allowed = ", ".join(sorted(FILE_BACKED_IMPORT_TYPES))
        raise ValidationError(f"Artifact import supports file-backed artifact types only: {allowed}.")
    config = load_project_config(request.project_root, config_path=request.config_path)
    artifact, version = _store(config).write_artifact_version(
        artifact_type=request.artifact_type,
        name=request.name,
        content=None,
        file_path=source,
        metadata={},
        created_by_step_id=None,
        lineage={"source": "cli_import", "original_path": str(source)},
    )
    return ArtifactImportResult(artifact=artifact.record, version=version)


def list_artifacts(*, project_root: Path, config_path: Path | None = None) -> list[ArtifactRecord]:
    config = load_project_config(project_root, config_path=config_path)
    return _store(config).list_artifacts()


def _store(config) -> ProjectStore:
    return ProjectStore(config.storage.root, artifacts_root=config.storage.artifacts, state_root=config.storage.state)
```

- [ ] **Step 6: Update CLI handlers to call application services**

In `src/openbbq/cli/app.py`, replace direct orchestration in `_run()`:

```python
result = run_workflow_command(
    WorkflowRunRequest(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
        workflow_id=args.workflow,
        force=args.force,
        step_id=args.step,
    )
)
```

Replace `_artifact_import()` direct store access with:

```python
result = import_artifact(
    ArtifactImportRequest(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        path=Path(args.path),
        artifact_type=args.artifact_type,
        name=args.name,
    )
)
payload = {"ok": True, "artifact": result.artifact, "version": result.version.record}
```

Move the remaining handlers by adding these service functions and replacing direct CLI orchestration with calls to them:

- `application.workflows.resume_workflow_command()`
- `application.workflows.abort_workflow_command()`
- `application.workflows.unlock_workflow_command()`
- `application.workflows.workflow_logs()`
- `application.artifacts.show_artifact()`
- `application.artifacts.diff_artifact_versions()`
- `application.plugins.list_plugins()`
- `application.plugins.plugin_info()`
- `application.runtime.show_runtime_settings()`
- `application.runtime.set_provider_profile()`
- `application.auth.set_provider_auth()`
- `application.auth.check_provider_auth()`
- `application.diagnostics.run_doctor()`
- `application.workflows.run_generated_youtube_subtitle_workflow()`

- [ ] **Step 7: Run application and CLI tests**

Run:

```bash
uv run pytest tests/test_application_workflows.py tests/test_application_artifacts.py tests/test_cli_integration.py tests/test_cli_quickstart.py tests/test_runtime_cli.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit application service layer**

Run:

```bash
git add src/openbbq/application src/openbbq/cli tests/test_application_workflows.py tests/test_application_artifacts.py tests/test_cli_integration.py tests/test_cli_quickstart.py tests/test_runtime_cli.py
git commit -m "refactor: Add application service layer"
```

## Task 7: Modularize Translation And Transcript Built-In Plugins

**Files:**

- Create: translation and transcript module files listed in File Structure.
- Modify: `src/openbbq/builtin_plugins/translation/plugin.py`
- Modify: `src/openbbq/builtin_plugins/transcript/plugin.py`
- Modify: `tests/test_builtin_plugins.py`
- Modify: `tests/test_phase2_asr_correction_segmentation.py`
- Modify: `tests/test_phase2_translation_slice.py`
- Modify: `tests/test_phase2_contract_regressions.py`

- [ ] **Step 1: Add dispatch tests for slim plugin entrypoints**

Append to `tests/test_phase2_contract_regressions.py`:

```python
def test_translation_plugin_entrypoint_dispatches_to_translate_module(monkeypatch):
    calls = []

    def fake_translate(request, client_factory=None):
        calls.append(request["tool_name"])
        return {"outputs": {"translation": {"type": "translation", "content": [], "metadata": {}}}}

    monkeypatch.setattr(translation_plugin, "run_translate", fake_translate)

    response = translation_plugin.run({"tool_name": "translate", "parameters": {}, "inputs": {}})

    assert calls == ["translate"]
    assert response["outputs"]["translation"]["type"] == "translation"


def test_transcript_plugin_entrypoint_dispatches_to_segment_module(monkeypatch):
    calls = []

    def fake_segment(request):
        calls.append(request["tool_name"])
        return {"outputs": {"subtitle_segments": {"type": "subtitle_segments", "content": [], "metadata": {}}}}

    monkeypatch.setattr(transcript_plugin, "run_segment", fake_segment)

    response = transcript_plugin.run({"tool_name": "segment", "parameters": {}, "inputs": {}})

    assert calls == ["segment"]
    assert response["outputs"]["subtitle_segments"]["type"] == "subtitle_segments"
```

- [ ] **Step 2: Run failing dispatch tests**

Run:

```bash
uv run pytest tests/test_phase2_contract_regressions.py::test_translation_plugin_entrypoint_dispatches_to_translate_module tests/test_phase2_contract_regressions.py::test_transcript_plugin_entrypoint_dispatches_to_segment_module -q
```

Expected: FAIL because the named dispatch functions do not exist.

- [ ] **Step 3: Split translation plugin modules**

Move translation behavior into:

- `translation/translate.py`: `run_translate(request: dict, client_factory=None) -> dict`
- `translation/qa.py`: `run_qa(request: dict) -> dict`
- `translation/llm_json.py`: `_default_client_factory`, chunk splitting, completion extraction, and JSON array parsing helpers.
- `translation/models.py`: typed models for timed segments, translation items, QA issues, and translation parameters.

Update `translation/plugin.py` to:

```python
from __future__ import annotations

from openbbq.builtin_plugins.translation.qa import run_qa
from openbbq.builtin_plugins.translation.translate import run_translate


def run(request: dict, client_factory=None) -> dict:
    tool_name = request.get("tool_name")
    if tool_name == "translate":
        return run_translate(request, client_factory=client_factory)
    if tool_name == "qa":
        return run_qa(request)
    raise ValueError(f"Unsupported tool: {tool_name}")
```

- [ ] **Step 4: Split transcript plugin modules**

Move transcript behavior into:

- `transcript/correct.py`: `run_correct(request: dict, client_factory=None) -> dict`
- `transcript/segment.py`: `run_segment(request: dict) -> dict`
- `transcript/llm_json.py`: client factory, completion extraction, JSON array parsing helpers.
- `transcript/models.py`: typed transcript segment, word, correction item, and segmentation parameter models.

Update `transcript/plugin.py` to:

```python
from __future__ import annotations

from openbbq.builtin_plugins.transcript.correct import run_correct
from openbbq.builtin_plugins.transcript.segment import run_segment


def run(request: dict, client_factory=None) -> dict:
    tool_name = request.get("tool_name")
    if tool_name == "correct":
        return run_correct(request, client_factory=client_factory)
    if tool_name == "segment":
        return run_segment(request)
    raise ValueError(f"Unsupported tool: {tool_name}")
```

- [ ] **Step 5: Add typed parameter tests**

Append to `tests/test_builtin_plugins.py`:

```python
def test_translation_parameters_reject_empty_target_lang():
    from openbbq.builtin_plugins.translation.models import TranslationParameters

    with pytest.raises(ValueError, match="target_lang"):
        TranslationParameters(source_lang="en", target_lang="", model="gpt-4o-mini")


def test_segmentation_parameters_reject_zero_max_lines():
    from openbbq.builtin_plugins.transcript.models import SegmentationParameters

    with pytest.raises(ValueError, match="max_lines"):
        SegmentationParameters(max_lines=0)
```

Define the models so these tests pass:

```python
class TranslationParameters(OpenBBQModel):
    source_lang: str
    target_lang: str
    model: str | None = None
    temperature: float = 0


class SegmentationParameters(OpenBBQModel):
    max_duration_seconds: float = 6.0
    min_duration_seconds: float = 0.8
    max_lines: int = Field(default=2, ge=1)
    max_chars_per_line: int = Field(default=40, ge=1)
    max_chars_per_second: float = Field(default=20.0, gt=0)
    pause_threshold_ms: int = Field(default=500, ge=0)
    prefer_sentence_boundaries: bool = True
```

- [ ] **Step 6: Run built-in plugin tests**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py tests/test_phase2_asr_correction_segmentation.py tests/test_phase2_translation_slice.py tests/test_phase2_contract_regressions.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit plugin modularization**

Run:

```bash
git add src/openbbq/builtin_plugins/translation src/openbbq/builtin_plugins/transcript tests/test_builtin_plugins.py tests/test_phase2_asr_correction_segmentation.py tests/test_phase2_translation_slice.py tests/test_phase2_contract_regressions.py
git commit -m "refactor: Modularize built-in language plugins"
```

## Task 8: Remove Compatibility Paths And Align Documentation

**Files:**

- Delete: `src/openbbq/builtin_plugins/llm/`
- Modify: `pyproject.toml`
- Modify: `src/openbbq/runtime/provider.py`
- Modify: `src/openbbq/runtime/doctor.py`
- Modify: `src/openbbq/workflow_templates/youtube_subtitle/openbbq.yaml`
- Modify: fixture workflow YAML files that use `llm.translate`.
- Modify: `docs/Target-Workflows.md`
- Modify: `docs/phase1/Plugin-System.md`
- Modify: `README.md`
- Modify: tests referencing legacy provider fallback or `llm.translate`.

- [ ] **Step 1: Write failing tests for named-provider-only LLM resolution**

Replace the legacy fallback test in `tests/test_runtime_context.py` with:

```python
def test_llm_provider_from_request_requires_named_provider_runtime_context(monkeypatch):
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-env")

    with pytest.raises(ValueError, match="provider 'openai' is not configured"):
        llm_provider_from_request(
            {
                "parameters": {"provider": "openai"},
                "runtime": {"providers": {}},
            },
            error_prefix="translation.translate",
        )
```

- [ ] **Step 2: Run the failing provider test**

Run:

```bash
uv run pytest tests/test_runtime_context.py::test_llm_provider_from_request_requires_named_provider_runtime_context -q
```

Expected: FAIL until `llm_provider_from_request()` stops falling back to process environment variables.

- [ ] **Step 3: Remove legacy provider fallback**

In `src/openbbq/runtime/provider.py`, replace `llm_provider_from_request()` with:

```python
def llm_provider_from_request(request: JsonObject, *, error_prefix: str) -> LlmProviderCredentials:
    parameters = request.get("parameters", {})
    provider_name = parameters.get("provider")
    if not isinstance(provider_name, str) or not provider_name.strip():
        raise ValueError(f"{error_prefix} parameter 'provider' must name a runtime provider.")
    runtime = request.get("runtime", {})
    providers = runtime.get("providers", {}) if isinstance(runtime, dict) else {}
    provider = providers.get(provider_name)
    if not isinstance(provider, dict):
        raise ValueError(f"{error_prefix} provider '{provider_name}' is not configured.")
    provider_type = provider.get("type")
    if provider_type != "openai_compatible":
        raise ValueError(f"{error_prefix} provider '{provider_name}' must be openai_compatible.")
    api_key = provider.get("api_key")
    if not isinstance(api_key, str) or not api_key:
        raise RuntimeError(f"{error_prefix} provider '{provider_name}' API key is not resolved.")
    base_url = provider.get("base_url")
    model_default = provider.get("default_chat_model")
    return LlmProviderCredentials(
        name=provider_name,
        type="openai_compatible",
        api_key=api_key,
        base_url=base_url if isinstance(base_url, str) and base_url else None,
        model_default=model_default if isinstance(model_default, str) and model_default else None,
    )
```

- [ ] **Step 4: Remove `llm.translate` alias**

Delete:

```text
src/openbbq/builtin_plugins/llm/
```

Remove `llm` from the expected built-in manifest set in `tests/test_package_layout.py`.

Update workflows that use:

```yaml
tool_ref: llm.translate
```

to:

```yaml
tool_ref: translation.translate
```

When the input is `asr_transcript`, insert or use a `transcript.segment` step before translation so `translation.translate` receives `subtitle_segments`.

- [ ] **Step 5: Remove manifest v1 compatibility fields**

In `src/openbbq/plugins/registry.py`, remove support for required `input_artifact_types` and `output_artifact_types` fields. `ToolSpec` should derive input and output type lists from v2 `inputs` and `outputs` only if callers still need allowlist helpers.

Update tests so invalid manifests fail when v2 `outputs` are missing.

- [ ] **Step 6: Update documentation**

Change docs to say:

- plugin manifests use `manifest_version = 2`;
- tools declare named `inputs` and `outputs`;
- LLM-backed tools require named runtime providers;
- `llm.translate` is removed;
- `OPENBBQ_LLM_API_KEY` is only usable through an explicit runtime setting such as `api_key = "env:OPENBBQ_LLM_API_KEY"`;
- CLI remains supported but is now an adapter over application services.

- [ ] **Step 7: Run compatibility-removal tests**

Run:

```bash
uv run pytest tests/test_runtime_context.py tests/test_runtime_doctor.py tests/test_package_layout.py tests/test_phase2_translation_slice.py tests/test_phase2_contract_regressions.py tests/test_cli_quickstart.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit compatibility removal**

Run:

```bash
git add -A src/openbbq tests docs README.md pyproject.toml
git commit -m "chore: Remove legacy backend compatibility paths"
```

## Task 9: Final Verification And Backend Hardening Acceptance

**Files:**

- Modify: `docs/Roadmap.md`
- Modify: `docs/Architecture.md`
- Modify: `README.md`
- Modify: `AGENTS.md` if development commands or behavior changed.

- [ ] **Step 1: Update high-level docs**

Ensure docs state:

- backend has a typed application service layer;
- plugin contract v2 is the current manifest contract;
- desktop should call application services or future API wrappers, not CLI internals;
- legacy `llm.translate` and implicit LLM env fallback are removed;
- workflow events include `level` and `data`.

- [ ] **Step 2: Run full lint**

Run:

```bash
uv run ruff check .
```

Expected: PASS with `All checks passed!`.

- [ ] **Step 3: Run full test suite**

Run:

```bash
uv run pytest
```

Expected: PASS with all non-skipped tests passing.

- [ ] **Step 4: Run representative CLI smoke commands**

Run:

```bash
uv run openbbq --json validate text-demo --project tests/fixtures/projects/text-basic
uv run openbbq --json plugin list --project tests/fixtures/projects/text-basic
uv run openbbq --json doctor --workflow local-video-corrected-translate-subtitle --project tests/fixtures/projects/local-video-corrected-translate-subtitle
```

Expected:

- validate returns `{"ok": true, "workflow_id": "text-demo"}`;
- plugin list returns `mock_text` and built-in plugins;
- doctor returns a JSON envelope with check objects and no traceback.

- [ ] **Step 5: Commit documentation and acceptance updates**

Run:

```bash
git add docs README.md AGENTS.md
git commit -m "docs: Document hardened backend contracts"
```

## Self-Review Checklist

- Spec coverage: tasks cover event contracts, plugin response events, manifest v2, execution split, storage split, application services, plugin modularization, compatibility removal, docs, and verification.
- Placeholder scan: this plan contains concrete files, commands, expected outputs, and code snippets for each task.
- Type consistency: planned names are consistent across tasks: `PluginEventPayload`, `WorkflowEvent.level`, `WorkflowEvent.data`, `ExecutionContext`, `StepAttemptResult`, `ArtifactIndex`, `WorkflowRunRequest`, and `ArtifactImportRequest`.
- Risk control: every task has a focused test command and commit step before the next slice.

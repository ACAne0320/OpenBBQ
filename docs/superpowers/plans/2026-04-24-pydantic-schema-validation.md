# Pydantic Schema Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace OpenBBQ's core dataclass and loose payload contracts with Pydantic v2 `BaseModel` schemas while preserving existing CLI behavior and file formats.

**Architecture:** Add a shared Pydantic base and named JSON aliases, then migrate domain, runtime, plugin registry, storage, workflow state, and plugin payload contracts in bounded slices. Keep JSON Schema for plugin tool parameters and keep context-dependent validation in service modules.

**Tech Stack:** Python 3.11, Pydantic v2, PyYAML, TOML via `tomllib`, `jsonschema`, pytest, Ruff.

---

## Scope Check

The approved spec is one coordinated backend contract migration. It crosses several modules, but the modules all depend on the same model contract change, so it should stay as one plan with frequent commits after each green slice.

## File Structure

Create these files:

- `src/openbbq/domain/base.py`: shared `OpenBBQModel`, JSON aliases, and Pydantic error formatting.
- `src/openbbq/storage/models.py`: persisted artifact, workflow state, step run, event, and output binding models.
- `src/openbbq/plugins/payloads.py`: plugin request and response boundary models.

Modify these files:

- `pyproject.toml`: add Pydantic runtime dependency.
- `src/openbbq/domain/models.py`: migrate project, workflow, step, and output models to Pydantic.
- `src/openbbq/config/loader.py`: construct and normalize Pydantic models while preserving cross-step validation.
- `src/openbbq/runtime/models.py`: migrate runtime models to Pydantic.
- `src/openbbq/runtime/settings.py`: validate runtime TOML through runtime Pydantic models.
- `src/openbbq/plugins/registry.py`: migrate plugin registry models and manifest parsing to Pydantic.
- `src/openbbq/storage/project_store.py`: return and accept storage models at public boundaries.
- `src/openbbq/workflow/state.py`: use `model_dump(mode="json")` for config hashing and workflow state helpers.
- `src/openbbq/workflow/bindings.py`: build typed plugin input payloads and validate plugin output payloads.
- `src/openbbq/workflow/execution.py`: build typed plugin requests and consume typed output bindings.
- `src/openbbq/workflow/rerun.py`: consume `StepRunRecord` and `OutputBinding` models.
- `src/openbbq/workflow/aborts.py`: use a typed abort request payload.
- `src/openbbq/workflow/locks.py`: migrate lock info to Pydantic.
- `src/openbbq/engine/service.py`: use `WorkflowState` and typed result models.
- `src/openbbq/engine/validation.py`: migrate validation result to Pydantic and use named aliases.
- `src/openbbq/cli/quickstart.py`: migrate `GeneratedWorkflow` to Pydantic.
- `src/openbbq/cli/app.py`: dump models at CLI output boundaries.
- Tests under `tests/`: update model expectations and add focused validation coverage.

Keep these files conceptually unchanged:

- Built-in plugin TOML manifests keep JSON Schema parameter declarations.
- Built-in plugin functions still receive plain JSON-like request dictionaries for compatibility.

## Task 1: Add Pydantic Dependency And Shared Base

**Files:**

- Modify: `pyproject.toml`
- Create: `src/openbbq/domain/base.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for the shared Pydantic base**

Replace `tests/test_models.py` with this content:

```python
import pytest
from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import OpenBBQModel, format_pydantic_error
from openbbq.domain import models


class ExampleModel(OpenBBQModel):
    name: str


def test_openbbq_model_is_frozen_and_forbids_extra_fields():
    value = ExampleModel(name="demo")

    with pytest.raises(PydanticValidationError):
        value.name = "changed"

    with pytest.raises(PydanticValidationError):
        ExampleModel(name="demo", extra=True)


def test_format_pydantic_error_includes_entity_and_field_path():
    with pytest.raises(PydanticValidationError) as exc:
        ExampleModel()

    assert format_pydantic_error("example", exc.value) == "example.name: Field required"


def test_domain_models_exports_artifact_type_registry():
    assert {
        "text",
        "video",
        "audio",
        "image",
        "asr_transcript",
        "subtitle_segments",
        "glossary",
        "translation",
        "translation_qa",
        "subtitle",
    }.issubset(models.ARTIFACT_TYPES)
```

- [ ] **Step 2: Run the model test and verify it fails**

Run:

```powershell
uv run pytest tests/test_models.py -q
```

Expected: FAIL because `openbbq.domain.base` does not exist and domain models are still dataclasses.

- [ ] **Step 3: Add Pydantic to runtime dependencies**

In `pyproject.toml`, change:

```toml
dependencies = ["PyYAML>=6.0", "jsonschema>=4.0"]
```

to:

```toml
dependencies = ["PyYAML>=6.0", "jsonschema>=4.0", "pydantic>=2.0"]
```

- [ ] **Step 4: Create the shared base module**

Create `src/openbbq/domain/base.py` with this content:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list[Any] | dict[str, Any]
JsonObject: TypeAlias = dict[str, JsonValue]
PluginParameters: TypeAlias = JsonObject
PluginInputs: TypeAlias = JsonObject
ArtifactMetadata: TypeAlias = JsonObject
LineagePayload: TypeAlias = JsonObject


class OpenBBQModel(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )


def model_payload(value: OpenBBQModel) -> dict[str, Any]:
    return value.model_dump(mode="json")


def format_pydantic_error(entity: str, error: PydanticValidationError) -> str:
    first = error.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "__root__")
    message = str(first.get("msg", "invalid value"))
    if location:
        return f"{entity}.{location}: {message}"
    return f"{entity}: {message}"


def dump_jsonable(value: Any) -> Any:
    if isinstance(value, OpenBBQModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): dump_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [dump_jsonable(item) for item in value]
    return value
```

- [ ] **Step 5: Run the focused test**

Run:

```powershell
uv run pytest tests/test_models.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the dependency and base module**

Run:

```powershell
git add pyproject.toml src/openbbq/domain/base.py tests/test_models.py
git commit -m "feat: Add Pydantic model base"
```

The committed test file must pass at this point.

## Task 2: Migrate Domain Models And Project Config Loading

**Files:**

- Modify: `src/openbbq/domain/models.py`
- Modify: `src/openbbq/config/loader.py`
- Modify: `src/openbbq/workflow/state.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_workflow_state.py`

- [ ] **Step 1: Add focused tests for strict domain validation**

Append these tests to `tests/test_models.py`:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError


def test_domain_models_export_pydantic_models():
    exported_names = {
        "ProjectMetadata",
        "StorageConfig",
        "PluginConfig",
        "StepOutput",
        "StepConfig",
        "WorkflowConfig",
        "ProjectConfig",
    }

    for name in exported_names:
        exported = getattr(models, name)

        assert issubclass(exported, OpenBBQModel)


def test_domain_models_dump_paths_as_strings():
    storage = models.StorageConfig(
        root=Path(".openbbq"),
        artifacts=Path(".openbbq/artifacts"),
        state=Path(".openbbq/state"),
    )

    assert storage.model_dump(mode="json") == {
        "root": ".openbbq",
        "artifacts": ".openbbq/artifacts",
        "state": ".openbbq/state",
    }


def test_step_config_rejects_bool_max_retries():
    with pytest.raises(PydanticValidationError) as exc:
        models.StepConfig(
            id="seed",
            name="Seed",
            tool_ref="mock_text.echo",
            outputs=(models.StepOutput(name="text", type="text"),),
            max_retries=True,
        )

    assert "max_retries" in str(exc.value)


def test_step_config_rejects_duplicate_output_names():
    with pytest.raises(PydanticValidationError) as exc:
        models.StepConfig(
            id="seed",
            name="Seed",
            tool_ref="mock_text.echo",
            outputs=(
                models.StepOutput(name="text", type="text"),
                models.StepOutput(name="text", type="text"),
            ),
        )

    assert "Duplicate output name" in str(exc.value)


def test_project_config_rejects_non_one_version(tmp_path):
    with pytest.raises(PydanticValidationError) as exc:
        models.ProjectConfig(
            version=2,
            root_path=tmp_path,
            config_path=tmp_path / "openbbq.yaml",
            project=models.ProjectMetadata(name="Demo"),
            storage=models.StorageConfig(
                root=tmp_path / ".openbbq",
                artifacts=tmp_path / ".openbbq" / "artifacts",
                state=tmp_path / ".openbbq" / "state",
            ),
            plugins=models.PluginConfig(),
            workflows={},
        )

    assert "version" in str(exc.value)
```

- [ ] **Step 2: Run domain and config tests and verify failures**

Run:

```powershell
uv run pytest tests/test_models.py tests/test_config.py tests/test_workflow_state.py -q
```

Expected: FAIL because `domain.models` still imports `dataclass`.

- [ ] **Step 3: Replace domain dataclasses with Pydantic models**

Replace the dataclass definitions in `src/openbbq/domain/models.py` with these model definitions:

```python
from __future__ import annotations

from pathlib import Path
import re
from typing import Literal, TypeAlias

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from openbbq.domain.base import OpenBBQModel, PluginInputs, PluginParameters

ARTIFACT_TYPES: frozenset[str] = frozenset(
    {
        "text",
        "video",
        "audio",
        "image",
        "asr_transcript",
        "subtitle_segments",
        "glossary",
        "translation",
        "translation_qa",
        "subtitle",
    }
)

IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9_-]+$")
OnErrorPolicy: TypeAlias = Literal["abort", "retry", "skip"]


class ProjectMetadata(OpenBBQModel):
    id: str | None = None
    name: str

    @field_validator("id", "name")
    @classmethod
    def nonempty_string(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class StorageConfig(OpenBBQModel):
    root: Path
    artifacts: Path
    state: Path


class PluginConfig(OpenBBQModel):
    paths: tuple[Path, ...] = ()


class StepOutput(OpenBBQModel):
    name: str
    type: str

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("type")
    @classmethod
    def registered_artifact_type(cls, value: str) -> str:
        if value not in ARTIFACT_TYPES:
            raise ValueError(f"Artifact type '{value}' is not registered")
        return value


class StepConfig(OpenBBQModel):
    id: str
    name: str
    tool_ref: str
    inputs: PluginInputs = Field(default_factory=dict)
    outputs: tuple[StepOutput, ...]
    parameters: PluginParameters = Field(default_factory=dict)
    on_error: OnErrorPolicy = "abort"
    max_retries: StrictInt = Field(default=0, ge=0)
    pause_before: StrictBool = False
    pause_after: StrictBool = False

    @field_validator("id")
    @classmethod
    def valid_step_id(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        if IDENTIFIER_PATTERN.fullmatch(value) is None:
            raise ValueError(f"Invalid step id: '{value}'")
        return value

    @field_validator("name", "tool_ref")
    @classmethod
    def nonempty_string(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("outputs")
    @classmethod
    def nonempty_unique_outputs(cls, value: tuple[StepOutput, ...]) -> tuple[StepOutput, ...]:
        if not value:
            raise ValueError("must define at least one output")
        seen: set[str] = set()
        for output in value:
            if output.name in seen:
                raise ValueError(f"Duplicate output name '{output.name}'")
            seen.add(output.name)
        return value


class WorkflowConfig(OpenBBQModel):
    id: str
    name: str
    steps: tuple[StepConfig, ...]

    @field_validator("id")
    @classmethod
    def valid_workflow_id(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        if IDENTIFIER_PATTERN.fullmatch(value) is None:
            raise ValueError(f"Invalid workflow id: '{value}'")
        return value

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("steps")
    @classmethod
    def nonempty_steps(cls, value: tuple[StepConfig, ...]) -> tuple[StepConfig, ...]:
        if not value:
            raise ValueError("must define a non-empty steps list")
        return value

    @model_validator(mode="after")
    def unique_step_ids(self) -> WorkflowConfig:
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"Duplicate step id '{step.id}'")
            seen.add(step.id)
        return self


WorkflowMap: TypeAlias = dict[str, WorkflowConfig]


class ProjectConfig(OpenBBQModel):
    version: StrictInt
    root_path: Path
    config_path: Path
    project: ProjectMetadata
    storage: StorageConfig
    plugins: PluginConfig
    workflows: WorkflowMap

    @field_validator("version")
    @classmethod
    def version_one(cls, value: int) -> int:
        if value != 1:
            raise ValueError("Project config version must be 1")
        return value

    @property
    def plugin_paths(self) -> tuple[Path, ...]:
        return self.plugins.paths
```

- [ ] **Step 4: Convert Pydantic errors in project config loading**

In `src/openbbq/config/loader.py`, import Pydantic validation error and the formatter:

```python
from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import format_pydantic_error
```

Change model construction blocks so Pydantic performs local validation, and wrap failures like this:

```python
try:
    storage = StorageConfig(root=storage_root, artifacts=artifacts_path, state=state_path)
except PydanticValidationError as exc:
    raise ValidationError(format_pydantic_error("storage", exc)) from exc
```

For each step, replace the direct `StepOutput` and `StepConfig` construction with:

```python
try:
    outputs.append(StepOutput(name=output_name, type=output_type))
except PydanticValidationError as exc:
    raise ValidationError(format_pydantic_error(f"step '{step_id}' output", exc)) from exc
```

and:

```python
try:
    step = StepConfig(
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
except PydanticValidationError as exc:
    raise ValidationError(format_pydantic_error(f"step '{step_id}'", exc)) from exc
```

For the final project model, use:

```python
try:
    return ProjectConfig(
        version=1,
        root_path=root_path,
        config_path=resolved_config_path,
        project=ProjectMetadata(id=project_id, name=project_name),
        storage=storage,
        plugins=plugins,
        workflows=workflows,
    )
except PydanticValidationError as exc:
    raise ValidationError(format_pydantic_error("project config", exc)) from exc
```

Keep `_validate_step_inputs()` in this file because it needs workflow ordering context.

- [ ] **Step 5: Replace dataclass hashing helper**

In `src/openbbq/workflow/state.py`, replace the dataclass-based `_jsonable()` helper with:

```python
from openbbq.domain.base import dump_jsonable
```

and update `compute_workflow_config_hash()` to use:

```python
payload = {
    "version": config.version,
    "workflow_id": workflow_id,
    "workflow": dump_jsonable(workflow),
    "plugin_paths": [str(path) for path in config.plugin_paths],
}
```

Remove the `dataclasses` imports and the old `_jsonable()` function.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
uv run pytest tests/test_models.py tests/test_config.py tests/test_workflow_state.py -q
```

Expected: PASS.

- [ ] **Step 7: Run Ruff on changed modules**

Run:

```powershell
uv run ruff check src/openbbq/domain/base.py src/openbbq/domain/models.py src/openbbq/config/loader.py src/openbbq/workflow/state.py tests/test_models.py tests/test_config.py tests/test_workflow_state.py
```

Expected: PASS.

- [ ] **Step 8: Commit domain migration**

Run:

```powershell
git add src/openbbq/domain/models.py src/openbbq/config/loader.py src/openbbq/workflow/state.py tests/test_models.py tests/test_config.py tests/test_workflow_state.py
git commit -m "feat: Migrate domain models to Pydantic"
```

## Task 3: Migrate Runtime Models And Settings Validation

**Files:**

- Modify: `src/openbbq/runtime/models.py`
- Modify: `src/openbbq/runtime/settings.py`
- Modify: `src/openbbq/runtime/context.py`
- Modify: `src/openbbq/runtime/provider.py`
- Modify: `src/openbbq/runtime/doctor.py`
- Modify: `src/openbbq/runtime/secrets.py`
- Modify: `tests/test_runtime_settings.py`
- Modify: `tests/test_runtime_context.py`
- Modify: `tests/test_runtime_doctor.py`
- Modify: `tests/test_runtime_secrets.py`

- [ ] **Step 1: Add runtime model behavior tests**

Append these tests to `tests/test_runtime_settings.py`:

```python
from pydantic import ValidationError as PydanticValidationError


def test_provider_profile_rejects_literal_api_key():
    with pytest.raises(PydanticValidationError) as exc:
        ProviderProfile(
            name="openai",
            type="openai_compatible",
            api_key="sk-not-allowed",
        )

    assert "api_key" in str(exc.value)


def test_runtime_settings_model_copy_preserves_provider_models(tmp_path):
    settings = RuntimeSettings(
        version=1,
        config_path=tmp_path / "config.toml",
        cache=CacheSettings(root=tmp_path / "cache"),
        providers={
            "openai": ProviderProfile(
                name="openai",
                type="openai_compatible",
                api_key="env:OPENBBQ_LLM_API_KEY",
            )
        },
    )

    copied = settings.model_copy()

    assert copied.providers["openai"].api_key == "env:OPENBBQ_LLM_API_KEY"
```

- [ ] **Step 2: Run runtime tests and verify failure**

Run:

```powershell
uv run pytest tests/test_runtime_settings.py tests/test_runtime_context.py tests/test_runtime_doctor.py tests/test_runtime_secrets.py -q
```

Expected: FAIL because runtime models are still dataclasses.

- [ ] **Step 3: Replace runtime dataclasses with Pydantic models**

In `src/openbbq/runtime/models.py`, replace dataclass imports and class decorators with `OpenBBQModel`. Use this structure:

```python
from __future__ import annotations

from pathlib import Path
import re
from typing import Literal, TypeAlias

from pydantic import Field, field_validator

from openbbq.domain.base import JsonObject, OpenBBQModel

SUPPORTED_PROVIDER_TYPES: frozenset[str] = frozenset({"openai_compatible"})
PROVIDER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
ProviderMap: TypeAlias = dict[str, "ProviderProfile"]
ResolvedProviderMap: TypeAlias = dict[str, "ResolvedProvider"]


class CacheSettings(OpenBBQModel):
    root: Path


class ProviderProfile(OpenBBQModel):
    name: str
    type: Literal["openai_compatible"]
    base_url: str | None = None
    api_key: str | None = None
    default_chat_model: str | None = None
    display_name: str | None = None

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not value or PROVIDER_NAME_PATTERN.fullmatch(value) is None:
            raise ValueError("Provider names must use only letters, digits, '_' or '-'")
        return value

    @field_validator("api_key")
    @classmethod
    def valid_secret_reference(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value.startswith("env:") and value != "env:":
            return value
        if value.startswith("keyring:"):
            payload = value.removeprefix("keyring:")
            service, separator, username = payload.partition("/")
            if separator and service and username:
                return value
        raise ValueError("must use an env: or keyring: secret reference")

    def public_dict(self) -> JsonObject:
        return self.model_dump(mode="json")
```

Continue the same pattern for the remaining classes:

```python
class FasterWhisperSettings(OpenBBQModel):
    cache_dir: Path
    default_model: str = "base"
    default_device: str = "cpu"
    default_compute_type: str = "int8"


class ModelsSettings(OpenBBQModel):
    faster_whisper: FasterWhisperSettings


class RuntimeSettings(OpenBBQModel):
    version: int
    config_path: Path
    cache: CacheSettings
    providers: ProviderMap = Field(default_factory=dict)
    models: ModelsSettings | None = None

    @field_validator("version")
    @classmethod
    def version_one(cls, value: int) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("Runtime settings version must be 1")
        return value

    def public_dict(self) -> JsonObject:
        return self.model_dump(mode="json")


class SecretCheck(OpenBBQModel):
    reference: str
    resolved: bool
    display: str
    value_preview: str | None = None
    error: str | None = None


class ResolvedProvider(OpenBBQModel):
    name: str
    type: str
    api_key: str | None
    base_url: str | None
    default_chat_model: str | None = None

    def request_payload(self) -> JsonObject:
        return self.model_dump(mode="json")


class RuntimeContext(OpenBBQModel):
    providers: ResolvedProviderMap = Field(default_factory=dict)
    cache_root: Path | None = None
    faster_whisper_cache_dir: Path | None = None
    redaction_values: tuple[str, ...] = ()

    def request_payload(self) -> JsonObject:
        return {
            "providers": {
                name: provider.request_payload()
                for name, provider in sorted(self.providers.items())
            },
            "cache": {
                "root": str(self.cache_root) if self.cache_root is not None else None,
                "faster_whisper": str(self.faster_whisper_cache_dir)
                if self.faster_whisper_cache_dir is not None
                else None,
            },
        }


class ModelAssetStatus(OpenBBQModel):
    provider: str
    model: str
    cache_dir: Path
    present: bool
    size_bytes: int = 0
    error: str | None = None

    def public_dict(self) -> JsonObject:
        return self.model_dump(mode="json")


class DoctorCheck(OpenBBQModel):
    id: str
    status: str
    severity: str
    message: str

    def public_dict(self) -> dict[str, str]:
        return self.model_dump(mode="json")
```

- [ ] **Step 4: Simplify runtime settings validation around Pydantic models**

In `src/openbbq/runtime/settings.py`, remove duplicated provider name, type, and secret validation logic from helper functions once `ProviderProfile` handles it. Keep path resolution helpers. Wrap Pydantic errors at boundaries:

```python
from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import format_pydantic_error
```

In `load_runtime_settings()`, wrap final construction:

```python
try:
    return RuntimeSettings(
        version=version,
        config_path=path,
        cache=CacheSettings(root=cache_root),
        providers=providers,
        models=ModelsSettings(faster_whisper=faster_whisper),
    )
except PydanticValidationError as exc:
    raise ValidationError(format_pydantic_error("runtime settings", exc)) from exc
```

In `_provider_profiles()`, construct providers like this:

```python
try:
    providers[name] = ProviderProfile(
        name=name,
        type=provider_type,
        base_url=_optional_string(profile_raw.get("base_url"), f"providers.{name}.base_url"),
        api_key=api_key,
        default_chat_model=_optional_string(
            profile_raw.get("default_chat_model"),
            f"providers.{name}.default_chat_model",
        ),
        display_name=_optional_string(
            profile_raw.get("display_name"), f"providers.{name}.display_name"
        ),
    )
except PydanticValidationError as exc:
    raise ValidationError(format_pydantic_error(f"providers.{name}", exc)) from exc
```

In `with_provider_profile()`, replace manual validation and object reconstruction with:

```python
providers = dict(settings.providers)
providers[provider.name] = provider
return settings.model_copy(update={"providers": providers})
```

- [ ] **Step 5: Update direct dataclass usage in runtime modules**

Search:

```powershell
rg -n "dataclass|field\\(" src/openbbq/runtime
```

Expected after edits: no `dataclass` import in `src/openbbq/runtime/models.py`. Other runtime modules should import and construct models normally.

- [ ] **Step 6: Run runtime tests**

Run:

```powershell
uv run pytest tests/test_runtime_settings.py tests/test_runtime_context.py tests/test_runtime_doctor.py tests/test_runtime_secrets.py -q
```

Expected: PASS.

- [ ] **Step 7: Run Ruff**

Run:

```powershell
uv run ruff check src/openbbq/runtime tests/test_runtime_settings.py tests/test_runtime_context.py tests/test_runtime_doctor.py tests/test_runtime_secrets.py
```

Expected: PASS.

- [ ] **Step 8: Commit runtime migration**

Run:

```powershell
git add src/openbbq/runtime tests/test_runtime_settings.py tests/test_runtime_context.py tests/test_runtime_doctor.py tests/test_runtime_secrets.py
git commit -m "feat: Migrate runtime models to Pydantic"
```

## Task 4: Migrate Plugin Registry Models

**Files:**

- Modify: `src/openbbq/plugins/registry.py`
- Modify: `tests/test_plugins.py`

- [ ] **Step 1: Add plugin registry model tests**

Append these tests to `tests/test_plugins.py`:

```python
from pydantic import ValidationError as PydanticValidationError

from openbbq.plugins.registry import PluginRegistry, ToolSpec


def test_tool_spec_rejects_non_object_parameter_schema(tmp_path):
    with pytest.raises(PydanticValidationError) as exc:
        ToolSpec(
            plugin_name="demo",
            name="echo",
            description="Echo text.",
            input_artifact_types=[],
            output_artifact_types=["text"],
            parameter_schema=[],
            effects=[],
            manifest_path=tmp_path / "openbbq.plugin.toml",
        )

    assert "parameter_schema" in str(exc.value)


def test_plugin_registry_defaults_to_empty_collections():
    registry = PluginRegistry()

    assert registry.plugins == {}
    assert registry.tools == {}
    assert registry.invalid_plugins == []
    assert registry.warnings == []
```

- [ ] **Step 2: Run plugin tests and verify failure**

Run:

```powershell
uv run pytest tests/test_plugins.py -q
```

Expected: FAIL because plugin registry models are still dataclasses and do not validate constructor input with Pydantic.

- [ ] **Step 3: Replace registry dataclasses with Pydantic models**

In `src/openbbq/plugins/registry.py`, remove `dataclasses` imports. Import Pydantic and base aliases:

```python
from pydantic import Field, field_validator
from pydantic import ValidationError as PydanticValidationError

from openbbq.domain.base import JsonObject, OpenBBQModel, format_pydantic_error
```

Replace the model classes with:

```python
class ToolSpec(OpenBBQModel):
    plugin_name: str
    name: str
    description: str
    input_artifact_types: list[str]
    output_artifact_types: list[str]
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

- [ ] **Step 4: Wrap Pydantic errors during manifest parsing**

In `_parse_tool_manifest()`, keep `Draft7Validator.check_schema(schema)` after Pydantic construction. Build the tool as:

```python
try:
    tool = ToolSpec(
        plugin_name=plugin_name,
        name=name,
        description=description,
        input_artifact_types=input_artifact_types,
        output_artifact_types=output_artifact_types,
        parameter_schema=schema,
        effects=effects,
        manifest_path=manifest_path,
    )
except PydanticValidationError as exc:
    raise ValueError(format_pydantic_error(f"tools[{index}]", exc)) from exc

try:
    Draft7Validator.check_schema(tool.parameter_schema)
except SchemaError as exc:
    raise ValueError(_format_schema_error(index, exc)) from exc

return tool
```

In `_parse_plugin_manifest()`, build `PluginSpec` in a `try` block and wrap Pydantic errors with `ValueError(format_pydantic_error("plugin manifest", exc))`.

- [ ] **Step 5: Run plugin tests**

Run:

```powershell
uv run pytest tests/test_plugins.py -q
```

Expected: PASS.

- [ ] **Step 6: Run Ruff**

Run:

```powershell
uv run ruff check src/openbbq/plugins/registry.py tests/test_plugins.py
```

Expected: PASS.

- [ ] **Step 7: Commit plugin registry migration**

Run:

```powershell
git add src/openbbq/plugins/registry.py tests/test_plugins.py
git commit -m "feat: Migrate plugin registry models to Pydantic"
```

## Task 5: Add Storage And Workflow State Models

**Files:**

- Create: `src/openbbq/storage/models.py`
- Modify: `src/openbbq/storage/project_store.py`
- Modify: `src/openbbq/workflow/state.py`
- Modify: `src/openbbq/workflow/rerun.py`
- Modify: `src/openbbq/workflow/aborts.py`
- Modify: `src/openbbq/workflow/locks.py`
- Modify: `tests/test_storage.py`
- Modify: `tests/test_workflow_state.py`
- Modify: `tests/test_workflow_locks.py`
- Modify: control-flow tests that read workflow state directly

- [ ] **Step 1: Add storage model tests**

At the top of `tests/test_storage.py`, add imports:

```python
from openbbq.storage.models import ArtifactRecord, OutputBinding, WorkflowState
```

Add these tests:

```python
def test_storage_models_dump_to_current_json_shape(tmp_path):
    state = WorkflowState(
        id="text-demo",
        name="Text Demo",
        status="running",
        current_step_id="seed",
        config_hash="abc",
        step_run_ids=("sr_1",),
    )

    assert state.model_dump(mode="json") == {
        "id": "text-demo",
        "name": "Text Demo",
        "status": "running",
        "current_step_id": "seed",
        "config_hash": "abc",
        "step_run_ids": ["sr_1"],
    }


def test_output_binding_is_typed():
    binding = OutputBinding(artifact_id="art_1", artifact_version_id="av_1")

    assert binding.artifact_id == "art_1"
    assert binding.model_dump(mode="json") == {
        "artifact_id": "art_1",
        "artifact_version_id": "av_1",
    }


def test_artifact_record_versions_are_tuple_for_internal_use():
    artifact = ArtifactRecord(
        id="art_1",
        type="text",
        name="seed.text",
        versions=["av_1"],
        current_version_id="av_1",
        created_by_step_id="seed",
        created_at="2026-04-24T00:00:00+00:00",
        updated_at="2026-04-24T00:00:00+00:00",
    )

    assert artifact.versions == ("av_1",)
```

- [ ] **Step 2: Run storage tests and verify failure**

Run:

```powershell
uv run pytest tests/test_storage.py tests/test_workflow_state.py tests/test_workflow_locks.py -q
```

Expected: FAIL because `openbbq.storage.models` does not exist.

- [ ] **Step 3: Create storage models**

Create `src/openbbq/storage/models.py` with:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypeAlias

from pydantic import Field

from openbbq.domain.base import ArtifactMetadata, JsonObject, JsonValue, LineagePayload, OpenBBQModel

WorkflowStatus: TypeAlias = Literal["pending", "running", "paused", "completed", "failed", "aborted"]
StepRunStatus: TypeAlias = Literal["running", "completed", "failed", "skipped"]
ArtifactContent: TypeAlias = JsonValue | bytes


class OutputBinding(OpenBBQModel):
    artifact_id: str
    artifact_version_id: str


OutputBindings: TypeAlias = dict[str, OutputBinding]


class StepErrorRecord(OpenBBQModel):
    code: str
    message: str
    step_id: str | None = None
    plugin_name: str | None = None
    plugin_version: str | None = None
    tool_name: str | None = None
    attempt: int | None = None


class WorkflowState(OpenBBQModel):
    id: str
    name: str | None = None
    status: WorkflowStatus
    current_step_id: str | None = None
    config_hash: str | None = None
    step_run_ids: tuple[str, ...] = ()


class StepRunRecord(OpenBBQModel):
    id: str
    workflow_id: str
    step_id: str | None = None
    attempt: int | None = None
    status: StepRunStatus
    input_artifact_version_ids: dict[str, str] = Field(default_factory=dict)
    output_bindings: OutputBindings = Field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None
    error: StepErrorRecord | None = None


class WorkflowEvent(OpenBBQModel):
    id: str
    workflow_id: str
    sequence: int
    type: str
    message: str | None = None
    created_at: str
    step_id: str | None = None
    attempt: int | None = None


class ArtifactRecord(OpenBBQModel):
    id: str
    type: str
    name: str
    versions: tuple[str, ...] = ()
    current_version_id: str | None = None
    created_by_step_id: str | None = None
    created_at: str
    updated_at: str


class ArtifactVersionRecord(OpenBBQModel):
    id: str
    artifact_id: str
    version_number: int
    content_path: Path
    content_hash: str
    content_encoding: Literal["text", "json", "bytes", "file"]
    content_size: int
    metadata: ArtifactMetadata = Field(default_factory=dict)
    lineage: LineagePayload = Field(default_factory=dict)
    created_at: str


class StoredArtifact(OpenBBQModel):
    record: ArtifactRecord

    @property
    def id(self) -> str:
        return self.record.id


class StoredArtifactVersion(OpenBBQModel):
    record: ArtifactVersionRecord
    content: ArtifactContent | dict[str, Any]

    @property
    def id(self) -> str:
        return self.record.id

    @property
    def artifact_id(self) -> str:
        return self.record.artifact_id


class AbortRequest(OpenBBQModel):
    workflow_id: str
    pid: int
    requested_at: str


class WorkflowLockInfo(OpenBBQModel):
    path: Path
    workflow_id: str
    pid: int | None
    created_at: str | None
    stale: bool
```

- [ ] **Step 4: Update ProjectStore read and write boundaries**

In `src/openbbq/storage/project_store.py`, import models:

```python
from openbbq.domain.base import dump_jsonable
from openbbq.storage.models import (
    ArtifactRecord,
    ArtifactVersionRecord,
    StoredArtifact,
    StoredArtifactVersion,
    StepRunRecord,
    WorkflowEvent,
    WorkflowState,
)
```

Update `write_json_atomic()` payload generation:

```python
payload = json.dumps(dump_jsonable(data), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

Update `write_workflow_state()`:

```python
def write_workflow_state(self, workflow_id: str, state: Mapping[str, Any] | WorkflowState) -> WorkflowState:
    raw = dump_jsonable(state)
    record = dict(raw)
    record["id"] = workflow_id
    workflow_state = WorkflowState.model_validate(record)
    self.write_json_atomic(state_path, workflow_state.model_dump(mode="json"))
    return workflow_state
```

Update `read_workflow_state()`:

```python
return WorkflowState.model_validate(json.loads(state_path.read_text(encoding="utf-8")))
```

Update `write_step_run()`:

```python
def write_step_run(self, workflow_id: str, step_run: Mapping[str, Any] | StepRunRecord) -> StepRunRecord:
    record = dict(dump_jsonable(step_run))
    record["workflow_id"] = workflow_id
    step_run_id = record.get("id") or self.id_generator.step_run_id()
    record["id"] = step_run_id
    typed = StepRunRecord.model_validate(record)
    path = self._workflow_dir(workflow_id) / "step-runs" / f"{step_run_id}.json"
    self.write_json_atomic(path, typed.model_dump(mode="json"))
    return typed
```

Update `append_event()` to return `WorkflowEvent`, and update artifact read/write methods to return `ArtifactRecord`, `StoredArtifact`, and `StoredArtifactVersion` models.

- [ ] **Step 5: Replace subscript access in workflow state helpers**

In `src/openbbq/workflow/state.py`, change return types to `WorkflowState` and `OutputBindings`. Use attribute access:

```python
def build_pending_state(workflow: WorkflowConfig) -> WorkflowState:
    return WorkflowState(
        id=workflow.id,
        name=workflow.name,
        status="pending",
        current_step_id=workflow.steps[0].id if workflow.steps else None,
        step_run_ids=(),
    )
```

In `rebuild_output_bindings()`, read `step_run.output_bindings` and return:

```python
bindings[f"{step_id}.{output_name}"] = binding
```

- [ ] **Step 6: Update tests from subscript access to attributes for typed store returns**

Apply these representative changes:

```python
assert store.read_workflow_state("text-demo").status == "running"
assert step_run.id == "sr_1"
assert event1.sequence == 1
assert version.record.artifact_id == artifact.id
assert store.read_artifact(artifact.id).current_version_id is not None
```

Use `model_dump(mode="json")` only where a test explicitly checks the persisted JSON shape.

- [ ] **Step 7: Run focused storage and state tests**

Run:

```powershell
uv run pytest tests/test_storage.py tests/test_workflow_state.py tests/test_workflow_locks.py tests/test_engine_abort.py tests/test_engine_rerun.py -q
```

Expected: PASS.

- [ ] **Step 8: Run Ruff**

Run:

```powershell
uv run ruff check src/openbbq/storage src/openbbq/workflow/state.py src/openbbq/workflow/rerun.py src/openbbq/workflow/aborts.py src/openbbq/workflow/locks.py tests/test_storage.py tests/test_workflow_state.py tests/test_workflow_locks.py
```

Expected: PASS.

- [ ] **Step 9: Commit storage and workflow state models**

Run:

```powershell
git add src/openbbq/storage src/openbbq/workflow/state.py src/openbbq/workflow/rerun.py src/openbbq/workflow/aborts.py src/openbbq/workflow/locks.py tests/test_storage.py tests/test_workflow_state.py tests/test_workflow_locks.py tests/test_engine_abort.py tests/test_engine_rerun.py
git commit -m "feat: Add typed storage and workflow state models"
```

## Task 6: Add Plugin Request And Response Models

**Files:**

- Create: `src/openbbq/plugins/payloads.py`
- Modify: `src/openbbq/plugins/registry.py`
- Modify: `src/openbbq/workflow/bindings.py`
- Modify: `src/openbbq/workflow/execution.py`
- Modify: `tests/test_workflow_bindings.py`
- Modify: execution tests that inspect step run records

- [ ] **Step 1: Add plugin payload tests**

Create these tests in `tests/test_workflow_bindings.py`:

```python
from pydantic import ValidationError as PydanticValidationError

from openbbq.plugins.payloads import PluginOutputPayload, PluginResponse


def test_plugin_response_requires_outputs_object():
    with pytest.raises(PydanticValidationError):
        PluginResponse.model_validate({"pause_requested": False})


def test_plugin_output_payload_requires_exactly_one_payload(tmp_path):
    with pytest.raises(PydanticValidationError):
        PluginOutputPayload(type="text")

    with pytest.raises(PydanticValidationError):
        PluginOutputPayload(type="text", content="hello", file_path=tmp_path / "content.txt")

    assert PluginOutputPayload(type="text", content="hello").content == "hello"
```

- [ ] **Step 2: Run binding tests and verify failure**

Run:

```powershell
uv run pytest tests/test_workflow_bindings.py -q
```

Expected: FAIL because `openbbq.plugins.payloads` does not exist.

- [ ] **Step 3: Create plugin payload models**

Create `src/openbbq/plugins/payloads.py` with:

```python
from __future__ import annotations

from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import Field, model_validator

from openbbq.domain.base import ArtifactMetadata, JsonObject, JsonValue, OpenBBQModel, PluginParameters
from openbbq.storage.models import OutputBinding


class PluginLiteralInput(OpenBBQModel):
    literal: JsonValue


class PluginArtifactInput(OpenBBQModel):
    artifact_id: str
    artifact_version_id: str
    type: str
    metadata: ArtifactMetadata = Field(default_factory=dict)
    file_path: str | None = None
    content: JsonValue | bytes | None = None


PluginInputValue: TypeAlias = PluginLiteralInput | PluginArtifactInput
PluginInputMap: TypeAlias = dict[str, PluginInputValue]


class PluginRequest(OpenBBQModel):
    project_root: str
    workflow_id: str
    step_id: str
    attempt: int
    tool_name: str
    parameters: PluginParameters
    inputs: PluginInputMap
    runtime: JsonObject = Field(default_factory=dict)
    work_dir: str


class PluginOutputPayload(OpenBBQModel):
    type: str
    content: JsonValue | bytes | None = None
    file_path: Path | None = None
    metadata: ArtifactMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def exactly_one_payload(self) -> PluginOutputPayload:
        has_content = self.content is not None
        has_file = self.file_path is not None
        if has_content == has_file:
            raise ValueError("must include exactly one of content or file_path")
        return self


class PluginResponse(OpenBBQModel):
    outputs: dict[str, PluginOutputPayload]
    pause_requested: bool = False


class PersistedOutput(OpenBBQModel):
    name: str
    binding: OutputBinding
```

- [ ] **Step 4: Keep plugin execution compatibility**

In `src/openbbq/plugins/registry.py`, import `PluginRequest` and `PluginResponse`. Change `execute_plugin_tool()` signature:

```python
def execute_plugin_tool(
    plugin: PluginSpec,
    tool: ToolSpec,
    request: PluginRequest,
    redactor=None,
) -> PluginResponse:
```

Before calling the plugin entrypoint, dump to a plain payload:

```python
request_payload = request.model_dump(mode="json")
```

Call:

```python
response = entrypoint(request_payload)
```

After checking the raw response is a dictionary, return:

```python
try:
    return PluginResponse.model_validate(response)
except PydanticValidationError as exc:
    raise PluginError(
        f"Plugin '{plugin.name}' tool '{tool.name}' returned an invalid response: "
        f"{format_pydantic_error('response', exc)}"
    ) from exc
```

- [ ] **Step 5: Build typed plugin inputs and typed plugin requests**

In `src/openbbq/workflow/bindings.py`, update `artifact_input()` to return `PluginArtifactInput`, and `build_plugin_inputs()` to return `PluginInputMap`.

Use:

```python
plugin_inputs[input_name] = PluginLiteralInput(literal=input_value)
```

and:

```python
return PluginArtifactInput(
    artifact_id=artifact.id,
    artifact_version_id=version.id,
    type=artifact.type,
    metadata=version.record.metadata,
    file_path=str(version.content["file_path"]) if version.record.content_encoding == "file" else None,
    content=None if version.record.content_encoding == "file" else version.content,
)
```

In `src/openbbq/workflow/execution.py`, build request as:

```python
request = PluginRequest(
    project_root=str(config.root_path),
    workflow_id=workflow.id,
    step_id=step.id,
    attempt=attempt,
    tool_name=tool.name,
    parameters=step.parameters,
    inputs=plugin_inputs,
    runtime=runtime_payload,
    work_dir=str(config.storage.root / "work" / workflow.id / step.id),
)
response = execute_plugin_tool(plugin, tool, request, redactor=redact_runtime_secrets)
```

- [ ] **Step 6: Validate typed plugin responses in output persistence**

In `persist_step_outputs()`, change `response` type to `PluginResponse` and read:

```python
response_outputs = response.outputs
```

For each output:

```python
payload = response_outputs.get(output_name)
if payload is None:
    raise ValidationError(
        f"Plugin response for step '{step.id}' is missing output '{output_name}'."
    )
```

Use `payload.type`, `payload.content`, `payload.file_path`, and `payload.metadata` instead of dictionary indexing. Return `dict[str, OutputBinding]`.

- [ ] **Step 7: Run binding and engine tests**

Run:

```powershell
uv run pytest tests/test_workflow_bindings.py tests/test_engine_run_text.py tests/test_engine_run_media.py tests/test_engine_error_policy.py -q
```

Expected: PASS.

- [ ] **Step 8: Run Ruff**

Run:

```powershell
uv run ruff check src/openbbq/plugins/payloads.py src/openbbq/plugins/registry.py src/openbbq/workflow/bindings.py src/openbbq/workflow/execution.py tests/test_workflow_bindings.py
```

Expected: PASS.

- [ ] **Step 9: Commit plugin payload models**

Run:

```powershell
git add src/openbbq/plugins/payloads.py src/openbbq/plugins/registry.py src/openbbq/workflow/bindings.py src/openbbq/workflow/execution.py tests/test_workflow_bindings.py tests/test_engine_run_text.py tests/test_engine_run_media.py tests/test_engine_error_policy.py
git commit -m "feat: Type plugin request and response payloads"
```

## Task 7: Migrate Engine, CLI, And Remaining Dataclasses

**Files:**

- Modify: `src/openbbq/engine/service.py`
- Modify: `src/openbbq/engine/validation.py`
- Modify: `src/openbbq/workflow/execution.py`
- Modify: `src/openbbq/cli/quickstart.py`
- Modify: `src/openbbq/cli/app.py`
- Modify: `src/openbbq/runtime/provider.py`
- Modify: `src/openbbq/runtime/secrets.py`
- Modify: tests that assert CLI JSON output or result objects

- [ ] **Step 1: Add tests that result models dump cleanly**

Add this to `tests/test_models.py`:

```python
from openbbq.engine.service import WorkflowRunResult
from openbbq.engine.validation import WorkflowValidationResult
from openbbq.workflow.execution import ExecutionResult


def test_engine_result_models_dump_to_json_objects():
    assert WorkflowRunResult(
        workflow_id="text-demo",
        status="completed",
        step_count=2,
        artifact_count=2,
    ).model_dump(mode="json") == {
        "workflow_id": "text-demo",
        "status": "completed",
        "step_count": 2,
        "artifact_count": 2,
    }
    assert WorkflowValidationResult(workflow_id="text-demo", step_count=2).step_count == 2
    assert ExecutionResult(
        workflow_id="text-demo",
        status="completed",
        step_count=2,
        artifact_count=2,
    ).artifact_count == 2
```

- [ ] **Step 2: Run result model tests and verify failure**

Run:

```powershell
uv run pytest tests/test_models.py -q
```

Expected: FAIL because engine result classes are still dataclasses.

- [ ] **Step 3: Replace remaining result dataclasses with Pydantic models**

In `src/openbbq/engine/service.py`, replace `@dataclass` `WorkflowRunResult` with:

```python
from openbbq.domain.base import OpenBBQModel


class WorkflowRunResult(OpenBBQModel):
    workflow_id: str
    status: str
    step_count: int
    artifact_count: int
```

In `src/openbbq/engine/validation.py`:

```python
from openbbq.domain.base import OpenBBQModel


class WorkflowValidationResult(OpenBBQModel):
    workflow_id: str
    step_count: int
```

In `src/openbbq/workflow/execution.py`:

```python
from openbbq.domain.base import OpenBBQModel


class ExecutionResult(OpenBBQModel):
    workflow_id: str
    status: str
    step_count: int
    artifact_count: int
```

In `src/openbbq/cli/quickstart.py`, replace `GeneratedWorkflow` dataclass with `OpenBBQModel`.

- [ ] **Step 4: Update CLI output boundary**

In `src/openbbq/cli/app.py`, update `_emit()` or call sites so Pydantic models are dumped before JSON serialization:

```python
from openbbq.domain.base import dump_jsonable
```

Change `_emit()`:

```python
def _emit(payload: dict[str, Any], json_output: bool, text: Any) -> None:
    payload = dump_jsonable(payload)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(text)
```

For artifact output call sites, convert models explicitly:

```python
payload = {
    "ok": True,
    "artifact": artifact.record.model_dump(mode="json"),
    "version": version.record.model_dump(mode="json"),
}
```

- [ ] **Step 5: Search and remove remaining production dataclasses where in scope**

Run:

```powershell
rg -n "from dataclasses import|@dataclass" src/openbbq
```

Expected acceptable remaining results only in files outside the approved migration scope. For this plan, remaining dataclasses should be removed from:

- `src/openbbq/domain/models.py`
- `src/openbbq/runtime/models.py`
- `src/openbbq/plugins/registry.py`
- `src/openbbq/storage/project_store.py`
- `src/openbbq/workflow/execution.py`
- `src/openbbq/workflow/locks.py`
- `src/openbbq/engine/service.py`
- `src/openbbq/engine/validation.py`
- `src/openbbq/cli/quickstart.py`

- [ ] **Step 6: Run CLI and engine tests**

Run:

```powershell
uv run pytest tests/test_cli_integration.py tests/test_cli_control_flow.py tests/test_cli_quickstart.py tests/test_engine_run_text.py tests/test_engine_pause_resume.py tests/test_engine_abort.py tests/test_engine_rerun.py -q
```

Expected: PASS.

- [ ] **Step 7: Run Ruff**

Run:

```powershell
uv run ruff check src/openbbq/engine src/openbbq/workflow src/openbbq/cli src/openbbq/runtime tests/test_models.py
```

Expected: PASS.

- [ ] **Step 8: Commit result and CLI migration**

Run:

```powershell
git add src/openbbq/engine src/openbbq/workflow src/openbbq/cli src/openbbq/runtime tests/test_models.py tests/test_cli_integration.py tests/test_cli_control_flow.py tests/test_cli_quickstart.py tests/test_engine_run_text.py tests/test_engine_pause_resume.py tests/test_engine_abort.py tests/test_engine_rerun.py
git commit -m "feat: Migrate engine and CLI result models"
```

## Task 8: Reduce Loose Dictionary Type Hints And Verify The Whole Suite

**Files:**

- Modify: modules found by the searches in this task
- Modify: tests found by failing verification
- Modify: docs if behavior text changed

- [ ] **Step 1: Search for remaining broad dictionary annotations in shared contracts**

Run:

```powershell
rg -n "dict\\[str, Any\\]|Mapping\\[str, Any\\]|list\\[dict\\[str, Any\\]\\]" src/openbbq tests
```

Expected: remaining matches are limited to:

- low-level raw parser helpers that read YAML, TOML, JSON, or third-party plugin dictionaries;
- built-in plugin internals that the approved spec excludes from the first migration;
- tests that intentionally construct raw plugin or storage payloads.

- [ ] **Step 2: Replace shared-contract raw annotations with named aliases**

For each shared-contract match, import named aliases instead of spelling broad dictionaries:

```python
from openbbq.domain.base import JsonObject, PluginInputs, PluginParameters
from openbbq.storage.models import OutputBindings
```

Use replacements such as:

```python
def _load_yaml_mapping(path: Path) -> JsonObject:
    ...

def _validate_step_inputs(inputs: PluginInputs, ...) -> None:
    ...

def build_artifact_reuse_map(...) -> dict[str, str]:
    ...
```

Keep `dict[str, str]` for fixed string maps such as artifact reuse maps. The readability issue is broad unstructured payloads, not every dictionary.

- [ ] **Step 3: Run import and type-shape smoke tests**

Run:

```powershell
uv run pytest tests/test_package_layout.py tests/test_models.py tests/test_plugins.py tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 4: Run Phase 1 and Phase 2 focused suites**

Run:

```powershell
uv run pytest tests/test_phase1_acceptance.py tests/test_phase2_contract_regressions.py tests/test_phase2_local_video_subtitle.py tests/test_phase2_remote_video_slice.py tests/test_phase2_translation_slice.py tests/test_phase2_asr_correction_segmentation.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full verification**

Run:

```powershell
uv run ruff check .
uv run pytest
```

Expected: both commands PASS.

- [ ] **Step 6: Run CLI smoke commands**

Run:

```powershell
uv run openbbq validate text-demo --project tests/fixtures/projects/text-basic
uv run openbbq run text-demo --project tests/fixtures/projects/text-basic --force
```

Expected:

- `validate` exits 0 and reports the workflow as valid.
- `run --force` exits 0 and completes the fixture workflow.

- [ ] **Step 7: Commit cleanup and verification fixes**

Run:

```powershell
git add src tests docs pyproject.toml
git commit -m "chore: Clean up Pydantic migration type hints"
```

## Final Verification Checklist

- [ ] `uv run ruff check .` passes.
- [ ] `uv run pytest` passes.
- [ ] `uv run openbbq validate text-demo --project tests/fixtures/projects/text-basic` exits 0.
- [ ] `uv run openbbq run text-demo --project tests/fixtures/projects/text-basic --force` exits 0.
- [ ] `rg -n "from dataclasses import|@dataclass" src/openbbq` shows no matches in migrated model/result modules.
- [ ] `rg -n "dict\\[str, Any\\]|Mapping\\[str, Any\\]" src/openbbq` shows only raw parser helpers, plugin compatibility boundaries, or built-in plugin internals outside the first migration scope.
- [ ] `git status --short` is clean after the final commit.

## Notes For Implementers

- Keep plugin parameter validation on `jsonschema.Draft7Validator`; do not convert plugin `parameter_schema` to Pydantic.
- Keep external plugin function compatibility by passing plain dictionaries into plugin entrypoints.
- Use Pydantic models internally and dump only at file, CLI, or plugin compatibility boundaries.
- Preserve on-disk JSON field names and list shapes by using `model_dump(mode="json")`.
- Convert `pydantic.ValidationError` to OpenBBQ `ValidationError` or `PluginError` at public boundaries.

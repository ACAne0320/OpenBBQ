# Pydantic Schema Validation Design

## Goal

Migrate OpenBBQ's core contract objects from frozen dataclasses and loose dictionary-heavy type hints to Pydantic v2 `BaseModel` schemas. The migration should make project configuration, runtime settings, plugin manifests, workflow state, artifact records, and plugin request and response payloads declarative, validated, and easier to read in type hints.

The user-facing goal is not only stronger validation. The code should expose explicit model names instead of repeating `dict[str, Any]` across the backend.

## Current Baseline

Current code facts:

- [`src/openbbq/domain/models.py`](../../../src/openbbq/domain/models.py) defines project, storage, workflow, step, and output contracts as frozen dataclasses.
- [`src/openbbq/config/loader.py`](../../../src/openbbq/config/loader.py) performs project YAML validation manually while constructing those dataclasses.
- [`src/openbbq/runtime/models.py`](../../../src/openbbq/runtime/models.py) defines runtime settings, provider, secret, context, model asset, and doctor result contracts as frozen dataclasses.
- [`src/openbbq/runtime/settings.py`](../../../src/openbbq/runtime/settings.py) performs runtime TOML validation manually.
- [`src/openbbq/plugins/registry.py`](../../../src/openbbq/plugins/registry.py) defines plugin manifest contracts as frozen dataclasses, validates manifest structure manually, and keeps plugin tool `parameter_schema` as JSON Schema.
- [`src/openbbq/storage/project_store.py`](../../../src/openbbq/storage/project_store.py), [`src/openbbq/workflow/state.py`](../../../src/openbbq/workflow/state.py), and [`src/openbbq/workflow/bindings.py`](../../../src/openbbq/workflow/bindings.py) still expose many persisted records and plugin payloads as raw dictionaries.
- [`tests/test_models.py`](../../../tests/test_models.py) currently asserts that the domain models are dataclasses. That test must change to assert Pydantic model behavior.

There is no `docs/solutions/` directory with prior decisions for this topic. The GitHub CLI is not installed in the current environment, so related remote issues or pull requests could not be checked through `gh`. A browser search of the public repository did not surface an existing Pydantic migration discussion.

## Scope

This design includes:

- adding Pydantic v2 as a runtime dependency;
- introducing a shared OpenBBQ Pydantic base model;
- migrating core domain, runtime, plugin registry, workflow, storage, and engine result dataclasses to `BaseModel`;
- replacing repeated loose dictionary signatures with named Pydantic models or named type aliases;
- keeping dynamic JSON fields explicit through shared aliases such as `JsonValue`, `JsonObject`, `PluginParameters`, `PluginInputs`, and `ArtifactMetadata`;
- preserving the plugin `parameter_schema` contract as JSON Schema validated by `jsonschema`;
- converting Pydantic validation failures into OpenBBQ `ValidationError` or `PluginError` messages at CLI-facing boundaries;
- preserving current CLI behavior, JSON output shape, workflow config hash semantics, and fixture behavior.

This design excludes:

- replacing plugin-authored JSON Schema parameter contracts with Pydantic models;
- changing the `openbbq.yaml`, runtime TOML, plugin manifest TOML, workflow state JSON, or artifact JSON on-disk formats except for intentional normalization already present in the code;
- adding a FastAPI or HTTP request layer;
- modeling every internal built-in plugin helper payload in this first migration;
- rewriting plugin implementations unless needed to consume the new plugin request and response models cleanly.

## Options Considered

### Option 1: Boundary-only Pydantic models

Use Pydantic only for YAML, TOML, and plugin manifest parsing while keeping internal dataclasses.

Effort is moderate and risk is low. It builds on the current loaders and registry code. It does not satisfy the user's readability goal because many internal signatures would still expose `dict[str, Any]` and dataclasses.

### Option 2: Core contract migration

Migrate the main OpenBBQ contract objects to Pydantic and introduce named payload models for workflow state, artifact records, plugin requests, and plugin responses.

Effort is high and risk is moderate. It builds on the existing module boundaries while addressing the main readability problem. This is the recommended approach.

### Option 3: Full domain modeling, including built-in plugin internals

Migrate core contracts and also model subtitle segments, glossary rules, translation QA issues, remote download attempts, transcript correction chunks, and similar plugin-internal structures.

Effort is very high and risk is high. It would improve some plugin code, but it expands this migration beyond the requested backend contract cleanup. It should be considered after the core migration lands.

## Recommended Approach

Use Option 2. Migrate the core contracts to Pydantic in one coordinated implementation, but keep the scope limited to shared OpenBBQ schemas and plugin boundary payloads.

The key rule is: every persistent or cross-module OpenBBQ contract should have a named model, while intentionally dynamic user or plugin content should have a named JSON alias.

## Architecture

```text
YAML / TOML / persisted JSON / plugin payloads
        |
        v
Pydantic schema models
        |
        +-- field constraints
        +-- defaults
        +-- path normalization where local context is available
        +-- cross-field validators for object-local rules
        |
        v
OpenBBQ services
        |
        +-- workflow graph validation
        +-- plugin discovery and JSON Schema validation
        +-- execution, storage, and CLI output
```

Pydantic should handle local shape, type, default, and object-level invariants. Service modules should keep validations that require external context:

- step input references that depend on step order and declared outputs;
- `tool_ref` lookup in the discovered plugin registry;
- parameters checked against a plugin tool's JSON Schema;
- file existence checks for plugin response file-backed artifacts;
- lock liveness checks and stale lock recovery.

## Shared Model Base

Add `src/openbbq/domain/base.py` with:

- `OpenBBQModel`, a common `BaseModel` subclass;
- `ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)`;
- shared JSON aliases:
  - `JsonScalar`;
  - `JsonValue`;
  - `JsonObject`;
  - `PluginParameters`;
  - `PluginInputs`;
  - `ArtifactMetadata`;
  - `LineagePayload`;
- helper functions for OpenBBQ-style validation error formatting.

The base should avoid broad coercion where current behavior rejects values. For fields like `version`, `max_retries`, and booleans, validators must keep the existing strict semantics where bool is not accepted as an int and non-boolean values are rejected.

## Domain Models

Migrate these models from dataclasses to `OpenBBQModel`:

- `ProjectMetadata`;
- `StorageConfig`;
- `PluginConfig`;
- `StepOutput`;
- `StepConfig`;
- `WorkflowConfig`;
- `ProjectConfig`.

Important field decisions:

- `StepConfig.inputs` becomes `PluginInputs`, not a raw dictionary annotation.
- `StepConfig.parameters` becomes `PluginParameters`.
- `StepConfig.outputs` remains an immutable tuple of `StepOutput`.
- `ProjectConfig.workflows` may remain a mapping keyed by workflow id, but its annotation should be a named alias such as `WorkflowMap`.
- ID and step output constraints should live on models when they are local to the object.
- duplicate step IDs, duplicate output names across a single step, and forward references can remain in `config.loader` because they depend on collection context.

## Runtime Models

Migrate runtime contracts in `src/openbbq/runtime/models.py`:

- `CacheSettings`;
- `ProviderProfile`;
- `FasterWhisperSettings`;
- `ModelsSettings`;
- `RuntimeSettings`;
- `SecretCheck`;
- `ResolvedProvider`;
- `RuntimeContext`;
- `ModelAssetStatus`;
- `DoctorCheck`.

`public_dict()` and `request_payload()` methods can remain, but should internally use `model_dump(mode="json")` with explicit redaction or sorting where needed.

`runtime.settings` should stop manually checking every field shape and instead validate raw TOML through Pydantic models plus targeted validators for provider names, provider types, and secret references.

## Plugin Registry Models

Migrate these registry contracts:

- `ToolSpec`;
- `PluginSpec`;
- `InvalidPlugin`;
- `PluginRegistry`.

Add raw manifest models for TOML parsing and error formatting:

- `RawPluginManifest`;
- `RawToolManifest`.

`ToolSpec.parameter_schema` remains `JsonObject` and continues to be checked with `Draft7Validator.check_schema()`. Pydantic validates that the field is an object; `jsonschema` validates that the object is a valid JSON Schema.

The registry can keep `PluginRegistry.plugins` and `PluginRegistry.tools` as map-like fields, but they should use named aliases such as `PluginMap` and `ToolMap`.

## Storage And Workflow State Models

Introduce models for persisted records:

- `ArtifactRecord`;
- `ArtifactVersionRecord`;
- `WorkflowState`;
- `StepRunRecord`;
- `WorkflowEvent`;
- `OutputBinding`;
- `OutputBindings`;
- `StepErrorRecord`;
- `WorkflowLockInfo`.

These models should be used at read and write boundaries, then dumped to JSON with stable sorting through the existing `ProjectStore.write_json_atomic()` behavior.

`ProjectStore.write_json_atomic()` remains the low-level JSON writer and can accept a mapping. Higher-level store methods should accept and return named models where the rest of the code consumes structured fields. CLI output can dump those models to dictionaries at the output boundary.

## Plugin Request And Response Models

Add explicit boundary models for plugin execution:

- `PluginArtifactInput`;
- `PluginLiteralInput`;
- `PluginRequest`;
- `PluginOutputPayload`;
- `PluginResponse`;

`execute_plugin_tool()` should still call third-party plugin functions with a plain JSON-like dictionary for compatibility. OpenBBQ should build that dictionary from a `PluginRequest` model and validate plugin return values into a `PluginResponse` model before persisting outputs.

This keeps external plugin compatibility while removing loose payloads from internal engine signatures.

## Error Handling

Pydantic validation errors should not leak as raw Pydantic tracebacks at CLI boundaries. Loader and registry modules should catch `pydantic.ValidationError` and convert it to:

- `openbbq.errors.ValidationError` for project config, runtime settings, workflow state, and plugin response validation;
- `PluginError` or invalid plugin registry entries for plugin manifest validation.

Error messages should include the entity and field path. Exact wording can change where tests only assert meaningful substrings, but CLI behavior should remain understandable and stable.

## Configuration Hashing

`compute_workflow_config_hash()` should use Pydantic `model_dump(mode="json")` instead of dataclass `asdict()`.

The hash payload must continue to include:

- project config version;
- selected workflow id;
- normalized workflow config;
- resolved plugin paths.

Path fields must dump as strings so the hash remains JSON serializable.

## Testing Strategy

Update and add tests for these paths:

- model tests assert Pydantic model behavior instead of dataclass behavior;
- project config happy path still loads canonical fixtures;
- project config failures still reject invalid version, invalid IDs, duplicate step IDs, invalid plugin paths, invalid storage paths, bad references, and invalid pause fields;
- runtime settings defaults and TOML parsing still work;
- runtime provider name, provider type, and secret reference failures still raise OpenBBQ `ValidationError`;
- plugin discovery still validates manifests without importing plugin code;
- invalid plugin manifests still populate `registry.invalid_plugins`;
- workflow validation still uses JSON Schema for step parameters;
- workflow config hash remains stable for unchanged config and changes when step parameters change;
- plugin response validation rejects missing outputs, wrong artifact type, and invalid file-backed outputs;
- storage read and write tests pass through new record models;
- CLI JSON outputs remain serializable and stable.

Full verification should run:

```text
uv run ruff check .
uv run pytest
```

Focused implementation runs can use:

```text
uv run pytest tests/test_models.py tests/test_config.py tests/test_runtime_settings.py tests/test_plugins.py tests/test_workflow_state.py tests/test_storage.py -q
```

## Rollback Plan

The migration does not require data migration or credential changes. If the approach proves too noisy, rollback is a normal code revert of the Pydantic model changes plus the dependency addition.

Because on-disk formats should stay unchanged, existing fixtures and `.openbbq/` state directories remain compatible as long as model dumping preserves the current JSON shape.

## Dependency And Tooling Impact

Add `pydantic>=2.0` to `pyproject.toml` runtime dependencies.

No API keys, external services, or new CLIs are required. The existing `jsonschema` dependency remains necessary for plugin parameter schemas.

## Design Attacks

Dependency failure: if Pydantic is unavailable, OpenBBQ cannot import core models. This is acceptable because Pydantic becomes a required runtime dependency in `pyproject.toml`, installed by `uv sync`.

Scale explosion: at 10x workflow size, model validation adds object construction overhead. This should be acceptable for CLI workflow config and state sizes. Plugin artifact content should not be loaded into deep Pydantic models beyond existing read paths.

Rollback cost: rollback is code-only because persisted formats do not change. The main rollback risk is tests updated from dataclass expectations to Pydantic expectations.

Premise collapse: the fragile assumption is that removing raw dictionary annotations everywhere is desirable. The design limits that risk by keeping named JSON aliases for truly dynamic plugin and artifact content instead of forcing fake schemas over unknown data.

## Approved Design Summary

Building: OpenBBQ will move core backend contracts to Pydantic v2 `BaseModel` schemas and introduce named payload models and JSON aliases so declarations are explicit, validated, and easier to read.

Not building: this migration will not replace plugin JSON Schema contracts, change file formats, add an HTTP API, or model every built-in plugin helper payload.

Approach: migrate core contract objects in one coordinated pass while preserving existing module boundaries and service-level validations that require external context.

Key decisions:

- Use a shared `OpenBBQModel` base for frozen, extra-forbidden models.
- Keep JSON Schema for plugin tool parameters.
- Use named aliases for dynamic JSON instead of repeating `dict[str, Any]`.
- Convert Pydantic errors into OpenBBQ errors at boundaries.
- Preserve on-disk JSON/TOML/YAML shapes and workflow config hash semantics.

Unknowns: none blocking. During implementation, exact error wording may be adjusted, but tests should assert stable field paths and meaningful reasons.

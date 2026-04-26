# Backend Hardening Design

> Status: historical design. The hardening work has since been implemented and
> followed by SQLite-backed storage plus the FastAPI sidecar. Treat the
> "original baseline" sections below as the code state at the time this design
> was written, not as the current repository facts.

## Goal

Harden the current OpenBBQ backend before desktop development by turning the working CLI-first implementation into a stricter headless application core. The work should treat the current behavior, tests, fixtures, and Phase 2 workflow as the factual baseline, but it should not preserve compatibility mechanisms that would make the desktop architecture weaker.

The target outcome is a backend that an Electron desktop, the current HTTP API
sidecar, worker process, or automation client can call through stable typed
services instead of CLI internals.

## Original Baseline Before Hardening

Code facts at the time this design was written:

- `src/openbbq/domain/models.py` defines Pydantic project, workflow, step, and output config models, but several mapping fields remain mutable dictionaries.
- `src/openbbq/storage/models.py` defines typed persisted records, but the record models still expose dict-like `__getitem__` and `get` methods.
- `src/openbbq/plugins/payloads.py` validates plugin requests and responses, but plugin responses only preserve `outputs` and `pause_requested`.
- `src/openbbq/config/loader.py` manually parses and validates the full YAML project shape before constructing Pydantic models.
- `src/openbbq/plugins/registry.py` validates plugin manifests and imports plugin entrypoints, but plugin tools still declare only flat input and output artifact type allowlists.
- `src/openbbq/workflow/execution.py` contains the main execution loop, including state transitions, step run creation, plugin invocation, retry and skip policy, pause handling, abort handling, artifact persistence, and event emission.
- `src/openbbq/storage/project_store.py` owns workflow state JSON, event JSONL, step run JSON, artifact metadata, artifact content storage, atomic writes, directory fsyncs, and artifact version lookup.
- `src/openbbq/cli/app.py` is the only user-facing adapter, but it also contains application-level behavior for runtime settings, generated subtitle workflows, artifact lookup, and command dispatch.
- Built-in media and LLM plugins are functional, but `translation/plugin.py` and `transcript/plugin.py` are large modules with raw dictionary payloads and duplicated client, chunking, and model-response parsing patterns.

Verification baseline on April 24, 2026:

- `uv run ruff check .` passes.
- `uv run pytest` passes with 229 passed and 1 skipped.

## Desktop Pressure

The desktop will need backend properties that are useful but not required by a CLI:

- typed workflow, artifact, plugin, runtime, and event contracts that can be exposed through an API without reshaping;
- stable event records with severity and structured data for progress timelines, logs, notifications, and review panes;
- plugin tool declarations rich enough to drive configuration forms and wiring validation;
- inspectable artifact metadata and version indexes that can support project browsing without directory scans;
- clear service methods for run, resume, abort, validate, status, logs, artifact import, artifact export, settings, auth, and generated workflows;
- execution internals split enough to add streaming, async workers, cancellation checkpoints, and human review gates in future phases;
- no accidental dependency on CLI parser internals, dict-like model access, or compatibility aliases.

## Scope

This hardening includes:

- making persisted, cross-module, and API-facing models stricter and less dict-like;
- aligning the workflow event implementation with the documented event schema;
- preserving plugin response metadata and plugin events and wrapping them into workflow events;
- introducing a plugin contract v2 for named inputs, named outputs, runtime requirements, and UI-friendly parameter metadata;
- removing legacy compatibility paths that obscure the future contract;
- splitting the execution loop into smaller components with explicit state transition and step execution boundaries;
- splitting the filesystem store into workflow state, event, artifact metadata, artifact content, and artifact index responsibilities;
- introducing an application service layer that CLI and desktop/API adapters can share;
- modularizing built-in plugins where large files mix parameter parsing, provider resolution, model calls, response parsing, and domain logic;
- expanding tests around the new contracts and migration decisions.

This hardening excludes:

- building the Electron desktop UI;
- adding FastAPI routes or an HTTP server in this hardening milestone;
- adding a background worker runtime;
- implementing real-time websocket streaming;
- changing the product-level target workflow beyond making its backend contracts stricter;
- preserving old `llm.translate`, implicit legacy LLM environment fallback, package-level compatibility imports, or model dict access when they conflict with the new architecture.

## Options Considered

### Option 1: Small Cleanup Only

Keep the current module layout and remove only obvious duplication.

This is low effort and low risk, but it leaves the desktop to depend on CLI-shaped backend behavior. It also leaves the largest risks in place: event contracts, plugin contracts, storage boundaries, and execution-loop complexity.

### Option 2: Contract-First Backend Hardening

Stabilize the contracts first, then split execution, storage, application services, and built-in plugin internals around those contracts.

This is higher effort, but it gives the desktop a clean backend surface and removes most future technical debt before UI code depends on it. This is the recommended approach.

### Option 3: Full Platform Rewrite

Replace the local synchronous engine with an API-first worker and database-backed implementation now.

This would have overreached for that slice. At the time, the filesystem-backed
engine was well-tested and useful for local desktop workflows. The chosen path
was to harden it first, then add SQLite storage and the API sidecar in later
work.

## Recommended Approach

Use Option 2. Implement the hardening as a series of behavior-preserving but compatibility-breaking backend slices:

1. Contract hardening.
2. Plugin contract v2.
3. Execution boundary refactor.
4. Storage boundary refactor and artifact lookup records.
5. Application service layer.
6. Built-in plugin modularization.
7. Compatibility removal and documentation alignment.

Each slice should keep the full test suite green before the next slice begins. The implementation should prefer precise tests over broad snapshots, because this work changes internal structure while preserving product behavior.

## Contract Hardening

Models that cross module, storage, or API boundaries should stop pretending to
be dictionaries. Remove `__getitem__`, `get`, and dict equality helpers from
record and payload models once direct attribute access is migrated.

Use explicit types for common state:

- workflow status;
- step run status;
- workflow event type;
- workflow event level;
- artifact content encoding;
- plugin runtime;
- plugin effect;
- provider type;
- secret reference kind.

Use immutable containers for model fields where practical:

- mappings should become `MappingProxyType`-like values, Pydantic frozen mappings, or tuples of keyed records when true deep immutability is needed;
- lists in registry and plugin specs should become tuples;
- CLI JSON output should dump models at the output boundary instead of relying on dict-like access.

The domain model should remain strict about booleans and integers. Values such as `max_retries: true` must stay invalid.

## Workflow Events

Workflow events should match the documented schema:

- `id`;
- `sequence`;
- `workflow_id`;
- `step_id`;
- `type`;
- `level`;
- `message`;
- `data`;
- `created_at`.

Default `level` should be `info`. Step failures should use `error`, skipped steps can use `warning`, plugin notices can use the plugin-provided level, and debug-only diagnostics can use `debug`.

Plugin response events should be accepted as plugin-owned event payloads, validated, redacted, and persisted as workflow events with type `plugin.event`. The engine owns workflow-level fields such as event ID, sequence, workflow ID, step ID, attempt, and timestamp.

This event contract is important for desktop because it becomes the timeline, progress panel, log viewer, notification source, and debugging surface.

## Plugin Contract V2

The current manifest contract validates only flat artifact type allowlists. That is not enough for desktop configuration and wiring. A v2 plugin tool should describe named input slots and named output slots.

Tool declarations should support:

- `inputs`: keyed input specs with allowed artifact types, required flag, description, and cardinality;
- `outputs`: keyed output specs with artifact type and description;
- `parameters`: JSON Schema plus UI hints where useful;
- `runtime_requirements`: binaries, Python extras, network, model caches, provider profiles, and filesystem permissions;
- `effects`: normalized effect values;
- `ui`: optional form and preview hints for future desktop rendering.

The workflow config should validate step inputs against named input specs, not only against an artifact type allowlist. Existing built-in and fixture manifests should be migrated to v2. The old `input_artifact_types` and `output_artifact_types` fields can be removed after the migration because compatibility is not required.

The plugin execution payload can remain JSON-compatible at the external boundary, but OpenBBQ internals should use typed `PluginRequest`, `PluginResponse`, `PluginInput`, `PluginOutput`, and `PluginEvent` models.

## Execution Boundary

Split `workflow.execution` into explicit responsibilities:

- `WorkflowRunner`: owns run mode, loop over steps, pause and abort checkpoints, and final result.
- `StepExecutor`: owns one step attempt, request construction, plugin invocation, output validation, and output persistence.
- `StateTransitions`: owns workflow state and step run state changes.
- `EventSink`: owns event construction, redaction, and persistence.
- `ExecutionContext`: carries config, registry, store, runtime context, config hash, artifact reuse map, output bindings, and redaction.

This keeps the synchronous local engine intact, but makes it possible to add:

- progress callbacks;
- desktop event streaming;
- async wrappers;
- finer cancellation checks;
- human review gates;
- richer retry policy;
- partial execution plans.

State changes should be named operations, not repeated dictionaries. Examples: `mark_workflow_running`, `mark_step_run_started`, `mark_step_run_completed`, `mark_workflow_paused`, and `mark_workflow_failed`.

## Storage Boundary

This storage recommendation was superseded by the current SQLite-backed
`ProjectStore` and `ProjectDatabase` implementation. Current code stores
workflow state, runs, step runs, events, artifact records, and artifact-version
metadata in `.openbbq/openbbq.db`; artifact payloads remain file-backed under
`.openbbq/artifacts/`.

The original recommendation was to keep local filesystem storage for that slice
and split `ProjectStore` into smaller collaborators:

- `JsonFileStore`: atomic JSON reads and writes, JSONL append, fsync behavior.
- `WorkflowStateStore`: workflow state, step runs, lock files, abort request files.
- `EventStore`: event sequence allocation, JSONL recovery, event reads.
- `ArtifactStore`: artifact records and version records.
- `ArtifactContentStore`: content normalization, file-backed copies, hashes, and durable writes.
- `ArtifactIndex`: lookup by artifact ID, artifact version ID, workflow ID, step ID, artifact type, artifact name, and current version.

The on-disk layout can remain compatible with current generated state unless a stronger versioned layout is intentionally chosen. Since compatibility is not required, this hardening may add an index file such as `.openbbq/state/artifact-index.json` or `.openbbq/artifacts/index.json`, and it may provide a rebuild command or automatic rebuild from artifact metadata.

Artifact writes should have a recovery story when a process crashes after content or version metadata is written but before the parent artifact record or index is updated. At minimum, the store should be able to detect orphaned version directories and rebuild indexes.

## Application Service Layer

Introduce a backend application layer that CLI and desktop/API adapters share.

Candidate package:

```text
src/openbbq/application/
  artifacts.py
  auth.py
  diagnostics.py
  plugins.py
  projects.py
  quickstart.py
  runtime.py
  workflows.py
```

These modules should expose typed request and result models and should contain user-facing operations:

- project initialization and project info;
- workflow validation, run, resume, abort, unlock, status, logs, and step rerun;
- artifact import, list, show, diff, and export;
- plugin list and plugin info;
- runtime settings show and set provider;
- auth set and auth check;
- doctor checks;
- generated YouTube subtitle workflow execution.

`cli/app.py` should become a parser and output adapter. It should not own artifact lookup rules, generated workflow behavior, settings mutation, or backend orchestration.

## Runtime And Secrets

Remove implicit legacy LLM behavior from core provider resolution. LLM-backed steps should resolve named provider profiles from runtime settings. Secrets should be resolved before plugin execution and redacted from all events, errors, and persisted step run records.

Environment-backed secrets remain useful through explicit `env:` references in runtime settings. What should go away is the special case where a workflow omits `provider` and plugin code directly reads `OPENBBQ_LLM_API_KEY` and `OPENBBQ_LLM_BASE_URL`.

The desktop can then present provider setup as a first-class settings flow instead of inheriting hidden process environment behavior.

## Built-In Plugin Modularization

Large built-in plugin modules should be split by tool and shared helpers:

```text
src/openbbq/builtin_plugins/translation/
  plugin.py
  translate.py
  qa.py
  llm_json.py
  models.py

src/openbbq/builtin_plugins/transcript/
  plugin.py
  correct.py
  segment.py
  llm_json.py
  models.py
```

The top-level `plugin.py` should dispatch based on `tool_name` and keep the external entrypoint small. Tool modules should parse typed parameters, validate typed artifact content, run the operation, and return typed plugin outputs.

Shared LLM JSON completion behavior should be reused by transcript correction and translation:

- build system and user messages;
- call OpenAI-compatible chat completions;
- extract message content;
- parse JSON arrays;
- split chunks recursively on parse failure;
- preserve stable error messages.

## Compatibility Removal

Because this phase is intentionally allowed to break compatibility, remove:

- `llm.translate` compatibility alias;
- legacy `OPENBBQ_LLM_API_KEY` / `OPENBBQ_LLM_BASE_URL` provider fallback;
- package-level compatibility re-exports that make import boundaries unclear;
- dict-like access on Pydantic models;
- manifest v1 fields after built-in and fixture manifests are migrated;
- tests whose only purpose is preserving obsolete behavior.

Fixture workflows should be migrated to the future contract rather than keeping old and new forms side by side.

## Testing Strategy

Testing should move from broad compatibility assertions to explicit contract assertions:

- model tests prove strict validation, immutability, event schema, plugin payload schema, and manifest v2 schema;
- config tests prove workflow graph validation against named plugin inputs and outputs;
- registry tests prove plugin discovery does not import code and produces typed specs;
- execution tests prove state transitions, retries, skips, pauses, aborts, plugin events, output metadata, and redaction;
- storage tests prove index writes, index rebuild, orphan detection, artifact lookup, and JSONL recovery;
- application service tests prove CLI-independent operations;
- CLI tests prove parser-to-service wiring and JSON output envelopes;
- built-in plugin tests prove typed parameters, typed content, LLM JSON parsing, segmentation, QA, and file-backed media behavior.

Full verification remains:

```bash
uv run ruff check .
uv run pytest
```

## Rollback Strategy

Each slice should land as a separate commit. If a hardening slice creates unacceptable churn, revert that slice while keeping earlier contract work. The most important irreversible decision is plugin contract v2. Once the desktop depends on it, old manifest fields should stay removed.

## Success Criteria

The backend is ready for desktop development when:

- CLI behavior still covers the current target workflows through application services;
- workflow events have structured levels and data;
- plugin manifests describe named input and output contracts;
- plugin responses preserve metadata and events;
- execution is split into testable units;
- storage has indexed artifact lookup and recovery checks;
- CLI no longer owns application behavior;
- legacy compatibility paths are removed;
- `uv run ruff check .` and `uv run pytest` pass.

# Slice 1 Backend CLI Design

## Goal

Implement the first vertical slice of OpenBBQ Phase 1: a local Python CLI can initialize a project, validate a workflow, discover trusted local plugins, execute a workflow to completion, persist artifacts and events, and inspect the resulting state.

## Scope

Slice 1 includes:

- Python package scaffolding managed by `uv`.
- `openbbq` CLI entrypoint.
- YAML project config loading and validation.
- Local plugin manifest discovery and validation without executing plugin code.
- Python plugin execution for validated workflows.
- Ordered workflow execution to completion.
- Local artifact, artifact version, workflow state, step run, and event persistence.
- CLI inspection commands for project info, plugins, workflow status, logs, artifacts, and version.
- JSON output envelopes for inspection and validation commands.
- Canonical fixtures for text and mock media workflows.

Slice 1 excludes pause/resume, abort, retry/skip, stale lock recovery, `run --force`, `run --step`, and `artifact diff`. Commands for excluded behavior may exist but must return clear "not implemented in Slice 1" errors.

## Architecture

Use a small Python package under `src/openbbq/` with explicit module boundaries:

- `cli`: argument parsing, exit codes, human and JSON output.
- `config`: YAML loading, path resolution, config hashing, and schema validation.
- `domain`: dataclasses and validation helpers for workflows, steps, step runs, plugins, tools, artifacts, artifact versions, and events.
- `plugins`: TOML manifest discovery, validation, registry construction, and Python entrypoint execution.
- `storage`: atomic JSON writes, JSONL event append, artifact content persistence, and state loading.
- `engine`: workflow validation and run-to-completion orchestration.

The CLI delegates to application services and does not own business rules. Runtime state is persisted under `.openbbq/` using the layout documented in `docs/phase1/Domain-Model.md`.

## Data Flow

`openbbq init` creates `openbbq.yaml` and `.openbbq/`. `openbbq validate <workflow>` loads config, resolves plugin search paths, discovers manifests, validates step references, validates parameters with JSON Schema, and verifies input/output artifact type compatibility. It must not import plugin code.

`openbbq run <workflow>` performs validation, creates or loads workflow state, rejects already-completed workflows, executes steps in order, resolves literal and artifact inputs, calls Python plugin entrypoints, validates plugin responses, writes artifacts and versions, records step runs, appends events, and marks the workflow `completed`.

Inspection commands read persisted state only when possible. `status` summarizes workflow state, `logs` prints events in sequence, `artifact list` and `artifact show` inspect stored artifacts, and plugin commands show discovered manifest data.

## Error Handling

Return documented CLI exit codes where Slice 1 behavior exists:

- `0`: success.
- `1`: runtime failure or unsupported Slice 2 command.
- `2`: invalid CLI usage.
- `3`: validation failure.
- `4`: plugin discovery or manifest failure.
- `5`: workflow execution failure.
- `6`: artifact lookup failure.

Human output should be concise and stable. JSON output must emit one object with `ok: true` or `ok: false`; failures include `error.code` and `error.message`.

## Testing

Use pytest with TDD for implementation. Tests must cover:

- config loading and validation failures.
- plugin manifest discovery without importing `plugin.py`.
- plugin info/list output.
- text workflow run to completion.
- mock YouTube-to-subtitle workflow run to completion with deterministic mock outputs.
- persisted artifact metadata, versions, content, and lineage.
- event log ordering.
- CLI status, logs, artifact list/show, project info, version, and JSON envelopes.
- clear errors for excluded Slice 2 commands.

Canonical fixtures should live under `tests/fixtures/projects/` and `tests/fixtures/plugins/` as documented in `docs/phase1/Project-Config.md`.

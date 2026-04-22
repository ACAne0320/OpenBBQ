# Phase 1 Completion Design

## Goal

Complete the remaining Phase 1 backend and CLI contracts after Slice 2 MVP.

Phase 1 completion should make the local headless backend launch-ready: workflows can be initialized, validated, executed, paused, resumed, aborted, recovered after stale locks, rerun from supported boundaries, inspected through artifacts and logs, and verified through the documented CLI.

## Current Baseline

The repository already implements:

- Project config loading from YAML.
- Local mock plugin discovery and manifest validation.
- Ordered workflow execution to completion.
- Artifact and artifact version persistence.
- Status, logs, artifact list/show, plugin list/info, project info/list, and JSON output basics.
- `pause_before`, `pause_after`, `resume`, paused `abort`, config hash drift rejection, and basic `run`/`resume` locks.
- Modular workflow package boundaries under `src/openbbq/core/workflow/`.

The remaining Phase 1 work is the set of explicit contracts still guarded or absent in the docs:

- `openbbq unlock <workflow>`
- stale lock detection and crash recovery guidance
- cooperative abort for `running` workflows
- `run --force`
- `run --step <step-id>`
- retry and skip error policies
- artifact text diff
- complete artifact filtering
- environment/config precedence
- launch documentation and CI workflow

## Scope

This design includes only Phase 1 backend and CLI behavior from `docs/phase1/`.

This design excludes:

- Phase 2 Agent API.
- Desktop UI.
- Real media integrations.
- Remote plugin registries.
- Distributed execution.
- Mid-step cancellation.
- Downstream artifact invalidation after `run --step`.

## Architecture

Keep `openbbq.engine` as the public facade. Continue moving workflow mechanics into small modules under `openbbq.core.workflow`.

The implementation should extend the existing modular layout instead of creating another top-level engine:

```text
src/openbbq/
  core/
    workflow/
      aborts.py
      bindings.py
      diff.py
      execution.py
      locks.py
      rerun.py
      state.py
  models/
    workflow.py
```

Responsibilities:

- `locks.py`: lock acquisition, stale lock inspection, PID liveness, unlock operations.
- `aborts.py`: abort request file paths, atomic request writes, request detection and cleanup.
- `rerun.py`: force rerun preparation, dangling step-run failure marking, artifact ID reuse lookup, single-step rerun preparation.
- `diff.py`: artifact version content diffing and validation.
- `execution.py`: shared step loop, retry/skip policy, abort request checks, pause handling.
- `bindings.py`: artifact selector resolution and output persistence, with optional artifact ID reuse.
- `state.py`: effective workflow state, config hash, output binding rebuild.

The CLI should remain thin: parse command options, load config/plugins, call facade functions, emit stable human and JSON output.

## Lock Recovery And Unlock

Lock files remain the concurrency guard for `run` and `resume`.

Behavior:

- `run` and `resume` attempt exclusive lock creation.
- If a lock exists and its PID is alive, return `workflow_locked`.
- If a lock exists and its PID is not alive, return a stale-lock error that includes the recorded PID and tells the user to run `openbbq unlock <workflow>`.
- `unlock <workflow>` reads the stale lock, prints the recorded PID, and removes the lock only when:
  - `--yes` is present, or
  - the user confirms interactively.
- `unlock` does not modify workflow state, step runs, artifacts, or events.
- Unlocking a live PID must be rejected unless later phases add an explicit unsafe override.

This keeps recovery explicit and avoids silently changing persisted workflow history.

## Running Abort

Paused abort is already synchronous. Running abort adds cooperative cancellation:

- `abort <workflow>` against `running` state writes `<workflow-state-root>/<workflow-id>.abort_requested` atomically and returns `0`.
- The abort CLI must not append workflow events for running workflows.
- The execution loop checks for the abort request after each completed step and before the next step starts.
- When observed, the engine removes the request file, emits `workflow.abort_requested`, persists `aborted`, emits `workflow.aborted`, releases the lock, and exits.
- In-flight plugin execution is allowed to finish normally.

Abort remains invalid for `pending`, `completed`, `failed`, and already `aborted` workflows.

## Forced Rerun

`run --force` supports two recovery cases:

- rerun a `completed` workflow from the beginning;
- recover a `running` workflow after a stale lock has been cleared.

Before executing:

- mark dangling `running` StepRuns as `failed` with `engine.crash_recovery`;
- reset workflow state to `pending`;
- preserve previous artifact IDs by reusing the most recent output binding for each `(step_id, output_name)`;
- create new artifact versions for outputs produced during the new run.

`run --force` is rejected for `paused` and `aborted` workflows. It cannot be combined with `--step`.

## Single-Step Rerun

`run --step <step-id>` reruns exactly one step.

Rules:

- allowed for `completed` and `failed` workflows;
- rejected for `pending`, `running`, `paused`, and `aborted`;
- rejected when `--force` is also present;
- rebuilds bindings from completed prior StepRuns;
- resolves the target step inputs from current persisted bindings;
- creates a new StepRun for the target step;
- writes new artifact versions for the target step outputs only;
- reuses existing artifact IDs where prior target-step output bindings exist;
- leaves downstream artifacts untouched.

The workflow status remains terminal after the single-step rerun:

- `completed` if the step rerun succeeds;
- `failed` if the step rerun fails under unrecovered error policy.

## Retry And Skip

Remove the current MVP guard that rejects retry/skip.

Step policy behavior:

- `abort`: current behavior, stop workflow and mark failed.
- `retry`: on plugin/validation execution failure, create another StepRun attempt until `max_retries` is exhausted. Attempts start at `1`; total attempts are `1 + max_retries`. If all attempts fail, mark workflow `failed`.
- `skip`: on failure, persist the StepRun as `skipped`, emit `step.skipped`, and continue. No output bindings are created for the skipped step.

Downstream selector resolution remains strict. If a downstream step references an output from a skipped step, input resolution fails and the workflow becomes `failed`.

The execution loop should normalize plugin exceptions into persisted error objects that include at least:

- error code;
- step ID;
- plugin name and version;
- tool name;
- attempt number;
- message.

## Plugin Pause Requests

Phase 1 docs allow plugin responses to include `pause_requested: true`. Treat this as implicit `pause_after`:

- persist outputs first;
- mark the StepRun completed;
- pause before the next step when one exists;
- complete normally if the plugin requested pause on the final step.

## Artifact Diff And Filtering

`artifact diff <v1> <v2>` supports text-like versions:

- resolve both IDs as `ArtifactVersion` records;
- accept `content_encoding == "text"`;
- accept JSON/list/dict content only when it is rendered deterministically as pretty JSON text;
- reject bytes with validation exit code `3`;
- return artifact lookup failures with exit code `6`;
- human output uses unified diff headers `--- <v1>` and `+++ <v2>`;
- JSON output includes `ok`, `from`, `to`, `format`, and `diff`.

`artifact list --workflow <workflow>` must filter artifacts by lineage workflow ID. Existing `--step` and `--type` filters should compose with it.

## Configuration Precedence

Implement the documented precedence matrix:

1. CLI flags
2. Environment variables
3. Project config
4. defaults

Required environment variables:

- `OPENBBQ_PROJECT`
- `OPENBBQ_CONFIG`
- `OPENBBQ_PLUGIN_PATH`
- `OPENBBQ_LOG_LEVEL`

Plugin paths concatenate in precedence order while preserving first occurrence:

1. repeated `--plugins`
2. `OPENBBQ_PLUGIN_PATH`
3. project config paths
4. defaults, if defaults are added later

`OPENBBQ_PROJECT` should affect CLI project root defaults. `OPENBBQ_CONFIG` should affect CLI config defaults but be overridden by `--config`.

## CLI Output And Exit Codes

Keep documented exit codes:

- `0`: success
- `1`: general runtime failure
- `2`: invalid command usage
- `3`: validation failure
- `4`: plugin discovery or manifest failure
- `5`: workflow execution failure
- `6`: artifact lookup failure

JSON errors should continue to emit one object:

```json
{"ok": false, "error": {"code": "...", "message": "..."}}
```

`--debug` may include tracebacks for unexpected errors later, but Phase 1 completion should at least preserve structured OpenBBQ errors.

## Tests

Add focused tests around each remaining contract:

- stale lock detection and unlock;
- pending stale-lock recovery followed by normal run;
- running stale-lock recovery followed by `run --force`;
- running abort request file and engine-side abort processing;
- force rerun artifact version history and artifact ID reuse;
- single-step rerun output versioning without downstream invalidation;
- retry success after an initial plugin failure;
- retry exhaustion failure;
- skip policy followed by independent downstream step;
- skipped output referenced by downstream step fails;
- plugin `pause_requested`;
- text artifact diff human and JSON output;
- artifact list workflow filter;
- configuration precedence matrix;
- Phase 1 acceptance scenarios A, B, and C as CLI process-boundary tests.

## Documentation And CI

Update repository docs after behavior lands:

- README should describe Phase 1 CLI instead of Slice 1-only behavior.
- AGENTS.md should mention implemented Phase 1 control-flow features and remaining future-phase exclusions.
- `docs/phase1/` should only change if the contract itself changes; implementation status belongs in README/AGENTS or release notes.
- Add GitHub Actions workflow for `uv sync`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest`.

## Delivery Strategy

Implement in small vertical tasks with a commit after each passing slice:

1. lock recovery and unlock;
2. running abort request files;
3. force rerun;
4. single-step rerun;
5. retry/skip and plugin pause requests;
6. artifact diff and filters;
7. config precedence;
8. documentation, CI, and final Phase 1 acceptance verification.

This order builds the recovery primitives before rerun behavior and keeps user-visible inspection features near the end, after the engine can produce the histories those commands inspect.

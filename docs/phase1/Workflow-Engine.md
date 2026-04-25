# Workflow Engine

## Responsibility

The workflow engine loads a validated workflow, resolves plugin tools, executes steps in order, persists state transitions, and records artifact lineage.

The Phase 1 engine is local and synchronous. It should be designed so an async worker or API layer can wrap it later without changing domain contracts.

## Workflow Status

Allowed workflow statuses:

- `pending`: configured but not started.
- `running`: actively executing.
- `paused`: waiting for human intervention or explicit resume.
- `completed`: all required steps completed.
- `failed`: execution stopped because a step failed and policy did not recover.
- `aborted`: execution was intentionally stopped.

## Config Hash

At `run`, `run --force`, `run --step`, and `resume`, the engine computes a SHA-256 hash over the normalized workflow config:

1. Load the YAML project config after applying config path resolution.
2. Extract the selected workflow definition and the resolved plugin search path list after configuration precedence is applied.
3. Normalize to JSON with sorted object keys and no insignificant whitespace.
4. Hash the UTF-8 encoded normalized JSON bytes.

The resulting hash is persisted as `Workflow.config_hash` and included in deterministic replay metadata.

## Step Lifecycle

For each step:

1. Resolve the referenced plugin tool.
2. Resolve input selectors to `ArtifactVersion` IDs by reading `StepRun.output_bindings[output_name].artifact_version_id` for prior completed steps.
3. Validate input artifact types and parameters.
4. Create a `StepRun` record with `status: running`, recording resolved `input_artifact_version_ids`. **Immediately append the StepRun ID to `Workflow.step_run_ids`** so it is reachable even if the process crashes during plugin execution. Emit `step_run.created` and `step.started`.
5. Call the plugin execution contract.
6. Validate declared output artifact types against the plugin response.
7. Persist output artifacts and artifact versions. For each output name, write both `artifact_id` and `artifact_version_id` into `StepRun.output_bindings`.
8. Mark `StepRun.status` as `completed` (or `failed`).
9. Emit `step.completed` or `step.failed`.
10. Check for an abort request file between steps (see Abort section). Advance `current_step_id`.

## Pause And Resume

A workflow pauses when a step's `pause_before` or `pause_after` flag is `true`, or when a plugin response includes `pause_requested: true`.

- `pause_before: true` on a step causes the engine to pause and persist state **before** invoking the plugin for that step.
- `pause_after: true` on a step causes the engine to pause and persist state **after** the step completes and its artifacts are written.
- A plugin returning `pause_requested: true` is treated as an implicit `pause_after` for that step.

Pause requirements:

- Persist workflow status as `paused`.
- Persist the next step to execute.
- Persist all artifacts produced before the pause.
- Remove the workflow lock file before the CLI process exits so a later `openbbq resume <workflow>` process can acquire a fresh lock.
- Emit `workflow.paused`.

Resume requirements:

- Reload workflow state from disk.
- Revalidate current config and plugin availability.
- Recompute the normalized workflow config hash and compare it to `Workflow.config_hash`. If the hash changed while paused, reject `resume` with exit code `3` and a validation error explaining that Phase 1 does not support resuming across workflow config edits.
- Rebuild the in-memory selector→artifact map by reading `StepRun.output_bindings[output_name].artifact_version_id` for all `completed` step runs recorded in `Workflow.step_run_ids`. Step runs with `status: running` (from a prior crash) are treated as `failed` for selector resolution purposes — they do not supply output bindings. This is what makes selector resolution safe across process restarts.
- Continue from the persisted next step.
- Emit `workflow.resumed`.

Phase 1 does not support workflow config edits while paused. Manual changes to step order, step parameters, outputs, plugin paths, or pause flags must be rejected on resume through the config hash check. If artifact content changes while paused, the resumed workflow should use the artifact version selected in the persisted workflow state unless the user explicitly selects a newer version.

Required config-drift tests:

- Pause a workflow, change a paused step parameter, then confirm `openbbq resume <workflow>` exits `3`.
- Pause a workflow, change only artifact content outside workflow config, then confirm resume still uses the persisted artifact version.

## Abort

`openbbq abort <workflow>` may be called against a workflow in `paused` or `running` status.

**Aborting a `paused` workflow** is synchronous: the engine transitions the status to `aborted`, persists state, removes the lock file, emits `workflow.aborted`, and the command returns exit code `0`.

**Aborting a `running` workflow** uses cooperative cancellation and returns immediately. The abort command writes an abort request file atomically (write to a temp file in the same directory, then rename) at:

```
<workflow-state-dir>/<workflow-id>.abort_requested
```

The command prints a message that the abort will take effect between steps and returns exit code `0`. The running engine process checks for this file after each step completes and before the next one starts (step 10 of the step lifecycle). When detected, the engine removes the request file, emits `workflow.abort_requested`, persists `aborted` status and all artifacts written so far, removes the lock file, emits `workflow.aborted`, and exits. The in-flight plugin call is allowed to complete normally. The abort CLI does **not** emit `workflow.abort_requested` directly — only the engine does, to avoid concurrent writes to the event log.

Mid-step interruption is **not** supported in Phase 1. `openbbq status` will show `running` until the engine processes the request.

Abort requirements:

- For paused workflows: synchronous transition to `aborted`.
- For running workflows: atomic write of abort request file; return immediately with exit `0`.
- Persist workflow status as `aborted` (engine side, when processed).
- Persist all artifacts produced before the abort point.
- Remove the lock file as part of the final `aborted` transition.
- Emit `workflow.aborted`.
- Return exit code `1` if the workflow was not in an abortable state (e.g., already `completed` or `aborted`).

## Forced Rerun

`openbbq run <workflow> --force` is allowed when the workflow status is `completed` or `running` (crash-recovered, no lock file present). It resets the workflow to `pending` before starting a fresh execution.

Before executing the first step, the engine must:

1. Mark any `StepRun` records with `status: running` as `failed` with error code `engine.crash_recovery`. This ensures orphaned step runs from a prior crash are not treated as completed and do not contribute output bindings.
2. Reset `Workflow.status` to `pending` and clear `current_step_id`.

**Artifact reuse:** Forced reruns produce new `ArtifactVersion` records but reuse existing `Artifact` IDs where possible. For each step output, the engine looks up the `artifact_id` from the most-recent `StepRun.output_bindings` for that `(step_id, output_name)` pair. If found, a new version is appended to that artifact and `current_version_id` is updated. If not found (the step never completed previously), a new `Artifact` is created as usual.

This keeps the logical artifact entity stable across reruns while preserving the full version history.

## Guard Against Double-Run

The engine uses a **workflow lock file** to prevent concurrent execution, not status checking alone. Status checking is a TOCTOU race: two CLI processes can both read `pending` before either writes `running`.

Lock file behavior:

- On `run` or `resume`: attempt to create `<workflow-state-dir>/<workflow-id>.lock` exclusively (e.g., using `O_CREAT | O_EXCL` or equivalent). If the lock already exists, reject the request with a clear error message and exit code `1`.
- The lock file should record the PID of the process holding it so stale locks (from crashed processes) can be identified.
- On `paused`, `completed`, `failed`, or `aborted`: remove the lock file as part of the persisted state transition before the CLI process exits.
- If the lock file exists but the recorded PID is no longer running, the CLI should warn the user about a stale lock and direct them to run `openbbq unlock <workflow>` before retrying.
- If a process crashes after lock creation but before writing workflow status, the workflow may remain `pending` with a stale lock. After `openbbq unlock <workflow>`, a normal `openbbq run <workflow>` may proceed. If the workflow state is `running` after unlock, use `openbbq run <workflow> --force` for crash recovery.

Required lock recovery tests:

- `pending` workflow plus stale lock: `unlock`, then plain `run` succeeds.
- `running` workflow plus stale lock and dangling `StepRun`: `unlock`, then `run --force` marks dangling `StepRun` as failed and starts fresh.

## Error Handling

Each step has an `on_error` policy:

- `abort`: stop workflow and mark it `failed`.
- `retry`: retry until `max_retries` is exhausted, then mark it `failed`. Each attempt creates a separate `StepRun` with incremented `attempt`.
- `skip`: record the failure, mark the failed `StepRun` as `skipped`, emit `step.skipped`, and continue if downstream inputs remain valid. A skipped step does not create output bindings.

Plugin exceptions must be normalized into engine errors with:

- error code.
- step ID.
- plugin name and version.
- tool name.
- retry count.
- short message.
- structured details when available.

## Deterministic Replay

Phase 1 deterministic replay means the engine can explain what ran and with which inputs. It does not require nondeterministic tools, such as LLM calls, to produce identical output.

Replay metadata must include:

- workflow config hash.
- plugin name and version.
- tool name.
- parameter values.
- input artifact version IDs and hashes.
- output artifact version IDs and hashes.

## Event Persistence

Events are append-only. They should be useful for CLI status, logs, debugging, and future API streaming.

Event records should not depend on process memory. A workflow run that crashes should still leave inspectable events up to the failure point.

Storage requirements:

- Store workflow events in the project SQLite `workflow_events` table.
- Each row stores query columns and the canonical event JSON object with the schema from [Domain Model](./Domain-Model.md).
- Append events synchronously in a database transaction before returning from the state transition.
- Assign `sequence` by reading the current maximum event sequence for the workflow and adding `1`.
- Do not write or recover `events.jsonl`; SQLite is the event source of truth.

## Validation Before Execution

`openbbq validate <workflow>` must check:

- project config YAML matches [Project Config](./Project-Config.md).
- workflow exists.
- every step ID is unique within the workflow.
- every `tool_ref` resolves to a discovered plugin tool.
- parameters match the tool schema.
- input artifact types are compatible with the tool declaration.
- output artifact names are unique **within each step** (not globally). Two steps may declare the same output name independently; selectors already disambiguate by `<step_id>.<output_name>`.
- error policy values are valid.
- `pause_before` and `pause_after` are valid booleans when present.

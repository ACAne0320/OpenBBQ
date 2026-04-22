# Slice 2 Control Flow MVP Design

## Goal

Implement the next Phase 1 vertical slice for persisted workflow control flow: pause, resume, paused abort, and basic run/resume locking.

This slice should make OpenBBQ workflows survive process boundaries while keeping the codebase modular enough for the later retry, rerun, unlock, and artifact diff work.

## Scope

This design includes:

- `pause_before` and `pause_after` step flags.
- `openbbq resume <workflow>`.
- `openbbq abort <workflow>` for paused workflows only.
- Config hash persistence and paused config drift rejection.
- Basic workflow lock files for `run` and `resume`.
- A canonical `text-pause` fixture.
- Tests for process-restart style CLI pause/resume behavior.

This design excludes:

- Running workflow cooperative abort request files.
- `openbbq unlock`.
- Stale lock detection and recovery.
- Retry and skip policies.
- `run --force`.
- `run --step`.
- `artifact diff`.
- Broader artifact or workflow model redesign beyond the files needed for this slice.

## Package Layout

The Slice 1 code uses flat modules under `src/openbbq/`. Slice 2 should introduce a clearer package layout while keeping the public imports stable.

New modules:

```text
src/openbbq/
  core/
    __init__.py
    workflow/
      __init__.py
      bindings.py
      execution.py
      locks.py
      state.py
  models/
    __init__.py
    workflow.py
```

Existing modules stay in place for compatibility:

- `openbbq.engine` remains the public facade for workflow validation and control commands.
- `openbbq.domain` remains available during this slice. Workflow-related dataclasses can be re-exported from `openbbq.models.workflow` rather than moved all at once.
- `openbbq.cli` continues to call facade functions from `openbbq.engine`.
- `openbbq.storage` remains the durable store abstraction.

This avoids a large import churn while establishing the package boundaries expected for later phases.

## Module Responsibilities

### `openbbq.models.workflow`

Owns workflow model names for new code.

For this slice, it should import and re-export the existing workflow-related dataclasses from `openbbq.domain`:

- `ProjectConfig`
- `WorkflowConfig`
- `StepConfig`
- `StepOutput`

Later phases can move model definitions here when the API shape is stable.

### `openbbq.core.workflow.state`

Owns persisted workflow state behavior that is not storage mechanics:

- Build a pending state for configured workflows that have not run.
- Compute a workflow config hash from the selected workflow definition and resolved plugin paths.
- Read workflow state and normalize missing state to pending state where appropriate.
- Require a workflow to be in a specific status.
- Rebuild selector output bindings from completed `StepRun` records listed in `Workflow.step_run_ids`.

The config hash should be a SHA-256 hash of normalized JSON containing:

- selected workflow ID and definition,
- resolved plugin search paths,
- project config version.

Any config change that can affect resumed execution should change the hash.

### `openbbq.core.workflow.locks`

Owns workflow lock files:

- Create `<workflow-state-dir>/<workflow-id>/<workflow-id>.lock` using exclusive file creation.
- Store the current PID and creation timestamp.
- Reject `run` and `resume` when the lock exists.
- Remove the lock on `paused`, `completed`, `failed`, or `aborted`.

This MVP should not attempt stale lock detection. If a lock exists, the command fails with a clear execution error.

### `openbbq.core.workflow.bindings`

Owns artifact selector and output binding behavior:

- Resolve literal inputs and artifact selector inputs into plugin request inputs.
- Read selected artifact versions from storage.
- Persist step outputs as artifact versions.
- Update the in-memory selector binding map after step completion.

This moves the Slice 1 helper logic out of the public engine facade before resume adds more paths through the same behavior.

### `openbbq.core.workflow.execution`

Owns the shared execution loop:

- Start execution from the first step for `run`.
- Start execution from a persisted `current_step_id` for `resume`.
- Apply `pause_before` before plugin execution.
- Apply `pause_after` after artifact persistence and completed `StepRun` persistence.
- Persist `StepRun` IDs before plugin execution so crash recovery can inspect partial progress later.
- Emit workflow and step events.
- Release locks before returning from paused or terminal states.

The execution loop should be the only code path that invokes plugin code.

### `openbbq.engine`

Remains the public facade:

- `validate_workflow(config, registry, workflow_id)`
- `run_workflow(config, registry, workflow_id)`
- `resume_workflow(config, registry, workflow_id)`
- `abort_workflow(config, workflow_id)`

It should coordinate validation and delegate runtime behavior to `openbbq.core.workflow`.

## Workflow State Contract

Persisted workflow state should include:

```json
{
  "id": "text-demo",
  "name": "Text Demo",
  "status": "paused",
  "current_step_id": "uppercase",
  "config_hash": "<sha256>",
  "step_run_ids": ["sr_..."]
}
```

Status meanings in this MVP:

- `pending`: configured but no persisted run state exists.
- `running`: engine is actively executing under a lock.
- `paused`: engine stopped at a resumable boundary and released the lock.
- `completed`: all steps completed and lock released.
- `failed`: execution failed and lock released.
- `aborted`: paused workflow was intentionally stopped and lock released.

## Run Behavior

`run_workflow` should:

1. Validate the workflow.
2. Reject persisted statuses `running`, `paused`, `completed`, and `aborted`.
3. Acquire the workflow lock.
4. Persist `running` state with `config_hash`.
5. Execute from step index `0`.
6. Release the lock on `paused`, `completed`, or `failed`.

`run` should still reject completed workflows. `run --force` remains unsupported in this slice.

## Pause Behavior

### `pause_before`

When a step has `pause_before: true`:

1. Persist workflow state as `paused`.
2. Set `current_step_id` to the paused step ID.
3. Do not create a `StepRun` for the paused step.
4. Emit `workflow.paused`.
5. Release the workflow lock.
6. Return a result with status `paused`.

### `pause_after`

When a step has `pause_after: true`:

1. Execute the step normally.
2. Persist output artifacts and mark the `StepRun` completed.
3. If there is a next step, persist workflow state as `paused` with `current_step_id` set to the next step.
4. Emit `workflow.paused`.
5. Release the workflow lock.
6. Return a result with status `paused`.

If there is no next step after a pause-after step, the workflow should complete instead of pausing with a null next step.

## Resume Behavior

`resume_workflow` should:

1. Validate the workflow and plugins.
2. Read persisted state.
3. Require status `paused`; otherwise return an execution error.
4. Compare persisted `config_hash` with the current hash; if different, return a validation error with exit code `3`.
5. Rebuild output bindings from completed `StepRun` records listed in `step_run_ids`.
6. Acquire the workflow lock.
7. Emit `workflow.resumed`.
8. Continue execution at `current_step_id`.
9. Release the lock on `paused`, `completed`, or `failed`.

Resume must work across CLI process boundaries because it depends only on persisted workflow state, step runs, artifacts, and events.

## Abort Behavior

`abort_workflow` in this MVP should only support paused workflows:

1. Read persisted state.
2. Require status `paused`.
3. Persist status `aborted`.
4. Keep `current_step_id` and `step_run_ids` for inspection.
5. Emit `workflow.aborted`.
6. Release the workflow lock if present.

Abort should reject `pending`, `running`, `completed`, `failed`, and `aborted` states with exit code `1`.

Running abort request files remain a later Slice 2 increment.

## CLI Behavior

Remove Slice 1 guardrails for:

- `resume`
- `abort`

Keep Slice 1-style unsupported errors for:

- `unlock`
- `run --force`
- `run --step`
- `artifact diff`

Expected CLI results:

- `openbbq run text-demo` on the pause fixture prints a paused message and returns `0`.
- `openbbq status text-demo --json` reports `status: "paused"` and the correct `current_step_id`.
- `openbbq resume text-demo` completes the workflow and returns `0`.
- `openbbq abort text-demo` on a paused workflow writes `aborted` and returns `0`.
- `openbbq resume text-demo` on an aborted workflow returns exit code `1`.
- `openbbq resume text-demo` after paused config drift returns exit code `3`.

## Fixtures

Add:

```text
tests/fixtures/projects/text-pause/openbbq.yaml
```

It should use the text-basic workflow with `pause_before: true` on the `uppercase` step.

Tests may create additional temporary configs for `pause_after` and config drift rather than adding more canonical fixtures.

## Testing

Add focused tests for:

- Config loading accepts pause flags now that Slice 2 implements them.
- Validation no longer rejects pause flags.
- `run_workflow` pauses before a step and does not create a `StepRun` for that step.
- `resume_workflow` completes from a persisted paused state.
- CLI run/status/resume works across separate `main()` calls.
- Paused abort persists `aborted` and preserves artifacts.
- Resume rejects aborted workflows.
- Resume rejects paused config drift with a validation error.
- Lock file exists during execution and is removed on paused/completed/failed/aborted.
- Run and resume reject an existing lock file.

Existing Slice 1 tests should continue to pass.

## Migration Strategy

The implementation should move code in small steps:

1. Add package directories and re-export model types.
2. Add lock helpers and tests.
3. Move artifact binding helpers out of `engine.py`.
4. Add state helpers and config hash tests.
5. Move the execution loop into `core.workflow.execution`.
6. Add pause/resume behavior.
7. Add paused abort behavior.
8. Update CLI command dispatch.
9. Remove obsolete Slice 1 guardrail tests for resume/abort and replace them with behavior tests.

Each step should keep the full test suite passing before continuing.

## Open Decisions

This design intentionally chooses simple lock rejection over stale lock recovery. The later `unlock` increment can build on the same `locks.py` file without changing the pause/resume contract.

This design also keeps model migration shallow. New code should import workflow names from `openbbq.models.workflow`, but existing code does not need to be rewritten solely for import style.

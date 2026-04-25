# Run lifecycle executor cleanup design

## Purpose

Background run execution is part of the backend surface that the desktop UI will
depend on. The current run service preserves the needed behavior, but the start
and resume execution paths duplicate lifecycle state changes, project context
loading, workflow command execution, and error-to-run-failure handling. This
cleanup extracts the shared lifecycle mechanics so future run behavior changes
have one place to update.

## Scope

In scope:

- Refactor private execution helpers in `src/openbbq/application/runs.py`.
- Keep public functions and request/result models unchanged.
- Keep `_execute_run()` and `_execute_resume()` as private entry points because
  they are used by current executor submission paths and tests.
- Add or adjust focused tests only where they document behavior that the
  extraction must preserve.
- Preserve existing broad exception-to-failed-run behavior.

Out of scope:

- Changing run status names, run record schema, API response schemas, or storage
  layout.
- Changing the thread executor, queueing behavior, or background execution
  model.
- Adding structured traceback persistence, diagnostic artifacts, retries, or
  cancellation behavior.
- Refactoring workflow command functions or engine execution.

## Current code evidence

`src/openbbq/application/runs.py` currently has two similar private helpers:

- `_execute_run(run_id, request)` loads project context, reads the run, marks it
  running, calls `run_workflow_command(...)`, converts `OpenBBQError` and
  unexpected `Exception` into failed run records, then writes final status and
  latest event sequence.
- `_execute_resume(run_id, request)` repeats the same lifecycle shape, calls
  `resume_workflow_command(...)`, and clears `error` on successful completion.

This duplication means status transitions, failure handling, timestamps, and
latest event sequence updates can drift between initial run and resume paths.

## Design

Add a private lifecycle helper in `src/openbbq/application/runs.py`:

- `_execute_run_lifecycle(run_id, request, command, *, clear_error_on_success=False) -> None`

The helper owns the shared sequence:

1. Load `ProjectContext` from `request.project_root`, `request.config_path`, and
   `request.plugin_paths`.
2. Read the current `RunRecord`.
3. Write the run as `running` and set `started_at` using the existing `_now()`.
4. Execute the supplied zero-argument `command`.
5. On `OpenBBQError`, call `_mark_run_failed(...)` with the exception code and
   message, then return.
6. On any other `Exception`, call `_mark_run_failed(...)` with
   `code="internal_error"` and `message=str(exc)`, then return.
7. On success, read the run again, update `status` from the command result,
   update `latest_event_sequence`, and set `completed_at` when the final status
   is `completed`, `failed`, or `aborted`.
8. If `clear_error_on_success=True`, set `error=None` in the successful update.

`_execute_run()` becomes a thin wrapper that builds the existing
`WorkflowRunRequest` command and calls `_execute_run_lifecycle(...)`.

`_execute_resume()` becomes a thin wrapper that builds the existing
`WorkflowCommandRequest` command and calls `_execute_run_lifecycle(...,
clear_error_on_success=True)`.

The helper remains private to avoid creating a new public application contract.
The command type can use a small local `Protocol` or `Callable[[],
WorkflowRunResult]`; either is acceptable as long as the implementation stays
simple and type-readable.

## Behavior preservation

This cleanup must preserve:

- `create_run(..., execute_inline=True)` still returns a final run record after
  executing the workflow synchronously.
- `create_run(..., execute_inline=False)` still submits `_execute_run`.
- `resume_run(..., execute_inline=True)` still returns a final run record after
  resume completes.
- `resume_run(..., execute_inline=False)` still submits `_execute_resume`.
- `OpenBBQError` still becomes a failed run with the original error code and
  message.
- Unexpected exceptions still become failed runs with `internal_error` and the
  exception string.
- Successful initial runs preserve existing error field behavior.
- Successful resumes clear any previous run error.
- Final `latest_event_sequence` is still read after workflow command execution.
- `completed_at` is still set only for terminal statuses:
  `completed`, `failed`, and `aborted`.

## Testing

Existing tests already cover:

- initial inline run completes;
- resume completes and updates latest event sequence;
- abort syncs final run status;
- unexpected initial run exceptions become `internal_error`;
- non-blocking resume still submits `_execute_resume`.

Add focused coverage for at least one currently implicit behavior before
refactoring:

- `OpenBBQError` from initial execution preserves its domain error code and
  message in the run record; or
- a successful resume clears a previous run error if one is present.

The implementation plan can choose the smaller test that exercises the shared
lifecycle path directly through public functions or by calling private helpers
only if public setup is impractical. Prefer public application functions when
reasonable.

Final verification must include:

- `uv run pytest tests/test_application_runs.py -q`
- `uv run pytest tests/test_api_workflows_artifacts_runs.py -q`
- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`

## Acceptance criteria

- `_execute_run()` and `_execute_resume()` no longer duplicate the shared
  lifecycle control flow.
- A private lifecycle helper owns running-state marking, command execution,
  error-to-failed-run conversion, and successful final run update.
- Public run service behavior is unchanged.
- Focused tests cover the extraction and at least one previously implicit
  lifecycle behavior.
- No desktop API, CLI, storage schema, or engine behavior changes are introduced.

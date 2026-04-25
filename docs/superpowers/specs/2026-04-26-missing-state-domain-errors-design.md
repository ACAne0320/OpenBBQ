# Missing-state domain errors design

## Context

Most user-facing backend errors already use `OpenBBQError` subclasses so CLI
and API callers receive stable error codes, messages, and exit/status codes.
Artifact lookups use `ArtifactNotFoundError`, and config-file absence is
normalized to `ValidationError`.

Some storage and workflow state paths still leak Python `FileNotFoundError`:

- `src/openbbq/storage/runs.py::read_run()` raises `FileNotFoundError` for a
  missing run.
- `src/openbbq/storage/workflow_repository.py` raises `FileNotFoundError` for a
  missing workflow state or step run.
- `src/openbbq/workflow/state.py` and `src/openbbq/workflow/rerun.py` catch
  `FileNotFoundError` to model missing workflow state/history.
- `src/openbbq/api/errors.py` has a generic `FileNotFoundError` handler that
  turns missing run state into a generic `not_found` envelope.

Those paths are domain state misses, not filesystem misses. Desktop UI and API
callers benefit from stable domain-specific error codes such as
`run_not_found`, while workflow internals still need to treat missing state and
step runs as recoverable history gaps in the same places they do today.

## Goals

- Introduce a shared `NotFoundError` domain base class under `OpenBBQError`.
- Keep `ArtifactNotFoundError` behavior and code stable while making it a
  domain not-found subtype.
- Add domain-specific `RunNotFoundError`, `WorkflowStateNotFoundError`, and
  `StepRunNotFoundError`.
- Replace storage-level `FileNotFoundError` raises for runs, workflow state,
  and step runs with the new domain errors.
- Replace workflow internal `except FileNotFoundError` catches with the new
  specific errors.
- Make API status mapping derive 404 from the domain not-found base.
- Remove API reliance on a generic `FileNotFoundError` handler for domain
  misses.
- Preserve existing recovery behavior for missing effective workflow state and
  missing historical step runs.

## Non-goals

- Do not wrap every real filesystem `FileNotFoundError`.
- Do not change config loading behavior for missing config files.
- Do not change plugin dependency errors such as missing `ffmpeg`, missing
  `openai`, or missing browser cookies.
- Do not change workflow lock file handling; it intentionally catches real
  lock-file absence and already raises an `ExecutionError` where user-facing.
- Do not change artifact not-found messages or `artifact_not_found` code.
- Do not invent a generic resource registry or HTTP exception layer.

## Proposed architecture

Update `src/openbbq/errors.py`:

- Add `NotFoundError(OpenBBQError)` with code `not_found` and exit code `6`.
- Make `ArtifactNotFoundError` inherit from `NotFoundError` while preserving
  its default code `artifact_not_found`.
- Add:
  - `RunNotFoundError`, code `run_not_found`;
  - `WorkflowStateNotFoundError`, code `workflow_state_not_found`;
  - `StepRunNotFoundError`, code `step_run_not_found`.

Update storage accessors:

- `storage.runs.read_run()` raises `RunNotFoundError`.
- `WorkflowRepository.read_workflow_state()` raises
  `WorkflowStateNotFoundError`.
- `WorkflowRepository.read_step_run()` raises `StepRunNotFoundError`.

Update workflow internals:

- `workflow.state.read_effective_workflow_state()` catches
  `WorkflowStateNotFoundError` and still returns a pending state.
- `workflow.state.rebuild_output_bindings()` and `workflow.rerun` catch
  `StepRunNotFoundError` and still ignore missing historical step runs.

Update API error mapping:

- `_status_code()` returns HTTP 404 for `isinstance(error, NotFoundError)`.
- Remove the domain-facing `FileNotFoundError` handler from
  `api.errors.install_error_handlers()`.

## Error contracts

Expected domain error codes:

- missing artifact: `artifact_not_found` (unchanged);
- missing artifact version: `artifact_not_found` (unchanged);
- missing run: `run_not_found`;
- missing workflow state: `workflow_state_not_found`;
- missing step run: `step_run_not_found`.

Expected messages keep the current human-readable shape:

- `run not found: <run_id>`;
- `workflow state not found: <workflow_id>`;
- `step run not found: <step_run_id>`.

API responses for these errors use the error's domain code and HTTP 404.

## Testing

Add focused tests:

- `storage.runs.read_run()` raises `RunNotFoundError` with code
  `run_not_found`.
- `WorkflowRepository.read_workflow_state()` raises
  `WorkflowStateNotFoundError`.
- `WorkflowRepository.read_step_run()` raises `StepRunNotFoundError`.
- `read_effective_workflow_state()` still returns pending state when workflow
  state is missing.
- `rebuild_output_bindings()` still ignores a missing historical step run.
- API missing run response returns HTTP 404 with code `run_not_found`.
- API missing artifact response still returns HTTP 404 with code
  `artifact_not_found`.
- Package layout import coverage imports the new error classes through
  `openbbq.errors`.

Run:

- `uv run pytest tests/test_storage_runs.py tests/test_storage_repositories.py tests/test_workflow_state.py tests/test_api_workflows_artifacts_runs.py tests/test_package_layout.py -q`
- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`

## Acceptance criteria

- Domain missing state no longer raises or catches `FileNotFoundError` in run,
  workflow state, or step-run repository paths.
- Recoverable missing workflow state/history behavior is unchanged.
- API not-found responses are driven by `OpenBBQError` domain subclasses.
- No broad filesystem error wrapping is introduced.
- The code-quality audit closure document marks missing-state domain errors
  complete after implementation and verification.

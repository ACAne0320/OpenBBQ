# Desktop backend readiness design

> Status: implemented. Current code exposes the readiness surfaces described
> here through `openbbq.application` services and `openbbq.api` routes.

## Goal

Prepare the Python backend for the first desktop UI integration by making the
FastAPI sidecar stable enough for Electron to call directly. The desktop should
not parse CLI output or duplicate CLI workflow orchestration.

This design focuses on the backend work needed before wiring a rich UI:

- stable typed API response models for workflow, run, artifact, and event views;
- predictable API error envelopes for missing resources and invalid lifecycle
  operations;
- run/job lifecycle hardening for background execution;
- API-accessible generated subtitle workflows for local files and remote video
  URLs;
- artifact preview and export operations suitable for subtitle and transcript
  UI surfaces;
- safe sidecar startup defaults for desktop production.

## Current baseline

The repository already has a working headless backend:

- `openbbq.application.workflows` exposes run, resume, abort, unlock, status,
  logs, and events.
- `openbbq.application.artifacts` exposes import, list, show, version lookup,
  and diff.
- `openbbq.application.runs` persists run records and can execute workflows in a
  background thread.
- `openbbq.api` exposes FastAPI routes for health, projects, plugins, runtime,
  workflows, runs, artifacts, and SSE events.
- `openbbq.application.quickstart` writes and starts generated local and YouTube
  subtitle jobs, including generated project context needed by run, event,
  artifact, preview, export, and file routes.
- `openbbq.cli.app` is an adapter. The API quickstart routes call
  `openbbq.application.quickstart`; the CLI quickstart commands keep
  synchronous output-file orchestration while sharing the lower-level workflow
  template, artifact import, and workflow run services.

The current automated baseline passes with `uv run pytest`.

## Non-goals

This milestone does not build the Electron UI, an IPC bridge, packaging, or a
multi-project desktop workspace manager. It also does not redesign the workflow
engine, plugin trust model, or artifact storage format.

## Approach

Implement the work as a thin API and application-service hardening milestone.
The core engine remains the source of truth. The API adapts application service
models into Pydantic response contracts and does not call CLI helpers.

The first desktop UI can then rely on these backend surfaces:

- project and workflow dashboard queries;
- workflow run, resume, abort, status, event stream, and logs;
- artifact list, metadata, preview content, file download, export, and diff;
- runtime provider setup, secret checks, model status, and doctor checks;
- generated local and YouTube subtitle jobs exposed as backend commands.

## API contract design

All desktop-facing JSON routes return `ApiSuccess[T]` or `ApiErrorResponse`.
Routes that previously used `ApiSuccess[dict[str, Any]]` now have concrete
response models in `openbbq.api.schemas`.

Workflow routes return:

- `WorkflowListData` with workflow summaries;
- `WorkflowDetailData` with steps, declared outputs, current state, latest event
  sequence, and validation result when requested;
- `WorkflowStatusData`;
- `WorkflowEventsData`.

Artifact routes return:

- `ArtifactListData`;
- `ArtifactShowData`;
- `ArtifactVersionData`;
- `ArtifactDiffData`;
- `ArtifactImportData`;
- `ArtifactExportData`.

Plugin manifest metadata can keep dynamic parameter JSON Schema, but the outer
shape remains typed. Event stream payloads continue to use `EventStreamItem`.

## Error handling design

The API must never return a raw 500 for expected user or desktop errors. Missing
run records, workflow state, step runs, artifacts, or artifact versions become
typed `not_found` errors with HTTP 404. Invalid workflow lifecycle operations
remain 409 when they use existing `invalid_workflow_state` or
`invalid_command_usage` codes. Request validation remains 422 with Pydantic error
details.

Unexpected exceptions inside background run execution are recorded on the
`RunRecord` as `status="failed"` with `error.code="internal_error"`. The API
process may still log the exception, but the desktop must be able to observe the
failed run record.

## Run lifecycle design

`RunRecord` stays the desktop handle for workflow execution. The run service
keeps the existing workflow-scoped engine state, but the record is hardened for
desktop use:

- create and resume operations both return quickly when executed through the
  API;
- queued and running records are treated as active;
- failed, paused, completed, and aborted records are not active;
- unexpected background exceptions update the run to failed;
- missing run IDs return 404 through the API;
- run list ordering is deterministic.

Resume keeps using the existing workflow resume command, but API route behavior
should match create-run behavior: it should not block a desktop request during a
long workflow continuation.

## Generated subtitle API design

Non-blocking API subtitle orchestration lives in
`openbbq.application.quickstart`. CLI quickstart commands still run the generated
workflow synchronously and write the requested output file after completion.

The backend exposes:

- `POST /quickstart/subtitle/local`
- `POST /quickstart/subtitle/youtube`

The local request accepts source file path, source language, target language,
provider, optional chat model, ASR options, optional output path, and force
behavior. The YouTube request accepts URL, source language, target language,
provider, optional chat model, ASR options, quality, auth mode, browser cookie
options, optional output path, and force behavior.

Both routes create or reuse an isolated generated project under
`.openbbq/generated`, start a run through the same run service, and return a
typed job response containing:

- generated project root;
- generated config path;
- workflow ID;
- run ID;
- output path when requested;
- source artifact ID for local imports when available.

The API should not wait for the full media workflow to finish before returning.
The desktop follows run status and run-scoped workflow events to drive progress.
Because generated subtitle jobs live in isolated generated projects, the sidecar
keeps enough run-to-project context for `/runs/{run_id}`, run events, run event
streams, run artifacts, and artifact-version preview/export/file routes to work
without restarting the sidecar against the generated project.

## Artifact preview and export design

The desktop needs artifact metadata and bounded preview content without always
loading entire files into JSON responses.

Add application services and API routes for:

- metadata-only artifact version lookup;
- preview content for text, JSON, subtitle, transcript, translation, and QA
  artifact versions;
- file-backed artifact download using the existing file endpoint;
- exporting a text-like artifact version to a caller-provided local path.

Preview responses include content encoding, content size, truncation status, and
content for text/JSON values. Binary and file-backed content returns metadata
only unless the caller uses the file route. Text and JSON previews must read at
most the requested preview byte budget plus one sentinel byte before returning,
so a preview request does not load a large artifact version into memory.

## Sidecar security design

For production desktop use, the sidecar must require a bearer token. Development
can still run without a token by passing an explicit development flag. Health and
OpenAPI routes remain auth-exempt for startup and local development.

The server already binds to `127.0.0.1` by default and supports `--token`.
Harden startup so a production invocation without a token fails with a typed
startup error or parser error. Keep an explicit `--no-token-dev` option for local
manual testing.

## Testing strategy

Use TDD for each behavior change:

- API schema tests for every new response model;
- API route tests with `TestClient` for typed responses and error envelopes;
- application run tests for unexpected exception handling and non-blocking resume;
- quickstart application and API tests using mock text/media fixtures;
- artifact preview/export tests using temporary project fixtures;
- server argument tests for token enforcement and explicit dev no-token mode.

Run focused tests after each task, then run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Acceptance criteria

- Desktop-facing API routes do not use `ApiSuccess[dict[str, Any]]` for
  workflow, run, event, artifact, quickstart, plugin, runtime, or project
  responses.
- Missing run IDs return a JSON 404 error envelope, not raw 500.
- Background runs record unexpected exceptions as failed run records.
- API resume is non-blocking in the same way as API run creation.
- Local and YouTube generated subtitle jobs can be started via API without
  calling CLI code.
- Artifact preview and export are available through application services and API
  routes.
- Production sidecar startup requires a bearer token unless an explicit dev flag
  disables auth.
- All tests and Ruff checks pass.

## Spec self-review

- Placeholder scan: no placeholder sections or unresolved requirements remain.
- Internal consistency: the design keeps CLI as an adapter and puts reusable
  behavior into application services before exposing it through API routes.
- Scope check: the work is one backend readiness milestone and excludes Electron
  UI, packaging, and IPC.
- Ambiguity check: production token behavior and generated workflow API behavior
  are explicitly defined.

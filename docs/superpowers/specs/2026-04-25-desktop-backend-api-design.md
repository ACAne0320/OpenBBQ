# Desktop Backend API Design

> Status: this design has been implemented and partially superseded by the
> desktop backend readiness work. Current code uses the `openbbq.api` FastAPI
> sidecar, `openbbq.application` services, SQLite-backed project storage, run
> records, typed envelopes, and SSE routes described below.

## Goal

Prepare OpenBBQ for the Phase 3 desktop by adding a stable, typed backend API
adapter over the existing headless application services. The desktop should be a
rich client of the backend, not a second workflow engine.

The target integration model is:

```text
Electron renderer -> preload IPC -> Electron main -> Python FastAPI sidecar -> OpenBBQ application services
```

The API should make workflow execution, event streaming, artifact inspection,
runtime settings, diagnostics, and plugin metadata available to the desktop
through Pydantic-validated contracts.

## Current Baseline And Closed Gaps

The repository already has the right backend foundation:

- `src/openbbq/application/workflows.py` exposes workflow run, resume, abort,
  unlock, status, and logs operations.
- `src/openbbq/application/artifacts.py` exposes artifact import, list, show,
  and diff operations.
- `src/openbbq/engine/service.py` owns workflow execution entry points without
  depending on CLI parsing.
- `src/openbbq/workflow/*` persists state transitions, step runs, events, locks,
  abort requests, retries, skips, pauses, resumes, and reruns.
- `src/openbbq/storage/*` keeps workflow state, events, step run records, run
  records, artifacts, and artifact-version metadata in SQLite under
  `.openbbq/`, with artifact payloads stored on disk.
- `src/openbbq/runtime/*` owns provider profiles, settings, secrets, redaction,
  model cache settings, and doctor checks.
- `src/openbbq/cli/app.py` is an adapter over command modules that call
  application services.

The original desktop API gaps were:

- no long-lived backend process;
- no HTTP or streaming API at that point;
- no API-level authentication boundary for local desktop use;
- no run handle for background execution;
- no live event subscription contract;
- no shared API response envelope;
- several CLI-only paths for project, plugin, runtime, auth, doctor, and
  generated subtitle workflows.

Current code closes those backend gaps. Remaining desktop work is Electron
process management, preload IPC, renderer UI, packaging, and product UX.

## Options Considered

### Option 1: FastAPI sidecar managed by Electron

Electron starts a Python FastAPI process, waits for a machine-readable startup
message, and routes desktop requests to it. REST handles commands and queries.
SSE handles event streaming.

This is the recommended approach. It matches the roadmap, reuses the existing
Python application services, gives the desktop OpenAPI-compatible schemas, and
can later support external automation with the same adapter.

### Option 2: stdio JSON-RPC sidecar

Electron talks to Python over stdin and stdout. This is more private than a
local HTTP port, but it loses HTTP tooling, browser-friendly development,
OpenAPI schema generation, and natural event streaming.

This is a viable fallback only if packaging or local-port policy becomes a
major blocker.

### Option 3: CLI subprocess calls

Electron repeatedly spawns `openbbq` commands and parses JSON output. This is
low effort, but it makes progress streaming, cancellation, run ownership,
diagnostics, and error consistency worse. It would make the desktop depend on
CLI-shaped behavior that the backend should be free to change.

This option should not be used for the desktop.

## Recommended Architecture

Add an API adapter package:

```text
src/openbbq/api/
  __init__.py
  app.py
  auth.py
  errors.py
  schemas.py
  server.py
  routes/
    __init__.py
    artifacts.py
    events.py
    plugins.py
    projects.py
    runs.py
    runtime.py
    workflows.py
```

Responsibilities:

- `api/*` owns HTTP routing, local auth, request parsing, response models,
  OpenAPI metadata, and SSE serialization.
- `application/*` owns user-facing backend operations shared by CLI, API, and
  automation adapters.
- `engine/*`, `workflow/*`, `storage/*`, `plugins/*`, and `runtime/*` remain
  headless core layers.
- `cli/*` parses terminal arguments and formats terminal output. It should not
  be the integration point for the desktop.

Rules:

- API routes must not import `openbbq.cli.app`.
- API routes should not directly call workflow runner internals.
- If an API capability currently exists only in CLI code, move it into
  `application/*` first, then have CLI and API call the same service.
- The API layer may adapt application models into API view models, but it
  should not reimplement business behavior.

## Pydantic Contract

Every cross-process or cross-adapter data structure must be a Pydantic model.
This includes:

- HTTP request bodies;
- HTTP success responses;
- HTTP error responses;
- run records;
- workflow summaries;
- artifact summaries;
- runtime settings responses;
- plugin metadata responses;
- doctor check responses;
- SSE event payloads.

Dynamic JSON is still allowed where it is part of the product model:

- plugin parameter JSON Schema;
- plugin custom event `data`;
- artifact JSON content;
- artifact metadata and lineage;
- API error `details`.

Add shared API models in `openbbq.api.schemas`:

```python
from typing import Generic, Literal, TypeVar

from pydantic import Field

from openbbq.domain.base import JsonObject, OpenBBQModel

T = TypeVar("T")


class ApiSuccess(OpenBBQModel, Generic[T]):
    ok: Literal[True] = True
    data: T


class ApiError(OpenBBQModel):
    code: str
    message: str
    details: JsonObject = Field(default_factory=dict)


class ApiErrorResponse(OpenBBQModel):
    ok: Literal[False] = False
    error: ApiError
```

FastAPI routes must use `response_model=...` so outgoing responses are validated
and OpenAPI schemas are generated from the same contracts the desktop consumes.

SSE messages must also be built from Pydantic models and serialized with
`model_dump_json()`. The API should not hand-write JSON strings for stream
payloads.

## Process And Security Model

Production desktop flow:

1. Electron main starts the Python sidecar.
2. Electron main passes a random bearer token and asks the sidecar to bind to
   `127.0.0.1` with port `0`.
3. The sidecar starts FastAPI and writes one startup JSON line to stdout:

   ```json
   {"ok":true,"host":"127.0.0.1","port":53124,"pid":12345}
   ```

4. Electron main keeps the token private.
5. Electron renderer calls preload IPC methods.
6. Preload IPC forwards requests to Electron main.
7. Electron main calls the sidecar with `Authorization: Bearer <token>`.
8. Electron main terminates the sidecar when the desktop exits.

Development flow:

- The sidecar can be started manually with a known token.
- Renderer direct HTTP access is acceptable for development only.
- CORS should be disabled by default and explicitly enabled for local dev.

Security defaults:

- bind only to `127.0.0.1`;
- require bearer token for every route except health checks needed during
  startup;
- do not expose secrets in responses, events, logs, or OpenAPI examples;
- keep provider secret values behind existing `SecretResolver` behavior;
- treat local plugins as trusted code, matching the current plugin model.

## API Surface

The current API surface is intentionally local and shaped for the desktop.

### Health

```text
GET /health
```

Returns process and version status. This endpoint is used by Electron main to
detect readiness.

### Projects

```text
GET  /projects/current
POST /projects/init
```

`/projects/current` reports project metadata, root path, config path, workflow
count, plugin paths, and storage paths for the active project.

`/projects/init` wraps project initialization. The first desktop version can
support one active project per sidecar process. Multi-project management can be
added later without changing the lower backend layers. When initialization is
performed through the sidecar, the created project becomes the active project
for subsequent routes in the same process.

### Workflows

```text
GET  /workflows
GET  /workflows/{workflow_id}
POST /workflows/{workflow_id}/validate
GET  /workflows/{workflow_id}/status
GET  /workflows/{workflow_id}/events?after_sequence=0
GET  /workflows/{workflow_id}/events/stream?after_sequence=0
```

Workflow list and detail responses should include enough metadata for a desktop
dashboard:

- workflow ID and name;
- step list;
- current state;
- current step ID;
- latest event sequence;
- validation status when requested;
- declared input, output, and plugin tool metadata.

### Runs

```text
POST /workflows/{workflow_id}/runs
GET  /runs
GET  /runs/{run_id}
POST /runs/{run_id}/resume
POST /runs/{run_id}/abort
GET  /runs/{run_id}/events?after_sequence=0
GET  /runs/{run_id}/events/stream?after_sequence=0
GET  /runs/{run_id}/artifacts
```

The desktop should receive a stable run handle immediately after starting work.
The API should not make the renderer wait for a full workflow to finish before
receiving a response. Run-scoped event and artifact routes let the desktop
follow generated quickstart jobs without switching the sidecar's active project.

### Artifacts

```text
GET  /artifacts
GET  /artifacts/{artifact_id}
GET  /artifact-versions/{version_id}
POST /artifacts/import
GET  /artifact-versions/{from_version_id}/diff/{to_version_id}
GET  /artifact-versions/{version_id}/preview
POST /artifact-versions/{version_id}/export
GET  /artifact-versions/{version_id}/file
```

Artifact responses should separate metadata from potentially large content.
File-backed artifacts should return file metadata and an internal path only when
the caller is authorized by the local desktop boundary. Later desktop previews
can add dedicated content-serving or thumbnail endpoints.

### Plugins

```text
GET /plugins
GET /plugins/{plugin_name}
```

Plugin responses should expose manifest v2 metadata that the desktop can use to
render workflow configuration forms:

- tool names and descriptions;
- named inputs and outputs;
- parameter schema;
- UI hints;
- runtime requirements;
- declared effects;
- invalid plugin diagnostics.

### Runtime

```text
GET /runtime/settings
PUT /runtime/providers/{name}
GET /runtime/providers/{name}/check
PUT /runtime/providers/{name}/auth
POST /runtime/secrets/check
PUT /runtime/secrets
GET /runtime/models
GET /doctor
GET /doctor?workflow_id={workflow_id}
```

These routes wrap runtime settings, auth checks, model cache status, settings
doctor checks, and workflow-specific doctor checks.

### Quickstart

```text
POST /quickstart/subtitle/local
POST /quickstart/subtitle/youtube
```

These routes start generated local or remote subtitle workflows and return run
handles plus generated project context.

## Run Model

Introduce a run/job layer for desktop operations:

```text
Project
  WorkflowConfig
    WorkflowState
    RunRecord[]
      StepRunRecord[]
      WorkflowEvent[]
```

The current implementation preserves workflow-scoped engine state and stores
run records in the project SQLite database:

```text
.openbbq/
  openbbq.db
  artifacts/
    <artifact-id>/
      versions/
        <version-number>-<artifact-version-id>/
          content
  state/
    workflows/
      <workflow-id>.lock
      <workflow-id>.abort_requested
```

`RunRecord` should include:

- `id`;
- `workflow_id`;
- `mode` such as `start`, `resume`, `step_rerun`, or `force_rerun`;
- `status` such as `queued`, `running`, `paused`, `completed`, `failed`, or
  `aborted`;
- `project_root`;
- `started_at`;
- `completed_at`;
- `latest_event_sequence`;
- `error` when failed;
- `created_by` with values such as `api`, `cli`, or `desktop`.

First-stage constraints:

- only one active run per workflow;
- workflow locks remain the concurrency source of truth;
- `RunRecord` is an API/job handle, not a complete replacement for
  `WorkflowState`;
- workflow events can remain workflow-scoped;
- artifact lineage remains workflow and step scoped; run records provide the
  desktop handle for background work.

This gives the desktop a stable handle for user-triggered work without forcing
an immediate storage migration for historical runs.

## Event Streaming

The current event model has append-only SQLite records with `sequence`, `type`,
`level`, `message`, `data`, and timestamps. The desktop API builds on that
instead of inventing a separate progress channel.

Add event read helpers:

- `read_events(workflow_id)`;
- `read_events_after(workflow_id, sequence)`;
- `latest_event_sequence(workflow_id)`.

Add SSE streaming:

```text
GET /workflows/{workflow_id}/events/stream?after_sequence=42
```

Behavior:

- replay existing events after the requested sequence;
- keep the connection open while the workflow is active;
- poll SQLite-backed event helpers with a short interval;
- emit heartbeat comments or heartbeat events so clients can detect connection
  health;
- stop streaming when the client disconnects;
- let clients reconnect with the last seen sequence.

The first implementation does not need an in-memory pub/sub system. Polling the
durable event log is simpler, deterministic, and directly matches the recovery
story.

## Application Service Completion

Move CLI-owned behavior into application services before exposing it through
the API.

Target package shape:

```text
src/openbbq/application/
  artifacts.py
  diagnostics.py
  plugins.py
  projects.py
  quickstart.py
  runtime.py
  runs.py
  workflows.py
```

New or expanded services:

- project initialization and current project info;
- plugin list and plugin info;
- runtime settings read and provider mutation;
- auth set and auth check;
- secret check and secret set where appropriate for desktop flows;
- doctor checks;
- generated local and YouTube subtitle workflows;
- run creation, run status, resume, and abort.

CLI commands and API routes should call shared services where the behavior is
the same. Current API quickstart routes use `openbbq.application.quickstart`;
current CLI quickstart commands keep synchronous output-file orchestration over
shared lower-level helpers. Tests should cover the service layer directly and
the adapter layers separately.

## Dependency And Packaging

Keep the core CLI lightweight by making API dependencies optional:

```toml
[project.optional-dependencies]
api = ["fastapi>=0.115", "uvicorn>=0.30"]
```

The desktop package can install:

```text
openbbq[api,download,media,llm,secrets]
```

Add a sidecar entry point:

```toml
[project.scripts]
openbbq = "openbbq.cli.app:main"
openbbq-api = "openbbq.api.server:main"
```

`openbbq api serve` can also exist for discoverability, but Electron should be
able to use a dedicated sidecar command with machine-readable startup output.

## CLI Compatibility Direction

The CLI remains supported as a debugging and automation adapter. It should not
be the desktop transport.

Because breaking changes are allowed, CLI JSON output may migrate toward the
same API envelope:

```json
{"ok":true,"data":{}}
```

Errors should already remain structurally close to the API error model:

```json
{"ok":false,"error":{"code":"validation_error","message":"...","details":{}}}
```

This migration should be deliberate and tested because current tests assert
several command-specific JSON shapes.

## Testing Strategy

Use focused tests for each boundary:

- `tests/test_api_health.py` for app factory, auth middleware, and health.
- `tests/test_api_workflows.py` for workflow list, detail, validate, status,
  and run creation.
- `tests/test_api_events.py` for historical event replay and SSE serialization.
- `tests/test_api_artifacts.py` for artifact list, show, version, import, and
  diff routes.
- `tests/test_application_runs.py` for run record persistence, single active run
  enforcement, status transitions, and abort behavior.
- Existing CLI tests should remain until CLI JSON envelope migration is
  intentionally performed.

Verification commands:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build --wheel --out-dir /tmp/openbbq-wheel-check
```

API dependencies should be covered by a targeted command after the optional
extra exists:

```bash
uv sync --extra api
uv run pytest tests/test_api_*.py tests/test_application_runs.py \
  tests/test_application_artifacts.py tests/test_application_quickstart.py
```

## Implementation Slices

### Slice 1: API and Pydantic contract foundation

The completed first slice added the `api` optional dependency,
`openbbq.api.schemas`, FastAPI app factory, auth middleware, error conversion,
and `GET /health`.

Expected result: a sidecar app can be instantiated in tests, validates responses
with Pydantic, and rejects unauthorized requests where auth is required.

### Slice 2: Application service completion

The service slice moved project, plugin, runtime, auth, doctor, run, artifact,
and API quickstart operations into `application/*` where they are shared by
adapters.

Expected result: API work can build on application services without importing
CLI internals.

### Slice 3: Run manager

The run-manager slice added `RunRecord`, SQLite run storage, a small in-process
task manager, run creation, run status, resume, and abort. It enforces one
active run per workflow.

Expected result: `POST /workflows/{workflow_id}/runs` can return immediately
with a run ID while workflow execution continues in the backend.

### Slice 4: Workflow and artifact API routes

The route slice exposes workflow list, detail, validate, status, event history,
artifact list, artifact show, artifact version, artifact import, artifact diff,
plugin list, plugin info, runtime settings, provider mutation, and doctor
checks.

Expected result: the desktop has enough API coverage for an initial project
dashboard, run monitor, settings panel, plugin browser, and artifact inspector.

### Slice 5: Event streaming

The event slice added SQLite event read helpers and SSE streaming based on
workflow event sequence.

Expected result: the desktop can replay historical workflow events and keep a
live connection open for progress updates.

### Slice 6: Sidecar launcher

The launcher slice added `openbbq-api` and `openbbq api serve` with `--host`,
`--port`, `--token`, `--no-token-dev`, and machine-readable startup output.

Expected result: Electron main can launch the backend, discover the selected
port, authenticate requests, and terminate the sidecar cleanly.

## Future Work

These items are intentionally outside the first desktop backend slice:

- multi-project sidecar sessions;
- external network API exposure;
- WebSocket command channels;
- in-memory event pub/sub;
- plugin sandboxing;
- multi-user collaboration.

The proposed design keeps these possible without requiring them before the
desktop can start integrating with the backend.

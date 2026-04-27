# Desktop backend integration design

> Status: design approved for specification. Implementation has not started.

## Goal

Connect the approved desktop renderer to the real OpenBBQ backend through an
Electron-managed FastAPI sidecar. The first integration milestone should produce
a real local desktop loop: choose a URL or local file, configure the generated
subtitle workflow, start a backend run, and monitor the run with real status and
runtime events.

This work should replace the renderer's mock client at the boundary, not rewrite
the UI components or duplicate backend workflow logic in TypeScript.

## Current baseline

The repository now has both sides of the future desktop stack:

- `desktop/` contains a React renderer with source import, workflow
  arrangement, task monitor, and results review screens.
- `desktop/src/lib/apiClient.ts` defines a typed `OpenBBQClient` boundary that
  currently returns mock data.
- `openbbq.api` exposes a local FastAPI sidecar with health, project, runtime,
  workflow, run, event, artifact, and quickstart routes.
- `openbbq.application.quickstart` can create generated local and YouTube
  subtitle workflows and start non-blocking run records.
- `openbbq.application.runs` persists run records, executes runs in a background
  executor, and records expected or unexpected failures.
- `/runs/{run_id}/events` and `/runs/{run_id}/events/stream` expose workflow
  events for known runs.
- `/runs/{run_id}/artifacts`, `/artifacts/{artifact_id}`,
  `/artifact-versions/{version_id}/preview`, `/artifact-versions/{version_id}/file`,
  and `/artifact-versions/{version_id}/export` expose artifact metadata,
  preview, file, and export operations.

The backend is ready enough for a first desktop vertical slice. The remaining
gap is the desktop shell and client integration layer.

## Non-goals

This milestone does not implement:

- installers, code signing, or packaged Python distribution;
- a general workflow graph editor;
- plugin marketplace or plugin installation;
- a persistent multi-workspace registry;
- arbitrary existing-workspace switching inside one running sidecar;
- a backend API for saving edited transcript or translation segment text;
- an export flow that uses edited subtitle text from the results editor;
- a server-derived waveform pipeline;
- a new checkpoint retry API beyond the existing resume and step-rerun
  mechanics.

The renderer may continue to show the existing results review UI, but production
editing, autosave, and export semantics need a later result-persistence design.

## Options considered

### Option 1: Electron-managed sidecar vertical slice

Electron main starts `uv run openbbq api serve`, keeps the bearer token private,
waits for the sidecar startup JSON line, and exposes a small preload API to the
renderer. The renderer replaces mock calls with sidecar-backed calls while
keeping React components independent of Electron and FastAPI details.

This is the recommended approach. It matches the existing backend API design,
solves local file path selection correctly, keeps credentials out of the
renderer, and produces the first real desktop task loop.

### Option 2: Browser renderer direct to manually started sidecar

The Vite renderer calls a manually started FastAPI server directly. This is
faster to prototype, but it cannot provide real local file paths from the
browser, requires development CORS, exposes tokens to renderer code, and would
need to be reworked for the production desktop.

This option is useful only as a temporary diagnostic mode, not as the primary
implementation plan.

### Option 3: Backend contract completion first

Before touching Electron, add richer workflow template metadata, result segment
persistence, checkpoint retry, and waveform routes. This would improve the final
desktop model, but it postpones the first real user-visible backend loop.

This option should be split into follow-up specs after the sidecar integration
proves the renderer can drive a real task.

## Recommended architecture

The integration should use the existing target model:

```text
Electron renderer -> preload IPC -> Electron main -> FastAPI sidecar -> OpenBBQ application services
```

Responsibilities:

- Electron main owns sidecar lifecycle, token generation, HTTP calls, local file
  dialogs, and process cleanup.
- Preload exposes a narrow typed API on `window.openbbq`; it does not expose
  Node primitives or the bearer token.
- Renderer code owns UI state and calls `OpenBBQClient`; React components do not
  import Electron modules.
- The sidecar remains the only backend adapter. The desktop does not parse CLI
  output or call workflow engine internals.

The existing mock client remains available for tests and browser-only design
work. The default Electron runtime uses the real client.

## File and module boundaries

Expected desktop additions:

- `desktop/electron/main.ts` starts and stops the sidecar, creates the browser
  window, owns IPC handlers, and handles local file selection.
- `desktop/electron/preload.ts` exposes `window.openbbq` through
  `contextBridge`.
- `desktop/electron/sidecar.ts` contains sidecar process startup, startup-line
  parsing, readiness timeout, stderr capture, and shutdown.
- `desktop/electron/http.ts` contains main-process HTTP helpers that add bearer
  auth and normalize API errors.
- `desktop/src/lib/sidecarClient.ts` adapts `window.openbbq` into the existing
  `OpenBBQClient` interface.
- `desktop/src/lib/apiTypes.ts` or a similar focused module contains TypeScript
  DTOs for the API payloads consumed by the renderer.
- `desktop/src/global.d.ts` declares the preload API shape.

Expected backend changes are minimal for this milestone. If a small schema or
route adjustment is needed to support the first vertical slice, it should be
added through `openbbq.api` and `openbbq.application`, not by routing through
CLI code.

## Sidecar lifecycle

Electron main starts the sidecar with:

```text
uv run openbbq api serve --project <workspace> --token <random-token>
```

Development builds may also pass `--allow-dev-cors` only when the renderer is
loaded from the Vite dev server. Production desktop builds should load local
renderer assets and should not enable CORS.

Startup behavior:

1. Generate a high-entropy token in Electron main.
2. Spawn the sidecar with host `127.0.0.1` and port `0`.
3. Read stdout until the first valid startup JSON line appears.
4. Extract host, port, and pid.
5. Call `/health` before reporting the backend as connected.
6. If startup times out or exits early, show a user-facing connection error in
   the renderer and keep stderr details for diagnostics.

Shutdown behavior:

- close the renderer window without leaving orphaned sidecar processes;
- terminate the sidecar on normal app quit;
- escalate to process kill only after a short graceful timeout;
- clear in-memory token and connection state after shutdown.

## Preload API

The preload API should stay small and product-oriented:

```ts
type OpenBBQDesktopApi = {
  chooseLocalMedia(): Promise<{ path: string; displayName: string } | null>;
  getWorkflowTemplate(source: SourceDraft): Promise<WorkflowStep[]>;
  startSubtitleTask(input: StartSubtitleTaskInput): Promise<{ runId: string }>;
  getTaskMonitor(runId: string): Promise<TaskMonitorModel>;
  streamRunEvents(
    runId: string,
    options: { afterSequence: number },
    onEvent: (event: RuntimeLogLine) => void
  ): () => void;
  getReview(runId: string): Promise<ReviewModel>;
  retryCheckpoint(runId: string): Promise<void>;
};
```

The exact TypeScript names can be refined in the implementation plan, but the
shape should preserve these rules:

- no token in renderer state;
- no raw filesystem access in renderer state;
- no generic arbitrary HTTP request method exposed to the renderer;
- no direct Node APIs exposed through preload.

## Source and workflow mapping

The source page keeps its current product model: one unified source frame with a
URL input and a local file picker/drop target.

Local file behavior:

- Renderer asks preload to open a native file dialog.
- Electron main returns a real absolute file path and display name.
- Renderer stores the display name for UI and passes the path back through the
  client boundary only when starting the task.
- Browser drag/drop can keep the current validation behavior for design mode,
  but production Electron should prefer the native file picker path.

Remote URL behavior:

- Renderer validates that the value is an `http` or `https` URL.
- The start request maps to `POST /quickstart/subtitle/youtube`.
- The URL becomes the backend `url` field.

Workflow behavior:

- For the first milestone, workflow templates are frontend view models derived
  from the source type and current backend quickstart parameters.
- Local file sources map to the local subtitle quickstart workflow.
- Remote URL sources map to the YouTube subtitle quickstart workflow.
- Editable parameters should map only to fields already accepted by the
  quickstart routes: source language, target language, provider, optional chat
  model, ASR model, ASR device, ASR compute type, and YouTube download options.
- Optional UI steps that do not have a backend quickstart toggle must either be
  disabled in the real client or omitted from the first real template.

This keeps the first integration honest: users can edit values the backend
actually consumes.

## Task creation

Starting a task calls one of the existing quickstart routes:

```text
POST /quickstart/subtitle/local
POST /quickstart/subtitle/youtube
```

The sidecar response returns `generated_project_root`, `generated_config_path`,
`workflow_id`, `run_id`, optional `output_path`, and optional
`source_artifact_id`. The renderer should keep `run_id` as the primary task
handle and should not show generated project paths by default.

The initial implementation should not ask for an output path before running.
Export belongs to the results flow after review.

## Task monitor mapping

`TaskMonitorModel` should be built from:

- `GET /runs/{run_id}` for run status, workflow ID, latest sequence, and error;
- `GET /runs/{run_id}/events?after_sequence=<n>` or
  `/runs/{run_id}/events/stream` for runtime log and progress updates.

The first implementation can use polling if SSE introduces Electron complexity,
but the plan should leave the interface shaped so SSE can replace polling
without changing `TaskMonitor`.

Progress mapping rules:

- completed step events become `done`;
- the latest running step becomes `running`;
- the failed step becomes `failed`;
- downstream known steps become `blocked`;
- run `error.message` becomes the failed-state error banner.

The error banner and `Retry checkpoint` action remain paired. They only appear
when the backend run status is `failed`.

## Retry behavior

The existing backend has resume and step-rerun mechanics, but it does not expose
a dedicated "retry from latest completed checkpoint" API. The first integration
should not pretend otherwise.

For this milestone, `retryCheckpoint(runId)` may map to one conservative backend
operation:

- if the run is paused, call `POST /runs/{run_id}/resume`;
- if the run is failed and the backend can identify a valid current step through
  workflow state, create a step-rerun through the existing run creation route;
- otherwise return a clear unsupported error that tells the UI to disable retry
  for that failed run.

If this behavior cannot be implemented without ambiguity, retry should stay
visually present only in mock mode and be disabled in real mode until a focused
backend retry spec is written.

## Results mapping

The first real results view should read backend artifacts after a completed run:

- list run artifacts through `GET /runs/{run_id}/artifacts`;
- identify transcript, translation, subtitle segment, subtitle output, audio,
  and video artifacts by artifact type, name, or producing step;
- preview text and JSON artifacts through `/artifact-versions/{version_id}/preview`;
- read file-backed media through `/artifact-versions/{version_id}/file` when the
  renderer can safely load local sidecar URLs.

Because edited segment persistence is out of scope, the first real results view
has two acceptable modes:

- read-only real backend result mode; or
- editable UI mode backed by local unsaved draft state, clearly not used for
  backend export.

The implementation plan should prefer read-only real result mode unless a small
backend result-save contract is approved separately.

Waveform data remains synthetic in this milestone unless an existing artifact
already contains loudness data. The UI should avoid claiming sample-accurate
waveform semantics until a media preview and waveform pipeline exists.

## Error handling

Electron main should normalize sidecar errors before returning them through IPC:

- API envelope errors preserve `code`, `message`, and details when safe;
- network failures become `sidecar_unreachable`;
- startup timeout becomes `sidecar_start_timeout`;
- process exit before readiness becomes `sidecar_exit_before_ready`;
- local file dialog cancellation returns `null`, not an error;
- unsupported real-client behavior returns a typed unsupported error rather than
  silently falling back to mock data.

The renderer should show concise user-facing errors in the existing warm alert
style. Diagnostics can expose technical details later.

## Security and privacy

The production desktop security model is local-only:

- sidecar binds to `127.0.0.1`;
- bearer token is generated in Electron main and never exposed to renderer code;
- preload exposes narrow methods, not arbitrary HTTP or filesystem primitives;
- local file paths are passed only to the backend routes that need them;
- provider secret values remain managed by existing runtime and secret services;
- logs and error messages should not include API keys or secret values.

The current plugin trust model remains unchanged: local plugins execute as local
code in the backend process.

## Development mode

Development should support both:

- Electron loading the Vite dev server for fast renderer iteration;
- Electron loading built renderer assets for smoke tests closer to production.

The existing mock client should remain available for renderer-only tests. Real
client tests should use mocked IPC or a test sidecar, not real network calls in
every component test.

## Testing strategy

Use TDD for implementation:

- unit tests for sidecar startup-line parsing and timeout handling;
- unit tests for main-process HTTP error normalization;
- unit tests for quickstart request mapping from `WorkflowStep` values;
- unit tests for run/event-to-`TaskMonitorModel` mapping;
- renderer tests proving existing screens still work with the real client seam;
- Electron or Playwright smoke tests for source selection, workflow start, and
  task monitor rendering;
- focused backend route tests only when a backend contract changes.

Final verification should run:

```bash
cd desktop
pnpm test
pnpm build
pnpm e2e

cd ..
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

If the existing Windows backend baseline still has unrelated path failures, the
implementation report must list them separately from desktop verification.

## Acceptance criteria

- Desktop can run in Electron and start a local FastAPI sidecar automatically.
- Renderer receives a connected or failed sidecar state without seeing tokens.
- Local media selection returns a real absolute path through the desktop shell.
- Remote URL source starts a real YouTube subtitle quickstart run.
- Local file source starts a real local subtitle quickstart run.
- Workflow parameter edits are included in the backend quickstart request when
  those fields are supported by the current backend.
- Task monitor shows real run status and runtime events for the created run.
- Failed runs show the existing paired error banner and retry action only when
  the backend status is failed.
- Real mode does not silently use mock data after a sidecar or API failure.
- Existing mock renderer tests remain useful for design-only development.

## Follow-up specs

The following work should stay separate unless the implementation discovers a
small non-invasive prerequisite:

1. Result segment persistence, versioning, and export from edited text.
2. Dedicated checkpoint retry API with unambiguous backend semantics.
3. Media preview and loudness waveform artifact pipeline.
4. Persistent workspace and generated-run discovery across sidecar restarts.
5. Desktop packaging, Python runtime bundling, and installer behavior.

## Self-review

- Placeholder scan: the spec contains no unresolved placeholder requirements.
- Internal consistency: the architecture, source mapping, task creation, monitor,
  and result sections all use the existing FastAPI sidecar as the only backend
  adapter.
- Scope check: the milestone is focused on one desktop vertical slice and
  defers result editing, packaging, workspace registry, waveform generation, and
  dedicated checkpoint retry.
- Ambiguity check: retry and results editing are explicitly constrained so the
  first implementation cannot promise unsupported production behavior.

# Desktop UI Frontend PRD

## Purpose

The OpenBBQ desktop UI should make media language workflows usable without
exposing backend implementation concepts. Users should think in terms of
sources, workflows, tasks, progress, results, and exportable files. The UI can
still map directly to the backend's project, workflow, run, event, artifact, and
artifact-version models internally.

This PRD defines the first desktop product surface that should be designed
before frontend implementation begins.

## Product Goals

- Let a user create a subtitle task from a local media file or a remote video URL
  without learning OpenBBQ's backend concepts.
- Let a user choose a workflow, configure required workflow inputs, run the
  currently available readiness checks, start the task, monitor progress, review
  outputs, and export subtitles.
- Keep the first version compatible with the existing backend quickstart
  workflows while leaving room for custom workflows and plugin-provided workflow
  templates.
- Use the local FastAPI sidecar as the desktop backend transport. The renderer
  should not parse CLI output or manage backend credentials directly.

## Backend Reality For First Release

This PRD separates the target desktop experience from what the current backend
can support immediately. The first UI design should use the current contract
where it exists, degrade to explicit first-release constraints where it does
not, and treat missing contracts as backend gaps.

Current backend support:

- Create a new workspace with `POST /projects/init`.
- Read the active workspace with `GET /projects/current`.
- Create local-video and YouTube subtitle quickstart runs.
- List runs known to the active sidecar process.
- Stream raw workflow events for a known run.
- Read artifacts, preview artifact versions, diff artifact versions, and export
  artifact versions.
- Configure runtime providers and provider auth.
- Read runtime settings and model status.
- Run general doctor checks and workflow-scoped doctor checks for workflows
  already present in the active project.

Current backend limitations that shape the UI:

- There is no API to open or switch to an existing workspace in-process.
- Quickstart run discovery is not persistent across sidecar restarts.
- Run list records do not include user-facing source, workflow template, result,
  or error-summary fields.
- Workflow template metadata for quickstart cards is not exposed by the backend.
- Doctor checks are mostly environment-level checks, not request-specific
  preflight for a selected source and quickstart request.
- Quickstart `output_path` is echoed by the response but is not used to
  auto-export after workflow completion.
- Runtime model/cache settings are read-only through the current API.
- Duplicate task and retry-from-original-quickstart-request are not implemented.
- Abort for a running workflow is cooperative and only takes effect after the
  current step reaches an abort checkpoint.

## Non-Goals For The First UI Slice

- A full visual workflow graph editor.
- A plugin marketplace.
- Multi-user collaboration.
- Cloud sync or remote API exposure.
- Complex subtitle timeline editing.
- Automatic downstream invalidation for single-step reruns.
- Direct exposure of backend identifiers such as generated project paths, run
  IDs, artifact IDs, selectors, config hashes, or lineage in the primary UI.

Advanced diagnostics may reveal some of these fields, but they should not be
part of the default user journey.

## Target Users

### Primary User

A creator, translator, fansubber, or editor who has a video and wants a usable
subtitle file with a chance to review the transcript and translation before
export.

### Secondary User

A technical user who wants to inspect workflow steps, artifacts, versions,
plugin behavior, and event logs while debugging or building custom workflows.

## Product Vocabulary

The UI should use user-centered labels while preserving backend mapping.

| UI term | Meaning | Backend mapping |
|---|---|---|
| Workspace | The folder where OpenBBQ stores project data | project root + project config |
| Source | The input media, URL, audio, transcript, or subtitle | imported artifact or literal URL input |
| Workflow | A reusable processing flow from source to results | workflow template or workflow config |
| Workflow settings | User-editable parameters required by a workflow | workflow parameters + runtime/plugin settings |
| Task | One execution of a workflow | run record |
| Progress | Human-readable execution timeline | workflow events + workflow state |
| Result | User-facing output such as transcript, translation, subtitle | artifact |
| Version | A saved immutable result snapshot | artifact version |
| Capability | A required backend ability such as ASR, translation, download, export | plugin tool + runtime provider/dependency |

Avoid using these backend terms in the default UI: artifact, artifact version,
run ID, generated project, selector, step run, lineage, config hash, manifest.

## Core User Journey

The recommended first-release journey is:

1. Open the app and create a workspace, or open an existing workspace through
   the desktop shell by launching the sidecar for that workspace.
2. Choose a source.
3. Choose a workflow filtered by that source.
4. Configure the workflow.
5. Run available readiness checks and frontend field validation.
6. Start the task.
7. Monitor progress.
8. Review transcript, translation, and subtitle results.
9. Export the final subtitle file.

## Information Architecture

### Global App Shell

The app should use a work-focused shell, not a marketing-style landing page.

Primary navigation:

- Home
- New Task
- Tasks
- Results
- Workflows
- Settings

Secondary surfaces:

- Activity/log drawer
- Diagnostics drawer
- Advanced details drawer

Global status indicators:

- Active workspace
- Sidecar connection status
- Setup readiness summary
- Active task count

### Home Page

Purpose: give users a clear starting point and show current workspace status.

Content:

- Current workspace name and path.
- Primary action: New Task.
- Current-session tasks with status, workflow ID, timestamp fields, and error
  status where available.
- Recent task summaries only when the desktop shell or a future backend registry
  can provide persisted run metadata.
- Environment readiness summary:
  - AI provider configured or missing.
  - ASR model cache status.
  - Sidecar connection status.
  - Future capability checks for ffmpeg, download tooling, and optional Python
    dependencies after a backend capability doctor or workflow-scoped check is
    available for the selected workflow.
- Shortcuts:
  - Configure AI provider.
  - Run diagnostics.
  - Open Settings.

Primary actions:

- Create a task.
- Resume or inspect a known task.
- Fix a blocking setup issue.

Backend data:

- `GET /projects/current`
- `GET /runs`
- `GET /doctor`
- `GET /runtime/settings`
- `GET /runtime/models`

First-release constraints:

- `GET /runs` only covers the active project and quickstart generated projects
  registered in the current sidecar process.
- After a sidecar restart, generated quickstart run directories are not
  rediscovered unless a backend workspace-level run registry or generated
  project scanner is added.
- Source name, friendly workflow template name, last result, and result
  availability should not be promised unless the UI keeps a volatile
  current-session cache or the backend adds a run summary API.

### Workspace Setup Page

Purpose: let users start in a valid local workspace.

Entry conditions:

- First app launch.
- No active project.
- User chooses Switch Workspace.

Content:

- Create new workspace.
- Open existing workspace through the desktop shell.
- Recent workspace list, if available in the desktop shell layer.
- Explanation that workspace data stays local.

Primary actions:

- Create workspace.
- Select an existing workspace folder.

Backend data:

- `POST /projects/init`
- `GET /projects/current`

First-release constraints:

- Creating a new workspace is supported by the backend.
- Opening an existing workspace is not supported by a current sidecar API.
- The first release can support existing workspace selection by having Electron
  main launch or restart the sidecar with `--project` pointing at the selected
  folder.
- If the app needs in-process switching without restarting the sidecar, the
  backend needs a project open/switch contract such as `POST /projects/open`.

### New Task Wizard

The wizard should guide users through source, workflow, settings, preflight, and
start. It should hide backend concepts and only ask for information that affects
the selected workflow.

#### Step 1: Choose Source

Purpose: determine the available workflows.

Source options for first release:

- Local video file.
- YouTube or remote video URL.

Future source options:

- Local audio file.
- Existing subtitle file.
- Existing transcript artifact.
- Existing project result.

Content for local video:

- File picker.
- Detected filename, extension, size.
- Optional display of duration and resolution when available later.

Content for remote URL:

- URL input.
- Download authentication mode:
  - Auto.
  - Anonymous.
  - Browser cookies.
- Browser and profile fields only when browser cookies are selected.

Output of this step:

- Normalized source descriptor.
- Source type.
- Source-specific metadata.

Backend mapping:

- Local video is imported by quickstart when the task is created.
- Remote URL is passed as a literal workflow parameter.

#### Step 2: Choose Workflow

Purpose: choose the processing flow that should handle the source.

First-release built-in workflows:

- Local video to translated SRT.
- YouTube to translated SRT.

Workflow cards should show:

- Workflow name.
- Source types it supports.
- Results it produces.
- Required capabilities.
- Estimated setup requirements.
- Whether it is built-in.

Filtering rules:

- Local video sources show local-video workflows.
- Remote URL sources show remote-video workflows.
- Workflows incompatible with the source are hidden by default and visible only
  in an advanced "show incompatible" mode with reasons.

Future workflow sources:

- Built-in templates.
- Plugin-provided templates.
- User-saved workflows.
- Duplicated and edited templates.

Backend mapping:

- Quickstart maps to generated workflow configs.
- Future template metadata should declare accepted source types, required
  parameters, required capabilities, and result types.

First-release constraints:

- The two quickstart workflow cards should be hard-coded in the frontend or
  desktop shell from known quickstart schemas.
- `GET /workflows` lists workflows in the active project. It does not list
  quickstart templates before a quickstart task creates a generated project.
- Plugin-provided, user-created, and duplicated workflow cards require a future
  workflow template metadata contract.

#### Step 3: Configure Workflow

Purpose: collect only the parameters required by the selected workflow.

Required first-release fields:

- Source language.
- Target language.
- AI provider.
- Optional chat model override.
- Optional ASR model.
- Optional ASR device.
- Optional ASR compute type.

Remote-video fields:

- Quality selector.
- Auth mode.
- Browser.
- Browser profile.

Advanced fields should be collapsed by default:

- ASR device.
- Compute type.
- yt-dlp quality selector.
- Temperature.
- Model override.

Workflow settings should be generated from:

- Built-in known quickstart request schemas for first release.
- Plugin and workflow metadata in later releases.

Validation:

- Required fields must be present.
- Language fields must be non-empty.
- Provider must be selected when the workflow includes LLM-backed steps.
- Destination path is not collected before running in the first release. Export
  happens after review through the artifact export API.

First-release constraints:

- The quickstart request models currently accept `output_path`, but quickstart
  does not automatically export to that path when the workflow finishes.
- The UI should avoid pre-run output-path selection until the backend either
  implements automatic export or removes the misleading field from the desktop
  contract.

#### Step 4: Preflight

Purpose: explain whether the selected workflow appears ready before the user
starts. The first release should be explicit that these are readiness checks,
not a full guarantee that a specific media file or URL will run successfully.

Checks should be grouped by capability:

- Source access.
- Download tools, future or diagnostics-only in the first release.
- Audio extraction, future or diagnostics-only in the first release.
- ASR runtime, future or diagnostics-only in the first release.
- AI provider and API key.
- Model cache.
- Subtitle export.

Each check should have:

- Status: ready, warning, blocked.
- Plain-language message.
- Fix action when possible.
- Advanced details drawer for exact backend messages.

Blocking examples:

- AI provider is missing.
- API key reference cannot be resolved.
- Required source fields are missing or invalid.
- Model/cache status indicates a known local runtime problem.

Backend data:

- `GET /doctor`
- `GET /runtime/providers/{name}/check`
- `GET /runtime/settings`
- `GET /runtime/models`
- `POST /runtime/secrets/check`

First-release checks:

| Check area | First-release source | Limitation |
|---|---|---|
| Required source fields | Frontend validation | Does not verify media readability or URL accessibility |
| Provider exists and secret resolves | Runtime provider and secret APIs | Does not validate every future provider behavior |
| Runtime settings are readable | `GET /runtime/settings` | Used to determine configured providers; does not prove a selected workflow can run |
| Provider connectivity and secret resolution | `GET /runtime/providers/{name}/check`, `POST /runtime/secrets/check` | Depends on provider behavior and network availability |
| Project/cache writability | `GET /doctor` without `workflow_id` | Settings-level only |
| Model cache status | `GET /runtime/models` | Read-only; cannot update cache config |

First-release diagnostics-only checks:

| Check area | Current source | First-release behavior |
|---|---|---|
| ffmpeg availability | Workflow-scoped doctor after a concrete workflow exists | Do not block quickstart creation before the generated workflow exists; show in diagnostics when available |
| yt-dlp importability | Workflow-scoped doctor after a concrete workflow exists | Do not block quickstart creation before the generated workflow exists; show in diagnostics when available |
| faster-whisper importability | Workflow-scoped doctor after a concrete workflow exists | Do not block quickstart creation before the generated workflow exists; show in diagnostics when available |

The first release should not call `GET /doctor?workflow_id=<id>` from the
quickstart wizard before creating the quickstart generated project. That endpoint
checks workflows in the active project and is not run-scoped.

Backend gap:

- A request-specific quickstart preflight API, such as
  `POST /quickstart/subtitle/local/preflight` and
  `POST /quickstart/subtitle/youtube/preflight`, would be needed to check local
  file readability, URL reachability, cookie validity, media probe/decode, and
  quickstart parameters before creating a run.
- A capability doctor such as `GET /doctor/capabilities` would be needed to
  expose global dependency checks before a concrete workflow exists.

#### Step 5: Start Task

Purpose: create a run and navigate to progress.

For built-in quickstart workflows:

- Local source uses `POST /quickstart/subtitle/local`.
- Remote source uses `POST /quickstart/subtitle/youtube`.

Expected response:

- Task/run identifier.
- Workflow identifier.
- Generated project context, stored internally.
- Optional source artifact reference.

UI behavior:

- Immediately navigate to the Task Detail page.
- Start event streaming.
- Do not show generated project paths in the primary UI.

### Task List Page

Purpose: list tasks known to the active sidecar process, with a path toward a
more durable workspace task history after backend support exists.

Content:

- Task title derived from workflow ID or current-session quickstart metadata.
- Source summary when available from current-session quickstart metadata.
- Workflow ID, or friendly workflow name when the UI can map a known quickstart
  workflow ID.
- Status.
- Started and completed timestamps when available.
- Error summary when failed.

Filters:

- Active.
- Completed.
- Failed.
- Aborted.
- Source type.
- Workflow.

Actions:

- Open task.
- Resume paused task.
- Request cancel for running task.

Backend data:

- `GET /runs`
- `GET /runs/{run_id}`

First-release constraints:

- The current `RunRecord` API includes `id`, `workflow_id`, `status`, project
  paths, timestamps, latest event sequence, error, and creator.
- It does not include source summary, workflow template name, last result,
  result availability, or a normalized user-facing error summary.
- Full task cards require either a backend `RunSummary` API or a limited
  frontend composition strategy.
- For quickstart generated projects, the first release should use hard-coded
  quickstart workflow mappings and current-session request metadata. The current
  API does not expose run-scoped workflow details, and
  `GET /workflows/{workflow_id}` reads only the active project.
- Duplicate task is deferred until the backend persists the original quickstart
  request or exposes a dedicated duplicate API.

### Task Detail / Run Monitor Page

Purpose: show live workflow execution in terms the user understands.

Layout:

- Header:
  - Task name.
  - Workflow name.
  - Source summary.
  - Status.
  - Primary action: Request Cancel, Resume, Review Results, or Export depending
    on state.
- Progress timeline:
  - Human-readable steps.
  - Status per step.
  - Last message.
  - Timestamps when available.
- Activity log:
  - Event stream with filtering.
  - Hidden by default on small screens or shown in a drawer.
- Result sidebar:
  - Produced results as they appear.
  - Transcript, translation, subtitle.

Step labels for translated subtitle workflows:

- Download video, remote URL only.
- Extract audio.
- Transcribe.
- Correct transcript.
- Segment subtitles.
- Translate.
- Export subtitle.

Task states:

- Queued: waiting to start.
- Running: timeline updates live.
- Cancel requested: UI-local pending cancel state after `POST /runs/{run_id}/abort`
  succeeds while the backend run status still reports `running`.
- Paused: show reason and Resume action.
- Completed: show Review Results and Export actions.
- Failed: show error summary, diagnostics, and completed partial results.
- Aborted: show final partial results if available.

Backend data:

- `GET /runs/{run_id}`
- `GET /runs/{run_id}/events`
- `GET /runs/{run_id}/events/stream`
- `GET /runs/{run_id}/artifacts`
- `POST /runs/{run_id}/resume`
- `POST /runs/{run_id}/abort`

First-release constraints:

- The backend exposes raw workflow events and workflow state, not a dedicated
  timeline DTO.
- The first UI should reconstruct the timeline from workflow steps and raw event
  types such as `step.started`, `step.completed`, `step.failed`,
  `workflow.paused`, `workflow.completed`, and `workflow.aborted`.
- Failed state should be derived from `step.failed` plus the run/workflow status
  becoming `failed`; the current runner does not append a `workflow.failed`
  event.
- Hard-coded friendly labels are acceptable for the two built-in quickstart
  workflows.
- A future `GET /runs/{run_id}/timeline` would reduce duplicate event parsing in
  frontend clients.
- Abort is cooperative for running workflows. After a successful abort request,
  the UI may show a local "Cancel requested" state while the backend still
  reports `running`. Copy should say "OpenBBQ will stop after the current step
  finishes" rather than promising immediate interruption of ffmpeg, Whisper,
  yt-dlp, or provider calls.

### Results Review Page

Purpose: let users inspect generated text and subtitle outputs before export.

Primary tabs:

- Transcript.
- Translation.
- Subtitle Preview.
- Files.
- Versions, advanced.

Transcript tab:

- Show ASR transcript and corrected transcript when both exist.
- Segment list with timestamps.
- Plain text search.
- Copy text action.
- Future: edit segment text.

Translation tab:

- Show source segment and translated segment side by side.
- Show warnings from translation QA when available.
- Plain text search.
- Future: edit translation.

Subtitle Preview tab:

- Show generated SRT blocks.
- Display timestamps and text.
- Future: video preview with subtitle overlay.
- Future: line length and reading speed indicators.

Files tab:

- List produced artifacts with friendly names.
- Show type, size, current version, and created time.
- Open file-backed video/audio when available.

Versions tab:

- Show artifact versions.
- Compare versions.
- Open advanced metadata.

Backend data:

- `GET /runs/{run_id}/artifacts`
- `GET /artifacts/{artifact_id}`
- `GET /artifact-versions/{version_id}`
- `GET /artifact-versions/{version_id}/preview`
- `GET /artifact-versions/{from_version_id}/diff/{to_version_id}`
- `GET /artifact-versions/{version_id}/file`

### Export Page Or Dialog

Purpose: write the selected result to a user-chosen file path.

Entry points:

- Task Detail page after completion.
- Subtitle Preview tab.
- Files tab.

Content:

- Selected result.
- Selected version.
- Format, first release: SRT.
- Destination path.
- File overwrite warning.

Actions:

- Export.
- Reveal in file manager, desktop shell responsibility.

Backend data:

- `POST /artifact-versions/{version_id}/export`
- `GET /artifact-versions/{version_id}/file`

### Workflow Library Page

Purpose: help users understand available workflow concepts and eventually
customize workflows. The first release should not depend on backend workflow
template discovery.

First-release content:

- Hard-coded built-in quickstart workflow cards.
- Supported source types.
- Produced result types.
- Required capabilities.
- Read-only step overview.

Future content:

- User-created workflows.
- Plugin-provided workflows.
- Duplicate workflow.
- Edit workflow.
- Import/export workflow.

Actions:

- Start task from workflow.
- Duplicate workflow, future.
- Edit workflow, future.

Design note:

The UI should use "Workflow" as the product term, but a workflow should be
presented as a user-facing processing flow, not as a raw backend YAML file.

First-release constraints:

- `GET /workflows` returns workflows defined in the active project. It is useful
  for diagnostics and for generated quickstart projects after creation, but it
  is not a quickstart template library.
- Source types, required capabilities, parameters, plugin dependencies, and
  result preview metadata require a future workflow template metadata endpoint.
- The first UI can keep Workflow Library read-only and static, or defer it and
  surface the two built-in workflow cards only inside New Task.

### Workflow Builder Page, Future

Purpose: create or modify workflows after the first quickstart-oriented UI is
usable.

Expected capabilities:

- Start from an existing template.
- Add, remove, reorder, and configure steps.
- Connect source and step outputs visually or through guided forms.
- Validate required inputs and artifact types.
- Save as a user workflow.

First version should not start with a blank canvas. The recommended flow is:

1. Choose a template.
2. Duplicate it.
3. Modify steps.
4. Validate.
5. Save.
6. Run as a task.

### Settings Page

Purpose: manage runtime configuration required by workflows.

Sections:

- Interface language.
- AI providers.
- Secrets and API keys.
- Model cache.
- Local dependencies.
- Sidecar status.
- Advanced paths.

Interface language:

- System default.
- English.
- Simplified Chinese.
- Stored in desktop-local preferences.
- Does not change workflow source or target language settings.

AI providers:

- Provider list.
- Add or edit provider.
- Type, currently OpenAI-compatible.
- Base URL.
- API key entry.
- Default chat model.
- Test connection or secret resolution.

Secrets:

- Store local API key.
- Check secret reference.
- Redacted preview only.

Model cache:

- faster-whisper cache path.
- Default model.
- Default device.
- Default compute type.
- Present/missing status.
- Read-only in the first release.

Dependencies:

- Future ffmpeg status.
- Future yt-dlp/download status.
- Future Python optional dependency status.

First-release dependency constraints:

- `GET /doctor` without `workflow_id` only reports settings-level readiness such
  as cache and provider checks.
- ffmpeg, yt-dlp, and faster-whisper dependency checks are currently available
  through workflow-scoped doctor checks only after a concrete workflow exists.
- The Settings page should not present dependency status as globally available
  until a capability doctor such as `GET /doctor/capabilities` exists.

Sidecar:

- Connected/disconnected.
- Host and port hidden by default.
- Advanced diagnostics visible in debug mode.

Backend data:

- `GET /runtime/settings`
- `PUT /runtime/providers/{name}`
- `PUT /runtime/providers/{name}/auth`
- `POST /runtime/secrets/check`
- `PUT /runtime/secrets`
- `GET /runtime/models`
- `GET /doctor`

First-release constraints:

- Interface language is a desktop renderer or shell preference. It is not part
  of runtime settings or project config.
- Provider profile and auth configuration are writable.
- Model cache path, default model, default device, and default compute type are
  readable through runtime settings/model APIs but are not writable through the
  current API.
- Editing model/cache settings should be deferred until a runtime settings
  update contract exists.

### Diagnostics Page Or Drawer

Purpose: provide actionable troubleshooting without overwhelming the main UI.

Content:

- Doctor checks.
- Recent errors.
- Backend event log.
- Selected task advanced details.
- Copy diagnostic bundle, future.

Backend data:

- `GET /doctor`
- `GET /doctor?workflow_id=<id>`
- `GET /runs/{run_id}/events`
- `GET /workflows/{workflow_id}/events`

First-release constraints:

- Workflow-scoped doctor checks require a concrete workflow in the active
  project. They are not a substitute for quickstart request-specific preflight
  before a quickstart generated project exists.

## Detailed User Flows

### Flow A: Local Video To Translated SRT

1. User opens Home.
2. User clicks New Task.
3. User chooses Local Video.
4. User selects `sample.mp4`.
5. UI filters workflows and shows Local video to translated SRT.
6. User selects that workflow.
7. User sets source language and target language.
8. User selects an AI provider.
9. UI runs available readiness checks.
10. If blocked, user fixes setup in Settings and returns.
11. User starts the task.
12. UI calls `POST /quickstart/subtitle/local`.
13. UI opens Task Detail and subscribes to run events.
14. User watches progress.
15. On completion, UI opens Results Review.
16. User inspects transcript, translation, and subtitle preview.
17. User exports SRT.

### Flow B: YouTube To Translated SRT

1. User opens New Task.
2. User chooses YouTube or remote URL.
3. User pastes a URL.
4. User keeps auth mode as Auto or chooses Browser Cookies.
5. UI filters workflows and shows YouTube to translated SRT.
6. User configures languages and provider.
7. UI runs available readiness checks.
8. User starts the task.
9. UI calls `POST /quickstart/subtitle/youtube`.
10. UI monitors download, audio extraction, transcription, correction,
    segmentation, translation, and subtitle export.
11. User reviews outputs and exports SRT.

### Flow C: Setup AI Provider From A Blocked Task

1. User reaches Preflight and sees "AI provider is missing" or "API key cannot
   be resolved."
2. User clicks Fix.
3. Settings opens with provider form focused.
4. User enters provider name, base URL, API key, and default model.
5. UI stores provider/auth through runtime APIs.
6. UI reruns provider check.
7. User returns to Preflight.
8. Preflight now passes.

### Flow D: Failed Task Investigation

1. Task enters Failed status.
2. Task Detail shows a plain-language failure summary.
3. User opens Diagnostics.
4. UI shows the failing progress item and relevant event messages.
5. User may:
   - fix settings and create a new task with the same source/settings if the UI
     still has current-session quickstart metadata;
   - inspect partial results;
   - export any completed useful result.

Duplicate and retry are future features unless the backend persists the
original quickstart request or exposes a duplicate/retry API.

### Flow E: Future Custom Workflow

1. User opens Workflow Library.
2. User selects an existing template.
3. User clicks Duplicate.
4. User modifies steps or parameters.
5. UI validates workflow compatibility.
6. User saves it as a custom workflow.
7. The workflow appears in New Task when its accepted source type matches the
   selected source.

## Workflow Selection Rules

Workflow selection should be source-driven.

Source type should determine the default workflow list:

| Source type | Default workflow examples |
|---|---|
| Local video | Local video to translated SRT |
| Remote URL | YouTube to translated SRT |
| Audio file, future | Audio to transcript, audio to translated SRT |
| Subtitle file, future | Translate subtitle, QA subtitle, re-export subtitle |
| Transcript, future | Segment, translate, export |

Workflow metadata should eventually include:

- `id`
- `name`
- `description`
- `source_types`
- `result_types`
- `required_capabilities`
- `parameters`
- `steps`
- `plugin_dependencies`
- `preview_artifacts`
- `export_artifacts`

The first release can hard-code metadata for built-in quickstart workflows while
the backend grows a formal workflow template metadata contract.

## Result Naming

Results should be named for users, not backend IDs.

Recommended labels:

- Source Video
- Extracted Audio
- Raw Transcript
- Corrected Transcript
- Subtitle Segments
- Translation
- Translation QA
- Subtitle File

Advanced details may show the backend artifact name, type, version ID, and
lineage.

## Error Handling

Errors should be handled at the level where the user can act.

### Source Errors

Examples:

- File does not exist.
- URL is invalid.
- Download requires login.

UI behavior:

- Show the source field as invalid.
- Explain the issue.
- Before starting a task, allow field retry or auth-mode changes when
  applicable.

### Setup Errors

Examples:

- Missing API key.
- Missing ffmpeg.
- Missing optional dependency.
- Model cache missing.

UI behavior:

- Show in Preflight.
- Provide a Fix action.
- Do not start the task if the error is blocking.

### Runtime Errors

Examples:

- Plugin execution failed.
- Provider returned an API error.
- Download failed after retry.
- Artifact output was invalid.

UI behavior:

- Show failed task status.
- Highlight the failed progress item.
- Show redacted message.
- Provide diagnostics.
- Offer duplicate/retry only in future releases after the backend preserves the
  original request or exposes a duplicate/retry API.
- In the first release, after a failed run, the UI may offer "Create new task
  with same settings" only while current-session quickstart metadata is still
  available.

### Partial Results

If a task fails after producing earlier results, the UI should still expose those
results. For example, a translation failure may still leave a usable transcript.

## Empty States

Home:

- No tasks yet: show New Task action and setup status.

Tasks:

- No matching tasks: show filter reset.

Results:

- No results yet: explain that results appear after a task starts producing
  outputs.

Workflows:

- No custom workflows: show built-in workflows and explain that custom workflows
  will be created from templates.

Settings:

- No provider configured: show Add Provider action.

## Internationalization And Localization

The desktop UI should be i18n-ready from the first implementation. UI locale is
separate from workflow source language and target language.

First-release requirements:

- Support English and Simplified Chinese UI strings.
- Use English as the fallback locale when a translation key is missing.
- Detect the initial locale from the desktop shell or operating system locale.
- Let users override the interface language in Settings.
- Persist the interface language in desktop-local preferences, not in workflow
  config.
- Keep workflow source language and target language as task settings. Changing
  the interface language must not change workflow language parameters.
- Externalize all visible renderer strings into translation resources.
- Localize navigation labels, buttons, form labels, validation messages, empty
  states, status labels, setup readiness labels, and export dialog text.
- Format dates, times, durations, file sizes, and counts through locale-aware
  formatters.
- Avoid string concatenation for user-visible sentences. Use parameterized
  translation strings instead.
- Keep backend identifiers, file paths, plugin IDs, workflow IDs, artifact IDs,
  event types, and diagnostic raw messages unchanged.

Backend message handling:

- The backend currently returns English/raw technical messages and does not
  accept a locale parameter.
- The first release should localize known UI-level states and known error
  categories in the renderer.
- Raw backend messages should be shown in advanced diagnostics and can remain
  untranslated.
- Future backend contracts may add stable error codes and localized message keys,
  but the first UI should not depend on them.

Settings content:

- Interface language selector:
  - System default.
  - English.
  - Simplified Chinese.
- Short note that workflow source and target languages are configured per task.

Design constraints:

- UI layouts must allow longer translated text without clipping.
- Buttons, tabs, sidebars, task cards, status chips, and dialogs should be
  tested with both English and Simplified Chinese text.
- Search, filtering, and workflow IDs should remain stable across locales.
- Documentation remains English according to repository guidelines.

## Permission And Security UX

- The renderer should not display or store the sidecar bearer token.
- API keys should be entered in Settings and displayed only as redacted previews.
- Advanced logs should be redacted.
- The app should make it clear that local SQLite credential storage is plaintext
  local storage when the user chooses desktop-style credential entry.

## Backend API Mapping

| UI capability | Backend route |
|---|---|
| Health and sidecar readiness | `GET /health` |
| Current workspace | `GET /projects/current` |
| Create workspace | `POST /projects/init` |
| Workflow list | `GET /workflows` |
| Workflow details | `GET /workflows/{workflow_id}` |
| Validate workflow | `POST /workflows/{workflow_id}/validate` |
| Create generic run | `POST /workflows/{workflow_id}/runs` |
| Subtitle workflow template | `GET /quickstart/subtitle/template` |
| Subtitle workflow tool catalog | `GET /quickstart/subtitle/tools` |
| Local subtitle quickstart | `POST /quickstart/subtitle/local` |
| YouTube subtitle quickstart | `POST /quickstart/subtitle/youtube` |
| List tasks | `GET /runs` |
| Task status | `GET /runs/{run_id}` |
| Resume task | `POST /runs/{run_id}/resume` |
| Abort task | `POST /runs/{run_id}/abort` |
| Task events | `GET /runs/{run_id}/events` |
| Live task events | `GET /runs/{run_id}/events/stream` |
| Task results | `GET /runs/{run_id}/artifacts` |
| Artifact details | `GET /artifacts/{artifact_id}` |
| Artifact preview | `GET /artifact-versions/{version_id}/preview` |
| Artifact diff | `GET /artifact-versions/{from_version_id}/diff/{to_version_id}` |
| Export artifact | `POST /artifact-versions/{version_id}/export` |
| File download/open | `GET /artifact-versions/{version_id}/file` |
| Runtime settings | `GET /runtime/settings` |
| Provider update | `PUT /runtime/providers/{name}` |
| Provider auth update | `PUT /runtime/providers/{name}/auth` |
| Secret check | `POST /runtime/secrets/check` |
| Secret set | `PUT /runtime/secrets` |
| Model status | `GET /runtime/models` |
| Diagnostics | `GET /doctor` |

## Backend Gaps For First Desktop Slice

These gaps should be tracked separately from UI design. The first release can
ship with documented constraints for some of them, but UI copy and flows must
not imply unsupported behavior.

| Priority | Gap | Current code fact | Product impact | Proposed resolution |
|---|---|---|---|---|
| P0 | Open existing workspace | `POST /projects/init` creates a new project and fails when `openbbq.yaml` already exists; there is no project-open API | A normal "Open Workspace" button cannot call the sidecar directly | Use Electron main to restart sidecar with `--project`, or add `POST /projects/open` / project switch API |
| P0 | Persistent quickstart task history | `GET /runs` lists the active project plus generated project refs registered in current sidecar memory | Quickstart tasks disappear from the task list after sidecar restart | Add workspace-level run registry or scan `.openbbq/generated/**/openbbq.yaml` |
| P0 | User-facing task summaries | `RunRecord` exposes backend fields such as run ID, workflow ID, status, paths, timestamps, and error; quickstart generated projects have no run-scoped workflow detail API | Task cards cannot reliably show source summary, friendly workflow name, last result, or result availability | Add `RunSummary` API, or use hard-coded quickstart mappings plus volatile current-session metadata |
| P1 | Workflow template library | `GET /workflows` returns workflows in the active project, not quickstart templates | Workflow Library cannot be driven by backend metadata | Hard-code two quickstart cards first; later add template metadata endpoint with source types, parameters, capabilities, results, and plugin dependencies |
| P1 | Request-specific preflight | Doctor checks environment and existing workflow requirements, but not selected file/URL/cookies/media decode | Preflight cannot guarantee the selected quickstart request will run | First release uses field validation plus environment checks; later add quickstart preflight endpoints |
| P1 | Pre-run output path | Quickstart request accepts and returns `output_path`, but does not auto-export to it | Asking for output path before running is misleading | Remove pre-run output-path UI; use artifact export after review, or implement backend auto-export |
| P1 | Timeline DTO | Backend exposes raw events and workflow state, not per-step timeline summaries | Frontend must reconstruct progress and duplicate event parsing logic | First release reconstructs from events; later add `GET /runs/{run_id}/timeline` |
| P2 | Global capability doctor | `GET /doctor` without `workflow_id` checks settings readiness, while ffmpeg, yt-dlp, and faster-whisper checks require a workflow-scoped doctor call | Home and Settings cannot show global dependency status accurately | First release shows provider/cache/sidecar only; later add `GET /doctor/capabilities` or equivalent |
| P2 | Writable model/cache settings | Runtime settings and model status are readable, provider/auth are writable, model/cache settings are not | Settings cannot edit cache path/default ASR model/device/compute type | Show model/cache settings read-only first; later add runtime model/settings update API |
| P2 | Duplicate and retry quickstart task | Backend does not persist the original quickstart request and has no duplicate task API | "Duplicate" or "retry with same settings" cannot survive navigation/restart | Defer, or add persisted quickstart request metadata and duplicate API |
| P2 | Immediate abort | Running abort writes an abort request; `RunStatus` remains `running` until the runner consumes the request after a step completes | UI must not promise instant cancellation or treat cancel requested as a backend status | Use UI-local "Cancel requested" copy and explain it stops after the current step |

## First Release Scope

The first release should include:

- Workspace creation.
- Existing workspace opening through desktop-shell sidecar launch/restart, unless
  a backend project-open API is added first.
- Home dashboard with active workspace status, sidecar/provider/cache readiness,
  and current-session run visibility.
- New Task wizard for local video and YouTube translated SRT.
- Runtime provider setup.
- Basic preflight using frontend field validation plus current doctor/runtime
  checks.
- Task monitor with live event streaming and frontend-reconstructed timeline.
- Results review with transcript, translation, subtitle preview, and files.
- Subtitle export.
- Hard-coded built-in workflow cards in New Task.
- Diagnostics drawer.
- English and Simplified Chinese UI localization, with English fallback.

The first release may defer:

- Full visual workflow editor.
- Editable subtitle rows.
- Artifact write-back from UI edits.
- Translation QA as a default workflow step.
- Plugin marketplace.
- Custom workflow persistence.
- Backend-driven Workflow Library.
- Persistent quickstart recent task history.
- Duplicate task and retry-from-original-request.
- Writable model/cache settings.
- Multi-workspace recent list if Electron shell support is not ready.

## Success Metrics

- A first-time user can create a translated SRT from a local video without
  understanding runs, artifacts, or generated projects.
- A first-time user can identify and fix a missing provider/API key before
  starting a task.
- A user can monitor a task and understand what stage is currently running.
- A user can inspect the generated transcript, translation, and subtitle before
  export.
- A user can export the final subtitle file.
- A user can switch the interface between English and Simplified Chinese without
  changing task source or target language settings.
- A technical user can access advanced diagnostics without cluttering the
  primary path for normal users.

## Open Product Questions

- Should "Workflow" be the only visible term, or should the UI introduce
  "Workflow Template" only in the library/customization context?
- Should the first release include translation QA as an optional checkbox in the
  translated subtitle workflow?
- Should the backend later implement automatic export from a pre-run destination
  path, or should desktop keep export strictly after review?
- How much video preview should be included in the first release: file metadata
  only, basic playback, or subtitle overlay?
- Should custom workflow editing wait until plugin metadata can fully describe
  source types, parameters, and result previews?

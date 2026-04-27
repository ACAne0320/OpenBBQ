# Desktop UI design

> Status: product and visual design approved. Implementation has not started.

## Goal

Design the first OpenBBQ desktop UI around a creator-facing subtitle task flow.
The UI should let a non-technical user choose a media source, arrange a
template-based workflow, monitor execution, review editable subtitle segments,
and export an SRT file without seeing backend concepts by default.

The design is intentionally product- and visual-first. It does not bind the
implementation to a frontend stack, but it stays compatible with the current
FastAPI sidecar and known backend limitations.

## Primary user

The first UI prioritizes creators, translators, fansubbers, and editors who
want to turn a local video or remote video URL into reviewed subtitles. Technical
diagnostics remain available, but they are not the primary journey.

## Visual direction

The approved direction is a warm editorial desktop workbench:

- paper-toned surfaces;
- ink-brown body text and controls;
- burnt ochre primary accent;
- compact, work-focused layout;
- media and segment review surfaces that feel like editing a subtitle draft
  rather than operating a backend dashboard.

The memorable product cue is the paper/source workbench. Source files, workflow
steps, logs, and segment cards should feel like parts of a local editing desk,
not like generic SaaS cards.

## Non-goals

This UI design does not include:

- a full blank-canvas workflow graph editor;
- a plugin marketplace;
- multi-user collaboration;
- cloud sync;
- a marketing landing page;
- raw run IDs, generated project paths, artifact IDs, selectors, or config hashes
  in the default flow;
- complex subtitle timeline editing beyond segment text review and autosave;
- pre-run output path selection.

## Design system

### Theme and atmosphere

Use a light warm theme. The app should feel local, calm, and editorial, with
enough density for repeated editing work. Avoid black navigation blocks, blue or
purple gradients, glassmorphism, and generic white-card dashboard styling.

### Color roles

Use the palette as roles, not one-off colors:

| Token | Value | Role |
|---|---:|---|
| `canvas` | `oklch(94% 0.025 82)` | App background |
| `paper` | `#fffaf0` | Primary work surfaces |
| `paper-muted` | `#f8f1e5` | Inputs, rows, editable fields |
| `paper-side` | `#eee1cc` | Sidebar and quieter shell surfaces |
| `paper-selected` | `#efe0c9` | Selected workflow rows and active segment cards |
| `ink` | `#20251f` | Main text |
| `ink-brown` | `#3b2a1f` | Strong secondary action |
| `accent` | `#b6632f` | Primary action, active nav, selected control |
| `accent-soft` | `#ead3c1` | Failed-state banner |
| `text-muted` | `#6d6251` | Secondary text |
| `line` | `#dfd0ba` | Dividers |
| `ready-dot` | `#6f7c46` | Small readiness/completed signal only |
| `log-bg` | `#2d241d` | Runtime log surface |

Green is not a button or selected-state color. It is only a small completion or
readiness indicator.

### Typography

Use an editorial serif for product identity and major page titles, paired with a
plain, compact UI sans for controls and dense content. The exact implementation
font can be decided later, but the spec rejects generic all-Inter styling.

Suggested type rules:

| Use | Style |
|---|---|
| Brand and page title | Editorial serif, 36-40px, line-height 1.02 |
| Section title | UI sans, 20-24px, weight 700-800 |
| Control label | UI sans, 11-12px, uppercase where useful |
| Body and cards | UI sans, 13-14px, line-height 1.4-1.5 |
| Logs | Monospace, 12px, line-height 1.55 |

Do not scale type with viewport width. Keep letter spacing normal.

### Radius and depth

Use a tight radius scale:

- `5px` for small nav items and inline tags;
- `6px` for buttons, inputs, and compact controls;
- `7px` for rows and segment cards;
- `8px` for main panels;
- `pill` for chips and toggles.

Use background-color steps and small shadows for depth:

- main panel: `0 2px 10px rgba(38,33,22,0.14)`;
- small control: `0 1px 4px rgba(38,33,22,0.12)`;
- selected row: inset accent outline plus soft shadow.

Do not use heavy borders around every container.

### Motion

Use motion only where it supports the workflow:

- source import: a selected source behaves like a sheet being filed into the
  task flow;
- results review: selecting a card seeks the video and highlights the waveform
  segment; selecting a waveform segment scrolls to and highlights the card;
- all buttons and toggles use a quick press scale;
- drawers and inline error banners fade/slide through transform and opacity
  only.

Respect reduced-motion preferences. Do not animate layout-heavy properties.

### CSS strategy note

The design does not bind the implementation stack. If implemented with the
roadmap stack later, use one styling strategy: Tailwind-only tokens/classes with
component primitives adapted to this design. Do not mix Tailwind and CSS Modules
on the same element.

## Global shell

The app uses a left rail and a main work surface.

Primary navigation:

- Home;
- New;
- Tasks;
- Results;
- Settings.

The sidebar uses a warm paper surface, not black. Active navigation uses burnt
ochre. The sidebar can show a small workspace/source/task context at the bottom,
but it should not become a status dashboard.

## New task wizard

The new task flow is the primary first-run experience.

### Step 1: Choose source

This page has one job: choose the input source. It must not show workflow,
provider, readiness, history, live tasks, or results.

Layout:

- Page title: `Choose a source`.
- One large import frame.
- Top of frame: URL input for a remote video link.
- Middle: visual divider with `or import a local file`.
- Bottom of frame: drag/drop and click target for local file import.
- Footer: Cancel and disabled Continue until a valid URL or file exists.

Supported source copy:

- remote URL, including YouTube or yt-dlp-compatible links;
- local video/audio files such as MP4, MOV, MKV, M4A, and WAV.

The source page should make file and URL feel like two ways to provide the same
source, not two separate product modes.

### Step 2: Arrange workflow

After source selection, OpenBBQ proposes a workflow template based on source
type:

- local video -> local video to translated SRT;
- remote URL -> remote video to translated SRT.

Layout:

- left side: workflow step list;
- right side: selected step parameters;
- bottom: Back and Continue.

The workflow list shows step order, name, artifact transition summary, and an
enable control.

Required steps have locked-on toggles. Optional steps have active on/off
toggles. The selected step uses `paper-selected` and `accent`.

The parameter panel is directly editable. There is no separate `Edit step`
button. The right side is fully dedicated to parameters for the selected step.

Example local workflow steps:

1. Extract Audio;
2. Transcribe;
3. Correct Transcript;
4. Segment Subtitle;
5. Translate Subtitle;
6. Export Subtitle.

AI provider credentials and API keys are not configured here. They belong in
global Settings. Provider names may appear as parameter values when the selected
step needs them, but credential management is out of scope for this page.

First implementation can restrict editing to valid template edits: optional
step toggles and step parameter edits. Full arbitrary reordering or graph editing
requires stronger backend template and save contracts.

### Step 3: Workflow settings and validation

This can be either a distinct step or a continuation of workflow arrangement,
depending on implementation. It should collect task-level values that are not
specific to one step, such as source and target language.

Preflight should run after the user has a source and workflow arrangement. It
should explain what is actually checked by the current backend and avoid
implying unsupported source-specific guarantees.

Output path is not requested before running. Export happens from Results after
review.

## Task monitor

The task monitor is a log-dominant runtime console.

Layout:

- header: task name, workflow summary, Diagnostics, Request cancel;
- top strip: compact progress and step summary;
- main area: runtime log;
- failed state only: error banner with `Retry checkpoint`.

The progress strip is intentionally small. It shows the current or failed step
and a compact sequence of completed/failed/blocked steps. It should not consume
the page.

The runtime log occupies most of the monitor. It streams backend events in real
time. Users can copy the log or open diagnostics for raw details.

Error behavior:

- running task: no error banner and no retry button;
- failed task: show error banner and `Retry checkpoint` together;
- completed task: no error banner and no retry button; actions move toward
  review/export.

The monitor does not contain runtime parameter selectors. Users fix the root
cause in Settings or workflow configuration, then return and retry.

Target retry behavior:

- retry from the nearest completed checkpoint after the failing step;
- preserve completed artifacts where valid;
- do not force a full restart unless the workflow change invalidates earlier
  outputs.

Backend note: this target behavior likely needs a run-scoped checkpoint retry
API for generated quickstart jobs. The current backend has run records, events,
abort, resume, artifacts, and rerun primitives, but the desktop contract should
make checkpoint retry explicit before the UI promises it.

## Results review

The results page is a media review editor, not a paper-stack document preview.

Layout:

- left side:
  - video preview with current subtitle overlay;
  - audio loudness waveform below the video;
  - translucent subtitle segment overlays on top of the waveform;
- right side:
  - continuous segment card list;
  - each card contains timestamp range, Transcript text, and Translation text;
  - the active card matches the active waveform segment and video time.

Interaction:

- selecting a card seeks the video and highlights its waveform segment;
- selecting a waveform segment scrolls to and highlights the matching card;
- transcript and translation fields are directly editable;
- edits autosave;
- a small status indicator can show `Saving`, `Saved`, or error state;
- `Export SRT` uses the latest saved segment text.

There is no explicit Save button in the approved design.

Backend note: editable segment cards require backend support for editable result
versions or segment patching before export. Current artifact preview/export
routes are not sufficient for reliable autosaving of edited segment content.

## Settings

Settings owns global runtime configuration:

- interface language;
- AI providers;
- API keys and secrets;
- model/cache status;
- local dependency diagnostics;
- sidecar status;
- advanced paths.

Provider setup should not appear inside the workflow arrangement page. The new
task flow may route users to Settings only when preflight or runtime errors
indicate missing global setup.

## Diagnostics

Diagnostics is an advanced surface reached from Task monitor, Settings, or
failed states. It can show:

- raw backend event payloads;
- run IDs;
- generated project paths;
- artifact and artifact version IDs;
- doctor checks;
- redacted backend errors.

These values do not appear in the primary creator-facing flow.

## Backend mapping

The first implementation should use the existing sidecar routes where they
exist:

| UI capability | Current route |
|---|---|
| Current workspace | `GET /projects/current` |
| Create workspace | `POST /projects/init` |
| Local subtitle job | `POST /quickstart/subtitle/local` |
| Remote subtitle job | `POST /quickstart/subtitle/youtube` |
| List tasks | `GET /runs` |
| Task detail | `GET /runs/{run_id}` |
| Runtime log | `GET /runs/{run_id}/events/stream` |
| Abort | `POST /runs/{run_id}/abort` |
| Task artifacts | `GET /runs/{run_id}/artifacts` |
| Artifact preview | `GET /artifact-versions/{version_id}/preview` |
| Artifact export | `POST /artifact-versions/{version_id}/export` |
| Runtime settings | `GET /runtime/settings` |
| Provider setup | `PUT /runtime/providers/{name}` and `PUT /runtime/providers/{name}/auth` |
| Diagnostics | `GET /doctor` |

## Backend gaps implied by the approved UI

These gaps should be tracked separately before promising the full UX:

| Gap | UI impact |
|---|---|
| Workflow template metadata | The first UI may hard-code local and remote subtitle templates. Backend-driven template cards need metadata. |
| Template edit persistence | Step toggles and parameter edits need a generated workflow save/update contract. |
| Run-scoped checkpoint retry | Failed task retry from latest completed step needs an explicit desktop-safe API. |
| Editable segment persistence | Autosaving transcript/translation edits needs editable result versions or segment patching. |
| Export from edited content | Export must use the latest saved edited segment version, not the original artifact. |
| Video preview and waveform assets | The UI needs access to source media and audio loudness data or a renderer-side waveform derivation strategy. |

## Responsive behavior

Desktop is primary. Minimum comfortable width is a desktop window where the left
rail, main media area, and segment editor can coexist.

For narrower widths:

- sidebar can collapse to icons;
- source import remains one vertical frame;
- workflow arrangement stacks parameters below steps;
- task monitor keeps progress above log;
- results review stacks video/waveform above segment cards.

Every interactive target should be at least 40px high.

## Accessibility

Required baseline:

- buttons are real buttons;
- navigation uses links;
- icon-only controls require labels;
- toggles expose checked/disabled state;
- editable segment fields are keyboard reachable and announce save state;
- waveform segment selection has a non-pointer alternative through segment
  cards;
- focus state is visible on every interactive element.

## Testing strategy

When implementation starts, use tests around:

- source validation for URL and local file modes;
- workflow template selection by source type;
- optional step toggle behavior and required-step lock behavior;
- direct parameter editing;
- runtime event streaming and failed-state rendering;
- absence of retry controls outside failed state;
- segment card selection syncing with video/waveform state;
- autosave state transitions;
- export using the latest saved edited text;
- English and Simplified Chinese strings without clipping.

## Acceptance criteria

- A user can start from New and see only source import on the first step.
- The workflow page proposes a source-appropriate template and edits step
  parameters directly.
- Required steps cannot be disabled; optional steps can be toggled.
- Runtime monitor shows compact progress and a dominant real-time log.
- Error banner and `Retry checkpoint` appear only in failed state.
- Results review has video preview, waveform with segment overlays, and editable
  transcript/translation segment cards.
- Segment edits autosave and export uses saved edited content.
- Provider setup remains in global Settings.
- Backend technical identifiers remain out of the primary creator flow.

## Spec self-review

- Placeholder scan: no placeholder sections remain.
- Internal consistency: source import, workflow arrangement, runtime monitor,
  and results editor all follow the warm editorial workbench direction.
- Scope check: this is one desktop UI design milestone; implementation,
  packaging, and backend gap closure are outside this spec.
- Ambiguity check: current backend support and target backend gaps are separated
  explicitly.

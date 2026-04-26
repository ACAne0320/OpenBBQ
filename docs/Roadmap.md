# Roadmap

## Tech Stack

| Layer | Technology |
|---|---|
| Backend language | Python |
| Backend framework | FastAPI |
| Backend package management | uv |
| Backend testing | pytest |
| Backend lint / format | Ruff |
| Desktop shell | Electron |
| Frontend renderer | React + TypeScript + Vite |
| Frontend package management | pnpm |
| UI styling / components | Tailwind CSS + shadcn/ui |
| Frontend unit tests | Vitest |
| Frontend end-to-end tests | Playwright |

## Phase 1 — Backend Core & CLI

See [Phase 1 Documentation](./phase1/README.md) and [Backend & CLI Goals](./phase1/Backend-CLI-Goals.md) for detailed short-term objectives.

**Goal:** Establish a stable, well-tested headless backend with a CLI adapter for debugging and early workflow execution.

- Project, Workflow, Tool, and Artifact domain models
- Plugin manifest v2 with named inputs, named outputs, parameter schema, and execution contract
- Workflow engine / orchestrator (step sequencing, pause/resume, error recovery)
- Typed workflow events with severity `level` and structured `data`
- Artifact persistence, versioning, and SQLite-backed artifact records
- Adapter-independent application services for workflow and artifact operations
- CLI for project management, workflow execution, and artifact inspection
- Configuration and plugin discovery

> The [YouTube → Subtitle pipeline](./Target-Workflows.md) is the production target workflow. Phase 1 validates this pipeline's full config and artifact type contracts using mock plugins; real plugin implementations are introduced in Phase 2.

## Phase 2 — Real Local Media and Translation Plugins

**Goal:** Make real local media language workflows usable from the CLI and
prepare the backend contracts that the desktop uses.

- Local file import and file-backed media artifacts
- Built-in yt-dlp remote video download
- Built-in ffmpeg audio extraction
- Built-in faster-whisper transcription
- Built-in glossary replacement
- Built-in transcript correction and subtitle segmentation
- Built-in OpenAI-compatible LLM translation
- Built-in subtitle export
- Deterministic tests with optional local real-media and real-LLM smoke runs
- Generated one-step `subtitle local` and `subtitle youtube` CLI workflows
- Local FastAPI sidecar with typed API envelopes, run records, background
  workflow execution, SSE event streaming, artifact preview/export/import,
  runtime/provider/secret/model/doctor routes, and API-accessible subtitle
  quickstart jobs

`llm.translate` and implicit LLM environment-variable fallback have been removed. LLM-backed tools require a named runtime provider profile, and environment variables are only read through explicit secret references such as `api_key = "env:OPENBBQ_LLM_API_KEY"`.

See [Phase 2 Exit Checklist](./phase2/Phase-2-Exit.md) for completion criteria and smoke checks.

> Desktop and automation adapters should call application services or the local
> API sidecar, not CLI parser internals.

## Phase 3 — Desktop Application

**Goal:** Provide a visual interface for non-technical users to build, monitor, and intervene in workflows.

The desktop communicates with a local Python sidecar over authenticated
loopback HTTP. Electron main owns the token and process lifecycle; the renderer
uses preload IPC rather than owning backend credentials directly.

- Project Dashboard — overview of projects, recent activity, quick actions
- Workflow Configuration Dashboard — visual workflow builder, step ordering, parameter editing
- Artifact Edit Panel — inline editing of transcriptions, translations, subtitles with diff view
- Preview Panel — real-time preview of subtitle renders, audio playback with transcript overlay
- Reusable Asset Pane — browse and manage reusable assets (glossaries, style guides, templates)
- Human-in-the-loop UI — review queues, approval gates, inline annotation
- Plugin marketplace / manager — install, configure, and update plugins from the desktop
- Multi-user collaboration — shared projects, conflict resolution, activity feeds
- Notification system — alerts for review requests, workflow failures, completed steps

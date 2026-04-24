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
- Artifact persistence, versioning, and artifact indexes
- Adapter-independent application services for workflow and artifact operations
- CLI for project management, workflow execution, and artifact inspection
- Configuration and plugin discovery

> The [YouTube → Subtitle pipeline](./Target-Workflows.md) is the production target workflow. Phase 1 validates this pipeline's full config and artifact type contracts using mock plugins; real plugin implementations are introduced in Phase 2.

## Phase 2 — Real Local Media and Translation Plugins

**Goal:** Make the CLI run real local media language workflows before adding an API or desktop surface.

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

`llm.translate` and implicit LLM environment-variable fallback have been removed. LLM-backed tools require a named runtime provider profile, and environment variables are only read through explicit secret references such as `api_key = "env:OPENBBQ_LLM_API_KEY"`.

See [Phase 2 Exit Checklist](./phase2/Phase-2-Exit.md) for completion criteria and smoke checks.

> Desktop, API, and automation adapters should call application services or future API wrappers, not CLI parser internals.

## Phase 3 — Desktop Application

**Goal:** Provide a visual interface for non-technical users to build, monitor, and intervene in workflows.

- Project Dashboard — overview of projects, recent activity, quick actions
- Workflow Configuration Dashboard — visual workflow builder, step ordering, parameter editing
- Artifact Edit Panel — inline editing of transcriptions, translations, subtitles with diff view
- Preview Panel — real-time preview of subtitle renders, audio playback with transcript overlay
- Ruler Asset Pane — browse and manage reusable assets (glossaries, style guides, templates)
- Human-in-the-loop UI — review queues, approval gates, inline annotation
- Plugin marketplace / manager — install, configure, and update plugins from the desktop
- Multi-user collaboration — shared projects, conflict resolution, activity feeds
- Notification system — alerts for review requests, workflow failures, completed steps

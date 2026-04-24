# Backend & CLI — Short-Term Goals

Detailed objectives for Phase 1 of the [Roadmap](../Roadmap.md).

For launch scope and implementation contracts, see the [Phase 1 Documentation Index](./README.md).

## Tech Stack

### Backend

| Concern | Tool |
|---|---|
| Language | Python |
| Package / dependency management | uv |
| Testing | pytest |
| Lint / format | Ruff |

> **Note:** FastAPI is still the planned web framework for a future API adapter. Phase 1 is headless — no HTTP routes are implemented.

### Desktop (Phase 3 reference)

| Concern | Tool |
|---|---|
| Shell | Electron |
| Renderer | React + TypeScript + Vite |
| Package management | pnpm |
| Styling / components | Tailwind CSS + shadcn/ui |
| Unit tests | Vitest |
| End-to-end tests | Playwright |

## Backend Goals

### Domain Models

- [ ] Define `Project` model — metadata, config, associated workflows
- [ ] Define `Workflow` model — ordered steps, parameters, status tracking (static config + mutable state separated)
- [ ] Define `Tool` model — capability declaration (inputs, outputs, parameters, effects)
- [ ] Define `Artifact` and `ArtifactVersion` models — typed output, versioning, lineage tracking

### Plugin System

- [ ] Plugin manifest schema (name, version, tool declarations, parameter schemas)
- [ ] Plugin loader — discover and validate manifests from configured directories without executing plugin code
- [ ] Input/output artifact type validation per plugin, pre- and post-execution
- [ ] Execution contract — standardized request/response interface plugins must implement

### Workflow Engine

- [ ] Step sequencer — execute steps in declared order, passing artifacts between them
- [ ] Pause/resume — halt before or after a step (`pause_before` / `pause_after` step config flags, or plugin `pause_requested` response), persist state, resume across process restarts
- [ ] Abort — immediate transition for `paused` workflows; cooperative cancellation between steps for `running` workflows; persist `aborted` status and all prior artifacts
- [ ] Workflow lock file — create `<workflow-id>.lock` (recording PID) atomically on `run`/`resume`; remove on `paused` or final status; detect and warn on stale locks; cleared via `openbbq unlock <workflow>`
- [ ] Guard against double-run — reject `run` or `resume` if lock file already exists
- [ ] Error handling & recovery — per-step `abort`, `retry`, and `skip` policies
- [ ] Deterministic replay metadata — record config hash, plugin version, parameter values, and artifact version IDs per step
- [ ] Event emission — append-only lifecycle events (step started, completed, failed, paused, aborted, plugin loaded/invalid)

### Artifact Management

- [ ] Artifact storage abstraction (local filesystem for Phase 1)
- [ ] Versioning — each re-run or edit produces a new immutable version
- [ ] Lineage — record producer plugin, tool, step, and input artifact versions per artifact version

### Configuration

- [ ] Project config format: **YAML** (decided; do not add TOML support)
- [ ] Implement the YAML project config schema from [Project Config](./Project-Config.md)
- [ ] Create canonical YAML project fixtures in `tests/fixtures/projects/`: small text workflow, pause workflow, and full mock YouTube → subtitle workflow
- [ ] Create canonical mock plugin fixtures in `tests/fixtures/plugins/`: `mock-text` and `mock-media`
- [ ] Plugin search paths from config, environment variables, and CLI flags
- [ ] Configuration precedence: CLI flags > env vars > project config > defaults
- [ ] Configuration precedence tests matching [Project Config](./Project-Config.md)
- [ ] Logging setup (structured, level-controlled via `OPENBBQ_LOG_LEVEL`)

## CLI Goals

### Project Management

- [ ] `openbbq init` — scaffold a new project with default config and directory layout
- [ ] `openbbq project list` — list projects in the current workspace
- [ ] `openbbq project info` — show project metadata, workflow count, plugin paths, and artifact storage path

### Workflow Operations

- [ ] `openbbq run <workflow>` — validate and execute a workflow end-to-end; reject if `running`, `paused`, or `completed`
- [ ] `openbbq run <workflow> --step <step-id>` — rerun a single step; allowed for `completed` and `failed` workflows; rejected for `running` and `paused`; creates new `StepRun` and artifact versions; leaves downstream artifacts intact; cannot combine with `--force`
- [ ] `openbbq run <workflow> --force` — reset a `completed` or crash-recovered `running` (no lock file) workflow to `pending` and rerun from scratch; marks dangling `running` StepRuns as `failed`; reuses existing artifact IDs and creates new versions; cannot combine with `--step`
- [ ] `openbbq status <workflow>` — show workflow status, current step, last event, and produced artifacts
- [ ] `openbbq resume <workflow>` — resume a paused workflow; rebuild output binding map from `StepRun` history
- [ ] `openbbq abort <workflow>` — synchronous for `paused`; atomic abort request file + immediate return for `running`
- [ ] `openbbq unlock <workflow>` — remove stale lock file; print recorded PID; require `--yes` to skip confirmation

### Artifact Inspection

- [ ] `openbbq artifact list` — list artifacts, filterable by `--workflow`, `--step`, and `--type`
- [ ] `openbbq artifact show <id>` — display artifact metadata, content preview, and lineage
- [ ] `openbbq artifact diff <v1> <v2>` — compare two artifact versions (text artifacts in Phase 1)

### Plugin Management

- [ ] `openbbq plugin list` — list discovered plugins; flag invalid ones with validation errors
- [ ] `openbbq plugin info <name>` — show manifest, tool declarations, parameter schemas, and declared effects

### Diagnostics

- [ ] `openbbq logs <workflow>` — print workflow events in chronological order
- [ ] `openbbq validate <workflow>` — validate config, plugin references, parameters, and artifact type compatibility without executing
- [ ] `openbbq version` — print installed OpenBBQ version
- [ ] `--json` flag — machine-readable JSON output for all inspection and status commands
- [ ] `--verbose` / `--debug` output modes

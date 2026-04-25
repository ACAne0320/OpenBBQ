# Architecture

OpenBBQ is a headless, artifact-driven media workflow backend. The current CLI is an adapter over typed application services; future desktop, API, and automation surfaces should use those services or API wrappers rather than CLI parser internals.

## Design Principles

1. Headless backend first, UI adapters later.
2. Workflows are explicit graphs of source inputs, tool steps, and artifact outputs.
3. Tools are plugins with strict manifest v2 contracts.
4. Artifacts are versioned, inspectable, and reusable across reruns.
5. Execution is deterministic where possible and LLM-backed where useful.
6. Human review should be modeled as workflow state, events, and artifacts.

## Backend Layers

1. Domain models: Pydantic models for project config, workflow state, plugin payloads, runtime settings, and artifacts.
2. Plugin registry: loads `manifest_version = 2` manifests with named inputs and outputs, JSON Schema parameters, side effects, runtime requirements, and optional UI metadata.
3. Workflow engine: validates named bindings, executes steps, persists transitions, emits typed events with `level` and `data`, and supports pause, resume, abort, retry, skip, and rerun.
4. Storage: keeps workflow state, event logs, artifacts, artifact versions, and run records in SQLite, with file-backed artifact payloads under `.openbbq/`.
5. Application services: expose workflow and artifact operations independent of the CLI.
6. Adapters: CLI today; desktop, HTTP API, and worker adapters later.

The desktop backend adapter is a local FastAPI sidecar managed by Electron main.
It exposes Pydantic-validated REST responses for commands and queries, and SSE
for workflow event streaming. The API layer calls `openbbq.application` services
and does not import CLI parser internals.

## Local Data Stores

OpenBBQ uses SQLite, SQLAlchemy ORM models, and Alembic migrations for
structured local records. The filesystem remains the store for large artifact
payloads.

- Project records live at `<project>/.openbbq/openbbq.db`. This database records
  run records, workflow state, step runs, workflow events, artifact records, and
  artifact version metadata. Artifact file bodies remain in
  `<project>/.openbbq/artifacts/`; database rows store paths, hashes, sizes,
  encodings, metadata, and lineage.
- SQLite is the source of truth for structured project records. Legacy
  `state.json`, `events.jsonl`, `artifact.json`, `version.json`, and artifact
  index files are no longer written or read by the current backend.
- ORM table definitions live in `openbbq.storage.orm`. Project database access
  is centralized in `openbbq.storage.database.ProjectDatabase`; future schema
  changes should be represented as Alembic revisions under
  `openbbq.storage.migrations`.
- User runtime records live at `~/.openbbq/openbbq.db`, or beside
  `OPENBBQ_USER_CONFIG` when that environment variable is set. Provider profiles
  and user-entered cloud API credentials are stored there. User-entered
  credentials use `sqlite:` secret references and are stored as plaintext by
  product decision for local-first desktop convenience.
- Project databases should reference provider names or secret references, not
  duplicate user-level credential values.

## Runtime Contracts

LLM-backed tools require a named runtime provider profile such as `openai`. Provider profiles own the OpenAI-compatible base URL, optional default chat model, and secret reference. Environment variables are only read through explicit secret references, for example `api_key = "env:OPENBBQ_LLM_API_KEY"`. User-entered desktop credentials are stored in the user SQLite database and referenced with `sqlite:openbbq/providers/<name>/api_key`.

The legacy `llm.translate` alias and implicit `OPENBBQ_LLM_API_KEY` fallback are removed. Translation flows should use `transcript.segment` to produce `subtitle_segments`, then `translation.translate` to produce `translation`.

## Desktop Direction

The desktop should be a rich adapter over the backend, not a separate workflow implementation. Expected desktop surfaces include:

1. Project dashboard.
2. Workflow configuration dashboard.
3. Artifact edit panel.
4. Preview panel.
5. Reusable asset pane for glossaries, style guides, and templates.
6. Human-in-the-loop review queues.

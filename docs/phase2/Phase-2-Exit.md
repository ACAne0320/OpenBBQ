# Phase 2 Exit Checklist

Phase 2 is complete when the CLI and local API sidecar can run or start real
local and remote media language workflows through the backend contracts that the
future desktop will use.

## Implemented capabilities

- File-backed import for local `video`, `audio`, and `image` artifacts.
- Built-in `remote_video.download` plugin backed by `yt-dlp`.
- Built-in `ffmpeg.extract_audio` plugin for audio extraction.
- Built-in `faster_whisper.transcribe` plugin with configurable model cache.
- Built-in `transcript.correct` plugin for source-language ASR correction.
- Built-in `transcript.segment` plugin for subtitle-ready timed units.
- Built-in `translation.translate` plugin for OpenAI-compatible LLM translation.
- Built-in `translation.qa` plugin for deterministic translation risk checks.
- Built-in `subtitle.export` plugin for SRT output.
- Runtime provider profiles, explicit `env:`, `sqlite:`, and `keyring:` secret
  references, redaction, model cache settings, settings-level `doctor` checks,
  and workflow-specific `doctor` checks.
- One-step generated workflows:
  - `openbbq subtitle local` for local video files.
  - `openbbq subtitle youtube` for remote video URLs supported by `yt-dlp`.
- Backend hardening for Phase 3:
  - Pydantic contract models.
  - Manifest v2 with named inputs and outputs.
  - Typed workflow events with `level` and structured `data`.
  - SQLite-backed workflow, run, event, artifact, and artifact-version records.
  - Workflow, run, artifact, runtime, quickstart, and diagnostic application
    services.
  - Local FastAPI sidecar with typed success/error envelopes, bearer-token
    enforcement by default, run records, non-blocking API workflow execution,
    event polling and SSE streaming, artifact preview/export/import, runtime
    setup, plugin metadata, project info, and generated subtitle job routes.
  - Removal of the legacy `llm.translate` tool and implicit LLM environment
    fallback.

## Automated exit checks

Run these from the repository root:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build --wheel --out-dir /tmp/openbbq-wheel-check
```

Verify the desktop API sidecar slice:

```bash
uv sync --extra api
uv run pytest tests/test_api_*.py tests/test_application_runs.py \
  tests/test_application_artifacts.py tests/test_application_quickstart.py
```

Validate the generated and canonical remote workflows:

```bash
uv run openbbq validate remote-video-translate-subtitle \
  --project tests/fixtures/projects/remote-video-translate-subtitle

uv run openbbq validate youtube-to-srt \
  --project src/openbbq/workflow_templates/youtube_subtitle

OPENBBQ_USER_CONFIG=/tmp/openbbq-phase2-empty.toml \
OPENBBQ_CACHE_DIR=/tmp/openbbq-phase2-cache \
uv run openbbq --json doctor
```

The local fixture workflows under `tests/fixtures/projects/local-video-*` are
templates that intentionally contain `project.art_imported_video`. They require a
real imported artifact selector before direct `openbbq validate` or `openbbq run`
can succeed. For user-facing local runs, prefer `openbbq subtitle local`, which
imports the video and generates an isolated workflow automatically.

## Manual real-environment smoke checks

These checks need local media, optional dependencies, network access, and LLM
credentials, so they are not part of the default test suite.

Install the optional runtime groups:

```bash
uv sync --extra download --extra media --extra llm --extra secrets
ffmpeg -version
```

Configure an OpenAI-compatible provider:

```bash
export OPENBBQ_LLM_API_KEY=sk-your-key
uv run openbbq auth set openai \
  --type openai_compatible \
  --base-url https://api.openai.com/v1 \
  --api-key-ref env:OPENBBQ_LLM_API_KEY \
  --default-chat-model gpt-4o-mini
uv run openbbq auth check openai --json
```

Run a local video smoke:

```bash
uv run openbbq --json subtitle local \
  --input ./sample.mp4 \
  --source en \
  --target zh \
  --output ./out.local.zh.srt \
  --provider openai
```

Run a remote video smoke:

```bash
uv run openbbq --json subtitle youtube \
  --url "https://www.youtube.com/watch?v=..." \
  --source en \
  --target zh \
  --output ./out.youtube.zh.srt \
  --provider openai
```

For each smoke run, inspect the generated project path from JSON output:

```bash
uv run openbbq status <workflow-id> --project <generated_project_root>
uv run openbbq logs <workflow-id> --project <generated_project_root>
uv run openbbq artifact list --project <generated_project_root>
```

The smoke is acceptable when the workflow completes, the output SRT exists, the
intermediate artifacts include audio, transcript, corrected transcript, subtitle
segments, translation, and subtitle, and no secret value appears in logs or
artifact metadata.

## Phase 3 handoff boundary

Phase 3 should treat the CLI as one adapter over the backend, not as the desktop
integration point. Desktop work should call the local FastAPI sidecar, which in
turn calls application services.

The first Phase 3 slice should reuse:

- workflow run, resume, abort, status, logs, and artifact services;
- run records, run-scoped event queries, run event streams, and run artifact
  queries;
- runtime settings, provider profile, secret, model cache, and doctor contracts;
- generated local and YouTube subtitle workflow entry points through both CLI
  and API routes;
- existing artifact versions, bounded artifact previews, export/file routes, and
  SQLite-backed event logs for project dashboards, run timelines, artifact
  inspection, and subtitle preview.

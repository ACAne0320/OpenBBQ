# OpenBBQ

**OpenBBQ** is an open-source workflow tool for media language work: transcription,
translation, subtitle generation, and review.

The project takes its name from Chinese fan-sub and creator communities, where
translating and subtitling a video is sometimes called "BBQ." Raw media is "raw
meat"; translated and subtitled output is "cooked."

OpenBBQ currently exposes the backend through a local CLI and an optional
FastAPI sidecar for desktop/API integration. Both adapters use backend
application services that read an `openbbq.yaml` workflow, discover local
plugins, write state and artifacts under `.openbbq/`, and let you inspect,
rerun, resume, stream, preview, or export the results.

## Install

Use `uv` from the repository root:

```bash
uv sync
```

For real video, audio, download, LLM, and keychain support, install the optional
dependency groups you need:

```bash
uv sync --extra download --extra media --extra llm --extra secrets
```

For the local API sidecar, include the `api` extra:

```bash
uv sync --extra api
```

Real media workflows also need `ffmpeg` available on `PATH`:

```bash
ffmpeg -version
```

## Quickstart: run a fixture workflow

Validate the bundled text workflow:

```bash
uv run openbbq validate text-demo --project tests/fixtures/projects/text-basic
```

Run it:

```bash
uv run openbbq run text-demo --project tests/fixtures/projects/text-basic
```

Check status and artifacts:

```bash
uv run openbbq status text-demo --project tests/fixtures/projects/text-basic
uv run openbbq artifact list --project tests/fixtures/projects/text-basic
```

Use `--json` before the command for machine-readable output:

```bash
uv run openbbq --json status text-demo --project tests/fixtures/projects/text-basic
```

## Quickstart: local video to SRT

Configure an OpenAI-compatible provider. For the desktop-style local workflow,
omit `--api-key-ref` and enter the key at the prompt; OpenBBQ stores it in the
user SQLite database as a plaintext local credential.

```bash
uv run openbbq auth set openai \
  --type openai_compatible \
  --base-url https://api.openai.com/v1 \
  --default-chat-model gpt-4o-mini
uv run openbbq auth check openai --json
```

LLM-backed workflow steps must name a runtime provider such as `openai`. The
CLI also supports explicit references such as `--api-key-ref
env:OPENBBQ_LLM_API_KEY` for users who prefer environment variables.

Generate a translated SRT file from a local video:

```bash
uv run openbbq subtitle local \
  --input ./sample.mp4 \
  --source en \
  --target zh \
  --output ./out.zh.srt \
  --provider openai
```

The command creates an internal workflow under `.openbbq/generated/`, imports
the video as a file-backed artifact, extracts audio, transcribes it, corrects and
segments the transcript, translates subtitle segments, and writes the final `.srt`
file. Each invocation creates an isolated generated project and prints
`generated_project_root` in JSON output.

## Quickstart: YouTube to SRT

Generate a translated SRT file:

```bash
uv run openbbq subtitle youtube \
  --url "https://www.youtube.com/watch?v=..." \
  --source en \
  --target zh \
  --output ./out.zh.srt \
  --provider openai
```

The command creates an internal workflow under `.openbbq/generated/`, downloads
the video, extracts audio, transcribes it, translates subtitle segments, and writes
the final `.srt` file. Each invocation creates an isolated generated project and
prints `generated_project_root` in JSON output.

Inspect the generated workflow afterward:

```bash
uv run openbbq --json subtitle youtube \
  --url "https://www.youtube.com/watch?v=..." \
  --source en \
  --target zh \
  --output ./out.zh.srt \
  --provider openai

uv run openbbq status youtube-to-srt --project <generated_project_root>
uv run openbbq logs youtube-to-srt --project <generated_project_root>
uv run openbbq artifact list --project <generated_project_root>
```

## Common CLI Commands

Run a workflow from the start:

```bash
uv run openbbq run <workflow-id> --project <project-dir>
```

Resume a paused workflow:

```bash
uv run openbbq resume <workflow-id> --project <project-dir>
```

Abort a paused or running workflow:

```bash
uv run openbbq abort <workflow-id> --project <project-dir>
```

Rerun a completed workflow:

```bash
uv run openbbq run <workflow-id> --force --project <project-dir>
```

Rerun one step:

```bash
uv run openbbq run <workflow-id> --step <step-id> --project <project-dir>
```

Import a local video as a file-backed artifact:

```bash
uv run openbbq artifact import ./sample.mp4 \
  --type video \
  --name source.video \
  --project <project-dir>
```

Compare two artifact versions:

```bash
uv run openbbq artifact diff <from-version-id> <to-version-id> --project <project-dir>
```

Run preflight checks:

```bash
uv run openbbq doctor --json
uv run openbbq doctor --workflow <workflow-id> --project <project-dir> --json
```

## Local API Sidecar

Start the FastAPI sidecar for desktop or automation clients:

```bash
uv run openbbq api serve \
  --project tests/fixtures/projects/text-basic \
  --token dev-token
```

The server binds to `127.0.0.1` by default and prints one startup JSON line with
the selected port and process ID. Non-health routes require bearer
authentication unless development mode is enabled explicitly:

```bash
uv run openbbq api serve \
  --project tests/fixtures/projects/text-basic \
  --no-token-dev \
  --allow-dev-cors
```

The direct script entry point is also available as `uv run openbbq-api`.

## Desktop renderer development

The desktop renderer lives under `desktop/`.

```bash
cd desktop
pnpm install
pnpm dev
pnpm test
pnpm build
pnpm e2e:install
pnpm e2e
```

Run `pnpm e2e:install` once per Playwright browser version before running the
desktop visual smoke tests.
If browser download is blocked in a local environment, set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to a local Chrome or Chromium executable
before running `pnpm e2e`.

The first renderer slice uses mock data behind a typed client boundary while
the Electron shell and missing backend contracts are implemented separately.

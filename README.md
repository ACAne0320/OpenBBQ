# OpenBBQ

**OpenBBQ** is an open-source workflow tool for media language work: transcription,
translation, subtitle generation, and review.

The project takes its name from Chinese fan-sub and creator communities, where
translating and subtitling a video is sometimes called "BBQ." Raw media is "raw
meat"; translated and subtitled output is "cooked."

OpenBBQ runs media workflows from a local CLI today. The CLI reads an
`openbbq.yaml` workflow, discovers local plugins, writes state and artifacts under
`.openbbq/`, and lets you inspect, rerun, resume, or export the results.

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

## Quickstart: YouTube to SRT

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
uv run openbbq doctor --workflow <workflow-id> --project <project-dir> --json
```

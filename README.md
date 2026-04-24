# OpenBBQ

**OpenBBQ** is an open-source workflow platform for media language processing.

It helps teams run structured pipelines for transcription, translation, subtitle generation, and quality review, while keeping humans in control at every important step.

OpenBBQ is designed for real production work: automate what should be automated, pause where judgment matters, and keep every output editable, versioned, and reusable.

## Why OpenBBQ?

In some Chinese fan-sub and creator communities, the process of translating and subtitling a video is colloquially called **“BBQ”**. Raw, untranslated media is sometimes described as “raw meat,” while translated and subtitled output becomes “cooked.”

**OpenBBQ** takes that cultural metaphor and gives it an open-source home: a platform for turning raw media into polished multilingual deliverables.

## What OpenBBQ Is

OpenBBQ is a workflow-first system for media language operations. It coordinates multi-stage pipelines such as:

- transcription
- translation
- subtitle segmentation
- review and quality assurance

The platform treats each stage as part of a controlled workflow rather than a one-off tool invocation. Human editors can step in, revise outputs, and continue execution from that point forward.

## Phase 1 CLI

The current backend is a local Python CLI managed with `uv`. It can initialize a project, load `openbbq.yaml`, discover trusted local plugin manifests, validate workflows, run deterministic mock workflows, pause and resume persisted workflow state, recover stale locks, rerun completed work, and inspect persisted artifacts under `.openbbq/`.

The Phase 1 source tree is split into strict backend subpackages under `src/openbbq/`: `cli`, `config`, `domain`, `engine`, `workflow`, `plugins`, and `storage`.

Install dependencies and run the text fixture:

```bash
uv sync
uv run openbbq validate text-demo --project tests/fixtures/projects/text-basic
uv run openbbq run text-demo --project tests/fixtures/projects/text-basic
uv run openbbq status text-demo --project tests/fixtures/projects/text-basic
```

Use `uv run openbbq --json <command>` for machine-readable output. `run` writes workflow state, event logs, and artifacts to the selected project's `.openbbq/` directory.

Common Phase 1 commands:

```bash
uv run openbbq run text-demo --project tests/fixtures/projects/text-pause
uv run openbbq status text-demo --project tests/fixtures/projects/text-pause
uv run openbbq resume text-demo --project tests/fixtures/projects/text-pause
uv run openbbq abort text-demo --project tests/fixtures/projects/text-pause
uv run openbbq run text-demo --force --project tests/fixtures/projects/text-basic
uv run openbbq run text-demo --step seed --project tests/fixtures/projects/text-basic
uv run openbbq artifact list --project tests/fixtures/projects/text-basic
uv run openbbq artifact diff <from-version-id> <to-version-id> --project tests/fixtures/projects/text-basic
```

Phase 1 fixtures still use deterministic mock plugins. Phase 2 adds real local media and translation plugins while API service layers and desktop UI remain later-phase work.

## Phase 2 Local Media Preview

Phase 2 begins with a local video-to-subtitle workflow driven by the existing CLI. Install optional media dependencies and system ffmpeg before running real local media smoke tests:

```bash
uv sync --extra media
ffmpeg -version
cp -R tests/fixtures/projects/local-video-subtitle ./demo
uv run openbbq artifact import ./sample.mp4 --type video --name source.video --project ./demo
# Replace project.art_imported_video in ./demo/openbbq.yaml with the returned project.<artifact-id>.
uv run openbbq run local-video-subtitle --project ./demo
```

Default CI does not download Whisper models or require ffmpeg.

## Phase 2 Translation Preview

Slice 2 adds deterministic glossary replacement and OpenAI-compatible LLM translation to the local video subtitle workflow. Install both optional dependency groups before running real local translated subtitle smoke tests:

```bash
uv sync --extra media --extra llm
export OPENBBQ_LLM_API_KEY=sk-your-key
export OPENBBQ_LLM_BASE_URL=https://api.openai.com/v1
cp -R tests/fixtures/projects/local-video-translate-subtitle ./demo-translate
uv run openbbq artifact import ./sample.mp4 --type video --name source.video --project ./demo-translate
# Replace project.art_imported_video in ./demo-translate/openbbq.yaml with the returned project.<artifact-id>.
uv run openbbq run local-video-translate-subtitle --project ./demo-translate
```

Default CI uses fake media and fake OpenAI clients; it does not require LLM credentials or network access.

### Runtime Settings Preview

OpenBBQ can load user runtime settings from `~/.openbbq/config.toml`. Project workflows should reference provider names, while API keys stay in environment variables or the OS keychain.

Example:

```toml
version = 1

[providers.openai]
type = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key = "env:OPENBBQ_LLM_API_KEY"
default_chat_model = "gpt-4o-mini"

[models.faster_whisper]
cache_dir = "~/.cache/openbbq/models/faster-whisper"
default_model = "base"
```

Run preflight checks before a real workflow:

```bash
uv run openbbq doctor --workflow local-video-corrected-translate-subtitle --project ./demo --json
```

## Phase 2 Remote Video Preview

Slice 3 adds remote video download through `yt-dlp` and a full remote translated subtitle workflow. Install the download, media, and LLM optional dependency groups before running a real remote smoke test:

```bash
uv sync --extra download --extra media --extra llm
export OPENBBQ_LLM_API_KEY=sk-your-key
export OPENBBQ_LLM_BASE_URL=https://api.openai.com/v1
cp -R tests/fixtures/projects/remote-video-translate-subtitle ./demo-remote
# Edit ./demo-remote/openbbq.yaml and set download.parameters.url to the source URL.
uv run openbbq run remote-video-translate-subtitle --project ./demo-remote
```

Default CI uses fake downloaders, fake media, and fake OpenAI clients; it does not require network access, ffmpeg, Whisper models, or LLM credentials.

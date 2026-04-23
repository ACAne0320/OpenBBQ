# Phase 2 Remote Video Download Slice Design

## Goal

Phase 2 Slice 3 adds a real remote video source step so OpenBBQ can run the complete target media language workflow from a URL:

```text
remote video URL
  -> remote_video.download
  -> ffmpeg.extract_audio
  -> faster_whisper.transcribe
  -> glossary.replace
  -> llm.translate
  -> subtitle.export
  -> translated subtitle artifact
```

This slice remains CLI-first. It does not add an HTTP API, agent protocol, or desktop UI.

## Scope

This design includes:

- a built-in `remote_video.download` plugin;
- `yt-dlp` Python package integration through an injectable downloader factory;
- a `download` optional dependency group;
- mp4-only output as the stable OpenBBQ artifact contract;
- a canonical `remote-video-translate-subtitle` fixture workflow;
- deterministic tests with fake downloader, fake media, fake Whisper, and fake OpenAI-compatible clients;
- documentation updates for the remote-video translated subtitle workflow.

This design excludes:

- a YouTube-only plugin name or contract;
- URL artifacts and `artifact import-url`;
- playlists, channels, and multi-video downloads;
- cookies, browser authentication, private media, and provider-specific login flows;
- direct file URL download logic outside `yt-dlp`;
- non-mp4 output formats;
- API, SDK, webhooks, queue workers, desktop UI, and agent-specific surfaces.

## Current Baseline

Phase 2 Slice 1 already provides local file import, built-in ffmpeg audio extraction, built-in faster-whisper transcription, and subtitle export.

Phase 2 Slice 2 adds deterministic glossary replacement and OpenAI-compatible LLM translation:

- `glossary.replace` transforms inline `asr_transcript` segment text deterministically.
- `llm.translate` uses the OpenAI Python SDK with `OPENBBQ_LLM_API_KEY` and `OPENBBQ_LLM_BASE_URL`.
- `local-video-translate-subtitle` proves the local translated subtitle chain.

The remaining gap in the target workflow is the source acquisition step. The target document still describes a URL-to-video step, but production built-ins currently start from a local imported video file.

## Design Principles

Use accurate naming. Because the slice intentionally supports the URLs that `yt-dlp` supports, the plugin should be named `remote_video.download`, not `youtube.download`.

Keep OpenBBQ's output contract narrow. `yt-dlp` supports many sites and container combinations, but this slice exposes one stable output shape: file-backed `video` with an mp4 path.

Keep default CI deterministic. Unit and integration tests must not access the network or download real media.

Keep URL input simple. The first implementation reads the URL from workflow parameters. It does not add a new artifact type for URLs.

Preserve the existing engine. Remote download is plugin behavior; workflow execution, artifact persistence, retries, and failure recording remain engine behavior.

## Built-In Plugin Layout

Add one built-in plugin package:

```text
src/openbbq/builtin_plugins/
  remote_video/
    __init__.py
    openbbq.plugin.toml
    plugin.py
```

The existing package data pattern remains sufficient:

```toml
"openbbq.builtin_plugins" = ["*/openbbq.plugin.toml"]
```

## Optional Dependency

Add a `download` optional dependency:

```toml
[project.optional-dependencies]
download = ["yt-dlp>=2024.12.0"]
```

Real remote translated subtitle runs should use:

```bash
uv sync --extra download --extra media --extra llm
```

## `remote_video.download` Manifest

The plugin manifest defines a single tool:

```toml
name = "remote_video"
version = "0.1.0"
runtime = "python"
entrypoint = "plugin:run"

[[tools]]
name = "download"
description = "Download a remote video URL to a file-backed mp4 video artifact."
input_artifact_types = []
output_artifact_types = ["video"]
effects = ["network", "writes_files"]
```

Parameter schema:

- `url`: string, required;
- `format`: string, optional, default `mp4`, enum `["mp4"]`;
- `quality`: string, optional, default `best`.

Example workflow step:

```yaml
- id: download
  name: Download Video
  tool_ref: remote_video.download
  inputs: {}
  outputs:
    - name: video
      type: video
  parameters:
    url: https://example.com/video
    format: mp4
    quality: best
  on_error: abort
  max_retries: 0
```

## Plugin Behavior

`remote_video.download` reads `parameters.url`, validates the requested output format, creates the step work directory, and asks `yt-dlp` to write the result to:

```text
<request.work_dir>/video.mp4
```

The plugin returns:

```python
{
    "outputs": {
        "video": {
            "type": "video",
            "file_path": "<work_dir>/video.mp4",
            "metadata": {
                "url": "<input URL>",
                "format": "mp4",
                "quality": "best",
                "title": "<yt-dlp title if available>",
                "source_id": "<yt-dlp id if available>",
                "extractor": "<yt-dlp extractor if available>",
            },
        }
    }
}
```

`title`, `source_id`, and `extractor` are included only when `yt-dlp` returns them as strings.

## Downloader Factory Seam

The plugin exposes a test seam similar to the LLM plugin's client factory. Its public entrypoint accepts the plugin request and an optional downloader factory: `run(request: dict, downloader_factory=None) -> dict`.

The default factory imports `yt_dlp.YoutubeDL` and returns a context-manager-compatible downloader:

```python
from yt_dlp import YoutubeDL

with YoutubeDL(options) as downloader:
    info = downloader.extract_info(url, download=True)
```

Tests inject a fake factory that records options, writes `video.mp4`, and returns deterministic metadata. Default tests never call real `yt-dlp` or the network.

## `yt-dlp` Options

The plugin should keep options minimal and explicit:

- `outtmpl`: `<work_dir>/video.%(ext)s`;
- `merge_output_format`: `mp4`;
- `format`: derived from `quality`.

For `quality = "best"`, use a format selector that prefers mp4 video and mp4-compatible audio while allowing `yt-dlp` to do normal merging:

```text
bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best
```

For any other `quality` string, pass it through as the `format` selector. This preserves `yt-dlp` power-user behavior without expanding OpenBBQ's output artifact contract beyond mp4.

After `extract_info`, the plugin verifies `<work_dir>/video.mp4` exists. If `yt-dlp` created a different extension, the run fails instead of returning a surprising artifact path.

## Error Handling

The plugin raises clear errors:

- missing or blank URL:
  `ValueError("remote_video.download parameter 'url' must be a non-empty string.")`
- unsupported format:
  `ValueError("remote_video.download currently supports mp4 output only.")`
- missing `yt-dlp` dependency:
  `RuntimeError("yt-dlp is not installed. Install OpenBBQ with the download optional dependencies.")`
- `yt-dlp` download failure:
  `RuntimeError("yt-dlp failed: <message>")`
- missing expected output:
  `RuntimeError("yt-dlp did not produce the expected video output.")`

The existing workflow engine records the failed step and applies configured retry and error policy behavior.

## Canonical Fixture Workflow

Create:

```text
tests/fixtures/projects/remote-video-translate-subtitle/openbbq.yaml
```

The workflow steps are:

```text
remote_video.download
  -> ffmpeg.extract_audio
  -> faster_whisper.transcribe
  -> glossary.replace
  -> llm.translate
  -> subtitle.export
```

The fixture includes a sample public URL in `parameters.url`. Default tests use fake downloader behavior and do not dereference that URL.

## Testing Strategy

Default tests:

- plugin discovery includes `remote_video.download`;
- package layout tests confirm the new manifest is found and packaged into wheels;
- dependency tests confirm `download = ["yt-dlp>=2024.12.0"]`;
- unit tests cover successful fake download, metadata, `yt-dlp` options, missing URL, unsupported format, missing dependency, failed download, and missing output file;
- fixture tests validate `remote-video-translate-subtitle` discovers all required built-ins;
- CLI end-to-end test runs the complete remote translated subtitle workflow with fake downloader, fake ffmpeg, fake Whisper, and fake OpenAI-compatible client.

Verification commands:

```bash
uv sync
uv sync --extra download
uv sync --extra download --extra media --extra llm
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run openbbq validate remote-video-translate-subtitle --project tests/fixtures/projects/remote-video-translate-subtitle
uv build --wheel --out-dir tmp/remote-video-wheel
```

## Documentation Updates

Update:

- `README.md`: document `uv sync --extra download --extra media --extra llm` and remote translated subtitle smoke flow;
- `docs/Target-Workflows.md`: rename the first target step from YouTube-only retrieval to remote video download with `remote_video.download`;
- `docs/Roadmap.md`: mark remote video download as part of Phase 2 real workflow support.

## Acceptance Criteria

Slice 3 is acceptable when:

- `remote_video.download` is discoverable as a built-in plugin;
- packaged wheels include `openbbq/builtin_plugins/remote_video/openbbq.plugin.toml`;
- the plugin returns a file-backed `video` artifact at `video.mp4`;
- `remote-video-translate-subtitle` validates through the CLI;
- deterministic CLI E2E proves the full remote translated subtitle chain;
- default tests do not require network, real media downloads, Whisper models, ffmpeg, or LLM credentials;
- full tests, Ruff lint, format check, and wheel build pass.

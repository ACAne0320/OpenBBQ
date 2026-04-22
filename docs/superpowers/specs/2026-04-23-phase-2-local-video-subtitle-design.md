# Phase 2 Local Video Subtitle Design

## Goal

Phase 2 starts by making OpenBBQ run a real local media workflow from the CLI:

```text
local video file
  -> ffmpeg.extract_audio
  -> faster_whisper.transcribe
  -> subtitle.export
  -> subtitle artifact
```

This slice keeps the Phase 1 CLI as the primary automation interface. It does not add an Agent HTTP API yet; agents and scripts can continue to drive OpenBBQ through CLI commands and JSON output.

## Scope

This design includes:

- importing local files into the artifact store from the CLI;
- file-backed artifact versions for video and audio;
- plugin response support for `file_path` outputs;
- plugin input support for file-backed artifact paths;
- built-in real plugins for local ffmpeg extraction, local faster-whisper transcription, and subtitle export;
- a canonical local-video-to-subtitle fixture workflow;
- deterministic default tests plus optional local integration tests for real ffmpeg and faster-whisper execution.

This design excludes:

- Agent HTTP API, gRPC API, SDKs, and webhooks;
- YouTube download;
- cloud ASR providers;
- cloud LLM translation;
- desktop UI;
- remote plugin registries or plugin marketplace;
- authentication, authorization, scoped tokens, and multi-user access;
- queue workers, distributed execution, and rate limiting.

## Current Baseline

Phase 1 provides the stable backend contracts this slice builds on:

- `openbbq.cli.app` exposes `validate`, `run`, `resume`, `abort`, `unlock`, `status`, `logs`, `artifact`, `plugin`, and `project` commands.
- `openbbq.engine.service` owns workflow orchestration.
- `openbbq.workflow.*` owns execution helpers, bindings, locks, reruns, aborts, state, and diffs.
- `openbbq.plugins.registry` discovers and executes local Python plugins.
- `openbbq.storage.project_store` persists workflow state, events, artifacts, and artifact versions.
- Artifact selectors already support `project.<artifact_id>` and prior step output selectors.

The main limitation is that artifact content is currently optimized for text, JSON, and small bytes. Real video and audio files should not be loaded into memory and passed through plugin JSON-like payloads as inline bytes.

## Design Principles

Keep the engine plugin-agnostic. The engine should not know how ffmpeg or Whisper works.

Keep workflows artifact-driven. Local files enter the system through `artifact import`, then workflows consume `project.<artifact_id>` selectors.

Keep large media file-backed. Video and audio artifacts should be stored and passed by durable file path, hash, and metadata, not by inline content.

Keep CI deterministic. Normal CI must not require ffmpeg binaries, Whisper model downloads, GPU libraries, or network access.

Keep the first slice local. The first real workflow should run on one machine through the existing CLI.

## User Flow

The target first-run CLI flow is:

```bash
openbbq init --project ./demo

openbbq artifact import ./sample.mp4 \
  --project ./demo \
  --type video \
  --name source.video

openbbq run local-video-subtitle --project ./demo

openbbq artifact list --project ./demo --workflow local-video-subtitle

openbbq artifact show <subtitle-artifact-id> --project ./demo
```

The imported video artifact ID is referenced by workflow config:

```yaml
workflows:
  local-video-subtitle:
    name: Local Video Subtitle
    steps:
      - id: extract_audio
        name: Extract Audio
        tool_ref: ffmpeg.extract_audio
        inputs:
          video: project.art_xxx
        outputs:
          - name: audio
            type: audio
        parameters:
          format: wav
          sample_rate: 16000
          channels: 1
        on_error: abort
        max_retries: 0

      - id: transcribe
        name: Transcribe
        tool_ref: faster_whisper.transcribe
        inputs:
          audio: extract_audio.audio
        outputs:
          - name: transcript
            type: asr_transcript
        parameters:
          model: base
          device: cpu
          compute_type: int8
          word_timestamps: true
        on_error: abort
        max_retries: 0

      - id: subtitle
        name: Export Subtitle
        tool_ref: subtitle.export
        inputs:
          transcript: transcribe.transcript
        outputs:
          - name: subtitle
            type: subtitle
        parameters:
          format: srt
        on_error: abort
        max_retries: 0
```

## CLI Artifact Import

Add:

```bash
openbbq artifact import <path> --type <artifact-type> --name <artifact-name>
```

Behavior:

- validate that `<path>` exists and is a file;
- validate that `--type` is registered in `ARTIFACT_TYPES`;
- copy the source file into the artifact version directory;
- create a project-level artifact with no workflow step creator;
- return artifact and version records in JSON output;
- print the artifact ID in human output.

The artifact version lineage should include:

```json
{
  "source": "cli_import",
  "original_path": "/absolute/path/to/sample.mp4"
}
```

The imported artifact should be usable immediately through `project.<artifact_id>`.

## File-Backed Artifact Storage

Extend `ProjectStore.write_artifact_version()` to accept either inline content or a file path:

```python
write_artifact_version(
    artifact_type="audio",
    name="extract_audio.audio",
    content=None,
    file_path=Path("/tmp/openbbq-work/audio.wav"),
    metadata={"format": "wav", "sample_rate": 16000, "channels": 1},
    created_by_step_id="extract_audio",
    lineage={"workflow_id": "local-video-subtitle", "step_id": "extract_audio"},
)
```

Rules:

- `content` and `file_path` are mutually exclusive;
- one of `content` or `file_path` is required;
- file-backed mode copies the file into the artifact version directory;
- `created_by_step_id` may be `None` for project-level artifacts imported through the CLI;
- the version record uses `content_encoding: "file"`;
- the version record stores `content_path`, `content_hash`, `content_size`, metadata, lineage, and timestamp;
- `read_artifact_version()` must not load file-backed video/audio bytes into memory.

For file-backed versions, `StoredArtifactVersion.content` should be a small descriptor:

```python
{
    "file_path": "/project/.openbbq/artifacts/art_x/versions/1-av_y/content",
    "size": 123456,
    "sha256": "86c5e7d3b8f2cbbd4af2d5c2b7e9a5f4d3c2b1a09876543210fedcba98765432"
}
```

This descriptor is what plugins receive for file-backed inputs.

## Plugin Response Contract

Phase 2 plugin outputs support inline content:

```json
{
  "outputs": {
    "transcript": {
      "type": "asr_transcript",
      "content": [
        {"start": 0.0, "end": 2.4, "text": "hello"}
      ],
      "metadata": {"language": "en"}
    }
  }
}
```

and file-backed outputs:

```json
{
  "outputs": {
    "audio": {
      "type": "audio",
      "file_path": "/tmp/openbbq-work/audio.wav",
      "metadata": {
        "format": "wav",
        "sample_rate": 16000,
        "channels": 1
      }
    }
  }
}
```

Validation rules:

- each declared output must be present;
- `type` must match the workflow step output declaration;
- `type` must be allowed by the tool manifest;
- exactly one of `content` or `file_path` must be present;
- `file_path` must point to an existing file;
- plugin-owned temporary output files may be copied into storage before cleanup.

## Plugin Input Contract

Inline text/JSON artifacts continue to pass `content`:

```json
{
  "artifact_id": "art_x",
  "artifact_version_id": "av_y",
  "type": "asr_transcript",
  "content": [
    {"start": 0.0, "end": 2.4, "text": "hello"}
  ]
}
```

File-backed artifacts pass `file_path`:

```json
{
  "artifact_id": "art_x",
  "artifact_version_id": "av_y",
  "type": "audio",
  "file_path": "/project/.openbbq/artifacts/art_x/versions/1-av_y/content",
  "metadata": {"format": "wav", "sample_rate": 16000, "channels": 1}
}
```

Plugins should treat `file_path` inputs as read-only.

## Built-In Real Plugins

Phase 2 Slice 1 should provide built-in plugin implementations while still exercising the same plugin manifest and execution contract as external local plugins.

Recommended source layout:

```text
src/openbbq/builtin_plugins/
  __init__.py
  ffmpeg/
    openbbq.plugin.toml
    plugin.py
  faster_whisper/
    openbbq.plugin.toml
    plugin.py
  subtitle/
    openbbq.plugin.toml
    plugin.py
```

The config loader can add this built-in plugin directory as a default plugin path after CLI, environment, and project plugin paths. This preserves the existing plugin precedence behavior.

### `ffmpeg.extract_audio`

Inputs:

- `video` artifact with `file_path`.

Outputs:

- `audio` artifact as a file-backed WAV or configured audio format.

Parameters:

- `format`: default `wav`;
- `sample_rate`: default `16000`;
- `channels`: default `1`.

Execution:

- run `ffmpeg` through `subprocess`;
- write output under the step work directory;
- return a file-backed output payload;
- convert missing binary, non-zero exit, and malformed inputs into plugin errors.

### `faster_whisper.transcribe`

Inputs:

- `audio` artifact with `file_path`.

Outputs:

- `asr_transcript` inline JSON content.

Default parameters:

- `model`: `base`;
- `device`: `cpu`;
- `compute_type`: `int8`;
- `language`: optional;
- `word_timestamps`: default `true`;
- `vad_filter`: optional.

Execution:

- load `faster_whisper.WhisperModel`;
- transcribe the audio file;
- emit a list of segments with `start`, `end`, `text`, optional `confidence`, and optional `words`;
- include metadata such as model, language, duration when available.

Normal CI should not download Whisper models. Tests should use a fake backend seam for unit coverage and reserve real transcription for optional local integration tests.

### `subtitle.export`

Inputs:

- `asr_transcript` or `translation` artifact with inline JSON segment content.

Outputs:

- `subtitle` artifact.

Parameters:

- `format`: initially `srt`;
- `max_chars_per_line`: optional;
- `max_lines`: optional.

For the first version, subtitle output can remain inline text because subtitle files are small and easy to inspect with `artifact show`.

## Dependency Strategy

Core dependencies should remain small. Heavy optional runtime dependencies should not be required for every developer just to run default tests.

Recommended packaging approach:

- keep Phase 1 dependencies as core;
- add optional dependency group for real media plugins;
- document local setup commands for real Phase 2 smoke tests.

Example:

```toml
[project.optional-dependencies]
media = ["faster-whisper>=1.2"]
```

The ffmpeg binary should be treated as a system dependency and detected at runtime.

## Error Handling

Follow the existing engine error model:

- plugin exceptions are normalized by the execution loop;
- failed steps persist `StepRun.error`;
- workflow status becomes `failed` unless policy recovers through retry or skip.

Additional Phase 2 plugin errors should include clear messages for:

- missing file-backed input path;
- missing `ffmpeg` binary;
- ffmpeg non-zero exit;
- faster-whisper package not installed;
- model load failure;
- transcription failure;
- malformed transcript input for subtitle export.

## Testing Strategy

Default CI must stay deterministic:

- unit test `artifact import` with a small temporary binary file;
- unit test file-backed artifact version read/write behavior;
- unit test plugin response validation for `content` vs `file_path`;
- unit test plugin input binding for file-backed artifacts;
- unit test subtitle export with inline transcript content;
- unit test ffmpeg plugin command construction through a fake subprocess runner;
- unit test faster-whisper plugin through a fake transcription backend.

Optional local integration tests:

- skip real ffmpeg tests when `ffmpeg` is unavailable;
- skip real faster-whisper tests unless dependencies and model settings are explicitly enabled;
- avoid model downloads in default CI;
- provide a local smoke workflow for users who install media dependencies.

## Acceptance Criteria

Phase 2 Slice 1 is complete when:

- `openbbq artifact import` can import a local video file as a file-backed `video` artifact;
- file-backed artifacts are persisted without loading large media bytes into memory;
- workflow plugins receive `file_path` for video/audio artifact inputs;
- `ffmpeg.extract_audio` can produce a file-backed `audio` artifact from a local video artifact;
- `faster_whisper.transcribe` can produce an `asr_transcript` artifact from an audio artifact;
- `subtitle.export` can produce an inspectable `subtitle` artifact from transcript segments;
- a canonical local-video-subtitle workflow can run from the CLI in a local environment with media dependencies installed;
- default CI remains deterministic and does not require ffmpeg, model downloads, GPU libraries, or network access.

## References

- OpenAI introduced Whisper as a multilingual ASR system and open-sourced model/code foundations: <https://openai.com/research/whisper/>
- `faster-whisper` provides a CTranslate2-based Whisper implementation with CPU/GPU options and word timestamps: <https://github.com/SYSTRAN/faster-whisper>
- `whisper.cpp` remains a future backend candidate for binary-oriented local deployment: <https://github.com/ggml-org/whisper.cpp>

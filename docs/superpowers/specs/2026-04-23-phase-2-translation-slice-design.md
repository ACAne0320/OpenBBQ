# Phase 2 Translation Slice Design

## Goal

Phase 2 Slice 2 extends the local video subtitle workflow from source-language subtitles to translated subtitles:

```text
local video file
  -> ffmpeg.extract_audio
  -> faster_whisper.transcribe
  -> glossary.replace
  -> llm.translate
  -> subtitle.export
  -> translated subtitle artifact
```

This slice keeps the existing CLI as the automation interface. Agents and scripts continue to drive OpenBBQ through CLI commands and JSON output. It does not add an HTTP API.

## Scope

This design includes:

- a built-in deterministic `glossary.replace` plugin;
- a built-in OpenAI-compatible `llm.translate` plugin implemented with the OpenAI Python SDK;
- optional `llm` dependencies so default installs stay lightweight;
- a canonical `local-video-translate-subtitle` fixture workflow;
- deterministic tests with fake media and fake OpenAI SDK clients;
- documentation updates that describe Phase 2 as real local media and translation plugins.

This design excludes:

- Agent HTTP API, gRPC API, SDKs, and webhooks;
- YouTube download;
- cloud ASR providers;
- provider-specific SDK abstractions beyond OpenAI-compatible clients;
- desktop UI;
- streaming translation;
- chunked long-video translation;
- queue workers, distributed execution, and rate limiting.

## Original Baseline

Slice 1 already provides the real local media spine:

- `openbbq artifact import` imports local `audio` and `video` files as file-backed artifacts.
- `ffmpeg.extract_audio` produces file-backed audio from local video.
- `faster_whisper.transcribe` produces inline `asr_transcript` segment content.
- `subtitle.export` can export `asr_transcript` or `translation` segments to SRT.
- Built-in plugins are discovered from `src/openbbq/builtin_plugins/` and their manifests are packaged into wheels.

The remaining gap is translation. The current target workflow document already models glossary replacement and translation with mock plugins, but production built-ins do not exist yet.

## Design Principles

Keep the engine plugin-agnostic. Translation is plugin behavior, not engine behavior.

Keep default CI deterministic. Normal tests must not require LLM credentials, network calls, or external provider availability.

Keep credentials out of project config. API keys should come from environment variables, not YAML workflows.

Use one OpenAI-compatible protocol first. The OpenAI Python SDK supports custom `base_url`, which is enough for OpenAI and compatible gateways without adding provider-specific abstractions in this slice.

Translate the full transcript in one request. Slice 2 optimizes for a clear end-to-end workflow. Chunking can be added later when long-video limits become a concrete problem.

## Built-In Plugin Layout

Add two built-in plugin packages:

```text
src/openbbq/builtin_plugins/
  glossary/
    __init__.py
    openbbq.plugin.toml
    plugin.py
  llm/
    __init__.py
    openbbq.plugin.toml
    plugin.py
```

Update package data so both new `openbbq.plugin.toml` files are included in wheels.

## `glossary.replace`

Inputs:

- `transcript`: `asr_transcript` artifact with inline segment content.

Outputs:

- `transcript`: `asr_transcript` artifact.

Parameters:

- `rules`: array of replacement rules.

Each rule contains:

- `find`: string, required;
- `replace`: string, required;
- `is_regex`: boolean, optional, default `false`;
- `case_sensitive`: boolean, optional, default `false`.

Behavior:

- read transcript segments from `inputs.transcript.content`;
- preserve segment order and all existing segment fields;
- update only each segment's `text` field;
- apply rules in the order provided;
- support literal and regex replacement;
- emit metadata with `segment_count`, `word_count`, and `rule_count`.

The implementation should be deterministic and should follow the behavior already proven by `mock_text.glossary_replace`.

## `llm.translate`

Inputs:

- `transcript`: `asr_transcript` artifact with inline segment content.

Outputs:

- `translation`: `translation` artifact.

Parameters:

- `source_lang`: string, required;
- `target_lang`: string, required;
- `model`: string, required;
- `temperature`: number, optional, default `0`;
- `system_prompt`: string, optional;
- `base_url`: string, optional.

Environment variables:

- `OPENBBQ_LLM_API_KEY`: API key used by the OpenAI SDK client.
- `OPENBBQ_LLM_BASE_URL`: default OpenAI-compatible endpoint.

The workflow parameter `base_url` overrides `OPENBBQ_LLM_BASE_URL`. The API key must not be accepted in workflow parameters.

Dependency:

```toml
[project.optional-dependencies]
llm = ["openai>=1.0"]
```

Real local translation setup should use:

```bash
uv sync --extra media --extra llm
```

### SDK Usage

The plugin creates an OpenAI SDK client with explicit credentials:

```python
from openai import OpenAI

client = OpenAI(api_key=api_key, base_url=base_url)
```

The first implementation uses `client.chat.completions.create()` because OpenAI-compatible services commonly implement the chat completions shape. A later slice can add a `responses` mode if the project needs OpenAI-specific Responses API features.

Tests must inject a fake client factory so no default test reaches the network.

## Translation Request Contract

The plugin normalizes transcript segments to compact JSON:

```json
[
  {"index": 0, "start": 0.0, "end": 1.5, "text": "Hello"},
  {"index": 1, "start": 1.5, "end": 3.0, "text": "OpenBBQ"}
]
```

The system prompt must instruct the model to:

- preserve segment count and order;
- translate only `text`;
- return JSON only;
- return an array of objects with `index` and `text`;
- keep `index` values unchanged.

The user message includes:

- source language;
- target language;
- compact segment JSON.

## Translation Response Contract

The model response must parse as JSON with this shape:

```json
[
  {"index": 0, "text": "你好"},
  {"index": 1, "text": "OpenBBQ"}
]
```

Validation rules:

- response content must be valid JSON;
- response must be an array;
- response length must equal input segment count;
- every item must be an object;
- every item must include the expected integer `index`;
- every item must include string `text`.

If validation fails, the plugin raises an error. The existing workflow engine records the failed step and applies the step's configured error policy.

The output `translation` segment for each input segment contains:

```json
{
  "start": 0.0,
  "end": 1.5,
  "source_text": "Hello",
  "text": "你好"
}
```

The plugin may preserve additional non-`text` segment fields when they are JSON-safe, but the required contract is timing plus `source_text` and translated `text`.

Output metadata includes:

- `source_lang`;
- `target_lang`;
- `model`;
- `segment_count`.

## Canonical Fixture Workflow

Create:

```text
tests/fixtures/projects/local-video-translate-subtitle/openbbq.yaml
```

The workflow extends the Slice 1 local fixture:

```yaml
version: 1

project:
  id: local-video-translate-subtitle
  name: Local Video Translate Subtitle

workflows:
  local-video-translate-subtitle:
    name: Local Video Translate Subtitle
    steps:
      - id: extract_audio
        name: Extract Audio
        tool_ref: ffmpeg.extract_audio
        inputs:
          video: project.art_imported_video
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

      - id: glossary
        name: Apply Glossary
        tool_ref: glossary.replace
        inputs:
          transcript: transcribe.transcript
        outputs:
          - name: transcript
            type: asr_transcript
        parameters:
          rules:
            - find: Open BBQ
              replace: OpenBBQ
              is_regex: false
              case_sensitive: false
        on_error: abort
        max_retries: 0

      - id: translate
        name: Translate
        tool_ref: llm.translate
        inputs:
          transcript: glossary.transcript
        outputs:
          - name: translation
            type: translation
        parameters:
          source_lang: en
          target_lang: zh-Hans
          model: gpt-4o-mini
          temperature: 0
        on_error: abort
        max_retries: 0

      - id: subtitle
        name: Export Subtitle
        tool_ref: subtitle.export
        inputs:
          translation: translate.translation
        outputs:
          - name: subtitle
            type: subtitle
        parameters:
          format: srt
        on_error: abort
        max_retries: 0
```

As in Slice 1, users replace `project.art_imported_video` with the artifact selector returned by `artifact import`.

## Testing Strategy

Default tests:

- manifest discovery includes `glossary.replace` and `llm.translate`;
- package layout test confirms new manifests are configured as package data;
- `glossary.replace` unit test covers literal, regex, case-insensitive replacement, and metadata;
- `llm.translate` unit test uses a fake OpenAI SDK client factory and verifies request shape, response parsing, output segment preservation, and metadata;
- `llm.translate` unit test covers missing API key and malformed model JSON;
- fixture validation test confirms `local-video-translate-subtitle` uses built-in plugins;
- deterministic end-to-end CLI test uses fake ffmpeg, fake faster-whisper, and fake OpenAI SDK client to complete the full workflow.

Optional local smoke:

```bash
uv sync --extra media --extra llm
export OPENBBQ_LLM_API_KEY=sk-your-key
export OPENBBQ_LLM_BASE_URL=https://api.openai.com/v1
cp -R tests/fixtures/projects/local-video-translate-subtitle ./demo
uv run openbbq artifact import ./sample.mp4 --type video --name source.video --project ./demo
# Replace project.art_imported_video in ./demo/openbbq.yaml with the returned project.<artifact-id>.
uv run openbbq run local-video-translate-subtitle --project ./demo
```

Default CI must not require `OPENBBQ_LLM_API_KEY`, media binaries, model downloads, or network access.

## Documentation Updates

Update:

- `README.md`: document optional LLM setup and translated subtitle smoke flow;
- `docs/Target-Workflows.md`: mark glossary, LLM translation, and subtitle export as real built-in Phase 2 capabilities after this slice;
- `docs/Roadmap.md`: correct Phase 2 from "Agent Interface" to "Real Local Media and Translation Plugins"; move Agent/API work to a later phase.

Repository documentation must remain in English.

## Acceptance Criteria

Slice 2 is complete when:

- `glossary.replace` is discoverable as a built-in plugin;
- `llm.translate` is discoverable as a built-in plugin;
- both new manifest files are included in built wheels;
- `uv sync --extra llm` installs the OpenAI Python SDK;
- deterministic tests cover glossary replacement and fake-client LLM translation;
- `local-video-translate-subtitle` validates with built-in plugin discovery;
- deterministic CLI E2E completes the full translated subtitle workflow without network;
- optional real smoke instructions are documented for users with media dependencies and LLM credentials.

## References

- OpenAI API libraries documentation: <https://platform.openai.com/docs/libraries>
- OpenAI Python SDK README: <https://github.com/openai/openai-python>
- OpenAI API authentication documentation: <https://platform.openai.com/docs/api-reference/authentication?lang=python>

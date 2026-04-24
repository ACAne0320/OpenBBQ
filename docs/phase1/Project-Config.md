# Project Config

Phase 1 uses one YAML project config file. `openbbq init` creates `openbbq.yaml` in the project root unless `--config` points somewhere else.

The schema below is the Phase 1 source of truth for config loading, validation, and canonical test fixtures. Do not add TOML support in Phase 1.

## Top-Level Schema

```yaml
version: 1

project:
  id: demo-project              # optional; generated and persisted on init if omitted
  name: Demo Project            # required

storage:
  root: .openbbq                # optional; defaults to .openbbq
  artifacts: .openbbq/artifacts # optional; defaults under storage.root
  state: .openbbq/state         # optional; defaults under storage.root

plugins:
  paths:
    - ./plugins                 # optional; merged with env and CLI plugin paths

workflows:
  workflow-id:                  # required map key; becomes Workflow.id
    name: Human-readable name   # required
    steps: []                   # required ordered list
```

## Step Schema

```yaml
id: transform-text              # required; unique within workflow
name: Transform Text            # required
tool_ref: mock_text.uppercase   # required; <plugin_name>.<tool_name>

inputs:                         # optional map; values are selectors or literals
  source: "hello world"
  previous: download.video

outputs:                        # required non-empty list
  - name: output                # unique within this step
    type: text                  # registered artifact type

parameters: {}                  # optional; defaults to {}
on_error: abort                 # optional; abort, retry, skip; defaults to abort
max_retries: 0                  # optional; defaults to 0
pause_before: false             # optional; defaults to false
pause_after: false              # optional; defaults to false
```

Validation requirements:

- `version` must be `1`.
- Workflow IDs and step IDs must be non-empty strings using lowercase letters, digits, `_`, or `-`.
- Every `tool_ref` must resolve to a discovered plugin tool.
- `inputs` values that match `<step_id>.<output_name>` or `project.<artifact_id>` are treated as artifact selectors; other values are literals.
- Every artifact selector that references a workflow step must reference an earlier step.
- Every output type must be registered in the artifact type registry.
- Parameters must validate against the plugin tool's JSON Schema.
- `pause_before` and `pause_after` must be booleans when present.
- `max_retries` must be a non-negative integer.

## Small Text Fixture

Canonical fixture path: `tests/fixtures/projects/text-basic/openbbq.yaml`.

```yaml
version: 1

project:
  id: text-basic
  name: Text Basic

storage:
  root: .openbbq

plugins:
  paths:
    - ../../plugins/mock-text

workflows:
  text-demo:
    name: Text Demo
    steps:
      - id: seed
        name: Seed Text
        tool_ref: mock_text.echo
        inputs:
          text: "hello openbbq"
        outputs:
          - name: text
            type: text
        parameters: {}
        on_error: abort
        max_retries: 0

      - id: uppercase
        name: Uppercase Text
        tool_ref: mock_text.uppercase
        inputs:
          text: seed.text
        outputs:
          - name: text
            type: text
        parameters: {}
        on_error: abort
        max_retries: 0
```

Expected final artifact content for `uppercase.text`: `HELLO OPENBBQ`.

## Pause Fixture

Canonical fixture path: `tests/fixtures/projects/text-pause/openbbq.yaml`.

Use the small text fixture with `pause_before: true` on the `uppercase` step. `openbbq run text-demo` must stop with status `paused`, `current_step_id: uppercase`, and no `StepRun` for `uppercase` yet. `openbbq resume text-demo` must execute `uppercase` and complete.

## Mock YouTube Fixture

Canonical fixture path: `tests/fixtures/projects/youtube-subtitle-mock/openbbq.yaml`.

```yaml
version: 1

project:
  id: youtube-subtitle-mock
  name: YouTube Subtitle Mock

storage:
  root: .openbbq

plugins:
  paths:
    - ../../plugins/mock-media
    - ../../plugins/mock-text

workflows:
  youtube-subtitle:
    name: YouTube To Subtitle Mock
    steps:
      - id: download
        name: Mock Download
        tool_ref: mock_media.youtube_download
        inputs: {}
        outputs:
          - name: video
            type: video
        parameters:
          url: "https://example.invalid/watch?v=openbbq"
          format: mp4
          quality: best

      - id: extract_audio
        name: Mock Extract Audio
        tool_ref: mock_media.extract_audio
        inputs:
          video: download.video
        outputs:
          - name: audio
            type: audio
        parameters:
          format: mp3
          sample_rate: 16000
          channels: 1

      - id: transcribe
        name: Mock ASR
        tool_ref: mock_media.transcribe
        inputs:
          audio: extract_audio.audio
        outputs:
          - name: transcript
            type: asr_transcript
        parameters:
          language: en
          model: mock-asr
          word_timestamps: true

      - id: glossary
        name: Mock Glossary Replacement
        tool_ref: mock_text.glossary_replace
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

      - id: translate
        name: Mock Translation
        tool_ref: mock_text.translate
        inputs:
          transcript: glossary.transcript
        outputs:
          - name: translation
            type: translation
        parameters:
          source_lang: en
          target_lang: zh-Hans
          model: mock-llm

      - id: subtitle
        name: Mock Subtitle Export
        tool_ref: mock_text.subtitle_export
        inputs:
          translation: translate.translation
        outputs:
          - name: subtitle
            type: subtitle
        parameters:
          format: srt
          max_chars_per_line: 40
          max_lines: 2
```

The mock workflow must execute without network or media binaries. Mock tools emit deterministic content and metadata matching the declared artifact types.

## Mock Plugin Fixtures

Canonical plugin fixture paths:

- `tests/fixtures/plugins/mock-text/openbbq.plugin.toml`
- `tests/fixtures/plugins/mock-text/plugin.py`
- `tests/fixtures/plugins/mock-media/openbbq.plugin.toml`
- `tests/fixtures/plugins/mock-media/plugin.py`

`mock_text` tools:

- `echo`: accepts literal `inputs.text`, emits `text`.
- `uppercase`: accepts `text`, emits uppercase `text`.
- `glossary_replace`: accepts `asr_transcript`, applies deterministic literal replacements from `parameters.rules`, emits `asr_transcript`.
- `translate`: accepts `asr_transcript`, emits `translation` preserving segment timing with deterministic mock translated text.
- `subtitle_export`: accepts `translation`, emits SRT `subtitle`.

`mock_media` tools:

- `youtube_download`: emits a deterministic `video` artifact with mock metadata.
- `extract_audio`: accepts `video`, emits deterministic `audio` metadata.
- `transcribe`: accepts `audio`, emits deterministic `asr_transcript` segments.

Minimal `mock-text` manifest:

```toml
name = "mock_text"
version = "0.1.0"
runtime = "python"
entrypoint = "plugin:run"
manifest_version = 2

[[tools]]
name = "echo"
description = "Emit literal text as a text artifact."
effects = []

[tools.parameter_schema]
type = "object"
additionalProperties = false
properties = {}

[tools.inputs.text]
artifact_types = ["text"]
required = true
description = "Literal or artifact text to emit."

[tools.outputs.text]
artifact_type = "text"
description = "Emitted text artifact."

[[tools]]
name = "uppercase"
description = "Convert text input to uppercase."
effects = []

[tools.parameter_schema]
type = "object"
additionalProperties = false
properties = {}

[tools.inputs.text]
artifact_types = ["text"]
required = true
description = "Text artifact to transform."

[tools.outputs.text]
artifact_type = "text"
description = "Uppercase text artifact."
```

The actual fixture manifest may include the remaining `mock_text` tools, but every tool must follow the same manifest shape and JSON Schema parameter validation rules.

Minimal `mock-media` manifest:

```toml
name = "mock_media"
version = "0.1.0"
runtime = "python"
entrypoint = "plugin:run"
manifest_version = 2

[[tools]]
name = "youtube_download"
description = "Emit deterministic mock video metadata."
effects = []

[tools.parameter_schema]
type = "object"
required = ["url"]
additionalProperties = false
properties = { url = { type = "string" }, format = { type = "string" }, quality = { type = "string" } }

[tools.outputs.video]
artifact_type = "video"
description = "Downloaded video artifact."
```

## Configuration Precedence Test Matrix

The implementation must include integration tests covering these conflicts:

| Case | Project config | Environment | CLI flags | Expected |
|---|---|---|---|---|
| Project default | plugin path `./plugins-a` | unset | unset | uses `./plugins-a` |
| Env overrides config | plugin path `./plugins-a` | `OPENBBQ_PLUGIN_PATH=./plugins-b` | unset | uses `./plugins-b` before defaults |
| CLI overrides env | plugin path `./plugins-a` | `OPENBBQ_PLUGIN_PATH=./plugins-b` | `--plugins ./plugins-c` | uses `./plugins-c` first |
| Project root from env | unset | `OPENBBQ_PROJECT=/tmp/proj` | unset | loads `/tmp/proj/openbbq.yaml` |
| Config path from CLI | `openbbq.yaml` exists | `OPENBBQ_CONFIG=env.yaml` | `--config cli.yaml` | loads `cli.yaml` |
| Log level | unset | `OPENBBQ_LOG_LEVEL=debug` | `--verbose` | verbose CLI output and debug log level are both applied |

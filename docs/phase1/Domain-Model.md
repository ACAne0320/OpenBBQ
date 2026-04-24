# Domain Model

## Design Rules

- Every persisted entity has a stable string ID.
- Every timestamp is UTC ISO 8601.
- Every persisted object is serializable to JSON.
- Runtime-only objects must not be required to inspect historical workflow results.
- Validation failures should include the entity type, field path, and reason.

## ID Generation

Phase 1 IDs are stable strings with a type prefix and a random UUID4 hex suffix for generated entities:

- Project: `proj_<uuid4hex>` when not supplied in config.
- Workflow: config-declared workflow map key.
- Step: config-declared step `id`.
- StepRun: `sr_<uuid4hex>`.
- Artifact: `art_<uuid4hex>`.
- ArtifactVersion: `av_<uuid4hex>`.
- WorkflowEvent: `evt_<uuid4hex>`.

Tests must be able to inject a deterministic ID generator so snapshots and fixture assertions are stable. Content hashes use SHA-256 over the stored content bytes and are not used as entity IDs in Phase 1.

## Local State Layout

Given `storage.root: .openbbq`, Phase 1 persists local state under:

```text
.openbbq/
  artifacts/
    <artifact-id>/
      artifact.json
      versions/
        <version-number>-<artifact-version-id>/
          content
          version.json
  state/
    workflows/
      <workflow-id>/
        state.json
        events.jsonl
        step-runs/
          <step-run-id>.json
      <workflow-id>.lock
      <workflow-id>.abort_requested
```

`state.json`, `artifact.json`, `version.json`, and step-run files are JSON objects written atomically by writing a temporary file in the same directory and renaming it into place.

## Project

A project is the local workspace boundary.

Required fields:

- `id`: stable project ID.
- `name`: human-readable project name.
- `root_path`: absolute project root.
- `config_path`: path to the active project config.
- `workflows`: workflow IDs declared by the project.
- `created_at`: creation timestamp.
- `updated_at`: last metadata update timestamp.

## Workflow

A workflow is an ordered set of steps plus persisted execution state.

The static portion (steps, parameters) comes from the project config file. The mutable portion (status, current step, step run records, events) is persisted separately in the workflow state file so the engine can reload it across process restarts without re-reading or re-validating the entire project config.

Required fields:

- `id`: stable workflow ID.
- `name`: human-readable workflow name.
- `steps`: ordered list of step definitions.
- `status`: one of `pending`, `running`, `paused`, `completed`, `failed`, `aborted`.
- `current_step_id`: active or next step when applicable.
- `config_hash`: SHA-256 hash of the normalized workflow config used by the current persisted workflow state.
- `step_run_ids`: ordered list of `StepRun` IDs in execution order. Used to resolve `<step_id>.<output_name>` selectors on resume — the engine reads the most-recent completed `StepRun` for each step to build the output binding map.
- `events`: append-only workflow event IDs.

## Step

A step binds a workflow position to a tool exposed by a plugin.

Required fields:

- `id`: stable step ID.
- `name`: human-readable step name.
- `tool_ref`: `<plugin_name>.<tool_name>`.
- `inputs`: artifact selectors or literal inputs. An artifact selector is a string of the form `<step_id>.<output_name>` referencing a named output from a previous step, or `project.<artifact_id>` referencing a project-level artifact. Literal inputs are plain values passed directly as parameters.
- `outputs`: ordered list of output declarations. Each entry must include `name` (unique within this step) and `type` (a registered artifact type). These drive artifact creation and are the source of truth for selector resolution — `<step_id>.<output_name>` maps to the output with the matching `name` from this list.
- `parameters`: validated parameter values.
- `on_error`: one of `abort`, `retry`, `skip`.
- `max_retries`: non-negative integer.

Optional fields:

- `pause_before`: boolean. When `true`, the engine pauses and persists state before invoking this step's plugin. Defaults to `false`.
- `pause_after`: boolean. When `true`, the engine pauses and persists state after this step's outputs are written. Defaults to `false`.

## StepRun

A `StepRun` records one execution attempt of a step. Multiple `StepRun` records may exist for a single step (retries, or a forced rerun). Only the most-recent `StepRun` with status `completed` is used when resolving selectors for downstream steps.

Required fields:

- `id`: stable step run ID.
- `workflow_id`: parent workflow ID.
- `step_id`: the step that was executed.
- `attempt`: attempt number, starting at `1`. Increments on each retry.
- `status`: one of `running`, `completed`, `failed`, `skipped`.
- `input_artifact_version_ids`: map of input selector string to the `ArtifactVersion` ID that was resolved and passed to the plugin at execution time. Recorded for deterministic replay.
- `output_bindings`: map of output name (as declared in `Step.outputs`) to an object containing both `artifact_id` (the stable logical artifact, used by forced reruns to create new versions under the same entity) and `artifact_version_id` (the immutable snapshot produced by this attempt, used for selector resolution and deterministic replay). Used to resolve `<step_id>.<output_name>` selectors after a process restart.
- `error`: optional error details (code, message, structured details). Present when `status` is `failed`.
- `started_at`: timestamp when the plugin call was initiated.
- `completed_at`: timestamp when the step run reached a terminal status.

## Tool

A tool is a capability declared by a plugin manifest.

Required fields:

- `name`: unique within the plugin.
- `description`: short human-readable description.
- `inputs`: named input slots, each with accepted artifact types and required/optional status.
- `outputs`: named output slots, each with one produced artifact type.
- `parameter_schema`: JSON Schema compatible parameter definition.
- `effects`: declared side effects, such as `reads_files`, `writes_files`, or `network`.

## Plugin

A plugin packages one or more tools.

Required fields:

- `name`: globally unique plugin name in the local registry.
- `version`: semantic version.
- `manifest_path`: path to manifest file.
- `tools`: tool declarations.
- `runtime`: execution runtime descriptor.

## Artifact

An artifact is a typed workflow input or output.

Required fields:

- `id`: stable artifact ID.
- `type`: artifact type. See **Artifact Type Registry** below.
- `name`: human-readable label.
- `versions`: ordered artifact version IDs.
- `current_version_id`: latest selected version.
- `created_by_step_id`: step that first produced the artifact, if any.
- `created_at`: creation timestamp.

## Artifact Type Registry

The `type` field must be one of the registered artifact types. Each type defines the expected content format and the type-specific metadata fields carried in `ArtifactVersion.metadata`.

### `text`

General-purpose plain text. Used for mock plugins and simple string transformations.

Metadata: none required.

### `video`

A video file produced by a download or encoding step.

Metadata:

- `format`: container format (e.g., `mp4`, `webm`).
- `duration_seconds`: total duration as a float.
- `resolution`: object with `width` and `height` in pixels.
- `fps`: frames per second as a float.
- `video_codec`: video codec identifier (e.g., `h264`).
- `audio_codec`: audio codec identifier (e.g., `aac`), if present.

### `audio`

An audio file extracted from a video or produced directly.

Metadata:

- `format`: audio format (e.g., `mp3`, `wav`, `flac`).
- `duration_seconds`: total duration as a float.
- `sample_rate`: sample rate in Hz.
- `channels`: number of audio channels.
- `codec`: audio codec identifier.

### `image`

An image file imported as a project-level resource or produced by a media step.

Metadata:

- `format`: image format (e.g., `png`, `jpeg`, `webp`).
- `width`: image width in pixels.
- `height`: image height in pixels.
- `color_space`: color space identifier, if known.

### `asr_transcript`

A word-level automatic speech recognition result.

Content format: JSON array of segment objects, each with:

- `start`: start time in seconds (float).
- `end`: end time in seconds (float).
- `text`: transcribed text for this segment.
- `confidence`: recognition confidence score between 0 and 1 (float), if available.
- `words`: optional array of per-word objects with the same `start`, `end`, `text`, and `confidence` fields.

Metadata:

- `language`: detected or declared BCP-47 language code.
- `model`: ASR model identifier used for recognition.
- `segment_count`: total number of segments.
- `word_count`: total number of words across all segments.

### `subtitle_segments`

A subtitle-ready timed text representation derived from an `asr_transcript`.

Content format: JSON array of segment objects, each with:

- `start`: start time in seconds (float).
- `end`: end time in seconds (float).
- `text`: source-language or pre-translated subtitle text for this timed unit.

Optional fields may include:

- `source_segment_indexes`: indexes of source transcript segments that contributed to this subtitle unit.
- `word_count`: number of source tokens or words grouped into this subtitle unit.
- `line_count`: number of rendered lines after pre-wrapping.
- `cps`: characters-per-second estimate for this subtitle unit.

Metadata:

- `segment_count`: total number of subtitle-ready units.
- `duration_seconds`: total duration as a float.
- `max_duration_seconds`: configured per-unit duration cap.
- `max_chars_per_line`: configured line-width cap used during segmentation.
- `max_lines`: configured maximum line count per unit.

### `glossary`

A set of find-and-replace rules used as a project-level resource. Typically referenced by a step via `project.<artifact_id>` rather than produced by a step.

Content format: JSON array of rule objects, each with:

- `source`: canonical source-language term.
- `target`: expected translated or normalized term.
- `aliases`: optional list of alternate source spellings.
- `protected`: optional boolean that means the target term should be preserved literally.
- Legacy `find` and `replace` fields remain accepted for compatibility with earlier workflows.
- `is_regex`: boolean, defaults to `false`.
- `case_sensitive`: boolean, defaults to `false`.

Metadata:

- `rule_count`: number of rules in the glossary.
- `language`: optional BCP-47 language code the glossary applies to.

### `translation`

A translated version of an `asr_transcript`, preserving segment structure and timing.

Content format: JSON array of segment objects with the same shape as `asr_transcript` segments, where `text` contains the translated content. Original source text may be included as `source_text` per segment for reference.

Metadata:

- `source_lang`: BCP-47 source language code.
- `target_lang`: BCP-47 target language code.
- `model`: LLM or translation model identifier.
- `segment_count`: total number of translated segments.
- `glossary_rule_count`: number of terminology rules forwarded to the translation step.

### `translation_qa`

Structured warnings derived from a `translation` artifact.

Content: JSON object with:

- `issues`: array of issue objects
- `summary`: aggregate counts

Issue objects include:

- `segment_index`: zero-based segment index
- `code`: stable issue code such as `term_mismatch`, `number_mismatch`, `line_too_long`, `too_many_lines`, or `cps_too_high`
- `severity`: current built-in QA emits `warning`
- `message`: human-readable summary
- `details`: structured per-issue metadata

Metadata:

- `segment_count`: total number of translated segments checked
- `issue_count`: total issue count
- `segments_with_issues`: count of segments that produced at least one warning
- per-code counters such as `term_mismatch_count`

### `subtitle`

A formatted subtitle file ready for distribution.

Content: the raw subtitle file content (SRT, ASS, or VTT text).

Metadata:

- `format`: subtitle format (`srt`, `ass`, `vtt`).
- `segment_count`: number of subtitle blocks.
- `duration_seconds`: total subtitle duration as a float.

## Artifact Version

An artifact version is immutable once written.

Required fields:

- `id`: stable version ID.
- `artifact_id`: parent artifact ID.
- `version_number`: monotonically increasing integer.
- `content_path`: local path to stored content.
- `content_hash`: hash of the stored content.
- `metadata`: artifact-type-specific metadata.
- `lineage`: producer plugin, tool, step, and input artifact versions.
- `created_at`: creation timestamp.

## Workflow Event

Events form the audit trail for workflow execution.

Required fields:

- `id`: stable event ID.
- `sequence`: monotonically increasing integer within a workflow event log, starting at `1`.
- `workflow_id`: workflow that emitted the event.
- `step_id`: related step when applicable.
- `type`: event type.
- `level`: one of `debug`, `info`, `warning`, `error`.
- `message`: human-readable summary.
- `data`: structured event details.
- `created_at`: event timestamp.

Initial event types:

- `workflow.started`
- `workflow.paused`
- `workflow.resumed`
- `workflow.abort_requested`
- `workflow.completed`
- `workflow.failed`
- `workflow.aborted`
- `step.started`
- `step.completed`
- `step.failed`
- `step.skipped`
- `step_run.created`
- `artifact.created`
- `artifact.version_created`
- `plugin.event`
- `plugin.loaded`
- `plugin.invalid`

## Event Storage

Workflow events are stored in `events.jsonl` under the workflow state directory. Each line is one complete JSON object matching the Workflow Event schema. Appends must write a full line ending in `\n`, flush, and fsync before returning from the state transition that emitted the event.

On startup, the event store reads valid complete lines in order. A trailing partial line caused by a process crash is ignored and should be reported as a warning in `--debug` output.

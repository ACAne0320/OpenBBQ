# Phase 2 ASR Correction and Segmentation Design

## Goal

Add an explicit post-ASR correction and subtitle segmentation layer so OpenBBQ can handle recognition errors, domain terminology, and subtitle timing constraints before translation.

The target processing chain becomes:

```text
remote_video.download or local video import
  -> ffmpeg.extract_audio
  -> faster_whisper.transcribe
  -> transcript.correct
  -> transcript.segment
  -> translation.translate (or llm.translate compatibility path)
  -> subtitle.export
```

This design keeps the system CLI-first. It does not add desktop UI, HTTP APIs, or agent-specific surfaces.

## Problem Statement

The current Phase 2 translated subtitle workflow is:

```text
faster_whisper.transcribe
  -> glossary.replace
  -> llm.translate
  -> subtitle.export
```

This is enough to prove an end-to-end flow, but it has structural limits:

- ASR recognition errors are handled too late.
- `glossary.replace` only rewrites segment text and does not help the recognizer avoid the error in the first place.
- `llm.translate` currently receives only `start`, `end`, `text`, and synthetic `index` values, so it cannot reason about word timestamps, low-confidence words, or recognition uncertainty.
- Whisper segments are decoding artifacts, not reliable sentence or subtitle boundaries.
- Subtitle segmentation is currently implicit in the ASR output, which reduces control over duration, readability, and timing.

The result is a pipeline where translation is asked to compensate for ASR mistakes, terminology normalization, and subtitle segmentation at the same time.

## Current Baseline

Current code facts:

- [`src/openbbq/builtin_plugins/faster_whisper/plugin.py`](../../../src/openbbq/builtin_plugins/faster_whisper/plugin.py) returns an `asr_transcript` artifact whose segment items contain:
  - `start`
  - `end`
  - `text`
  - `confidence` (`avg_logprob`)
  - `words` when `word_timestamps=true`
- [`src/openbbq/builtin_plugins/llm/plugin.py`](../../../src/openbbq/builtin_plugins/llm/plugin.py) does not pass the full transcript artifact to the model. It rebuilds a smaller request payload containing:
  - `source_lang`
  - `target_lang`
  - `segments: [{index, start, end, text}]`
- [`src/openbbq/builtin_plugins/glossary/plugin.py`](../../../src/openbbq/builtin_plugins/glossary/plugin.py) only updates `segment["text"]`. It does not reconcile word-level timestamps after replacement.
- [`src/openbbq/builtin_plugins/faster_whisper/openbbq.plugin.toml`](../../../src/openbbq/builtin_plugins/faster_whisper/openbbq.plugin.toml) currently exposes only:
  - `model`
  - `device`
  - `compute_type`
  - `language`
  - `word_timestamps`
  - `vad_filter`

Important implication: OpenBBQ already stores enough structure to support better correction and segmentation, but the current workflow does not use that structure.

## Design Principles

Treat ASR and translation as separate quality problems. Translation should not be the primary recovery layer for recognition errors.

Use terminology at multiple layers:

- ASR biasing and prompting to reduce recognition errors;
- LLM-assisted transcript correction to recover from recognition errors that still happen;
- translation constraints to preserve canonical target-language terms.

Do not treat ASR segments as subtitle segments. Subtitle segmentation should be an explicit derived step.

Preserve deterministic tests. The default test suite must not require live ASR, live translation, or real networks.

Prefer explicit artifacts over hidden prompt behavior. Quality decisions should produce inspectable intermediate outputs.

## Scope

This design includes:

- extending `faster_whisper.transcribe` to expose more decoding and biasing controls;
- a built-in `transcript.correct` plugin for source-language correction;
- a built-in `transcript.segment` plugin for subtitle-ready segmentation;
- a new `subtitle_segments` artifact type;
- compatibility guidance for the existing `llm.translate` plugin;
- validation and test strategy for the new intermediate stages.

This design excludes:

- replacing `faster-whisper` with a different ASR backend in this slice;
- final redesign of `translation.translate` provider abstractions;
- full human review UI;
- audio dubbing or voice cloning;
- multilingual target formatting policies beyond subtitle segmentation.

## Why glossary alone is not enough

Glossary replacement after ASR is useful for deterministic cleanup, but it cannot solve the entire recognition problem.

If the recognizer outputs the wrong source phrase, there are three different cases:

1. the recognizer can be biased earlier and avoid the mistake;
2. the recognizer is wrong, but context makes the intended source phrase recoverable;
3. the recognizer is wrong and the intended phrase is not recoverable from transcript text alone.

Case 1 belongs in ASR decoding controls.
Case 2 belongs in an explicit transcript correction step.
Case 3 should remain flagged as uncertain instead of being silently hallucinated during translation.

This is why glossary data should become a shared asset, not just a text replacement list.

## Extend `faster_whisper.transcribe`

The underlying `faster-whisper` API already supports several controls that are currently hidden from the OpenBBQ plugin. The plugin should expose a conservative subset:

- `initial_prompt`
- `hotwords`
- `condition_on_previous_text`
- `chunk_length`
- `hallucination_silence_threshold`
- `vad_parameters`

These parameters should remain optional. Default behavior should stay close to the current implementation.

Example extended step:

```yaml
- id: transcribe
  tool_ref: faster_whisper.transcribe
  parameters:
    model: base
    device: cpu
    compute_type: int8
    language: en
    word_timestamps: true
    vad_filter: true
    hotwords:
      - OpenBBQ
      - Moonshot
    initial_prompt: "This transcript may mention OpenBBQ, Moonshot, and Faster Whisper."
    condition_on_previous_text: true
    chunk_length: 30
```

This does not eliminate the need for correction, but it moves some terminology support into the recognition stage where it belongs.

## New built-in plugin: `transcript.correct`

### Purpose

Correct source-language ASR output before translation while preserving timing alignment and observability.

### Contract

```text
tool_ref: transcript.correct
input_artifact_types: ["asr_transcript"]
output_artifact_types: ["asr_transcript"]
```

The plugin should preserve segment count and segment timing. It corrects source-language text, not target-language translation.

### Inputs

- transcript content from `faster_whisper.transcribe`
- optional glossary or terminology hints
- optional domain context
- optional source language

### Parameters

- `model`: required LLM model name
- `source_lang`: required language code
- `domain_context`: optional free-text brief
- `glossary_rules`: optional inline rules for the correction pass
- `system_prompt`: optional override
- `temperature`: optional, default `0`
- `max_segments_per_request`: optional, default implementation limit
- `uncertainty_threshold`: optional threshold used to highlight suspicious words or segments

### Correction strategy

The plugin should not pass only plain text. It should construct a richer request payload for the model that can include:

- segment text;
- segment start and end;
- low-confidence markers;
- selected word-level details when available;
- glossary terms and aliases;
- domain brief.

The model should return corrected source text only. It must not translate.

Each output segment should keep:

- `start`
- `end`
- `text`
- `source_text`

Optional per-segment metadata fields should be allowed, for example:

- `correction_status`: `unchanged`, `corrected`, or `uncertain`
- `uncertainty_reasons`

Artifact metadata should include:

- `source_lang`
- `model`
- `segment_count`
- `corrected_segment_count`
- `uncertain_segment_count`

### Why this step is separate from translation

This is the direct response to the current weakness in the pipeline. An LLM can often recover likely intent from context and terminology hints, but that recovery should be explicit and inspectable.

Keeping correction separate from translation makes it possible to:

- inspect the corrected source transcript;
- compare raw and corrected text;
- retry correction without touching translation;
- flag uncertain source text before target text is generated.

## New built-in plugin: `transcript.segment`

### Purpose

Create subtitle-ready timed text units from a corrected transcript instead of inheriting raw Whisper segment boundaries.

### Contract

```text
tool_ref: transcript.segment
input_artifact_types: ["asr_transcript"]
output_artifact_types: ["subtitle_segments"]
```

### Why segmentation should not stay inside ASR

ASR segmentation is driven by model decoding and acoustic windows. Subtitle segmentation is a readability and timing problem.

The system should not try to force subtitle rules by limiting ASR to a maximum number of words per sentence. That would mix recognition behavior with presentation behavior.

Instead:

- ASR should provide accurate words and timings;
- segmentation should derive readable subtitle units from that timed transcript.

### Segmentation strategy

When word timestamps are present, segmentation should combine:

- punctuation boundaries;
- sentence-ending punctuation when available;
- pause gaps between words;
- maximum subtitle duration;
- maximum characters per line or language-aware text length heuristics;
- maximum characters per second or reading-speed heuristics.

When word timestamps are not present, the plugin should fall back to segment-level text splitting with weaker timing accuracy.

### Suggested parameters

- `max_duration_seconds`
- `min_duration_seconds`
- `max_lines`
- `max_chars_per_line`
- `max_chars_per_second`
- `pause_threshold_ms`
- `prefer_sentence_boundaries`

The exact defaults can be set in the implementation plan, but the logic must be explicit and testable.

### Output shape

`subtitle_segments` content items should at minimum contain:

- `start`
- `end`
- `text`

Optional fields may include:

- `source_segment_indexes`
- `word_count`
- `cps`
- `line_count`

This artifact becomes the stable input to subtitle translation and subtitle export.

## Translation implications

The current `llm.translate` plugin can remain as a compatibility path, but it should stop being the first place where source recognition errors are implicitly repaired.

Near-term compatibility path:

```text
faster_whisper.transcribe
  -> transcript.correct
  -> transcript.segment
  -> llm.translate
  -> subtitle.export
```

Longer-term target:

```text
faster_whisper.transcribe
  -> transcript.correct
  -> transcript.segment
  -> translation.translate
  -> subtitle.export
```

This keeps the future `translation.translate` work focused on translation quality, terminology enforcement, and target-language timing tradeoffs instead of raw ASR recovery.

## Glossary and terminology model

Terminology should be treated as a reusable asset with at least three uses:

1. ASR hints:
   - `hotwords`
   - `initial_prompt`
2. transcript correction hints:
   - aliases
   - canonical source spellings
   - domain brief
3. translation constraints:
   - canonical target renderings
   - protected terms

`glossary.replace` can remain for deterministic cleanup, but it should no longer be the primary terminology strategy for real media workflows.

## Artifact and workflow model impact

This slice introduces one new artifact type:

- `subtitle_segments`

It keeps `asr_transcript` as the main source-language timed transcript artifact.

Representative workflow:

```yaml
workflows:
  remote-video-translate-subtitle:
    steps:
      - id: transcribe
        tool_ref: faster_whisper.transcribe
        inputs:
          audio: extract_audio.audio
      - id: correct
        tool_ref: transcript.correct
        inputs:
          transcript: transcribe.transcript
      - id: segment
        tool_ref: transcript.segment
        inputs:
          transcript: correct.transcript
      - id: translate
        tool_ref: llm.translate
        inputs:
          transcript: segment.subtitle_segments
      - id: subtitle
        tool_ref: subtitle.export
        inputs:
          translation: translate.translation
```

The engine does not need new orchestration behavior. This is a plugin and artifact contract change.

## Testing strategy

Tests should cover:

- extended `faster_whisper.transcribe` parameter validation and forwarding;
- `transcript.correct` unit tests with fake LLM clients;
- `transcript.correct` behavior on low-confidence and glossary-sensitive inputs;
- `transcript.segment` unit tests using deterministic transcript fixtures with word timestamps;
- fallback segmentation when word timestamps are absent;
- end-to-end CLI workflow tests proving:
  - raw transcript correction;
  - stable subtitle segmentation;
  - translated subtitle export.

The default test suite should stay deterministic and offline.

## Acceptance Criteria

This design is ready to implement when the codebase provides:

- an extended `faster_whisper.transcribe` contract for ASR biasing and decoding controls;
- a real `transcript.correct` built-in plugin with inspectable corrected output;
- a real `transcript.segment` built-in plugin that no longer relies on Whisper segments as final subtitle boundaries;
- at least one canonical workflow fixture that uses correction and segmentation before translation;
- deterministic tests proving the new intermediate artifacts and workflow path.

## External References

- OpenAI speech-to-text guide: <https://platform.openai.com/docs/guides/speech-to-text>
- faster-whisper project and API behavior: <https://github.com/SYSTRAN/faster-whisper>
- Azure Speech phrase list guidance: <https://learn.microsoft.com/en-us/azure/ai-services/speech-service/improve-accuracy-phrase-list>
- Google Cloud Speech adaptation and timing guidance: <https://cloud.google.com/speech-to-text/docs/adaptation-model>, <https://cloud.google.com/speech-to-text/docs/async-time-offsets>
- Deepgram keyterm prompting: <https://developers.deepgram.com/docs/keyterm>
- Descript transcript correction and translation workflow guidance: <https://help.descript.com/hc/en-us/articles/10119613609229-Correct-your-transcript>, <https://help.descript.com/hc/en-us/articles/27177566394509-Translate-your-captions-into-another-language>
- HeyGen video translation glossary and duration controls: <https://help.heygen.com/en/articles/10029081-how-to-get-started-with-video-translation>
- ElevenLabs dubbing studio workflow: <https://elevenlabs.io/docs/eleven-creative/products/dubbing/dubbing-studio>

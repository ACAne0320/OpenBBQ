# Phase 2 ASR Correction and Segmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit ASR correction and subtitle segmentation stages so OpenBBQ can recover from recognition errors earlier, use terminology more effectively, and stop depending on raw Whisper segments as final subtitle boundaries.

**Architecture:** Keep the workflow engine unchanged and add quality control through built-in plugins. Extend `faster_whisper.transcribe` to expose ASR biasing controls, add `transcript.correct` as a source-language correction plugin, add `transcript.segment` as a subtitle-unit derivation plugin, and keep `llm.translate` as a compatibility translation path by accepting the new timed segment artifact.

**Tech Stack:** Python 3.11, uv, pytest, Ruff, faster-whisper, OpenAI Python SDK, existing OpenBBQ plugin registry, workflow validator, and artifact store.

---

## File Structure

- Modify `src/openbbq/builtin_plugins/faster_whisper/openbbq.plugin.toml`: expose additional ASR parameters.
- Modify `src/openbbq/builtin_plugins/faster_whisper/plugin.py`: forward new parameters to `WhisperModel.transcribe`.
- Create `src/openbbq/builtin_plugins/transcript/__init__.py`: package marker.
- Create `src/openbbq/builtin_plugins/transcript/openbbq.plugin.toml`: manifest for `transcript.correct` and `transcript.segment`.
- Create `src/openbbq/builtin_plugins/transcript/plugin.py`: correction and segmentation built-in implementation.
- Modify `src/openbbq/builtin_plugins/llm/openbbq.plugin.toml`: allow `subtitle_segments` input.
- Modify `src/openbbq/builtin_plugins/subtitle/openbbq.plugin.toml`: allow `subtitle_segments` input.
- Modify `tests/test_builtin_plugins.py`: discovery, forwarding, correction, segmentation, and compatibility tests.
- Modify `tests/test_package_layout.py`: package data assertions for the new built-in manifest.
- Modify `tests/test_fixtures.py`: fixture validation for the new workflow.
- Create `tests/fixtures/projects/local-video-corrected-translate-subtitle/openbbq.yaml`: canonical local workflow with correction and segmentation.
- Create `tests/test_phase2_asr_correction_segmentation.py`: deterministic CLI end-to-end test for the corrected subtitle workflow.
- Modify `docs/Target-Workflows.md`: document the new stages and updated flow.
- Modify `docs/phase1/Domain-Model.md`: define `subtitle_segments` as an artifact shape.

## Task 1: Manifest, discovery, and compatibility contracts

**Files:**
- Modify: `src/openbbq/builtin_plugins/llm/openbbq.plugin.toml`
- Modify: `src/openbbq/builtin_plugins/subtitle/openbbq.plugin.toml`
- Create: `src/openbbq/builtin_plugins/transcript/__init__.py`
- Create: `src/openbbq/builtin_plugins/transcript/openbbq.plugin.toml`
- Modify: `tests/test_builtin_plugins.py`
- Modify: `tests/test_package_layout.py`

- [ ] Add failing discovery assertions for `transcript.correct` and `transcript.segment`.
- [ ] Add package layout assertions so built-in manifests include `transcript`.
- [ ] Update manifest contract expectations so `llm.translate` accepts `["asr_transcript", "subtitle_segments"]`.
- [ ] Update manifest contract expectations so `subtitle.export` accepts `["asr_transcript", "translation", "subtitle_segments"]`.
- [ ] Add the transcript built-in package and manifest.
- [ ] Re-run targeted discovery and manifest tests until green.

## Task 2: Extend `faster_whisper.transcribe`

**Files:**
- Modify: `src/openbbq/builtin_plugins/faster_whisper/openbbq.plugin.toml`
- Modify: `src/openbbq/builtin_plugins/faster_whisper/plugin.py`
- Modify: `tests/test_builtin_plugins.py`

- [ ] Add failing tests that verify forwarding for:
  - `initial_prompt`
  - `hotwords`
  - `condition_on_previous_text`
  - `chunk_length`
  - `hallucination_silence_threshold`
  - `vad_parameters`
- [ ] Extend the plugin manifest schema to expose those parameters.
- [ ] Update the plugin implementation to pass those values through to `WhisperModel.transcribe`.
- [ ] Keep current defaults unchanged when parameters are absent.
- [ ] Re-run targeted faster-whisper plugin tests until green.

## Task 3: Implement `transcript.correct`

**Files:**
- Modify: `src/openbbq/builtin_plugins/transcript/plugin.py`
- Modify: `tests/test_builtin_plugins.py`

- [ ] Add fakeable client factory helpers for correction tests.
- [ ] Add failing tests for:
  - required parameter validation;
  - preserving segment count and timing;
  - returning corrected `text` plus original `source_text`;
  - propagating metadata such as corrected and uncertain counts;
  - splitting large correction requests into smaller chunks on malformed or incomplete model output.
- [ ] Implement `transcript.correct` using an OpenAI-compatible client factory seam.
- [ ] Build a richer prompt payload than the current translation step:
  - segment text;
  - start and end;
  - optional confidence and selected word details;
  - glossary rules and domain context when supplied.
- [ ] Require correction output to preserve order and segment cardinality.
- [ ] Re-run targeted correction tests until green.

## Task 4: Implement `transcript.segment`

**Files:**
- Modify: `src/openbbq/builtin_plugins/transcript/plugin.py`
- Modify: `tests/test_builtin_plugins.py`
- Modify: `docs/phase1/Domain-Model.md`

- [ ] Add failing tests for segmentation from word timestamps.
- [ ] Add fallback tests for segmentation without word timestamps.
- [ ] Add tests for subtitle constraints such as:
  - `max_duration_seconds`
  - `max_chars_per_line`
  - `max_lines`
  - `pause_threshold_ms`
- [ ] Implement deterministic segmentation logic that derives subtitle units from transcript timing instead of reusing Whisper segments directly.
- [ ] Emit `subtitle_segments` content with stable `start`, `end`, and `text`.
- [ ] Update the domain model documentation for `subtitle_segments`.
- [ ] Re-run targeted segmentation tests until green.

## Task 5: Workflow wiring and end-to-end validation

**Files:**
- Create: `tests/fixtures/projects/local-video-corrected-translate-subtitle/openbbq.yaml`
- Modify: `tests/test_fixtures.py`
- Create: `tests/test_phase2_asr_correction_segmentation.py`
- Modify: `docs/Target-Workflows.md`

- [ ] Add a canonical fixture:
  `ffmpeg.extract_audio -> faster_whisper.transcribe -> transcript.correct -> transcript.segment -> llm.translate -> subtitle.export`
- [ ] Add deterministic CLI end-to-end coverage with fake media, fake correction client, and fake translation client.
- [ ] Prove the resulting workflow stores intermediate corrected transcript artifacts and subtitle-ready segment artifacts.
- [ ] Update target workflow documentation to describe the new stages and explain why glossary-only cleanup is insufficient.
- [ ] Run `uv run openbbq validate` for the new fixture.
- [ ] Run targeted CLI E2E tests until green.

## Task 6: Full verification

**Files:**
- No new files; verification only.

- [ ] Run `uv run pytest`.
- [ ] Run `uv run ruff check .`.
- [ ] Run `uv run ruff format --check .`.
- [ ] Review changed docs and fixtures for English-only repository documentation compliance.

## Acceptance Criteria

- `faster_whisper.transcribe` exposes the planned ASR biasing and decoding controls.
- `transcript.correct` exists as a real built-in plugin and emits inspectable corrected transcripts.
- `transcript.segment` exists as a real built-in plugin and emits `subtitle_segments`.
- `llm.translate` and `subtitle.export` can consume the new segment artifact where appropriate.
- A canonical workflow fixture proves correction and segmentation before translation.
- The deterministic test suite remains green without requiring live ASR or live LLM calls.

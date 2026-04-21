# Target Workflows

This document describes concrete end-to-end workflow pipelines that OpenBBQ is designed to support. These workflows define the artifact types, plugin contracts, and parameter shapes the system must handle in production.

Phase 1 proves the workflow engine contracts using mock plugins. Real plugin implementations are introduced in later phases as the platform matures.

---

## YouTube Video to Subtitle File

A complete media language processing pipeline: retrieve a YouTube video, extract audio, transcribe speech word-by-word, apply glossary rules, translate with an LLM, and export a subtitle file.

```
youtube.download → ffmpeg.extract_audio → asr.transcribe → glossary.replace → llm.translate → subtitle.export
```

### Steps

#### 1. Retrieve YouTube Video

| Field | Value |
|---|---|
| `tool_ref` | `youtube.download` |
| `effects` | `network`, `writes_files` |
| Output artifact | `video` |

Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | YouTube video URL |
| `format` | string | no | Container format preference (`mp4`, `webm`). Defaults to `mp4`. |
| `quality` | string | no | Quality preference (`best`, `worst`, `720p`, `1080p`, etc.). Defaults to `best`. |

---

#### 2. Convert to Audio

| Field | Value |
|---|---|
| `tool_ref` | `ffmpeg.extract_audio` |
| `effects` | `reads_files`, `writes_files` |
| Input artifact | `video` (from step 1) |
| Output artifact | `audio` |

Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `format` | string | no | Audio format (`mp3`, `wav`, `flac`, `m4a`). Defaults to `mp3`. |
| `sample_rate` | integer | no | Sample rate in Hz (`16000`, `44100`, etc.). Defaults to `16000` for ASR compatibility. |
| `channels` | integer | no | Number of audio channels. Defaults to `1` (mono). |

---

#### 3. ASR Recognition (Word-by-Word)

| Field | Value |
|---|---|
| `tool_ref` | `asr.transcribe` |
| `effects` | `reads_files` |
| Input artifact | `audio` (from step 2) |
| Output artifact | `asr_transcript` |

Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `language` | string | no | BCP-47 language code of the source audio. Auto-detected if absent. |
| `model` | string | no | Model variant (`tiny`, `base`, `small`, `medium`, `large`). Defaults to `base`. |
| `word_timestamps` | boolean | no | Emit per-word start/end timestamps. Defaults to `true`. |

The output `asr_transcript` artifact contains an ordered list of word-level segments, each with `start`, `end`, `text`, and `confidence`.

---

#### 4. Rule / Glossary Replacement

| Field | Value |
|---|---|
| `tool_ref` | `glossary.replace` |
| `effects` | `reads_files` |
| Input artifacts | `asr_transcript` (from step 3), glossary resource via `project.<artifact_id>` |
| Output artifact | `asr_transcript` (modified version) |

Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `glossary_id` | string | no | ID of a project-level glossary artifact. |
| `rules` | array | no | Inline replacement rules: `[{"find": "...", "replace": "..."}]`. Supports plain strings and regular expressions. |
| `case_sensitive` | boolean | no | Whether matching is case-sensitive. Defaults to `false`. |

At least one of `glossary_id` or `rules` must be provided. Both may be used together; inline `rules` are applied after glossary substitutions.

---

#### 5. Translation (LLM)

| Field | Value |
|---|---|
| `tool_ref` | `llm.translate` |
| `effects` | `network` |
| Input artifact | `asr_transcript` (from step 4) |
| Output artifact | `translation` |

Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `target_lang` | string | yes | BCP-47 target language code. |
| `source_lang` | string | no | BCP-47 source language. Inferred from the transcript if absent. |
| `model` | string | no | LLM model identifier. Provider-specific; resolved from plugin config if absent. |
| `context` | string | no | Optional system-level instructions for style, tone, or domain guidance. |

The output `translation` artifact preserves the segment structure and timing from the input `asr_transcript` while replacing text with translated content.

> **Note:** This step requires outbound LLM API access. It is the only step in this pipeline that is non-deterministic.

---

#### 6. Export Subtitle File

| Field | Value |
|---|---|
| `tool_ref` | `subtitle.export` |
| `effects` | `writes_files` |
| Input artifact | `translation` (from step 5) |
| Output artifact | `subtitle` |

Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `format` | string | yes | Subtitle format: `srt`, `ass`, or `vtt`. |
| `max_chars_per_line` | integer | no | Maximum characters per subtitle line. Defaults to `40`. |
| `max_lines` | integer | no | Maximum lines per subtitle block (`1` or `2`). Defaults to `2`. |

---

### Artifact Flow Summary

```
url, format, quality
        │
        ▼
[youtube.download] ──► video
                          │
                          ▼
              [ffmpeg.extract_audio] ──► audio
                                           │
                                           ▼
                            [asr.transcribe] ──► asr_transcript
                                                       │
                                                  ┌────┘
                                                  │  glossary (project asset)
                                                  ▼
                               [glossary.replace] ──► asr_transcript (modified)
                                                              │
                                                              ▼
                                          [llm.translate] ──► translation
                                                                   │
                                                                   ▼
                                             [subtitle.export] ──► subtitle
```

### Phase Availability

| Step | Plugin | Phase |
|---|---|---|
| Retrieve YouTube video | `youtube.download` | Phase 2 (real network access) |
| Convert to audio | `ffmpeg.extract_audio` | Phase 2 (real media processing) |
| ASR recognition | `asr.transcribe` | Phase 2 (real speech recognition) |
| Glossary replacement | `glossary.replace` | Phase 1 compatible (pure text transform) |
| Translation (LLM) | `llm.translate` | Phase 2 (requires LLM API access) |
| Export subtitle | `subtitle.export` | Phase 1 compatible (pure text serialization) |

Phase 1 can validate the full workflow config and run it end-to-end using mock plugins that accept and emit the correct artifact types without performing real media operations.

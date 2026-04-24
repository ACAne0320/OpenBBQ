# Target Workflows

This document describes concrete end-to-end workflow pipelines that OpenBBQ is designed to support. These workflows define the artifact types, plugin contracts, and parameter shapes the system must handle in production.

Phase 1 proves the workflow engine contracts using mock plugins. Phase 2 introduces real remote video download, local media processing, transcript correction, subtitle segmentation, translation, and subtitle plugins for CLI-driven workflows.

---

## Remote Video to Subtitle File

A complete media language processing pipeline: download a remote video URL, extract audio, transcribe speech word-by-word, correct likely ASR errors, derive subtitle-ready segments, translate with an LLM, and export a subtitle file.

```
remote_video.download → ffmpeg.extract_audio → faster_whisper.transcribe → transcript.correct → transcript.segment → translation.translate → subtitle.export
```

### Steps

#### 1. Download Remote Video

| Field | Value |
|---|---|
| `tool_ref` | `remote_video.download` |
| `effects` | `network`, `writes_files` |
| Output artifact | `video` |

Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | Remote video URL supported by `yt-dlp`. |
| `format` | string | no | Output container. Currently only `mp4` is supported. Defaults to `mp4`. |
| `quality` | string | no | `yt-dlp` format selector. Defaults to `best`. |
| `auth` | string | no | Download auth strategy: `auto`, `anonymous`, or `browser_cookies`. Defaults to `auto`. |
| `browser` | string | no | Browser name for cookie loading when `auth` uses browser cookies. |
| `browser_profile` | string | no | Browser profile name/path for cookie loading when `auth` uses browser cookies. |

Behavior notes:

- `auth: auto` tries an anonymous download first, then retries with browser cookies for supported browsers when the site or error indicates authentication is required.
- For YouTube URLs, OpenBBQ retries browser cookies automatically to reduce user-visible login steps when a local browser session is available.
- For YouTube URLs, OpenBBQ also enables available local JavaScript runtimes and yt-dlp EJS remote components automatically when needed for challenge solving.

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
| `tool_ref` | `faster_whisper.transcribe` |
| `effects` | `reads_files` |
| Input artifact | `audio` (from step 2) |
| Output artifact | `asr_transcript` |

Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `language` | string | no | BCP-47 language code of the source audio. Auto-detected if absent. |
| `model` | string | no | Model variant (`tiny`, `base`, `small`, `medium`, `large`). Defaults to `base`. |
| `word_timestamps` | boolean | no | Emit per-word start/end timestamps. Defaults to `true`. |
| `initial_prompt` | string | no | Optional source-language prompt that biases recognition toward expected vocabulary. |
| `hotwords` | array[string] | no | Optional hotword list forwarded to `faster-whisper` to improve terminology recognition. |
| `condition_on_previous_text` | boolean | no | Forwarded decoder control for previous-window conditioning. |
| `chunk_length` | integer | no | Optional decoding chunk length in seconds. |
| `hallucination_silence_threshold` | number | no | Optional silence threshold used when hallucination detection is enabled. |
| `vad_filter` | boolean | no | Enable voice activity detection before decoding. Defaults to `false`. |
| `vad_parameters` | object | no | Optional VAD parameter overrides forwarded to `faster-whisper`. |

The output `asr_transcript` artifact contains an ordered list of word-level segments, each with `start`, `end`, `text`, and `confidence`.

---

#### 4. Transcript Correction

| Field | Value |
|---|---|
| `tool_ref` | `transcript.correct` |
| `effects` | `network` |
| Input artifact | `asr_transcript` (from step 3) |
| Output artifact | `asr_transcript` (corrected version) |

Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `source_lang` | string | yes | BCP-47 source language code. |
| `model` | string | yes | OpenAI-compatible correction model identifier. |
| `temperature` | number | no | Sampling temperature. Defaults to `0`. |
| `domain_context` | string | no | Free-text domain brief used to improve source-language correction. |
| `glossary_rules` | array | no | Terminology hints in the form `[{"source": "...", "target": "...", "aliases": [...] }]`. Legacy `find` / `replace` fields remain accepted for compatibility. |
| `max_segments_per_request` | integer | no | Maximum segment count sent to the model per request. |
| `uncertainty_threshold` | number | no | Optional threshold used to surface suspicious words or segments in the prompt. |

This step preserves segment count and timing while correcting source-language text and retaining `source_text` for inspection.

---

#### 5. Subtitle Segmentation

| Field | Value |
|---|---|
| `tool_ref` | `transcript.segment` |
| `effects` | none |
| Input artifact | `asr_transcript` (from step 4) |
| Output artifact | `subtitle_segments` |

Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `max_duration_seconds` | number | no | Maximum duration for a subtitle unit. Defaults to `6`. |
| `min_duration_seconds` | number | no | Minimum preferred duration before a pause or boundary split. Defaults to `0.8`. |
| `max_lines` | integer | no | Maximum number of lines in each subtitle unit. Defaults to `2`. |
| `max_chars_per_line` | integer | no | Maximum characters per line before pre-wrapping text. Defaults to `40`. |
| `max_chars_per_second` | number | no | Maximum preferred reading speed used when deciding where to split. Defaults to `20`. |
| `pause_threshold_ms` | integer | no | Silence gap threshold that encourages a subtitle boundary. Defaults to `500`. |
| `prefer_sentence_boundaries` | boolean | no | Prefer punctuation boundaries when splitting. Defaults to `true`. |

This step derives subtitle-ready timed units instead of treating Whisper decoding segments as final subtitle blocks.

---

#### 6. Translation

| Field | Value |
|---|---|
| `tool_ref` | `translation.translate` |
| `effects` | `network` |
| Input artifact | `subtitle_segments` (from step 5) |
| Output artifact | `translation` |

Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `provider` | string | no | Translation backend. The current built-in plugin supports `openai_compatible` only. |
| `target_lang` | string | yes | BCP-47 target language code. |
| `source_lang` | string | yes | BCP-47 source language code. |
| `model` | string | yes | OpenAI-compatible model identifier. |
| `temperature` | number | no | Sampling temperature. Defaults to `0`. |
| `system_prompt` | string | no | Optional system prompt override. |
| `base_url` | string | no | Optional provider base URL override. |
| `glossary_rules` | array | no | Optional terminology rules forwarded to the translation prompt. Accepts `{source,target,aliases,protected}` and legacy `{find,replace}` forms. |

The output `translation` artifact preserves the segment structure and timing from the input subtitle-ready segments while replacing text with translated content.

`llm.translate` remains available as a compatibility alias for the older Phase 2 workflows.

> **Note:** This step requires outbound LLM API access. It is the only step in this pipeline that is non-deterministic.

---

#### 7. Translation QA (Optional)

| Field | Value |
|---|---|
| `tool_ref` | `translation.qa` |
| `effects` | none |
| Input artifact | `translation` (from step 6) |
| Output artifact | `translation_qa` |

Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `max_lines` | integer | no | Maximum allowed line count in a translated subtitle unit. Defaults to `2`. |
| `max_chars_per_line` | integer | no | Maximum allowed line length before the QA step flags a risk. Defaults to `42`. |
| `max_chars_per_second` | number | no | Maximum preferred reading speed before the QA step flags a risk. Defaults to `20`. |
| `glossary_rules` | array | no | Optional terminology rules used to detect missing protected or expected target terms. |

This step emits structured warnings for terminology misses, numeric drift, and subtitle readability issues without modifying the translation itself.

---

#### 8. Export Subtitle File

| Field | Value |
|---|---|
| `tool_ref` | `subtitle.export` |
| `effects` | `writes_files` |
| Input artifact | `translation` (from step 6) |
| Output artifact | `subtitle` |

Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `format` | string | yes | Subtitle format. The current built-in plugin supports `srt` only. |

---

### Artifact Flow Summary

```
url, format, quality
        │
        ▼
[remote_video.download] ──► video
                               │
                               ▼
                   [ffmpeg.extract_audio] ──► audio
                                                │
                                                ▼
                          [faster_whisper.transcribe] ──► asr_transcript
                                                                 │
                                                                 ▼
                                        [transcript.correct] ──► asr_transcript (corrected)
                                                                        │
                                                                        ▼
                                        [transcript.segment] ──► subtitle_segments
                                                                        │
                                                                        ▼
                                            [translation.translate] ──► translation
                                                                             │
                                                                             ▼
                                                  [translation.qa] ──► translation_qa
                                                                             │
                                                                             └── optional review gate
                                                                             │
                                                                             ▼
                                                       [subtitle.export] ──► subtitle
```

### Phase Availability

| Step | Plugin | Phase |
|---|---|---|
| Download remote video | `remote_video.download` | Phase 2 Slice 3 |
| Convert to audio | `ffmpeg.extract_audio` | Phase 2 Slice 1 |
| ASR recognition | `faster_whisper.transcribe` | Phase 2 Slice 1 |
| Transcript correction | `transcript.correct` | Phase 2 correction and segmentation slice |
| Subtitle segmentation | `transcript.segment` | Phase 2 correction and segmentation slice |
| Translation | `translation.translate` | Phase 2 translation v1 |
| Translation compatibility alias | `llm.translate` | Phase 2 Slice 2 |
| Export subtitle | `subtitle.export` | Phase 2 Slice 1 |

Phase 1 can validate the full workflow config and run it end-to-end using mock plugins that accept and emit the correct artifact types without performing real media operations.

---
name: openbbq-subtitles
description: Use OpenBBQ/openbbq for subtitle and video-translation workflows: make subtitles, translate subtitles, create bilingual subtitles/videos, burn ASS hard subtitles, transcribe video/audio, or continue processing a video list/tracker. Trigger when the user mentions OpenBBQ/openbbq with tasks like 制作字幕, 翻译字幕, 双语字幕, 双语视频, 视频翻译, 烧录字幕, 生成字幕, or English requests such as make subtitles, translate subtitles, bilingual video, burn subtitles, transcribe this video.
---

# OpenBBQ Subtitle Workflow

<!-- Generated from SKILL.zh-CN.md (the maintainer-authored source). To change
     this skill, edit the Chinese source first, then regenerate this file. -->

Use this skill when an agent is asked to produce subtitles or a subtitled video
with OpenBBQ. Prefer OpenBBQ's atomic CLI commands over ad hoc scripts.

## Operating Rules

- Use `openbbq --json ...` for automation unless the user explicitly wants the
  human terminal UI. The `next` field in success payloads is the suggested
  next command.
- Fill translations only two ways: the Edit tool directly on the worksheet, or
  batch files merged via `openbbq translate apply` — NEVER a one-off script
  that edits the worksheet.
- Use `openbbq --json status --workspace <ws>` to resume after interruptions.
  The manifest is the source of truth for completed/running/failed stages: the
  translate stage carries real `progress` (filled/total), and a `running` stage
  flagged `stale` means its process is likely dead — safe to rerun. Rerunning a
  stage automatically resets downstream stages to pending.
- Quote URL arguments in shells such as zsh:
  `openbbq init --workspace workspaces/demo 'https://www.youtube.com/watch?v=...'`.
- Long tasks (`fetch`, `transcribe`, `burn`, `models pull`) write progress to
  the workspace (or stderr); poll `openbbq --json status --workspace <ws>` if
  you need progress outside the foreground command.
- Do not burn SRT for the default workflow. Export bilingual ASS and burn ASS.
- Pick an ASS preset only when the target surface needs it: `compact` for
  dense lower-third visuals, `fansub` for a more prominent bilingual style,
  and `mobile` for 9:16 vertical video.
- If the user says "process the first/next item" after a tracker or checklist
  was created, read the tracker, pick the requested pending video, create or
  reuse a per-video workspace, then run the OpenBBQ workflow for that item.

## First-Time Environment

```bash
openbbq doctor
```

For final local transcription, use a cached Whisper model such as
`large-v3-turbo`. If missing, run:

```bash
openbbq models pull large-v3-turbo
```

For hard-subtitle burning, `doctor` must report ASS/subtitles ffmpeg filters.
On macOS, Homebrew `ffmpeg-full` is a practical libass-enabled build.

## Glossary (strongly recommended for series / named content)

The glossary is a **living document you curate together with the user**. It
feeds three touchpoints at once: ASR biasing (fewer misheard proper nouns),
transcript correction during segment, and translated-term consistency checks
(`term_issues` in `translate check`). Any series, or content with names,
jargon, or brands, deserves one.

```bash
openbbq glossary new frieren --context "Frieren: Beyond Journey's End, fantasy anime"
openbbq glossary use frieren --workspace <ws>   # bind to the workspace
```

Workflow:

1. At the start, confirm the core terms with the user (established renderings
   of names, places, proper nouns) and record them in the glossary
   (`source` → `target`, or `keep: true` to render the source verbatim).
2. After `transcribe`, run `openbbq glossary suggest --workspace <ws>`: it
   deterministically mines the transcript for candidate terms. **Confirm the
   candidates with the user** before folding them into the glossary — do not
   invent official renderings on your own.
3. Once bound, `segment` / `translate init` use the glossary automatically;
   the worksheet embeds the glossary map — follow it while translating.
4. `translate check` returns `term_issues` (`[{id, term, expected}]`) naming
   cues whose translation dropped an established term — fix each and re-apply.

## Full YouTube Workflow

For YouTube URLs, anonymous fetch is tried first. If fetch fails with an
authentication or bot-check error, run the browser login once on a desktop UI:

```bash
openbbq auth browser-login youtube
```

Then run:

```bash
openbbq init --workspace workspaces/demo '<youtube-url>'
openbbq fetch --workspace workspaces/demo
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

Then fill the translations. Read `workspaces/demo/translation.zh.json` first
for the sources, each cue's char budget (`budget.max_chars`, computed from the
target language's CPS), and the glossary map. Keep every translation **within
its budget** (overruns get named in `over_budget` at check time). Do NOT write
helper scripts, and do NOT rewrite the whole worksheet file:

- Few cues (≤ ~30): edit the `target` fields in place with the Edit tool.
- More cues: Write one or more batch files containing only translations — a
  JSON object mapping cue id → translated text:

  ```json
  {"1": "第一句译文", "2": "第二句译文"}
  ```

  Merge each batch (repeatable; later batches never disturb earlier ones):

  ```bash
  openbbq translate apply zh --workspace workspaces/demo targets.batch1.json
  ```

When every cue is filled:

```bash
openbbq translate check zh --workspace workspaces/demo
```

Check reports three signals — clear all of them before exporting: `missing`
(untranslated ids), `over_budget` (ids over their char budget — tighten the
wording and re-apply), and `term_issues` (cues that dropped a glossary term).
Then:

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --output out/zh.ass
openbbq burn --workspace workspaces/demo
```

For dense or vertical video, pass an ASS preset during export:

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset compact
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset mobile
```

Final artifacts:

- `out/zh.ass`: bilingual ASS subtitles.
- `out/zh-burned.mp4`: MP4 with hard-burned subtitles.

## Local File Workflow

For a local video, skip `fetch`:

```bash
openbbq init --workspace workspaces/demo /path/to/video.mp4
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

Then fill/check/export/burn exactly as in the YouTube workflow.

## Boundaries

- First-stage browser auth is for local desktop environments. Do not promise a
  headless server login flow.
- Font rendering can vary by platform. Current ASS defaults are tuned for local
  macOS rendering; commercial redistribution should verify font licensing.
- OpenBBQ does not grant copyright permission. Translating or burning subtitles
  into someone else's video can still require permission from the rights holder.

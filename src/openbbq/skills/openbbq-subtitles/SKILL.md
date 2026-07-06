---
name: openbbq-subtitles
description: >-
  Use OpenBBQ/openbbq for subtitle and video-translation workflows: make subtitles, translate subtitles, create bilingual subtitles/videos, burn ASS hard subtitles, transcribe video/audio, or continue processing a video list/tracker. Trigger when the user mentions OpenBBQ/openbbq with tasks like 制作字幕, 翻译字幕, 双语字幕, 双语视频, 视频翻译, 烧录字幕, 生成字幕, or English requests such as make subtitles, translate subtitles, bilingual video, burn subtitles, transcribe this video.
---

# OpenBBQ Subtitle Workflow

<!-- Generated from SKILL.zh-CN.md (the maintainer-authored source). To change
     this skill, edit the Chinese source first, then regenerate this file. -->

Use this skill when an agent is asked to create subtitles, translate subtitles,
or produce a subtitled video with OpenBBQ. Prefer OpenBBQ's atomic CLI commands
over ad hoc scripts.

## Operating Rules

- Use `openbbq --json ...` for automation unless the user explicitly wants the
  human terminal UI. The `next` field in success payloads is only a suggested
  next command and may not always be exact.
- Fill translations only two ways: edit the worksheet directly with the Edit
  tool, or write batch files and merge them with `openbbq translate apply`.
  **Never** write a one-off script that edits the worksheet.
- After an interruption, run `openbbq --json status --workspace <ws>` to inspect
  the workspace state, then continue or rerun the relevant failed/stale/pending
  stage.
- The manifest is the source of truth for completed/running/failed stages. The
  translate stage carries real `progress` (filled/total); a `running` stage
  marked `stale` means the original process is likely dead and that stage is
  safe to rerun. Rerunning a stage automatically resets downstream stages to
  pending.
- Quote URL arguments in shells such as zsh:
  `openbbq init --workspace workspaces/demo 'https://www.youtube.com/watch?v=...'`.
- Long tasks (`fetch`, `transcribe`, `burn`, `models pull`) write progress to
  the workspace (or stderr); poll `openbbq --json status --workspace <ws>` if
  you need progress outside the foreground command.
- When the agent is running in a sandbox, it usually cannot use the existing GPU
  for ASR transcription acceleration. Ask the user whether they allow running
  the `transcribe` command outside the sandbox when GPU acceleration is needed.
- For the default bilingual-video workflow, do not burn SRT. Export bilingual
  ASS and burn ASS.
- Pick ASS presets by target surface: use `fansub` for a more prominent
  bilingual style, and `mobile` for 9:16 vertical video.

## Runtime Preflight

On the first subtitle job on a machine, or when a command reports an
environment/dependency error, run:

```bash
openbbq doctor
```

Before final transcription, confirm the Whisper model is cached, such as
`large-v3-turbo`; if missing, download the model you need:

```bash
openbbq models pull large-v3-turbo
```

For hard-subtitle burning, `doctor` must report ASS/subtitles ffmpeg filters.
On macOS, Homebrew `ffmpeg-full` is a practical libass-enabled build.

## Glossary (strongly recommended for series / named content)

The glossary is a **living document you curate together with the user**. It
feeds three touchpoints at once: ASR biasing (fewer misheard proper nouns),
transcript correction during segment, and translated-term consistency checks
(`term_issues` in `translate check`).

Any series, or content with names, places, terminology, or brands, should have a
maintained glossary. If these terms are discovered only after transcription,
still add them to the glossary: the current workspace can use them during
segment/translate, and future related videos can use them for ASR biasing.

For example, when translating *Frieren: Beyond Journey's End*, create a
`frieren` glossary:

```bash
openbbq glossary new frieren --context "Frieren: Beyond Journey's End, fantasy anime"
```

The `context` is the short series/topic background. After creation, maintain
the `terms` in `~/.openbbq/glossaries/<name>.json`:

- `source`: canonical source text used by ASR biasing, correction, and term
  checks.
- `target`: established translation.
- `aliases`: common ASR mishearings, spelling variants, or alternate names;
  segment corrects them back to `source`.
- `note`: disambiguation context for the agent.
- `keep: true`: keep the source form untranslated in the target language.

```text
~/.openbbq/glossaries/frieren.json
```

```json
{
  "schema": "openbbq/glossary@1",
  "name": "frieren",
  "context": "Frieren: Beyond Journey's End, fantasy anime",
  "terms": [
    {
      "source": "Frieren",
      "target": "芙莉莲",
      "aliases": ["Freiren", "Freeran", "Fearin", "Frieran", "Freerun", "Freer", "Furian"],
      "note": "series & title character"
    },
    {
      "source": "Himmel",
      "target": "辛美尔",
      "note": "hero of the party"
    },
    {
      "source": "Heiter",
      "target": "海塔",
      "aliases": ["Heider", "Haider", "Hyder"],
      "note": "priest"
    }
  ]
}
```

Workflow:

1. At the start, confirm core terms with the user (names, places, proper nouns,
   established translations) and record them in the glossary. Do not invent
   official translations on your own.
2. When the glossary is known up front, bind it during `init` with
   `--glossary <name>`. If the workspace already exists, bind it with
   `openbbq glossary use <name> --workspace <ws>`.
3. After `transcribe`, run `openbbq glossary suggest --workspace <ws>`: it mines
   the transcript for candidate terms. **Confirm candidates with the user**
   before folding them into the glossary.
4. If the glossary is bound before a stage starts, `transcribe` / `segment` /
   `translate init` use it automatically; the worksheet embeds the glossary map,
   and translations should follow it.
5. `translate check` returns `term_issues` (`[{id, term, expected}]`) naming cues
   whose translations dropped an established term. Fix each one and re-apply.

## Full YouTube Workflow

For YouTube URLs, anonymous fetch is tried first. If fetch fails because of
authentication, bot checks, or cookies, run the browser login once on a desktop
UI:

```bash
openbbq auth browser-login youtube
```

For series or named-entity-heavy content, prepare or reuse a glossary first. If
none exists, create one and maintain its terms as described in the Glossary
section. When the glossary is known, bind it during `init` so ASR, segment, and
translate can all use it:

```bash
openbbq init --workspace workspaces/demo --glossary frieren '<youtube-url>'
openbbq fetch --workspace workspaces/demo
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq glossary suggest --workspace workspaces/demo
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

After `glossary suggest`, show candidate terms to the user for confirmation. If
new terms are accepted, use the Edit tool to update the glossary file before
continuing to `segment`. If there was no glossary at first but transcription
reveals names or terms, run `openbbq glossary new <name> --context "..."`, edit
the terms, bind it with `openbbq glossary use <name> --workspace workspaces/demo`,
then continue to `segment`. Non-series content without named entities can skip
the glossary commands.

Then fill the translations. Read `workspaces/demo/translation.zh.json` first for
the sources, each cue's char budget (`budget.max_chars`, computed from the
target language's CPS), and the glossary map. Keep every translation **within
its budget** (overruns get named in `over_budget` at check time). Do not write
helper scripts, and do not rewrite the whole worksheet file:

- Few cues (<= ~30): edit the `target` fields in place with the Edit tool.
- More cues: write one or more batch files containing only translations: a JSON
  object mapping cue id to translated text.

  ```json
  {"1": "第一句译文", "2": "第二句译文"}
  ```

  Merge each batch. This is repeatable; later batches do not disturb earlier
  results:

  ```bash
  openbbq translate apply zh --workspace workspaces/demo targets.batch1.json
  ```

When every cue is filled:

```bash
openbbq translate check zh --workspace workspaces/demo
```

Check reports three signals. Clear all of them before exporting: `missing`
(untranslated ids), `over_budget` (ids over their budget; tighten the wording
and re-apply), and `term_issues` (entries that dropped glossary translations).
Then:

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --output out/zh.ass
openbbq burn --workspace workspaces/demo
```

You can pass a preset during export:

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset mobile
```

Final artifacts:

- `out/zh.ass`: bilingual ASS subtitles.
- `out/zh-burned.mp4`: MP4 with hard-burned subtitles.

## Local File Workflow

For a local video, skip `fetch`. If a glossary already exists, pass
`--glossary <name>` during `init` as well:

```bash
openbbq init --workspace workspaces/demo --glossary frieren /path/to/video.mp4
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq glossary suggest --workspace workspaces/demo
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

If there is no glossary, remove `--glossary frieren` and follow the YouTube
workflow rule after transcription to decide whether to create and bind one. Then
fill/check/export/burn exactly as in the YouTube workflow.

## Boundaries

- First-stage browser auth is for local desktop environments. Do not promise a
  headless server login flow.
- Font rendering can vary by platform. Current ASS defaults are tuned for local
  macOS rendering; commercial redistribution should verify font licensing.
- OpenBBQ does not grant copyright permission. Translating or burning subtitles
  into someone else's video can still require permission from the rights holder.

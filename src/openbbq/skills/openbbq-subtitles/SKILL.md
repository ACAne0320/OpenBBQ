---
name: openbbq-subtitles
description: >-
  Use OpenBBQ/openbbq for subtitle and video-translation workflows: make subtitles, translate subtitles, create bilingual subtitles/videos, burn ASS hard subtitles, transcribe video/audio, or continue processing a video list/tracker. Trigger when the user mentions OpenBBQ/openbbq with tasks like 制作字幕, 翻译字幕, 双语字幕, 双语视频, 视频翻译, 烧录字幕, 生成字幕, or English requests such as make subtitles, translate subtitles, bilingual video, burn subtitles, transcribe this video.
---

# OpenBBQ Subtitle Workflow

<!-- Generated from SKILL.zh-CN.md (the maintainer-authored source). To change
     this skill, edit the Chinese source first, then regenerate this file. -->

Use this skill when a user asks OpenBBQ to make subtitles, translate subtitles,
create bilingual subtitles/videos, burn subtitles, transcribe video/audio, or
continue an OpenBBQ workspace. The default target is a **generic single-video
workflow**; follow user-specific batch conventions only when the user
explicitly provides them.

Prefer OpenBBQ's atomic CLI commands over ad hoc scripts.

## Required Rules

- Use `openbbq --json ...` for automation unless the user explicitly wants the
  human terminal UI. The `next` field is only a suggestion and may be wrong.
- Fill translations only two ways: edit the worksheet with the Edit tool, or
  write batch files and merge them with `openbbq translate apply`. **Never**
  write a one-off script that edits the worksheet.
- After an interruption, run `openbbq --json status --workspace <ws>`. The
  manifest is the source of truth for stage state; a `running` stage marked
  `stale` is usually safe to rerun. Rerunning an upstream stage resets
  downstream stages to pending.
- Quote URL arguments in shells such as zsh.
- Long tasks (`fetch`, `transcribe`, `burn`, `models pull`) may require status
  polling.
- In a sandbox, the agent usually cannot use the local GPU for ASR. When GPU
  transcription is needed, ask whether the user allows running `transcribe`
  outside the sandbox.
- For the default bilingual-video workflow, do not burn SRT. Export bilingual
  ASS and burn ASS.
- Pick ASS presets by target surface: `fansub` for prominent bilingual subtitles,
  and `mobile` for 9:16 vertical video.

## When To Read References

- For series, anime, games, brands, courses, interviews, or other named-entity
  heavy content, or whenever `glossary suggest` returns candidates: read
  `references/glossary.md`.
- For full YouTube/local-file command templates, translation batch format, and
  completion QA: read `references/workflows.md`.
- For conceptual answers or checking an existing workspace state, this file is
  usually enough.

## Generic Single-Video Flow

1. Runtime preflight: on the first subtitle job on a machine, or after dependency
   errors, run `openbbq doctor`. Before final transcription, confirm the Whisper
   model is cached; if missing, run `openbbq models pull <model>`.
2. Initialize a workspace. YouTube URLs and local files both use
   `openbbq init --workspace <ws>`; for series/named content, prepare or reuse a
   glossary and bind it during `init` with `--glossary <name>`.
3. For YouTube input, first check auth: `openbbq auth status youtube`. If auth is
   configured, prefer `openbbq fetch --workspace <ws> --auth youtube`; otherwise
   try anonymous fetch. If anonymous fetch fails because of cookies/bot checks,
   run `openbbq auth browser-login youtube`.
4. For local files, skip fetch; after YouTube fetch, continue with
   `extract-audio`.
5. Transcribe, usually with `openbbq transcribe --workspace <ws> --model
   large-v3-turbo --language <lang> --gpu`. If the sandbox cannot use GPU,
   follow the required rule above.
6. Named-entity pass: after transcription, always run
   `openbbq glossary suggest --workspace <ws>`. Use `references/glossary.md` to
   actively audit ASR proper-noun mistakes, spelling variants, and new key terms;
   update the glossary before `segment`. If `segment` already ran, rerun
   `segment` and `translate init` after updating the glossary.
7. Segment, then initialize translation with `translate init <lang>`.
8. Fill translations: for few cues, use the Edit tool; for many cues, write a
   `{id: target}` batch JSON and merge it with `openbbq translate apply <lang>
   --workspace <ws> <batch.json>`.
9. Mechanical check: run `openbbq translate check <lang> --workspace <ws>` and
   clear `missing`, `over_budget`, and `term_issues`.
10. Human visual review: when the user asks for final manual review, cue timing
    changes, or sentence-boundary fixes, run `openbbq review --workspace <ws>
    --to <lang>`. The review service safely synchronizes cues and every
    worksheet; do not edit those files concurrently from another Agent.
11. Translation quality self-review: before export, spot-check or read through
    the worksheet and proactively fix mistranslations, unnatural phrasing, tone
    mismatches, broken context, term drift, and bilingual source/target
    mismatches. After revisions, rerun `translate apply` and `translate check`.
12. Export and burn: default to bilingual ASS, then burn. When a review file
    exists, incomplete review blocks export; use `--allow-unreviewed` only for
    an intentional draft. Pick `--ass-preset` by target surface.
13. Completion QA: follow `references/workflows.md` to check status,
    `translate check`, output MP4 duration/size, and a rendered subtitle frame.

## Glossary Principles

Glossary is a living document used for ASR biasing, segment correction, and
`translate check` term consistency. Series or named-entity heavy content should
actively maintain one.

Core decisions:

- ASR mistakes or spelling variants: add the incorrect form to an existing
  term's `aliases`, or add a canonical `source` and put the incorrect form in
  `aliases`. Do not let these errors flow into `segment`, especially for
  bilingual hard subtitles where the English source text is rendered.
- Confirmed new key terms: add them if the translation is known; otherwise ask
  the user or mark them as pending in `note`.
- One-off common words / low-confidence candidates: do not add them to the
  glossary and do not block the workflow.

See `references/glossary.md` for the full schema, examples, and active audit
workflow.

## Boundaries

- First-stage browser auth is for local desktop environments. Do not promise a
  headless server login flow.
- Font rendering can vary by platform. Current ASS defaults are tuned for local
  macOS rendering; commercial redistribution should verify font licensing.
- OpenBBQ does not grant copyright permission. Translating or burning subtitles
  into someone else's video can still require permission from the rights holder.

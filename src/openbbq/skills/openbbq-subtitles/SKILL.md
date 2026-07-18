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

## Defaults for a Simple Request

When a user supplies one video and asks only to “make this a bilingual subtitled
video,” run the full workflow without asking about routine options. Infer the
target language from the user's language (a Chinese request defaults to `zh`),
produce a hard-subtitled bilingual ASS video, and use `fansub` for landscape.
Pause only for genuinely ambiguous language, rights scope, or external
permission. Do not call the task complete until `delivery check` passes.

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
- Never delete fetch `.part` files; fetch supports resume. Do not give `fetch`,
  `transcribe`, or `burn` a harness timeout shorter than the task can reasonably
  take.
- Do not hand-edit `manifest.json`, `cues.json`, or exported ASS. Use
  `openbbq review` for source, timing, translation, or sentence-boundary edits;
  batch targets must go through `translate apply`.
- Quote URL arguments in shells such as zsh.
- Long tasks (`fetch`, `transcribe`, `burn`, `models pull`) may require status
  polling.
- In a sandbox, the agent usually cannot use the local GPU for ASR. When GPU
  transcription is needed, ask whether the user allows running `transcribe`
  outside the sandbox.
- For the default bilingual-video workflow, do not burn SRT. Export bilingual
  ASS and burn ASS.
- Pick ASS presets by target surface: `fansub` for prominent bilingual subtitles,
  `fansub-compact` for lower-third conflicts, overlap, or a crowded subtitle
  stack, and `mobile` for 9:16 vertical video.
- Final delivery must not skip the ASR uncertainty gate, risk-ranked translation
  audit, or structured QA. A rendered file is not a visual observation. Without
  actual image input, report `visual_status: not_performed` and never run
  `qa attest`.

## When To Read References

- For series, anime, games, brands, courses, interviews, or other named-entity
  heavy content, or whenever `glossary suggest` returns candidates: read
  `references/glossary.md`.
- For full YouTube/local-file command templates, translation batch format, and
  completion QA: read `references/workflows.md`.
- For conceptual answers or checking an existing workspace state, this file is
  usually enough.

## Generic Single-Video Flow

1. Runtime preflight: start every simple request with `openbbq --json doctor`.
   An installed but outdated agent skill makes doctor unhealthy; follow its fix
   with `openbbq skill install --force` before continuing. Confirm the Whisper
   model is cached before transcription.
2. Initialize a workspace. YouTube URLs and local files both use
   `openbbq init --workspace <ws>`; for series/named content, prepare or reuse a
   glossary and bind it during `init` with `--glossary <name>`.
3. For YouTube input, first check auth: `openbbq auth status youtube`. If auth is
   configured, prefer `openbbq fetch --workspace <ws> --auth youtube --max-height
   1080`; otherwise
   try anonymous fetch. If anonymous fetch fails because of cookies/bot checks,
   run `openbbq auth browser-login youtube`.
4. For local files, skip fetch; after YouTube fetch, continue with
   `extract-audio`.
5. Transcribe, usually with `openbbq transcribe --workspace <ws> --model
   large-v3-turbo --language <lang> --gpu`. If the sandbox cannot use GPU,
   follow the required rule above.
6. ASR review: run `openbbq --json asr check --workspace <ws>`, then read bounded
   `asr batch --limit 20` pages. Resolve low-confidence words, repeated segments,
   impossible word rates, and title/author entity conflicts; overlapping YouTube
   reference captions appear when available. Use accept/replace for words and
   entities, keep_first/drop for hallucinated repetitions, and whole-segment
   replace only for a damaged segment. Every decision needs evidence. Continue
   only at `ready: true`.
7. Named-entity pass: run
   `openbbq glossary suggest --workspace <ws>`. Use `references/glossary.md` to
   actively audit ASR proper-noun mistakes, spelling variants, and new key terms;
   update the glossary before `segment`. If `segment` already ran, rerun
   `segment` and `translate init` after updating the glossary.
8. Segment, then initialize translation with `translate init <lang> --max-lines
   2`. For bilingual video, use the second target line before deleting meaning.
9. Fill translations: for many cues, first read a bounded batch with
   `openbbq --json translate batch <lang> --workspace <ws> --from <id> --limit
   20 --only-missing`, then write a `{id: target}` batch JSON and merge it with
   `translate apply`. Do not load the entire worksheet into context.
10. Mechanical check: run `openbbq translate check <lang> --workspace <ws>` and
   clear `missing`, `over_budget`, `zero_budget`, `term_issues`, and
   `quality_issues`. Continue only at `ready: true`. The command is read-only;
   formal `export` completes the translation stage.
11. Full-coverage semantic audit: page through `translate audit <lang>
   --coverage all --limit 20`. Risky cues come first, but every translated cue
   must be accepted or revised against its previous and next context. Never
   bulk-accept because deterministic checks passed. Editing a cue invalidates
   its own and adjacent context reviews; rerun check/audit until ready.
12. Human visual review: when the user asks for final manual review, cue timing
    changes, or sentence-boundary fixes, run `openbbq review --workspace <ws>
    --to <lang>`. The review service safely synchronizes cues and every
    worksheet; do not edit those files concurrently from another Agent.
13. Export and burn: default to bilingual ASS, then burn. When a review file
    exists, incomplete review blocks export; use `--allow-unreviewed` only for
    an intentional draft. Pick `--ass-preset` by target surface.
    `--allow-quality-warnings` and `burn --allow-stale` are only for a
    user-requested draft or intentional external/manual artifact, never a final
    delivery.
14. Completion QA: `qa render` defaults to up to seven risk frames covering
    boundaries, midpoint, long lines, high CPS, and short cues. Inspect every
    image before attesting. A failed attestation must include structured
    `--issue` values; use `fansub-compact` for layout conflicts, or return to ASR
    and semantic audit for content errors. Without image input, never attest.
15. Hard delivery gate: run `openbbq --json delivery check --workspace <ws> --to
    <lang>`. Deliver only when it exits 0 with `ready: true`; follow its returned
    fix instead of explaining away a failed gate.

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

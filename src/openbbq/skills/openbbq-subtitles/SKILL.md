---
name: openbbq-subtitles
description: >-
  Use OpenBBQ/openbbq to transcribe, translate, create bilingual subtitles or
  bilingual hard-subtitled videos. Trigger for OpenBBQ, 制作字幕, 翻译字幕,
  双语字幕, 双语视频, make subtitles, bilingual video, or burn subtitles.
---

# OpenBBQ Subtitle Workflow

<!-- Generated from the maintainer-authored SKILL.zh-CN.md. Edit the Chinese
     source first, then synchronize this file. -->

Use this skill for one video at a time. A Chinese request defaults to target
language `zh`. Treat the output as a solid AI draft: ready to use casually and
easy to refine professionally.

## One-Prompt Flow

When the user only asks to “make this video into a bilingual subtitled video,”
do not ask about routine options. Create a fresh workspace, initialize once,
then let `agent next` drive the task:

```bash
openbbq --json agent init '<source>' --workspace '<ws>' --to zh
openbbq --json agent next --workspace '<ws>'
```

Repeat these steps until `done`:

1. For `run_command`, execute the returned `argv` exactly. Obey
   `execution.sandbox`: run `outside_required` on the host/outside the sandbox
   and run `inside_allowed` in the current environment. Fetch may require the
   host network and auth state. Transcription must use the returned outside-host
   GPU command; keep `--gpu`. Retry with `--cpu` only after that outside GPU
   command actually fails and `execution.cpu_fallback` permits it. Do not
   otherwise add, remove, or reorder arguments.
2. For `translate`, follow the returned `brief` and glossary context, translate
   every `selected_id` exactly once, and submit one response matching
   `response_schema`:

   ```bash
   openbbq --json agent apply --workspace '<ws>' response.json
   ```

   Echo `batch_id` and `policy_hash` exactly and submit the complete current ID
   set. Neighbor cues are context only. Keep translations aligned to their IDs.
   If the source is clearly wrong, include the cue-scoped `source_fix` defined
   by the schema and judge only its required `reusable: true/false` field.
   OpenBBQ records the glossary candidate and promotes reusable corrections;
   do not duplicate that correction in `glossary_updates`.
3. `review_source` is exceptional. Handle it only when `agent next` reports a
   structural ASR blocker that deterministic repair could not resolve. Respond
   to the exact schema and IDs, apply it once, then continue.
4. For `finish`, obey its execution policy and run the returned
   `openbbq agent finish` command once. It exports the bilingual ASS, burns the
   video once, and validates the artifacts.
5. For `done`, deliver the returned subtitle and video paths plus warnings.
   Report the returned `quality` and `human_reviewed` values verbatim.

Call `agent next` again after every successful command or apply. Keep only one
active action; repeated calls return the same lease. Continue while
`must_continue` is true or `terminal` is false. Only `done` with
`terminal: true` completes the task.

## Translation Guidance

- Follow the batch `brief`, glossary context, and target-language rules.
- Produce natural, faithful text; preserve negation, numbers, entities,
  conditions, and key relationships.
- Translate only the current cue. Use neighbors for disambiguation, never to
  move content between IDs.
- Prefer meaning and alignment over aggressive shortening. If unsure about a
  possible ASR error, translate the current source and include a warning instead
  of inventing a correction.

Do not hand-edit workspace data, create parallel leases, run visual QA, or use
`fansub-compact`. Long-running fetch, transcription, and finish commands need
reasonable time to complete.

For professional refinement after `done`, open the workspace with
`openbbq review --workspace '<ws>' --to zh`, or edit the exported subtitle in
Aegisub or an NLE. Human edits are authoritative and should not be overwritten
by rerunning the agent workflow.

OpenBBQ does not grant copyright permission; users remain responsible for the
rights required to process someone else's video.

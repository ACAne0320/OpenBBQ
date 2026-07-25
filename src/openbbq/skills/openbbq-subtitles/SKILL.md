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

Use this skill for a single OpenBBQ video. A Chinese request defaults to target
language `zh`.

## Default One-Prompt Flow

When the user only asks to “make this video into a bilingual subtitled video,”
do not ask about routine options. Initialize once, then obey only the action
returned by `agent next`:

```bash
openbbq --json agent init '<source>' --workspace '<ws>' --to zh
openbbq --json agent next --workspace '<ws>'
```

Loop on `agent next`:

1. `run_command`: execute the returned `argv` exactly and obey its
   machine-readable `execution` policy:
   - `sandbox: outside_required` means host/outside-sandbox execution is
     required. Request approval when needed; do not first run in a restricted
     sandbox and silently downgrade.
   - `accelerator: gpu` means keep the argv's `--gpu`. Only after the
     outside-sandbox GPU command actually fails, and only when
     `cpu_fallback: only_after_outside_gpu_failure`, may that command be retried
     with `--cpu`; preserve the original GPU error.
   - `inside_allowed` may run in the current sandbox. Do not add, remove, or
     reorder any other arguments.

   Call `agent next` again immediately after the command completes.
2. `select_glossary`, `review_source`, `translate`, or `review_risks`: write one
   JSON file matching the action's `response_schema`, then submit it:

   ```bash
   openbbq --json agent apply --workspace '<ws>' response.json
   ```

   Call `agent next` again. Echo `batch_id` and `policy_hash` exactly and submit
   the complete, exact current ID set. Never split, omit, or add IDs.
3. `finish`: obey `execution` in the same way and execute its returned `argv`;
   the default currently requires `outside_required`. `agent finish` exports
   bilingual ASS, burns once, runs the delivery check, and publishes
   non-conflicting glossary learning after successful delivery.
4. `done`: only now deliver the returned subtitle and video paths, including any
   structured warnings.

Never advance multiple actions concurrently. Repeated `agent next` calls return
the same active lease; do not continue until the semantic batch applies
successfully. Whenever an action or apply result says `must_continue: true` or
`terminal: false`, the current task is unfinished and must keep looping in the
same turn. Progress such as “translated N/total” is not a deliverable. Only
`done` with `terminal: true` may end the task.

## Semantic Decisions

### `review_source`

- Review every segment using the full sentence, neighboring context,
  title/author, optional reference captions, glossary, and topic. Confidence is
  evidence, not the verdict.
- Decide every current detector issue. Put contextual mistakes without an issue
  ID in `source_fixes` with one concrete evidence sentence.
- `collapsed_word_timestamps` and `reference_timeline_mismatch` mean the ASR
  timeline is corrupted and cannot be accepted. Use the timed reference
  replacement when available; otherwise explicitly replace or drop it from
  context. Never let a damaged timeline reach segmentation.
- Add a `glossary_update` with `reusable: true` only for a name, term, or ASR
  variant that is safe in future related videos. Never turn a one-off common
  word error into a global alias.
- Official-casing corrections such as `codex → Codex` are valid. Never modify an
  undeclared occurrence.

### `translate`

- The action's `brief`, `glossary`, and `policy_hash` are the only authoritative
  translation policy for the batch. Neighbor cues disambiguate only; content
  must remain aligned to the current ID.
- Simplified Chinese should be natural and concise while preserving negation,
  degree, numbers, entities, causality, conditions, and procedural steps. Follow
  glossary target/keep/note and keep commands, code, paths, flags, URLs, product
  names, and model names accurate.
- Meaning and cue alignment outrank the character budget. Keep meaning for risk
  review rather than silently omitting it.
- When translation reveals a likely ASR error, submit a cue-scoped `source_fix`
  and translate the corrected source instead of guessing from bad text.
- The CLI enforces at most 20 selected cues. Translate only `selected_ids`, not
  neighboring context items.

### `review_risks`

- Review only the returned high-risk cues against source, target, and neighbors.
  `accept` needs no fabricated long rationale; `revise` needs a new target and a
  short reason.
- `glossary_inconsistent` means a required term is missing from the current
  cue's target and cannot be accepted. Revise the target to preserve it, or
  include a `source_fix` when the source entity itself is wrong.
- If risk review is where an ASR mistake becomes clear, submit a cue-scoped
  `source_fix` in the same response and judge the target against the corrected
  source. Add a reusable `glossary_update` when the correction generalizes.
- Do not fabricate a full audit or export/burn after a revision. Apply, then
  continue with `agent next`.

## Invariants

- The default flow has no visual QA, risk-frame inspection, on-screen text
  prediction, or `fansub-compact`. Finish chooses `fansub` for landscape and
  `mobile` for portrait.
- Do not hand-edit `manifest.json`, `cues.json`, worksheets, or ASS. All semantic
  changes go through `agent apply`.
- Use a fresh independent workspace for every real regression or parallel
  harness run. Never reuse a workspace currently owned by another Agent or Pi
  session.
- Do not write one-off scripts to edit subtitle data.
- `fetch`, `transcribe`, and `burn` are long-running. Do not impose an
  unreasonable short timeout. Status polling is fine; creating a second
  workspace or parallel lease is not.
- `fetch` needs host network and YouTube auth state, GPU `transcribe` needs the
  host model cache and native acceleration, and `finish` may publish the global
  glossary. When those actions return `sandbox: outside_required`, run them
  outside the sandbox. Do not switch to CPU merely because Metal/CUDA is
  unavailable inside the sandbox.
- The glossary overlay stays in the workspace during the task. A global conflict
  or permission failure is a non-blocking warning: never overwrite an existing
  entry or reject an otherwise ready video.

## Expert References

Do not expand legacy atomic commands in the normal one-shot path. Read these
only for authentication, sandbox/GPU constraints, recovery, expert manual work,
or a legacy workspace:

- `references/workflows.md`: YouTube auth, long jobs, recovery, and legacy
  atomic commands.
- `references/glossary.md`: glossary schema, conflicts, and manual maintenance.

OpenBBQ does not grant copyright permission; users remain responsible for the
rights required to process someone else's video.

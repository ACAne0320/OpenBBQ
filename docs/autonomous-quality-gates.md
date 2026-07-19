# Autonomous Subtitle Quality Loop v3

## Objective

A one-prompt request such as “turn this video into a bilingual subtitle video”
should produce a verified artifact without asking an agent harness to remember a
long command sequence. Pi, Codex, and other harnesses consume one authoritative
state interface:

```text
openbbq agent init <source> --workspace <ws> --to zh
openbbq --json agent next --workspace <ws>
openbbq agent apply --workspace <ws> <response.json>
openbbq agent finish --workspace <ws>
```

Fine-grained ASR, glossary, translation, audit, export, and burn commands remain
available as expert and legacy interfaces.

## State Contract

`agent next` returns exactly one action:

- `run_command`: exact argv for a mechanical step;
- `select_glossary`: reuse, create, or explicitly disable a glossary;
- `review_source`: at most 20 complete transcript segments plus detector hints,
  neighbors, metadata, optional reference captions, and glossary context;
- `translate`: at most 20 selected cues plus neighbors, glossary hits, and a
  reproducible target-language brief;
- `review_risks`: at most 20 genuinely risky translations;
- `finish`: permission to export and burn once;
- `done`: fresh deliverables and non-blocking glossary warnings.

Every semantic action has one persistent lease containing a batch ID, exact ID
set, source and worksheet hashes, and policy hash. Repeated `next` reads are
idempotent. `apply` rejects partial/extra IDs, stale inputs, or an incorrect
policy. Short workspace locks serialize state transitions; long export/burn work
uses a persisted process claim rather than holding the lock.

State is stored in `.openbbq/agent-session.<lang>.json`. The manifest schema is
unchanged.

## Source Quality

- Detector and contextual replacements are occurrence-scoped. A word decision
  never changes the same common word in another segment or another occurrence.
- Only a deliberately reusable glossary alias is global across segments.
- Case-only canonicalization such as `codex → Codex` is valid and persists.
- `review_source` covers every transcript segment and resolves every current
  detector issue. Context and meaning are primary; probability and reference
  captions are evidence only.
- Inline-timed YouTube captions are used to detect and repair sustained ASR word
  timestamp collapse and the following drift. Timeline anomalies cannot be
  accepted; segmentation, export, and delivery independently reject zero- or
  negative-duration cues.
- Source batches include complete segment text but only timing/probability
  records that need attention, plus an omitted-word count. Unchanged raw and
  glossary variants are not duplicated in the payload.
- One-off errors become source fixes. Reusable canonical terms, aliases,
  target/keep guidance, and notes enter the workspace glossary overlay.
- `segment` blocks until balanced source-review evidence is complete.

## Glossary Overlay

The task stores its base glossary name/hash, reusable patches, and evidence in
`.openbbq/glossary-overlay.json`. Transcription, source review, segmentation,
and worksheet creation see base + overlay immediately. The global library is
not changed mid-task.

After delivery succeeds, every non-conflicting entry is published. Existing
global values are never overwritten. A conflict or permission failure leaves
the overlay intact and returns an exact retry command; it does not invalidate a
ready video.

## Translation Policy

New worksheets use `openbbq/translation@2`. `translation@1` remains readable and
is migrated in place when an agent session reaches translation; existing targets
are preserved.

Every `translation@2` embeds a brief with source/target language, title, author,
glossary domain context, ruleset, and fixed rules. `zh`, `zh-Hans`, and `zh-CN`
use `zh-Hans@1`; Traditional Chinese variants and other languages use an
explicit `generic@1` fallback.

Batch context includes all selected/neighbor glossary hits, including pending
note-only terms. Translation evidence is tied to cue source, target, budget,
relevant glossary snapshot, and policy hash. Translation-time ASR discoveries
use cue-scoped source fixes that update `cues.json` and worksheet source copies
as one rollback-safe transaction.

## Balanced Risk Review

The default workflow does not fabricate a full per-cue audit. Once all cues have
valid translation evidence, it reviews only current risks:

- a source correction discovered during translation;
- glossary inconsistency or likely entity omission;
- over-budget/zero-budget targets, extreme shortening, or likely omission;
- target-script residue, punctuation mismatch, source copy, and repeated target
  failures.

Accepting a risk needs no artificial long rationale. A revision supplies a new
target and short reason. Risk evidence is tied to the cue's own current content,
so revising a neighbor does not create an endless re-review/reburn loop.
Risk review can also submit a cue-scoped source fix and reusable glossary update
when translation is where the remaining ASR mistake becomes clear; source,
worksheet, audit, and overlay changes commit as one transaction.

Legacy workflows without an agent session still require `coverage=all`. If an
agent session exists but its evidence is stale, export and delivery block and
point to `agent next`; they never silently fall back to the weaker path.

## Finish and Delivery

`agent finish` requires fresh source, translation, and risk evidence. It exports
`out/<lang>.ass`, chooses `fansub` for landscape or `mobile` for portrait, burns
`out/<lang>-burned.mp4`, and runs the hard delivery check. A current export or
burn is reused; retries never burn a fresh artifact again.

Visual QA, sampled risk frames, text-position prediction, and
`fansub-compact` are not part of the default workflow. Mechanical non-empty and
provenance checks remain mandatory.

## Compatibility and Non-Goals

- No translation provider or model is embedded in OpenBBQ.
- Existing atomic commands and `translation@1` stay compatible.
- The glossary keeps its single `target` field.
- The first specialized translation policy is Simplified Chinese only.
- Multi-video queues, parallel target languages, OCR/layout prediction, and
  automatic visual rework are outside this version.

## Release Gate

CI must pass Ruff, ty, pytest, wheel/sdist builds, and isolated CLI smoke tests.
Before release, the identical one-shot prompt and independent workspaces must be
run with Pi + DeepSeek-v4-pro high and Codex + GPT-5.6 Luna medium on
`https://www.youtube.com/watch?v=neK8ydl0Vlk`. Release requires at least 95%
source correctness, 95% faithful cue alignment, an overall score of 80, batches
of at most 20, one burn, `delivery_ready: true`, and a successful or explicitly
retryable glossary publication result.

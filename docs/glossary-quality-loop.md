# Agent-driven glossary quality loop

## Goal

A one-shot subtitle task must let the agent discover ASR mistakes from meaning
and context, repair the current source occurrence, and preserve only genuinely
reusable terminology for later related videos. Confidence is an ordering clue,
not a correctness verdict.

## Default contract

1. `agent next` returns `review_source` batches containing complete segments,
   neighbors, word probabilities, detector issues, metadata, optional reference
   captions, and current glossary context.
2. The response covers every selected segment and detector issue. A contextual
   one-off correction goes in `source_fixes` with short evidence.
3. A name, term, official casing, translation rule, or recurring ASR variant
   goes in `glossary_updates` only when it is safe for future related videos and
   is explicitly marked `reusable: true`.
4. OpenBBQ keeps reusable learning in `.openbbq/glossary-overlay.json`. Base +
   overlay is used immediately by later source batches, segmentation, and
   translation, while the global glossary stays unchanged during the task.
5. Translation batches may discover missed ASR errors. They atomically update
   the stable cue ID and worksheet source, then translate the corrected text.
   The affected cue is automatically included in risk review.
6. Risk review may make the same cue-scoped source correction and reusable
   glossary update if the error becomes clear only during final semantic review.
7. Only after delivery succeeds does `agent finish` publish non-conflicting
   reusable entries to the global library.

## Safety rules

- Detector and contextual fixes are occurrence-scoped. Only an explicit
  glossary alias can correct text across segments.
- A common word that may be correct elsewhere must never become a global alias.
- Case-only aliases are retained, so `codex` reliably canonicalizes to `Codex`.
- Overlay updates are bounded and atomic. A malformed or form-owning conflict
  leaves canonical source products untouched.
- Publication never overwrites an existing target, keep decision, note, or
  alias owner. Safe entries can publish even when another entry conflicts.
- A conflict, missing global binding, or permission error keeps the overlay and
  returns a non-blocking retry warning. Failed/incomplete video tasks never
  publish.

## Legacy expert interfaces

`asr check/batch/apply`, `glossary audit`, `asr amend`, `glossary suggest`, and
`glossary apply` remain available for old workspaces and explicit manual work.
They are no longer the normal Skill happy path.

## Acceptance criteria

- High-confidence contextual errors can be fixed without inventing detector IDs.
- The same common word elsewhere is unchanged by an occurrence fix.
- A reusable alias affects segmentation and later workspaces.
- Translation receives glossary context plus selected and neighbor pending terms.
- Global publication is idempotent, conflict-safe, and never blocks delivery.

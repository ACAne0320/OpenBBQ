# Glossary Learning In The Draft Workflow

## Goal

OpenBBQ uses a glossary to improve related videos without turning uncertain ASR
text into a global rule. A one-shot task may repair an obvious source
occurrence and preserve a genuinely reusable term while translating.
Confidence and glossary-consistency findings are clues, not correctness
verdicts.

## Default Contract

1. Pass `--glossary <name>` to `agent init` when an existing glossary is
   explicitly relevant; it always wins. Otherwise a URL task derives a stable
   `author-<slug>-<target>-<hash>` glossary after fetch discovers the author.
   The target-language scope prevents one glossary's single `target` field from
   leaking across languages. There is no
   model-driven glossary selection step.
2. Normal `translate` batches receive the available glossary context, selected
   cues, and neighbor cues.
3. A translation response may include cue-scoped `source_fixes` when context
   makes an ASR error clear. Source and worksheet copies update atomically.
4. It may include `glossary_updates` only for a canonical term, official
   casing, translation rule, or recurring ASR alias that is safe to reuse.
5. OpenBBQ stores reusable learning in `.openbbq/glossary-overlay.json` and uses
   base glossary plus overlay for the rest of the task. Later videos for the
   same author and target language deterministically reuse the published
   glossary.
6. Only after successful delivery does `agent finish` publish non-conflicting
   reusable entries to the global library.

`review_source` may offer the same bounded fixes only when a structural ASR
problem blocks segmentation. It is not a full-transcript glossary pass.
Ordinary low-confidence or ambiguous wording remains a warning and does not
need a forced correction.

## Safety Rules

- Source fixes are occurrence-scoped.
- Only an explicit reusable alias may affect matching text beyond that
  occurrence.
- Common or ambiguous words must not become global aliases merely to satisfy a
  warning.
- Case-only aliases remain valid, so an intentional `codex → Codex`
  canonicalization can persist.
- Overlay updates are bounded and atomic.
- Publication never overwrites an existing target, keep decision, note, or
  alias owner.
- A conflict, missing binding, or permission failure keeps the overlay and
  returns a non-blocking retry warning.
- Failed or incomplete video tasks never publish.

## Expert Interfaces

`asr check/batch/apply`, `asr amend`, `glossary suggest/audit/apply`, and the
atomic `translate init/batch/apply/check` commands remain available for
diagnosis, migration, or a human-directed pass. They are not required by the
default one-shot workflow. Translation meaning is approved either by the
agent-draft evidence produced by the facade or by a complete, current human
review; there is no separate full-coverage AI audit.

## Acceptance Criteria

- An obvious cue-scoped error can be fixed without changing the same word
  elsewhere.
- Translation receives explicit glossary context and pending note-only terms.
- Reusable aliases affect later matching work, while uncertain guesses do not.
- Publication is idempotent, conflict-safe, and never blocks an otherwise valid
  draft.

# Agent-driven glossary quality loop

## Goal

A one-shot subtitle request must give the agent enough structured evidence and
safe write operations to discover ASR mistakes from meaning and context, repair
the current source subtitles, and preserve reusable names or mishearings for
future videos.

Word probability is evidence for ordering only. It is not a correctness gate:
high-confidence words can still be semantically wrong.

## Workflow contract

1. `asr check/batch/apply` resolves detector-found issues as before.
2. `glossary audit` pages through every transcript segment and exposes its
   surrounding text, word probabilities, overlapping reference caption, and
   current glossary matches. The agent reviews meaning rather than accepting a
   token only because its probability is high.
3. `asr amend` records a bounded, reasoned phrase correction even when no
   detector produced an issue ID.
4. Reusable names, terms, and recurring ASR variants are written atomically with
   `glossary apply`. One malformed or colliding change leaves the glossary
   untouched.
5. `glossary suggest` mines the ASR-resolved transcript, not the immutable raw
   transcript.
6. `segment` reports canonical term matches, alias corrections, and a clear
   no-effect signal for the bound glossary.

## Compatibility and safety

- Existing glossary and ASR review files remain readable.
- Review and glossary writes are capped at 20 entries per operation.
- Every manual ASR correction requires `segment_id`, `find`, `replacement`, and
  a non-empty reason.
- Updating a glossary for a workspace invalidates segmentation and all later
  artifacts; it does not trigger translation, export, or burn automatically.
  An idempotent no-op update leaves completed stages intact.
- Reference captions and probabilities are advisory evidence. The agent remains
  responsible for contextual judgment and must not copy reference text blindly.

## Acceptance criteria

- A high-confidence error can be found in a context audit and corrected without
  inventing a low-confidence issue ID.
- Adding `{"source": "hot take", "aliases": ["hot tick"]}` corrects the
  current segmentation and is available to later workspaces.
- Re-running `glossary suggest` after an ASR replacement cannot re-surface the
  replaced raw spelling.
- Segment JSON output distinguishes “glossary bound” from “glossary actually
  matched or corrected text.”

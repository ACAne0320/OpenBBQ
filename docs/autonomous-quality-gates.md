# Editable Subtitle Draft Workflow

## Product Contract

A one-prompt request such as “turn this video into a bilingual subtitle video”
should reliably produce an editable AI subtitle draft. The expected result is a
useful 70–80 point first pass, not an autonomously certified professional
translation.

Pi, Codex, and other harnesses consume one authoritative state interface:

```text
openbbq agent init <source> --workspace <ws> --to zh [--glossary <name>]
openbbq --json agent next --workspace <ws>
openbbq agent apply --workspace <ws> <response.json>
openbbq agent finish --workspace <ws>
```

Fine-grained ASR, glossary, translation, export, burn, and QA commands remain
available as expert interfaces. They are not extra steps in the default
one-shot path.

## Default State Machine

`agent next` returns exactly one action:

- `run_command`: exact argv for fetch, extract, transcribe, segment, or another
  mechanical step;
- `review_source`: a rare, bounded request for a structural ASR blocker that
  deterministic recovery could not safely resolve;
- `translate`: the current translation batch, with at most 20 cues;
- `finish`: permission to export and burn once;
- `done`: fresh deliverables, `quality`, `human_reviewed`, and warnings.

There is no model-driven glossary-selection dialogue, risk-review queue, or
full-coverage AI audit. An explicit glossary passed to `agent init` wins.
Otherwise, a URL task binds a stable author-and-target glossary after fetch
discovers the author; local-file tasks can still learn into their workspace
overlay.

Semantic actions use a persistent lease containing a batch ID, the exact ID
set, source/worksheet hashes, and a policy hash. Repeated `next` calls are
idempotent. `apply` rejects partial or extra IDs, stale inputs, and an incorrect
policy. Workspace locks serialize state transitions without holding a lock
through a long media encode.

State is stored in `.openbbq/agent-session.<lang>.json`. The manifest remains
the source of truth for pipeline stages and artifact provenance.

## Hard Gates And Warnings

The default workflow blocks only on conditions that make the draft incomplete,
corrupt, stale, or unsafe to continue:

- readable schemas and files;
- valid, monotonic cue timing with positive durations;
- exact and complete leased ID sets;
- non-empty source cues and translations;
- current source, worksheet, policy, and glossary hashes;
- atomic source/worksheet updates;
- fresh export and burn provenance;
- non-empty final artifacts.

Ordinary low-confidence words are advisory. Budget pressure and glossary
mismatch may appear as warnings, but do not create another mandatory action or
force the model to invent a correction.

`review_source` is reserved for a genuine structural blocker, such as damaged
timing or repetition that prevents valid segmentation. It is not a review of
every transcript segment. Source fixes are occurrence-scoped; only an explicit
reusable glossary alias may affect later matching occurrences.

## Translation And Glossary Learning

New worksheets use `openbbq/translation@2`. Each worksheet embeds a reproducible
brief with source/target language, title, author, target-language rules, and
available glossary context. Each `translate` action contains at most 20 selected
cues plus neighbor context for disambiguation. If a timed reference caption has
a short local substitution inside an otherwise close cue alignment, only that
cue receives compact advisory `reference_evidence`. This avoids repeating the
full reference or asking the agent to rediscover workspace files.

The response supplies the exact translations and may also include:

- `source_fixes` for an obvious ASR error in a selected cue;
- `glossary_updates` for a term or alias that is genuinely reusable;
- concise `warnings` when the agent is uncertain.

A cue-scoped source fix updates `cues.json` and the worksheet source atomically,
then invalidates only evidence affected by that change. The agent should leave
uncertain source text alone and translate it conservatively rather than forcing
a guess. Reusable fixes should identify the smallest stable term/alias instead
of preserving surrounding grammar in the glossary.

The task stores reusable learning in `.openbbq/glossary-overlay.json`. For a URL
without an explicit glossary, the author and target language deterministically
map to `author-<slug>-<target>-<hash>`, so later videos for the same author and
target reuse prior terms without mixing translations across languages.
Base glossary plus overlay are visible during the task, but the global glossary
is not changed mid-run. After successful delivery, non-conflicting entries are
published. Conflicts or permission failures keep the overlay and return a
retryable warning; they never overwrite an existing entry or invalidate the
video.

## Finish, Delivery, And Human Review

`agent finish` exports `out/<lang>.ass`, chooses `fansub` for landscape or
`mobile` for portrait, burns `out/<lang>-burned.mp4`, and checks freshness and
provenance. A fresh result is reused, so a successful task burns once.

The default response is:

```json
{
  "artifact_ready": true,
  "quality": "draft",
  "human_reviewed": false
}
```

This means the files are structurally complete and reproducible; it does not
claim that every sentence was professionally verified.

Professional users continue in the same workspace with:

```bash
openbbq review --workspace <ws> --to <lang>
```

The review UI supports source/target/timing edits, split/merge/insert/delete,
undo/redo, and review state. These human edits are authoritative and the agent
workflow does not overwrite them. The ASS can also be imported into Aegisub or
an editing application. Once every current cue has been reviewed, completion
may report `quality: "human-reviewed"` and `human_reviewed: true`.

Visual QA, sampled frames, text-position prediction, preset switching, and
automatic reburn are not part of the default workflow. Optional QA commands
remain available when a human explicitly requests them.

## Release Gate

CI must pass Ruff, ty, pytest, package builds, and isolated CLI smoke tests.
Before changing the default workflow, run the identical one-shot prompt in
independent workspaces across the supported harness/model matrix.

Release acceptance is based on:

- a useful 70–80 point draft with no systematic mistranslation or absurd error;
- 100% structural completeness and valid artifact provenance;
- translation batches of at most 20 cues with one active lease;
- consistent ordering and terminal behavior across harnesses;
- one export/burn pass;
- a successful glossary publication or an explicit non-blocking retry warning.

Per-cue 95% semantic accuracy is not an automated product guarantee. That level
of assurance belongs to the human review workflow and project-specific
evaluation.

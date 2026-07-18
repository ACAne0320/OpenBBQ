# Autonomous Subtitle Quality Loop v2

## Objective

Make the single-prompt workflow (for example, “turn this video into a bilingual
subtitle video”) produce an honestly verified final artifact without relying on
the agent to remember hidden cleanup or QA rules. The workflow must prevent
unresolved ASR uncertainty and decoder anomalies, require semantic review of
every translation with context, keep
diagnostic checks read-only, preserve meaning when a subtitle needs more room,
and prove which source video and subtitle were burned into the final MP4.

## Context

OpenBBQ's persisted `transcript@1`, `translation@1`, and `manifest@1` models are
strict compatibility contracts (`extra="forbid"`). New review state therefore
lives in versioned files under `.openbbq/`; the canonical transcript, cues, and
translation worksheet remain unchanged. Domain modules own review rules and
hashing. CLI commands own workspace I/O and user-facing results. Pipeline
commands consume verified state but do not duplicate review logic.

## Requirements

### 1. ASR uncertainty gate

- Add bounded `openbbq asr check`, `asr batch`, and `asr apply` commands.
- Surface every word occurrence below a conservative default probability
  threshold (`0.5`) with a stable occurrence id, timestamp, segment context,
  word probability, and neighboring word probabilities.
- Store decisions in `.openbbq/asr-review.json`, tied to the exact transcript
  content hash. A decision either accepts the transcription or supplies an
  exact phrase replacement and a reason.
- A replacement phrase must occur in the issue's source segment and include the
  uncertain word. Corrections are applied boundary-safely while cues are built.
- `segment` blocks when the current transcript has unresolved issues or a stale
  ASR review. Transcripts without word probabilities remain compatible and have
  no uncertainty issues.
- Detect repeated long segment runs, implausible word rates, and high-confidence
  named-entity conflicts with fetched title/author metadata. Decisions support
  `keep_first` and `drop` in addition to accept/replace.
- Preserve an available YouTube VTT as optional time-aligned evidence in ASR
  batches. Metadata and captions are evidence for an explicit decision, never
  an automatic correction.

### 2. Full-coverage contextual translation audit

- Add bounded `translate audit` and `translate audit-apply` commands.
- Rank cues that merit extra semantic attention first, including ASR-reviewed
  source text, near-budget translations, likely omissions, suspicious target
  script/Latin residue, and punctuation or intent mismatches.
- Every filled cue must be reviewed. Audit decisions are stored in
  `.openbbq/translation-audit.<lang>.json` and tied to the current cue plus one
  previous/next context hash, so changing one cue invalidates its own and
  adjacent reviews.
- `audit-apply` can accept the current translation or revise it, but always
  requires a concise reason. Revisions use the same worksheet integrity and
  budget checks as `translate apply`.
- Final export blocks while any current cue remains unaudited. The audit
  must not claim that deterministic heuristics prove semantic correctness.

### 3. Optional visual diagnostics

- Keep the QA report as an optional diagnostic that separates rendered-frame
  evidence from visual observation.
- A model that cannot receive images skips visual QA. This is not a delivery
  failure and does not reduce the assessed subtitle-content quality.
- A visual attestation, when available, is tied to the current MP4 and rendered
  frame hashes. Changing the video invalidates the attestation.
- The bundled skill must not run visual QA in the default one-shot flow or infer
  visual success from file existence alone.
- Select up to seven risk frames by boundaries, midpoint, source/target length,
  source CPS, and short duration when a user explicitly requests visual review.
- A visual result is advisory and never automatically selects `fansub-compact`
  or triggers export/burn rework.

### 4. Hard delivery gate

- `openbbq --json delivery check` is the sole final readiness decision. Any
  failed gate returns `ready:false` and a non-zero process exit.
- Aggregate ASR, fresh segmentation, deterministic translation checks,
  full-context audit, exact bilingual ASS events, burn provenance, and a
  non-empty burned artifact without duplicating the underlying domain rules.
- `status` reports the same delivery result. A successful command or existing
  MP4 alone never means delivery-ready.

### 5. Read-only translation checks

- `translate check` never writes `manifest.json` or invalidates later stages.
- `export` re-runs the same deterministic gate immediately before consuming the
  worksheet and records the translate stage as done before recording export.
- Re-running `translate check` after burn preserves completed export and burn
  states byte-for-byte.

### 6. Meaning-preserving target reflow

- `translate init` accepts target-side line-budget overrides. The bundled
  bilingual 1080p workflow uses up to two target lines before asking the agent
  to remove meaning.
- ASS export deterministically wraps target text according to the worksheet's
  snapshotted language profile and emits `\N`; source timing and source text do
  not change.
- A cue remains blocked when it exceeds the duration/CPS budget or cannot fit
  the configured line capacity. Reflow does not silently truncate text.

### 7. Burned-video provenance

- Successful burn records the MP4 hash plus exact source-video and ASS hashes in
  `.openbbq/artifacts.json` with producer `burn`.
- QA/status can distinguish a current burned artifact from a modified output or
  from an MP4 whose source video or ASS changed after burn.
- Existing ASS provenance and the deliberate `--allow-stale` draft escape hatch
  remain compatible.
- Segment output records transcript, ASR decision, and glossary hashes so an
  upstream correction cannot leave apparently fresh downstream subtitles.

## Non-Goals

- Embedding a translation LLM, OCR model, or vision model inside OpenBBQ.
- Automatically applying guessed replacements for uncertain speech without an explicit
  agent decision.
- Rewriting source cue timing during target-language reflow.
- Changing the existing public JSON schemas or silently accepting unknown keys.
- Requiring human interaction for the normal one-prompt agent workflow.

## Affected Surfaces

- CLI: `asr`, `qa`, and hard `delivery check` command groups; translation audit
  coverage and target profile options.
- Core: ASR review, translation audit, target wrapping, artifact freshness.
- Workspace: versioned `.openbbq/` sidecar readers/writers only.
- Pipeline: `segment`, `export`, and `burn` consume verified state.
- Skills/docs: bounded resolution, audit, and honest QA command sequence.

## Edge Cases

- Missing probabilities, repeated uncertain words, punctuation attached to a
  replacement, stale sidecars, multiple target languages, externally supplied
  subtitles, audio-only sources, and legacy workspaces without review files.
- Review writes must be atomic. Stale decisions must never be applied to a new
  transcript or changed target silently.
- A failed audit or QA must not corrupt a valid worksheet or completed output.

## Test Plan

- Unit-test issue extraction, stable ids, validation, phrase correction, risk
  ranking, per-cue hashes, target wrapping, and provenance freshness.
- CLI-test JSON contracts, bounded pagination, stale review behavior, and
  explicit next-action hints.
- Integration-test that unresolved ASR blocks segment, unaudited risk blocks
  export, a post-burn `translate check` is byte-for-byte read-only, two-line ASS
  preserves full target text, and modified MP4/source/ASS is detected.
- Run the complete pytest, Ruff, and ty suites after each vertical slice.

## Implementation Plan

1. Detect word and segment-level ASR failures with metadata/caption evidence.
2. Require full-coverage, neighbor-bound semantic translation decisions.
3. Keep risk-frame visual QA as an explicit, advisory diagnostic only.
4. Aggregate all facts into a non-zero hard delivery gate and status summary.
5. Keep deterministic checks read-only and every derived artifact hash-bound.
6. Update bundled skills/docs and run static, unit, and real-workspace regressions.

## Open Questions

None. Defaults are deliberately conservative and remain overridable at the CLI
without weakening final-delivery gates silently.

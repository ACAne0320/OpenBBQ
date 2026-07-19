# OpenBBQ Expert and Compatibility Workflow

Use this reference only for authentication, sandbox/GPU constraints, recovery,
legacy workspaces, or an explicitly requested manual atomic-command workflow.
New one-shot tasks should use `openbbq agent init/next/apply/finish` instead of
assembling their default flow from this document.

## YouTube Input

```bash
openbbq init --workspace workspaces/demo --glossary <name> '<youtube-url>'
openbbq auth status youtube
openbbq fetch --workspace workspaces/demo --auth youtube --max-height 1080
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq --json asr check --workspace workspaces/demo
openbbq glossary suggest --workspace workspaces/demo
openbbq --json glossary audit --workspace workspaces/demo --limit 20
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo --max-lines 2
```

If there is no glossary, remove `--glossary <name>`; if transcription reveals
names or terms, create or bind a glossary according to `glossary.md` before
continuing to `segment`.

If `auth status youtube` is not configured, try anonymous fetch first. If
anonymous fetch fails because cookies or bot checks are needed, run:

```bash
openbbq auth browser-login youtube
```

## Local File Input

```bash
openbbq init --workspace workspaces/demo --glossary <name> /path/to/video.mp4
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq --json asr check --workspace workspaces/demo
openbbq glossary suggest --workspace workspaces/demo
openbbq --json glossary audit --workspace workspaces/demo --limit 20
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo --max-lines 2
```

Local files skip `fetch`.

## Resolve ASR Uncertainty

When `asr check` is not ready, read a bounded page:

```bash
openbbq --json asr batch --workspace workspaces/demo --limit 20 --only-unresolved
```

After checking context, write reasoned decisions for both accepts and replacements:

```json
{
  "s3:w8": {"action": "accept", "reason": "Context and the glossary support this spelling"},
  "s7:w2": {
    "action": "replace",
    "find": "Sean Hongxiu",
    "replacement": "Sean Hongshu",
    "reason": "The end credit and earlier mention use Hongshu"
  },
  "a:repeat:205-221": {
    "action": "drop",
    "reason": "Seventeen identical segments span 30 seconds, confirming decoder hallucination"
  }
}
```

```bash
openbbq asr apply --workspace workspaces/demo asr-decisions.json
```

Repeat batch/apply until `asr check` is `ready: true`. Never accept blindly to
clear the gate. Then complete every `glossary audit` page: this second pass is
where the Agent catches semantic ASR errors regardless of confidence. Use
`asr amend` for context-specific errors without an issue id and `glossary apply`
for safe reusable terms/aliases, following `glossary.md`.

## Fill Translations

For many cues, first read a bounded batch of roughly 20 targets; do not load the
entire worksheet into model context:

```bash
openbbq --json translate batch zh --workspace workspaces/demo --from 1 --limit 20 --only-missing
```

Then write a batch JSON:

```json
{"1": "First translated line", "2": "Second translated line"}
```

Merge:

```bash
openbbq translate apply zh --workspace workspaces/demo targets.batch1.json
```

Multiple batches are fine; later batches only overwrite provided cue ids.

## Check, Risk Audit, Export, Burn

```bash
openbbq translate check zh --workspace workspaces/demo
openbbq --json translate audit zh --workspace workspaces/demo --coverage all --limit 20
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub --output out/zh.ass
openbbq burn --workspace workspaces/demo --subtitle out/zh.ass --output out/zh-burned.mp4
```

Clear `missing`, `over_budget`, `zero_budget`, `term_issues`, and
`quality_issues`, and require `ready: true`, before export.

`translate check` is read-only: it does not mutate the manifest or invalidate a
completed export/burn. When the risk audit returns pending cues, write reasoned
decisions:

```json
{
  "43": {"action": "revise", "target": "Garnt from Trash Taste went too.", "reason": "Restore the omitted show name"},
  "92": {"action": "accept", "reason": "Mew matches the creator name in context"}
}
```

```bash
openbbq translate audit-apply zh --workspace workspaces/demo translation-audit.json
```

Repeat check/audit until both return `ready: true`. `coverage: all` prioritizes
risk but requires every cue to be reviewed with neighboring context; changing a
cue invalidates adjacent context reviews. Minimum requirements:

- Compare source/target pairs in `translation.zh.json`; spot-check or read
  through the full worksheet.
- Proactively fix mistranslations, omissions, over-loose translations,
  unnatural target-language phrasing, tone mismatches, and broken context.
- Check whether names and terms stay consistent; for bilingual output, confirm
  source and target lines express the same meaning.
- Make revisions only with the Edit tool or a `{id: target}` batch JSON merged
  by `translate apply`.
- After revisions, rerun `translate check` and the affected audit; every gate
  must remain clear.

Only export and burn after both mechanical checks and quality self-review pass.

## Completion Checks

```bash
openbbq --json status --workspace workspaces/demo
openbbq translate check zh --workspace workspaces/demo
openbbq --json delivery check --workspace workspaces/demo --to zh
```

Confirm:

- Relevant manifest stages are complete, with no failed/stale/running state.
- `translate check` returns `ready: true`; the final flow did not use
  `--allow-quality-warnings` or `burn --allow-stale`.
- `delivery check` returns `ready: true`, proving that the bilingual ASS, source
  video, burned MP4, and stage provenance agree and that the MP4 is non-empty.

Visual QA is not part of the default one-shot flow. Only when the user explicitly
requests it and the current model has image input, optionally run:

```bash
openbbq --json qa render --workspace workspaces/demo
openbbq --json qa check --workspace workspaces/demo
openbbq qa attest --workspace workspaces/demo --result pass --reason '<actual observation>'
```

Visual results are advisory diagnostics only. They do not participate in
`delivery check`, automatically select `fansub-compact`, or trigger a reburn.
Models without image input should simply skip this optional step.

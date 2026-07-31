# OpenBBQ Usage

[README](../README.md) · [中文说明](usage.zh-CN.md)

OpenBBQ has two complementary paths:

- the default agent facade produces a structurally valid, editable AI subtitle
  draft from one prompt;
- expert commands and `openbbq review` support diagnosis and professional human
  finishing.

The expected automatic result is a useful 70–80 point draft. It is not a claim
that every cue has been professionally verified.

## Recommended: One-Prompt Agent Flow

With the packaged skill installed, the user-facing quickstart is just:

> Make this video into a bilingual Chinese-English subtitled video:
> https://www.youtube.com/watch?v=...

The agent owns the workflow below. The user does not need to name its internal
steps in the prompt.

Initialize once, optionally naming an existing glossary that is known to match
the video:

```bash
openbbq --json agent init 'https://www.youtube.com/watch?v=...' \
  --workspace workspaces/demo --to zh [--glossary <name>]
```

Then repeatedly request the authoritative next action:

```bash
openbbq --json agent next --workspace workspaces/demo
```

Handle the returned action as follows:

- `run_command`: execute the returned `argv` exactly;
- `review_source`: only when a structural ASR problem blocks segmentation,
  submit the complete bounded response to `agent apply`;
- `translate`: translate every selected ID and submit the response to
  `agent apply`;
- `finish`: execute its `argv`;
- `done`: deliver the returned subtitle and video paths.

For semantic actions:

```bash
openbbq --json agent apply --workspace workspaces/demo response.json
```

A normal run is:

```text
fetch → extract → transcribe → validate/segment
      → translate (≤20 cues per batch) → finish → done
```

There is no model-driven glossary-selection dialogue, risk-review queue, or
full-coverage AI audit. An explicit `--glossary` wins; otherwise a URL task
binds a stable author-and-target glossary after fetch discovers the author.
Repeated `next` calls return the same active lease.
`apply` requires the exact `batch_id`, `policy_hash`, and complete ID set, and
rejects stale source or worksheet content.

Translation may also submit:

- cue-scoped `source_fixes` for obvious ASR mistakes;
- reusable `glossary_updates`;
- a concise warning when the model is uncertain.

Ordinary low-confidence ASR words, display budgets, and glossary consistency
are advisory. Hard gates are limited to valid schemas and timing, complete IDs,
non-empty source/target content, current hashes, atomic updates, fresh
provenance, and non-empty final artifacts.

`finish` exports and burns once, using `fansub` for landscape or `mobile` for
portrait. It does not run visual QA or choose `fansub-compact`. A normal `done`
response includes:

```json
{
  "artifact_ready": true,
  "quality": "draft",
  "human_reviewed": false
}
```

## Check The Environment

Development setup:

```bash
uv sync --extra whispercpp --dev
uv run pytest
```

Runtime setup:

```bash
openbbq doctor
openbbq models list
openbbq models pull large-v3-turbo
```

Subtitle burning requires FFmpeg with the `ass` and `subtitles` filters.

## Sources, Authentication, And GPU

Quote URLs in shells such as zsh. The equivalent atomic YouTube flow is:

```bash
openbbq init --workspace workspaces/demo 'https://www.youtube.com/watch?v=...'
openbbq fetch --workspace workspaces/demo --max-height 1080
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
```

For a local file, skip `fetch`:

```bash
openbbq init --workspace workspaces/demo /path/to/video.mp4
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
```

If YouTube requests login or human verification:

```bash
openbbq auth browser-login youtube
openbbq fetch --workspace workspaces/demo --max-height 1080
```

Browser state is stored under `OPENBBQ_HOME`, which defaults to `~/.openbbq`.
Run browser authentication and network fetches in a normal user environment
when a restricted sandbox cannot access that state. For a public video where
saved authentication causes a 403, retry with `--no-auth`.

GPU is the default ASR path when supported. Native GPU/model-cache work should
run outside a restricted sandbox. Use CPU only after the outside-sandbox GPU
attempt actually fails:

```bash
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --cpu
```

## Glossaries

Use an existing glossary explicitly when its scope is known:

```bash
openbbq glossary list
openbbq glossary show <name>
openbbq --json agent init '<source>' --workspace workspaces/demo --to zh --glossary <name>
```

The explicit glossary always wins. Without one, a URL task waits for fetched
metadata, then derives a stable `author-<slug>-<target>-<hash>` glossary from
the author and target language. Later videos by the same author and target
language resolve to the same glossary, without relying on model judgment.
Local-file tasks without an explicit glossary keep only their task overlay.

During translation, OpenBBQ provides the bound glossary context and relevant
selected or neighboring terms. Reusable discoveries go to the task-local
`.openbbq/glossary-overlay.json`. Base glossary plus overlay are used during
the task; the global library is updated only after successful delivery.

Publication is conflict-safe and never overwrites an existing owner or value.
A conflict or permission error leaves the overlay intact and returns a
non-blocking retry warning.

## Expert ASR Diagnostics

The following commands are optional expert tools, not steps in the default
one-shot flow:

```bash
openbbq --json asr check --workspace workspaces/demo
openbbq --json asr batch --workspace workspaces/demo --limit 20 --only-unresolved
openbbq asr apply --workspace workspaces/demo asr-decisions.json
openbbq asr amend --workspace workspaces/demo asr-amendments.json
openbbq --json glossary suggest --workspace workspaces/demo
openbbq --json glossary audit --workspace workspaces/demo --offset 0 --limit 20
openbbq glossary apply --workspace workspaces/demo glossary-terms.json
```

Use them to diagnose a known ASR problem, migrate an old workspace, or run a
human-directed thorough pass. Low confidence alone does not require a
replacement, and a full transcript audit is not a default delivery gate.
Occurrence fixes must stay bounded; only a deliberately reusable glossary alias
may affect later matching text.

## Expert Translation Commands

The facade normally creates and manages the translation worksheet. The
equivalent atomic commands remain available:

```bash
openbbq translate init zh --workspace workspaces/demo --max-lines 2
openbbq --json translate batch zh --workspace workspaces/demo --from 1 --limit 20 --only-missing
openbbq translate apply zh --workspace workspaces/demo targets.json
openbbq translate check zh --workspace workspaces/demo
```

`translate check` reports missing/empty targets as errors and may report budget
or glossary findings as warnings. Warnings help an editor prioritize work; they
do not certify meaning and do not create a mandatory default review loop.

## Professional Review And Editing

Install the optional local review UI and open the generated workspace:

```bash
uv tool install 'openbbq[review]' --force
openbbq review --workspace workspaces/demo --to zh
```

The browser combines video or audio, waveform, cue timeline, source,
translation, timing, and review state. It supports source/target edits,
split/merge/insert/delete, undo/redo, and cue-level reviewed/flagged states.
Changes autosave to the canonical workspace data.

Human edits are authoritative. The automatic workflow does not overwrite them.
After editing, regenerate derived SRT/ASS and the burned video deliberately.
The ASS can also be imported into Aegisub or another editing application.

When every current cue has been confirmed, OpenBBQ may report:

```json
{
  "quality": "human-reviewed",
  "human_reviewed": true
}
```

That state records completed human review; it does not come from an automatic
semantic score.

## Export, Burn, And Delivery

Atomic export and burn commands remain useful after manual edits:

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual \
  --format ass --output out/zh.ass
openbbq burn --workspace workspaces/demo
openbbq --json delivery check --workspace workspaces/demo --to zh
```

Export records content hashes. Burn rejects a changed or untracked workspace
ASS and records the source-video, ASS, and final MP4 hashes. Delivery checks
schema validity, complete non-empty content, valid timing, artifact freshness,
and provenance. Semantic warnings do not claim or deny professional accuracy.

Long operations write progress to the workspace manifest:

```bash
openbbq --json status --workspace workspaces/demo
```

`qa render/check/attest` remain optional diagnostics when a human explicitly
requests visual inspection. They never run automatically, select a preset, or
trigger a reburn.

## ASS Presets

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset default
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub-compact
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset mobile
```

- `default`: normal 16:9 styling;
- `fansub`: a more prominent translated line and the default landscape choice;
- `fansub-compact`: an explicit smaller, raised bilingual stack;
- `mobile`: 9:16 styling with a larger bottom safe area.

Presets affect rendering, not translation meaning. OpenBBQ does not predict
where arbitrary text will appear in the video.

## Agent Installation And Output

Install the packaged skill:

```bash
openbbq skill install
```

Use `--agent claude`, `--agent codex`, or `--agent all` when a harness reads a
product-specific skill directory. `openbbq skill show` prints the installed
instructions.

Common workspace outputs:

- `transcript.json`: ASR transcript;
- `cues.json`: canonical source cues;
- `translation.<lang>.json`: editable translation worksheet;
- `.openbbq/agent-session.<lang>.json`: leases and translation evidence;
- `.openbbq/glossary-overlay.json`: task-local reusable glossary learning;
- `review.<lang>.json`: human review state;
- `.openbbq/artifacts.json`: export/burn provenance;
- `out/<lang>.srt` and `out/<lang>.ass`: subtitle exports;
- `out/<lang>-burned.mp4`: hard-subtitled video.

## Commands

```text
openbbq agent init/next/apply/finish
openbbq doctor
openbbq init
openbbq status
openbbq auth browser-login/status/clear
openbbq fetch
openbbq extract-audio
openbbq transcribe
openbbq segment
openbbq asr check/batch/apply/amend
openbbq translate init/batch/apply/check
openbbq review
openbbq glossary list/show/new/use/suggest/audit/apply
openbbq export
openbbq burn
openbbq qa render/check/attest
openbbq delivery check
openbbq models list/pull
```

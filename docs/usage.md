# OpenBBQ Usage

[README](../README.md) · [中文说明](usage.zh-CN.md)

This guide shows the full workflow for local video files and YouTube URLs.

## Check The Environment

Development setup:

```bash
uv sync --extra whispercpp --dev
uv run pytest
```

Runtime checks:

```bash
openbbq doctor
openbbq models pull large-v3-turbo
```

For subtitle burning, `doctor` should find FFmpeg with `ass` and `subtitles`
filters.

## YouTube Workflow

Quote URLs in shells such as zsh:

```bash
openbbq init --workspace workspaces/demo 'https://www.youtube.com/watch?v=...'
openbbq fetch --workspace workspaces/demo --max-height 1080
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
```

If YouTube asks for login or bot verification:

```bash
openbbq auth browser-login youtube
openbbq fetch --workspace workspaces/demo --max-height 1080
```

The browser auth profile is stored under `OPENBBQ_HOME`, defaulting to
`~/.openbbq`. That location must be writable. In restricted sandboxes, run
browser auth and `fetch` in a normal user environment, or set `OPENBBQ_HOME` to
a writable path. For public videos where saved auth causes a 403, retry with
`openbbq fetch --workspace workspaces/demo --no-auth`.

## Local File Workflow

For a local video, skip `fetch`:

```bash
openbbq init --workspace workspaces/demo /path/to/video.mp4
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
```

## ASR And GPU

`--gpu` is the default fast path when the selected ASR backend supports it. If a
native backend crashes or fails inside a restricted sandbox, rerun `transcribe`
outside the sandbox or retry with `--cpu`.

Before segmentation, resolve every low-confidence word and segment anomaly
(decoder repetition, impossible word rate, or title/author entity conflict):

```bash
openbbq --json asr check --workspace workspaces/demo
openbbq --json asr batch --workspace workspaces/demo --limit 20 --only-unresolved
openbbq asr apply --workspace workspaces/demo asr-decisions.json
```

Use accept/replace for words and entities, and keep_first/drop for repeated
segments. Every decision requires a reason; phrase replacements also include
the exact `find` phrase and `replacement`. When fetch preserved a YouTube VTT,
the batch includes overlapping reference text. Repeat until `asr check` returns
`ready: true`; `segment` blocks unresolved or stale decisions.

## Translate

Create a Chinese translation worksheet:

```bash
openbbq translate init zh --workspace workspaces/demo --max-lines 2
```

Read long worksheets in bounded batches so an Agent does not load the whole
video into context:

```bash
openbbq --json translate batch zh --workspace workspaces/demo --from 1 --limit 20 --only-missing
```

Write a JSON object mapping selected cue ids to translated text and merge it:

```bash
echo '{"1": "第一句译文", "2": "第二句译文"}' > targets.json
openbbq translate apply zh --workspace workspaces/demo targets.json
```

Validate it:

```bash
openbbq translate check zh --workspace workspaces/demo
```

The translation is complete only when `ready` is `true`. Resolve `missing`,
`over_budget`, `zero_budget`, `term_issues`, and `quality_issues`; export blocks
these warnings unless `--allow-quality-warnings` explicitly marks a draft.
`translate check` is read-only and never invalidates completed export/burn
stages. Bilingual ASS uses the worksheet's target line budget and inserts
deterministic `\N` wrapping without truncating target text.

Review the full-coverage semantic queue in bounded pages (risk first, with
neighbor context):

```bash
openbbq --json translate audit zh --workspace workspaces/demo --coverage all --limit 20
openbbq translate audit-apply zh --workspace workspaces/demo translation-audit.json
```

Each accept/revise decision requires a reason, and revisions include `target`.
Every cue requires an accept/revise decision. Editing one cue invalidates its
own and adjacent context reviews. Export blocks current unaudited items unless a deliberate draft uses
`--allow-quality-warnings`.

## Visual Review And Subtitle Editing

Install the optional local review UI, then open one target language:

```bash
uv tool install 'openbbq[review]' --force
openbbq review --workspace workspaces/demo --to zh
```

The browser keeps the video or audio, waveform, cue timeline, source text,
translation, timing, and review status in one workspace. Text edits autosave to
`cues.json` and `translation.<lang>.json`; split, merge, insert, delete,
undo/redo, and cue-level reviewed/flagged states are supported. SRT/ASS files
remain derived artifacts and are regenerated explicitly with `export`.

Once a `review.<lang>.json` exists, the matching target/bilingual export is
blocked until every cue is reviewed. Use `--allow-unreviewed` only when you
intentionally need a draft export.

## Export And Burn

Export bilingual ASS:

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --output out/zh.ass
```

Burn subtitles into the video:

```bash
openbbq burn --workspace workspaces/demo
```

Burning can take minutes. In JSON or non-TTY mode, stdout remains a single final
JSON object; progress is written to the workspace manifest. Poll it from another
terminal:

```bash
openbbq --json status --workspace workspaces/demo
```

Export records content hashes for cues, translation, review state, and the ASS.
Burn rejects a changed or untracked workspace ASS. `--allow-stale` is reserved
for an intentional manual draft; an explicitly supplied ASS outside the
workspace remains supported. Successful burn also records the final MP4 hash
and the exact source-video and ASS hashes.

## Completion QA

```bash
openbbq --json qa render --workspace workspaces/demo
openbbq --json qa check --workspace workspaces/demo
openbbq --json delivery check --workspace workspaces/demo --to zh
```

`qa render` defaults to up to seven boundary, midpoint, long-line, high-CPS,
and short-duration risk frames. `mechanical_status: pass` proves that the current non-empty MP4, source video,
ASS, and rendered frame hashes agree. It is not a visual observation. Only
after actually opening every returned frame should a vision-capable reviewer
run `qa attest --result pass|fail --reason ...`. A failure also requires one or
more structured `--issue` values. Without image input, leave
`visual_status: not_performed` and disclose that visual inspection was not
performed.

Final `delivery check` is a hard gate combining ASR, deterministic translation,
full-context semantic review, export/burn freshness, and visual QA. Any failure
returns `ready:false` with a non-zero exit code.

## ASS Presets

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset default
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub-compact
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset mobile
```

- `default`: normal 16:9 horizontal video.
- `fansub`: more prominent translated line.
- `fansub-compact`: a smaller, raised bilingual stack for lower-third conflicts
  and overlap remediation.
- `mobile`: 9:16 vertical video with a vertical canvas and larger bottom safe
  area.

The mobile preset changes rendering only. Use target-side `translate init`
overrides to set line capacity; content that still exceeds reading-speed or
line-capacity gates must be revised or resegmented.

## Agent Usage

Agents should use JSON output with the root flag before the command:

```bash
openbbq --json status --workspace workspaces/demo
openbbq --json export --workspace workspaces/demo --to zh --mode bilingual --format ass
```

Human Rich output is used only when stdout is an interactive TTY. In Codex, CI,
or other non-TTY runners, OpenBBQ emits compact JSON automatically even when
`--json` is omitted.

The workspace manifest records completed, running, and failed stages. Poll
`status` for progress during long tasks such as `fetch`, `transcribe`, and
`burn`.

Install the packaged agent skill. The default target is the shared agents
directory:

```bash
openbbq skill install
```

This writes to `~/.agents/skills/openbbq-subtitles/`. If your agent reads a
product-specific skills directory, use `openbbq skill install --agent claude` or
`openbbq skill install --agent codex`. To install all supported targets at once,
use `openbbq skill install --agent all`.

Installation always writes the English skill and its English `references/`.

Agents that read the skill directly from stdout can use `openbbq skill show`.

## Outputs

Common workspace outputs:

- `media/`: fetched or generated media.
- `transcript.json`: ASR output.
- `cues.json`: source subtitle cues.
- `translation.<lang>.json`: editable translation worksheet.
- `.openbbq/asr-review.json`: transcript-hash-bound uncertain-word decisions.
- `.openbbq/translation-audit.<lang>.json`: current-cue risk review decisions.
- `.openbbq/qa.json`: MP4/frame evidence and optional visual attestation.
- `review.<lang>.json`: cue-level human review state and reviewed-content hashes.
- `.openbbq/artifacts.json`: export provenance and content hashes used by burn.
- `.openbbq/review/`: local locks, checkpoints, waveform cache, and preview proxy.
- `out/<lang>.srt`: exported SRT subtitles.
- `out/<lang>.ass`: exported ASS subtitles.
- `out/<lang>-burned.mp4`: hard-subtitled video.

## Commands

```text
openbbq doctor
openbbq init
openbbq status
openbbq auth browser-login/status/clear
openbbq fetch
openbbq extract-audio
openbbq transcribe
openbbq segment
openbbq asr check/batch/apply
openbbq translate init/batch/apply/check/audit/audit-apply
openbbq review
openbbq glossary list/show/new/use/suggest
openbbq export
openbbq burn
openbbq qa render/check/attest
openbbq delivery check
openbbq models list/pull
```

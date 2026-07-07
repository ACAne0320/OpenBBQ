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
openbbq fetch --workspace workspaces/demo
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
```

If YouTube asks for login or bot verification:

```bash
openbbq auth browser-login youtube
openbbq fetch --workspace workspaces/demo
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

## Translate

Create a Chinese translation worksheet:

```bash
openbbq translate init zh --workspace workspaces/demo
```

Fill the `target` fields in `workspaces/demo/translation.zh.json` — either by
editing the file directly, or in batches: write a JSON object mapping cue id →
translated text and merge it (repeatable, ideal for long videos):

```bash
echo '{"1": "第一句译文", "2": "第二句译文"}' > targets.json
openbbq translate apply zh --workspace workspaces/demo targets.json
```

Validate it:

```bash
openbbq translate check zh --workspace workspaces/demo
```

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

## ASS Presets

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset default
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset mobile
```

- `default`: normal 16:9 horizontal video.
- `fansub`: more prominent translated line.
- `mobile`: 9:16 vertical video with a vertical canvas and larger bottom safe
  area.

The mobile preset changes rendering only. Long subtitles still need shorter
segments or tighter translations.

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

English is installed by default. Use `openbbq skill install --language zh-CN` for
the Chinese version. The full skill directory is copied, including `references/`.

Agents that read the skill directly from stdout can use `openbbq skill show`.

## Outputs

Common workspace outputs:

- `media/`: fetched or generated media.
- `transcript.json`: ASR output.
- `cues.json`: source subtitle cues.
- `translation.<lang>.json`: editable translation worksheet.
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
openbbq translate init/apply/check
openbbq glossary list/show/new/use/suggest
openbbq export
openbbq burn
openbbq models list/pull
```

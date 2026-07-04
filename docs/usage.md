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

## Local File Workflow

For a local video, skip `fetch`:

```bash
openbbq init --workspace workspaces/demo /path/to/video.mp4
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
```

## Translate

Create a Chinese translation worksheet:

```bash
openbbq translate init zh --workspace workspaces/demo
```

Fill every `target` field in:

```text
workspaces/demo/translation.zh.json
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

## ASS Presets

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset default
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset compact
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset mobile
```

- `default`: normal 16:9 horizontal video.
- `compact`: less bottom space.
- `fansub`: more prominent translated line.
- `mobile`: 9:16 vertical video with a vertical canvas and larger bottom safe
  area.

The mobile preset changes rendering only. Long subtitles still need shorter
segments or tighter translations.

## Agent Usage

Agents should use JSON output:

```bash
openbbq --json status --workspace workspaces/demo
openbbq --json export --workspace workspaces/demo --to zh --mode bilingual --format ass
```

The workspace manifest records completed, running, and failed stages. Poll
`status` for progress during long tasks such as `fetch`, `transcribe`, and
`burn`.

Codex-style agents should also read:

```text
skills/openbbq-subtitles/SKILL.md
```

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
openbbq translate init/check
openbbq glossary list/show/new/use/suggest
openbbq export
openbbq burn
openbbq models list/pull
```

---
name: openbbq-subtitles
description: Use OpenBBQ to make subtitles, translate subtitles, create bilingual subtitles/videos, burn ASS subtitles into video, or transcribe video/audio. Trigger on Chinese requests such as 制作字幕, 翻译字幕, 双语字幕, 双语视频, 视频翻译, 烧录字幕, 硬字幕, 生成字幕, and English requests such as make subtitles, translate subtitles, bilingual video, hard subtitles, burn subtitles, transcribe this video.
---

# OpenBBQ Subtitle Workflow

Use this skill when an agent is asked to produce subtitles or a subtitled video
with OpenBBQ. Prefer OpenBBQ's atomic CLI commands over ad hoc scripts.

## Operating Rules

- Use `openbbq --json ...` for automation unless the user explicitly wants the
  human terminal UI.
- Use `openbbq --json status --workspace <ws>` to resume after interruptions.
  The manifest is the source of truth for completed, running, and failed stages.
- Quote URL arguments in shells such as zsh:
  `openbbq init --workspace workspaces/demo 'https://www.youtube.com/watch?v=...'`.
- Long tasks (`fetch`, `transcribe`, `burn`) write progress to the workspace;
  poll `openbbq --json status --workspace <ws>` if you need progress outside
  the foreground command.
- Do not burn SRT for the default workflow. Export bilingual ASS and burn ASS.
- Pick an ASS preset only when the target surface needs it:
  `compact` for dense lower-third visuals, `fansub` for a more prominent
  bilingual style, and `mobile` for 9:16 vertical video.

## First-Time Environment

Run:

```bash
openbbq doctor
```

For final local transcription, use a cached Whisper model such as
`large-v3-turbo`. If missing, run:

```bash
openbbq models pull large-v3-turbo
```

For hard-subtitle burning, `doctor` must report ASS/subtitles ffmpeg filters.
On macOS, Homebrew `ffmpeg-full` is a practical libass-enabled build.

## Full YouTube Workflow

For YouTube URLs, anonymous fetch is tried first. If fetch fails with an
authentication or bot-check error, run the browser login once on a desktop UI:

```bash
openbbq auth browser-login youtube
```

Then run:

```bash
openbbq init --workspace workspaces/demo '<youtube-url>'
openbbq fetch --workspace workspaces/demo
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

Fill every `target` field in `workspaces/demo/translation.zh.json`, then:

```bash
openbbq translate check zh --workspace workspaces/demo
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --output out/zh.ass
openbbq burn --workspace workspaces/demo
```

For dense or vertical video, pass an ASS preset during export:

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset compact
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset mobile
```

Final artifacts:

- `out/zh.ass`: bilingual ASS subtitles.
- `out/zh-burned.mp4`: MP4 with hard-burned subtitles.

## Local File Workflow

For a local video, skip `fetch`:

```bash
openbbq init --workspace workspaces/demo /path/to/video.mp4
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

Then fill/check/export/burn exactly as in the YouTube workflow.

## Boundaries

- First-stage browser auth is for local desktop environments. Do not promise a
  headless server login flow.
- Font rendering can vary by platform. Current ASS defaults are tuned for local
  macOS rendering; commercial redistribution should verify font licensing.
- OpenBBQ does not grant copyright permission. Translating or burning subtitles
  into someone else's video can still require permission from the rights holder.

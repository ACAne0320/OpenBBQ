# OpenBBQ

[中文说明](README.zh-CN.md) · [Usage Guide](docs/usage.md)

**OpenBBQ** is a command-line tool for agent-driven video translation and subtitle production.

OpenBBQ provides composable tools for video download, audio extraction, ASR transcription, segmentation, translation, review, subtitle export, and subtitle burning.
It does not force one fixed pipeline. The goal is to let an agent choose the right workflow for each task.

## Why OpenBBQ?

In Chinese fansub and creator communities, the process of translating and subtitling foreign-language videos is often called "barbecue".
Raw untranslated material is "raw meat"; the translated, subtitled result is "cooked meat".

OpenBBQ is meant to be an open-source, open subtitle translation platform.

## Quick Start

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/), used to install the `openbbq` command and manage Python dependencies
- [ffmpeg](https://www.ffmpeg.org/), used for video download, audio/video merging, audio extraction, and video burning; subtitle burning also needs FFmpeg with `libass` support
- An ASR backend. OpenBBQ currently supports [whisper.cpp](https://github.com/absadiki/pywhispercpp) through its Python binding
- An ASR model. Models are not downloaded with the package. After installation, run `openbbq models list`, then explicitly run `openbbq models pull ...`
- A local desktop browser if the video platform requires login, human verification, or a browser challenge

## For Agent

```markdown
Read the [install guide](https://raw.githubusercontent.com/ACAne0320/OpenBBQ/main/docs/install-agent.md) and help me install [OpenBBQ](https://github.com/ACAne0320/OpenBBQ).
```

## Manual Install

```bash
uv tool install 'openbbq[whispercpp]'
openbbq doctor
openbbq models list
openbbq models pull large-v3-turbo
openbbq doctor
```

## Use

Human workflow:

```bash
openbbq init --workspace workspaces/demo 'https://www.youtube.com/watch?v=...'
cd workspaces/demo
openbbq fetch
openbbq extract-audio
openbbq transcribe --model large-v3-turbo --language en --gpu
openbbq segment
openbbq translate init zh
# fill in translations in translation.zh.json
openbbq translate check zh
openbbq export --to zh --mode bilingual --format ass --output out/zh.ass
openbbq burn
```

Agent workflow:

```bash
openbbq --json status --workspace workspaces/demo
```

Agents should use `--json` and pass the workspace explicitly with `-w`.
OpenBBQ also switches to compact JSON automatically when stdout is not a TTY,
which is expected in Codex, CI, and other agent runners.
For long-running tasks, poll the workspace state with `openbbq status`.
For subtitle tasks, install the packaged agent skill with `openbbq skill install`;
inspect it with `openbbq skill show`.

For local files, YouTube login, ASS presets, outputs, and command details, see
[docs/usage.md](docs/usage.md).

## Roadmap

- [ ] Windows and Linux support
- [ ] More ASR backends
- [ ] More video-platform authentication support
- [ ] Visual translation review for manual translators
- [ ] More subtitle editing and publishing workflows

## License

Apache-2.0. See [LICENSE](LICENSE).

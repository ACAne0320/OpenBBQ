# OpenBBQ

[中文说明](README.zh-CN.md) · [Usage Guide](docs/usage.md)

**OpenBBQ** is a command-line tool for agent-driven video translation and subtitle production.

OpenBBQ provides composable tools for video download, audio extraction, ASR transcription, segmentation, translation, review, subtitle export, and subtitle burning.
It does not force one fixed pipeline. The goal is to let an agent choose the right workflow for each task.

## Why OpenBBQ?

In Chinese fansub and creator communities, the process of translating and subtitling foreign-language videos is often called "barbecue".
Raw untranslated material is "raw meat"; the translated, subtitled result is "cooked meat".

OpenBBQ is meant to be an open-source, open subtitle translation platform.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/), used to install the `openbbq` command and manage Python dependencies
- [ffmpeg](https://www.ffmpeg.org/), used for video download, audio/video merging, audio extraction, and video burning; subtitle burning also needs FFmpeg with `libass` support
- An ASR backend. OpenBBQ currently supports [whisper.cpp](https://github.com/absadiki/pywhispercpp) through its Python binding
- An ASR model. Models are not downloaded with the package. After installation, run `openbbq models list`, then explicitly run `openbbq models pull ...`
- A local desktop browser if the video platform requires login, human verification, or a browser challenge

## Install

### Agent Install

```markdown
Read the [install guide](https://raw.githubusercontent.com/ACAne0320/OpenBBQ/main/docs/install-agent.md) and help me install [OpenBBQ](https://github.com/ACAne0320/OpenBBQ).
```

### Manual Install

```bash
uv tool install 'openbbq[whispercpp]'
openbbq doctor
openbbq models list
openbbq models pull large-v3-turbo
openbbq doctor
```

## Usage

For local files, YouTube login, ASS presets, outputs, and command details, see
the [Usage Guide](docs/usage.md).

For agent setup and the packaged OpenBBQ skill, see the
[Agent Install Guide](docs/install-agent.md) and the
[OpenBBQ Skill](src/openbbq/skills/openbbq-subtitles/SKILL.md).

## Roadmap

- [ ] Demo video
- [ ] Detailed documentation site
- [ ] Windows and Linux support
- [ ] More ASR backends
- [ ] More video-platform authentication support
- [ ] Agent-led discovery of videos worth translating
- [ ] Custom translation prompts
- [x] Visual translation review for manual translators
- [ ] More subtitle editing and publishing workflows

## License

Apache-2.0. See [LICENSE](LICENSE).

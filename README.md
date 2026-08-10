<p align="center">
  <img src="assets/brand/mascot-wave-512.png" alt="OpenBBQ mascot" width="160" />
</p>

# OpenBBQ

[Website](https://openbbq.acane.dev/en) · [Documentation](https://openbbq.acane.dev/en/docs) · [中文说明](README.zh-CN.md)

**OpenBBQ** turns a video URL or local file into an editable bilingual subtitle
draft and a burned video through one AI-agent prompt.

OpenBBQ provides a default `agent init/next/apply/finish` facade so different
agents can turn one simple prompt into an editable bilingual subtitle draft.
The default workflow aims for a reliable 70–80 point first pass: useful without
manual setup, but intentionally not presented as a professionally reviewed
final subtitle.

OpenBBQ keeps structural correctness, bounded translation batches, artifact
freshness, and one-time export/burn deterministic. The agent handles
translation and may correct an obvious ASR occurrence or learn a reusable
glossary term while translating. Low-confidence words, display budgets, and
glossary consistency are advisory, not mandatory review queues.

An explicit `--glossary` always wins. Otherwise, once a URL fetch identifies
the author, OpenBBQ binds a stable author-and-target glossary automatically.
Terms learned in the task overlay are published conflict-safely after delivery
and reused by later videos from the same author in that target language—without
asking the model to choose a glossary.

For professional work, open the same workspace with `openbbq review` or import
the exported ASS into Aegisub or an editor. Human edits are authoritative and
the automatic workflow does not overwrite them. Fine-grained ASR, glossary,
translation, export, and burn commands remain available as expert tools.

## Why OpenBBQ?

In Chinese fansub and creator communities, the process of translating and subtitling foreign-language videos is often called "barbecue".
Raw untranslated material is "raw meat"; the translated, subtitled result is "cooked meat".

OpenBBQ is an open-source, agent-native workflow for turning raw video into
editable bilingual subtitles and burned output.

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
Read the [install guide](https://openbbq.acane.dev/install-agent.md) and help me install [OpenBBQ](https://github.com/ACAne0320/OpenBBQ).
```

### Manual Install

```bash
uv tool install 'openbbq[whispercpp]'
openbbq doctor
openbbq models list
openbbq models pull large-v3-turbo
openbbq doctor
```

## Quickstart

After installing OpenBBQ and its agent skill, give the agent one simple prompt:

> Make this video into a bilingual Chinese-English subtitled video:
> https://www.youtube.com/watch?v=...

The agent should run the complete workflow and return the editable ASS plus the
hard-subtitled video. You do not need to describe ASR, batching, glossary
maintenance, export, or burning in the prompt.

The underlying agent entry point is:

```bash
openbbq --json agent init '<video-or-url>' --workspace workspaces/demo --to zh [--glossary <name>]
openbbq --json agent next --workspace workspaces/demo
```

Continue following `agent next` until it returns `done`. A normal task has only
mechanical commands, translation batches of at most 20 cues, one finish, and no
default visual QA.

For local files, YouTube login, professional review, ASS presets, outputs, and
command details, see the [Usage Guide](docs/usage.md).

For agent setup and the packaged OpenBBQ skill, see the
[Agent Install Guide](docs/install-agent.md) and the
[OpenBBQ Skill](src/openbbq/skills/openbbq-subtitles/SKILL.md).

## Roadmap

- [ ] Demo video
- [x] Detailed documentation site
- [ ] Windows and Linux support
- [ ] More ASR backends
- [ ] More video-platform authentication support
- [ ] Agent-led discovery of videos worth translating
- [x] Reproducible target-language translation briefs
- [x] Visual translation review for manual translators
- [ ] More subtitle editing and publishing workflows

## License

Apache-2.0. See [LICENSE](LICENSE).

# OpenBBQ Agent Install Playbook

This guide is for AI agents. The goal is to install OpenBBQ on the user's machine and only add the dependencies needed for the user's task.

## Principles

- Do not install system dependencies without asking.
- Do not download models without asking.
- Ask the questions that affect install size and install path first.
- Run `openbbq --json doctor`, then add only the missing pieces.
- Ask before installing system packages, downloading models, or writing browser login state.
- Make sure `OPENBBQ_HOME` and user caches are writable before browser auth,
  model downloads, and long media runs.
- Finish with a passing `openbbq doctor`.

## Ask First

Confirm these details before installing:

- Platform: macOS, Linux, or Windows.
- Input source: local video, local audio, YouTube, or another online video platform.
- Source language and target language.
- Model size: `base` for a quick preview, `large-v3` or `large-v3-turbo` for production subtitles.
- Whether the user needs hard-subtitle burning.
- Whether the machine has a GPU, and roughly what kind: Apple Silicon, NVIDIA, AMD / Intel, or CPU only.

## Bootstrap

Prefer the published package:

```bash
uv tool install openbbq
```

If the user has confirmed the default whisper.cpp backend:

```bash
uv tool install 'openbbq[whispercpp]'
```

Use a local repository install only for development or before a package has been published:

```bash
uv tool install '.[whispercpp]'
```

Then install the packaged agent skill. The default target is the shared agents
directory:

```bash
openbbq skill install
```

This copies the skill to `~/.agents/skills/openbbq-subtitles/`. If the user's
agent reads skills from a product-specific directory, install there instead:
Claude Code uses `openbbq skill install --agent claude`, and Codex uses
`openbbq skill install --agent codex`. To install all supported targets at once,
use `openbbq skill install --agent all`. Agents that read skills directly from
stdout can use `openbbq skill show`.

Installation always writes the English skill and its English `references/`, so
referenced workflow notes are available to the agent. Agents that need to
inspect packaged content directly can use `openbbq skill show`.

## Check The Environment

```bash
openbbq --json doctor
```

In Codex, CI, and other non-TTY runners, OpenBBQ may emit compact JSON even when
`--json` is omitted. Prefer `--json` explicitly when an agent parses output.

Use the output to decide what is missing:

- Python must be 3.12 or newer.
- If FFmpeg is missing, install an FFmpeg build with `libass`. Hard-subtitle burning needs the `ass` and `subtitles` filters.
- If the ASR backend is missing, install `pywhispercpp` by default. macOS wheels usually include Metal support. NVIDIA / Vulkan routes may need local toolkits and source builds.
- If the model is missing, ask the user to confirm the model size, then run `openbbq models pull <model>`.
- If YouTube requires login or human verification, run `openbbq auth browser-login youtube`.
- Browser auth and authenticated `fetch` need a writable `OPENBBQ_HOME`
  (default: `~/.openbbq`). In a restricted sandbox, run them in a normal user
  environment or set `OPENBBQ_HOME` to a writable path.
- If the agent skill is missing or outdated, run `openbbq skill install` or
  `openbbq skill install --force` as indicated by doctor.

## Models

List model sizes and cache state:

```bash
openbbq models list
```

Quick preview:

```bash
openbbq models pull base
```

Production subtitles:

```bash
openbbq models pull large-v3-turbo
```

If the user has trouble reaching Hugging Face, ask before using a mirror:

```bash
HF_ENDPOINT=https://hf-mirror.com openbbq models pull large-v3-turbo
```

Models are stored in OpenBBQ's global cache and reused across workspaces. They are not written into the video project directory.

If a native ASR backend fails or crashes with `--gpu` in a restricted sandbox,
rerun `transcribe` outside the sandbox or retry with `--cpu`.

## Finish

Run:

```bash
openbbq doctor
```

If the user needs subtitle burning, confirm that FFmpeg has both the `ass` and `subtitles` filters. Once the check passes, continue to the subtitle workflow.

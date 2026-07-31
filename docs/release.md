# Release

OpenBBQ publishes to PyPI from GitHub Actions with PyPI Trusted Publishing.

## One-time setup

1. In GitHub, create an environment named `pypi`.
2. In PyPI, open your account sidebar's **Publishing** page and add a pending trusted publisher for:
   - PyPI project name: `openbbq`
   - owner: `ACAne0320`
   - repository: `OpenBBQ`
   - workflow: `publish.yml`
   - environment: `pypi`

No PyPI token is stored in the repository. The workflow uses GitHub OIDC and `uv publish`.
The pending publisher creates the PyPI project on first publish; it does not reserve the name before that first successful publish.

## Publish a version

For changes to the default agent workflow, do not release from CI alone. Before
changing the version, run the same simple one-shot prompt in independent
workspaces:

> 帮我把这个视频制作成中英双语字幕视频。

Use a stable regression video such as
`https://www.youtube.com/watch?v=neK8ydl0Vlk` with the supported Pi and Codex
harness/model matrix. Record the session files and inspect both the workflow and
the resulting draft:

- the subtitle is a useful 70–80 point draft, with no systematic
  mistranslation, absurd translation, or repeated cue drift;
- source/target files, IDs, timing, leases, hashes, and final artifact
  provenance are structurally complete and valid;
- every translation batch has at most 20 cues and only one lease is active;
- each batch contains the target-language brief and relevant glossary context;
- ordinary low-confidence findings, display budgets, and glossary consistency
  remain advisory instead of triggering a full source review or full-coverage
  AI audit;
- the flow exports and burns once, then ends with `artifact_ready: true`,
  `quality: "draft"`, and `human_reviewed: false`;
- task glossary learning publishes safely (and reuses the stable
  author-and-target glossary on later matching videos) or returns a
  non-blocking structured retry warning;
- command ordering and terminal behavior are consistent across harnesses.

Do not treat per-cue 95% semantic accuracy as an automated release promise.
Professional assurance comes from `openbbq review` (or an external subtitle
editor) and project-specific human evaluation.

Only continue when CI and both harness runs pass.

Update the version in `pyproject.toml` and `src/openbbq/__init__.py`, then sync the lockfile:

```bash
uv lock
```

After the release commit is on `main`, create and push a matching tag:

```bash
git tag -a vX.Y.Z -m vX.Y.Z
git push origin vX.Y.Z
```

Tags beginning with `v` trigger `.github/workflows/publish.yml`.

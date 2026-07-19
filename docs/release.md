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
changing the version, run the same one-shot prompt in independent workspaces:

> 帮我把这个视频制作成中英双语字幕视频。

Use `https://www.youtube.com/watch?v=neK8ydl0Vlk` with both Pi +
DeepSeek-v4-pro high and Codex + GPT-5.6 Luna medium. Record the session files
and verify cue by cue:

- source and target correctness/alignment are each at least 95%, with an overall
  translation score of at least 80;
- every semantic translation batch has at most 20 cues and one active lease;
- each batch contains the target-language brief and glossary context;
- the flow uses risk-only review, burns once, and ends at `delivery_ready: true`;
- glossary publication succeeds or returns a non-blocking structured retry
  warning.

Only continue when CI and both harness runs pass.

Update the version in `pyproject.toml` and `src/openbbq/__init__.py`, then sync the lockfile:

```bash
uv lock
```

After the release commit is on `main`, create and push a matching tag:

```bash
git tag -a v0.0.1 -m v0.0.1
git push origin v0.0.1
```

Tags beginning with `v` trigger `.github/workflows/publish.yml`.

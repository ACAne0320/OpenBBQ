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

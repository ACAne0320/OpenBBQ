# Repository Guidelines

## Project Structure & Module Organization

OpenBBQ is currently documentation-first. The root `README.md` explains the product direction. Architecture, roadmap, and workflow notes live in `docs/`. Phase 1 backend and CLI requirements live in `docs/phase1/`; start with `docs/phase1/README.md`.

Source code has not landed yet. When adding Phase 1 code, follow the documented layout in `docs/phase1/Phase-1-Scope.md`:

```text
src/openbbq/      # Python package: cli, config, domain, engine, plugins, storage
tests/            # unit and integration tests
tests/fixtures/   # canonical project and plugin fixtures
```

## Build, Test, and Development Commands

There is no `pyproject.toml` or runnable CLI yet. Once the backend package is added, use the Phase 1 stack from `docs/phase1/Backend-CLI-Goals.md`:

- `uv sync` installs project dependencies.
- `uv run pytest` runs the test suite.
- `uv run ruff check .` lints Python code.
- `uv run ruff format .` formats Python code.
- `uv run openbbq validate <workflow>` validates a workflow without executing plugins.
- `uv run openbbq run <workflow>` executes a local workflow.

## Coding Style & Naming Conventions

Use Python for the Phase 1 backend. Format and lint with Ruff. Prefer small modules aligned to `config`, `domain`, `engine`, `plugins`, and `storage`. Workflow IDs and step IDs must use lowercase letters, digits, `_`, or `-`, matching `docs/phase1/Project-Config.md`.

Keep Markdown headings descriptive and sentence case where practical. Update docs when behavior, CLI flags, exit codes, config schema, or fixture paths change.

## Testing Guidelines

Use `pytest`. Required fixture families are documented in `docs/phase1/Project-Config.md`: `text-basic`, `text-pause`, `youtube-subtitle-mock`, plus mock text and media plugins. Cover the MVP acceptance scenarios from `docs/phase1/Phase-1-Scope.md`: run to completion, pause/resume, and abort. Add tests for configuration precedence, artifact diff behavior, retry/skip policies, and lock recovery as those features land.

## Commit & Pull Request Guidelines

This checkout does not include Git history, so no existing commit convention can be inferred. Use concise, imperative commit messages such as `Add phase 1 config loader` or `Document artifact diff contract`.

Pull requests should describe the user-facing change, list tests run, and link the relevant document or issue. Include CLI output examples when changing command behavior, JSON output, exit codes, or workflow state transitions.

## Security & Configuration Tips

Do not commit real media credentials, API keys, or private project data. Phase 1 fixtures should use deterministic mock plugins and local files only. Respect configuration precedence: CLI flags, environment variables, project config, then defaults.

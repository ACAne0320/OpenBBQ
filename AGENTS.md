# Repository Guidelines

## Project Structure & Module Organization

OpenBBQ now includes the Slice 1 Python backend and CLI. The root `README.md` explains the product direction and current CLI usage. Architecture, roadmap, and workflow notes live in `docs/`; Phase 1 contracts live in `docs/phase1/`, starting with `docs/phase1/README.md`.

Code and fixtures follow the documented layout in `docs/phase1/Phase-1-Scope.md`:

```text
src/openbbq/      # Python package: cli, config, domain, engine, plugins, storage
tests/            # unit and integration tests
tests/fixtures/   # canonical project and plugin fixtures
```

## Build, Test, and Development Commands

Use the Phase 1 stack from `pyproject.toml` and `docs/phase1/Backend-CLI-Goals.md`:

- `uv sync` installs project dependencies.
- `uv run pytest` runs the test suite.
- `uv run ruff check .` lints Python code.
- `uv run ruff format .` formats Python code.
- `uv run openbbq validate text-demo --project tests/fixtures/projects/text-basic` validates a workflow without executing plugins.
- `uv run openbbq run text-demo --project tests/fixtures/projects/text-basic` executes the text fixture and writes `.openbbq/` state.

## Coding Style & Naming Conventions

Use Python for the Phase 1 backend. Format and lint with Ruff. Prefer small modules aligned to `config`, `domain`, `engine`, `plugins`, and `storage`. Workflow IDs and step IDs must use lowercase letters, digits, `_`, or `-`, matching `docs/phase1/Project-Config.md`.

Keep Markdown headings descriptive and sentence case where practical. Update docs when behavior, CLI flags, exit codes, config schema, or fixture paths change.

## Testing Guidelines

Use `pytest`. Current fixtures are `text-basic` and `youtube-subtitle-mock`, plus deterministic mock text and media plugins. Slice 1 covers validation, run-to-completion, status, logs, artifact inspection, JSON output, and unsupported Slice 2 guardrails. Add tests for pause/resume, abort, artifact diff, retry/skip policies, and lock recovery as those features land.

## Commit & Pull Request Guidelines

This checkout does not include Git history, so no existing commit convention can be inferred. Use concise, imperative commit messages such as `Add phase 1 config loader` or `Document artifact diff contract`.

Pull requests should describe the user-facing change, list tests run, and link the relevant document or issue. Include CLI output examples when changing command behavior, JSON output, exit codes, or workflow state transitions.

## Security & Configuration Tips

Do not commit real media credentials, API keys, or private project data. Phase 1 fixtures should use deterministic mock plugins and local files only. Respect configuration precedence: CLI flags, environment variables, project config, then defaults.

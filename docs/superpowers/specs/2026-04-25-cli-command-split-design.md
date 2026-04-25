# CLI command split design

## Purpose

`src/openbbq/cli/app.py` is the only user-facing CLI entry point, but it now
combines parser construction, dispatch, output formatting, command handlers,
runtime settings commands, artifact lookup helpers, and subtitle quickstart
orchestration. This makes CLI behavior harder to maintain while desktop backend
work continues.

This cleanup splits CLI command groups into focused modules while preserving the
existing command-line contract.

## Scope

In scope:

- Split `src/openbbq/cli/app.py` into smaller modules under `src/openbbq/cli/`.
- Keep `openbbq.cli.app:main` as the console script entry point.
- Keep all existing command names, flags, defaults, exit codes, JSON payloads,
  human-readable output, and error mapping.
- Keep tests importing `main`, `_build_parser()`, and `_effective_log_level()`
  from `openbbq.cli.app`.
- Add focused characterization coverage only where it protects the split.

Out of scope:

- Adding, removing, or renaming CLI commands or flags.
- Changing API routes, application services, storage schema, plugin contracts,
  workflow execution, or runtime settings behavior.
- Moving subtitle output export into an application service.
- Rewriting argparse usage or replacing it with another CLI framework.
- Changing the `openbbq` console script target.

## Current code evidence

`src/openbbq/cli/app.py` is about 970 lines and currently owns:

- `main()`, `_build_parser()`, global option construction, logging setup, and
  `_dispatch()`.
- Project commands: `init`, `project list`, and `project info`.
- Workflow commands: `validate`, `run`, `resume`, `abort`, `unlock`, `status`,
  and `logs`.
- Artifact commands: `artifact list`, `artifact show`, `artifact diff`, and
  `artifact import`.
- Plugin commands: `plugin list` and `plugin info`.
- Runtime commands: `settings`, `auth`, `secret`, `models`, and `doctor`.
- API server command delegation through `api serve`.
- Subtitle quickstart commands: `subtitle local` and `subtitle youtube`.
- Shared output and error formatting helpers.
- Local project config/store helpers and artifact lookup helpers.

Relevant tests already exercise the CLI contract:

- `tests/test_cli_smoke.py`
- `tests/test_config_precedence.py`
- `tests/test_cli_integration.py`
- `tests/test_cli_control_flow.py`
- `tests/test_artifact_import.py`
- `tests/test_artifact_diff.py`
- `tests/test_cli_quickstart.py`
- `tests/test_runtime_cli.py`
- `tests/test_phase1_acceptance.py`
- Phase 2 CLI workflow tests for local video, remote video, translation, and
  ASR correction/segmentation.

## Design

Keep `src/openbbq/cli/app.py` as a thin entry point:

- `main(argv: list[str] | None = None) -> int`
- `_build_parser() -> argparse.ArgumentParser`
- `_global_options(defaults: bool) -> argparse.ArgumentParser`
- `_configure_logging(args: argparse.Namespace) -> None`
- `_effective_log_level(args: argparse.Namespace) -> int`
- `_dispatch(args: argparse.Namespace) -> int`

`app.py` should import command modules, call their parser registration functions
from `_build_parser()`, and call their dispatch functions from `_dispatch()`.
It should keep the top-level `version` command directly because that command is
small and depends only on `openbbq.__version__`.

Add internal CLI modules:

- `src/openbbq/cli/output.py`
  - Owns JSON/text output helpers and CLI error emission:
    - `emit(payload, json_output, text)`
    - `emit_error(error, json_output)`
    - `jsonable_content(content)`
  - Does not import command modules.
- `src/openbbq/cli/context.py`
  - Owns CLI-local project config, plugin registry, and project store helpers:
    - `load_config(args)`
    - `load_registry(args)`
    - `load_config_and_plugins(args)`
    - `project_store(config)`
  - Keeps command modules from repeating argparse-to-path conversion.
- `src/openbbq/cli/workflows.py`
  - Registers and handles `validate`, `run`, `resume`, `abort`, `unlock`,
    `status`, and `logs`.
  - Owns workflow event formatting.
- `src/openbbq/cli/artifacts.py`
  - Registers and handles `artifact list`, `artifact show`, `artifact diff`,
    and `artifact import`.
  - Owns artifact listing/showing/diff/import output assembly.
- `src/openbbq/cli/projects.py`
  - Registers and handles `init`, `project list`, and `project info`.
- `src/openbbq/cli/plugins.py`
  - Registers and handles `plugin list` and `plugin info`.
- `src/openbbq/cli/runtime.py`
  - Registers and handles `settings`, `auth`, `secret`, `models`, and
    `doctor`.
  - Owns interactive secret prompting for runtime/auth commands.
- `src/openbbq/cli/api.py`
  - Registers and handles `api serve`.
  - Keeps lazy import of `openbbq.api.server.main`.
- `src/openbbq/cli/quickstart.py`
  - Registers and handles `subtitle local` and `subtitle youtube`.
  - Owns CLI-specific subtitle output-file writing and latest-subtitle artifact
    lookup.

Each command module should expose two narrow functions:

- `register(subparsers, parents) -> None`
- `dispatch(args) -> int | None`

`dispatch()` returns `None` when the module does not handle the parsed command.
`app._dispatch()` checks modules in a fixed order and returns the first non-None
result. If no module handles the command, `_dispatch()` returns `2`, matching
the current fallback.

This keeps all command-specific behavior in command modules while preserving
one predictable parser and dispatch entry point.

## Dependency direction

The CLI package should keep a simple dependency direction:

- `app.py` imports command modules.
- command modules import `cli.output` and `cli.context` as needed.
- `cli.output` and `cli.context` do not import command modules or `app.py`.
- tests continue to import `openbbq.cli.app`.

This avoids circular imports and keeps command modules independently readable.

## Behavior preservation

The split must preserve:

- every current command path and argument name;
- default values from environment variables and hard-coded defaults;
- `argparse` parse failures returning their current exit codes through
  `main()`;
- JSON payload field names and values;
- text output strings;
- error envelope shape:
  `{"ok": false, "error": {"code": ..., "message": ...}}`;
- interactive prompting behavior for `auth set`, `secret set`, and `unlock`;
- lazy API server import behavior for `api serve`;
- subtitle quickstart generated workflow paths, force behavior, artifact lookup,
  and output file writing.

## Testing

Before moving behavior, add small characterization tests only where the current
contract is not already explicit. The implementation plan should decide the
smallest useful additions, such as:

- parser coverage for representative command groups; or
- direct import coverage for new CLI modules after they exist.

Existing tests are the main contract suite and must continue to pass:

- `uv run pytest tests/test_cli_smoke.py tests/test_config_precedence.py -q`
- `uv run pytest tests/test_cli_integration.py tests/test_cli_control_flow.py -q`
- `uv run pytest tests/test_artifact_import.py tests/test_artifact_diff.py -q`
- `uv run pytest tests/test_cli_quickstart.py tests/test_runtime_cli.py -q`
- `uv run pytest tests/test_phase1_acceptance.py -q`
- `uv run pytest tests/test_phase2_local_video_subtitle.py tests/test_phase2_remote_video_slice.py tests/test_phase2_translation_slice.py tests/test_phase2_asr_correction_segmentation.py -q`

Final verification must include:

- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`

## Acceptance criteria

- `src/openbbq/cli/app.py` is reduced to entry-point, parser orchestration,
  dispatch orchestration, global options, and logging helpers.
- Command-specific handlers live in focused modules under `src/openbbq/cli/`.
- Shared CLI output and context helpers live outside `app.py`.
- No command behavior changes are introduced.
- Existing tests importing `openbbq.cli.app.main`, `_build_parser()`, or
  `_effective_log_level()` continue to work.
- Full tests and Ruff checks pass.
- After merging this slice, update
  `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md` to
  mark the CLI split item done.

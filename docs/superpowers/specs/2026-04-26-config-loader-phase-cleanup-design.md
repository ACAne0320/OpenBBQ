# Config loader phase cleanup design

## Context

The project config loader is a core backend boundary. CLI commands, application services, API routes, engine tests, and fixture checks all rely on `openbbq.config.loader.load_project_config()` to load `openbbq.yaml`, normalize project-local paths, merge plugin paths, build Pydantic domain models, and validate workflow references.

The current implementation works, but `src/openbbq/config/loader.py` owns several phases at once:

- project root and config path resolution;
- YAML file reading and raw mapping validation;
- scalar helpers for mappings, strings, booleans, and paths;
- storage path normalization;
- plugin path loading from project config, `OPENBBQ_PLUGIN_PATH`, CLI extras, and built-in defaults;
- workflow, step, output, and input reference validation;
- Pydantic model construction and Pydantic error wrapping.

The file is about 375 lines and is harder to scan than the surrounding backend modules that have already been split by responsibility.

## Goals

- Keep `openbbq.config.loader.load_project_config()` as the stable public API.
- Preserve current config format, defaults, precedence, normalized path behavior, and CLI/API behavior.
- Preserve existing user-facing `ValidationError` messages where practical, especially messages currently asserted by tests.
- Split internal phases into focused modules so desktop-facing validation work can reuse smaller boundaries later.
- Keep Pydantic domain models as the final validated object boundary.
- Add characterization tests for the new internal boundaries before moving behavior.

## Non-goals

- Do not change `openbbq.yaml` schema.
- Do not add TOML or JSON config support.
- Do not move domain model validators out of `src/openbbq/domain/models.py`.
- Do not redesign plugin discovery or plugin duplicate handling.
- Do not add desktop-specific validation APIs in this cleanup slice.
- Do not change public import paths used by existing callers.
- Do not convert every private helper into public API.

## Proposed architecture

Keep `src/openbbq/config/loader.py` as the public orchestration facade.

Add focused internal modules under `src/openbbq/config/`:

- `raw.py`
  - Own YAML file loading and raw value helpers.
  - Export `load_yaml_mapping()`, `require_mapping()`, `optional_mapping()`, `require_nonempty_string()`, and `require_bool()`.
  - Keep malformed YAML, missing file, non-mapping file, and scalar type error messages compatible with the current loader.
- `paths.py`
  - Own config path resolution, project-relative path resolution, plugin path normalization, and plugin path merge precedence.
  - Export `resolve_config_path()`, `resolve_project_path()`, `load_plugin_paths()`, `normalize_plugin_paths()`, and `merge_paths()`.
  - Keep precedence as CLI extras, then `OPENBBQ_PLUGIN_PATH`, then project config paths, then built-in plugin root.
- `workflows.py`
  - Own workflow, step, output, and input reference parsing.
  - Export `build_workflows(raw_config: JsonObject) -> dict[str, WorkflowConfig]`.
  - Keep duplicate step ID, duplicate output name, invalid on-error/max-retries, and input selector validation messages compatible with the current loader.

`loader.py` will import these helpers and remain responsible for:

1. resolving `project_root`;
2. resolving the config path;
3. loading raw YAML;
4. checking config version;
5. building project metadata, storage config, plugin config, workflows, and final `ProjectConfig`;
6. wrapping Pydantic validation errors with `format_pydantic_error()`.

The helper modules are internal implementation modules. They improve readability and test locality but do not create a new public configuration API.

## Data flow

`load_project_config()` will continue to work as follows:

1. Normalize `project_root` with `Path(project_root).expanduser().resolve()`.
2. Resolve the config path from the optional argument or default `openbbq.yaml`.
3. Load YAML into a raw mapping.
4. Validate `version == 1`.
5. Parse the `project` table and build `ProjectMetadata`.
6. Parse storage paths relative to the project root and build `StorageConfig`.
7. Parse plugin paths from env and project config, merge with CLI extras and built-in defaults, then build `PluginConfig`.
8. Parse workflows and build immutable `WorkflowConfig`, `StepConfig`, and `StepOutput` models.
9. Build and return `ProjectConfig`.

The split should be a move and boundary cleanup, not a behavior rewrite.

## Error handling

`openbbq.errors.ValidationError` remains the user-facing exception for loader failures.

Pydantic validation failures continue to use `format_pydantic_error()` so callers do not receive raw Pydantic exceptions.

The following message families should remain stable:

- missing config file includes the resolved config path;
- malformed YAML mentions malformed YAML;
- non-mapping YAML mentions YAML mapping;
- version errors mention `Project config version must be 1.`;
- invalid storage/plugin path values mention the relevant field path;
- invalid workflow and step IDs mention `workflow id` or `step id`;
- duplicate step IDs and output names include the duplicate value;
- invalid forward/self/unknown input references preserve the current step and workflow context.

## Testing

Add focused characterization tests for new boundaries:

- `raw.load_yaml_mapping()` preserves missing file, malformed YAML, and non-mapping errors.
- `paths.resolve_config_path()` and plugin path normalization preserve project-relative resolution and de-duplication.
- `paths.load_plugin_paths()` preserves env-plus-config ordering.
- `workflows.build_workflows()` preserves duplicate step, invalid output, and input selector validation behavior.
- `loader.load_project_config()` still returns the same `ProjectConfig` shape for the canonical text fixture.
- Package layout import coverage includes the new config modules.

Run targeted config tests first, then the full suite:

- `uv run pytest tests/test_config.py tests/test_config_precedence.py tests/test_package_layout.py::test_new_package_modules_are_importable`
- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`

## Acceptance criteria

- `src/openbbq/config/loader.py` is reduced to orchestration and final model assembly.
- Raw YAML and scalar helpers live in `src/openbbq/config/raw.py`.
- Path and plugin path helpers live in `src/openbbq/config/paths.py`.
- Workflow parsing and input reference validation live in `src/openbbq/config/workflows.py`.
- Existing public callers continue importing `load_project_config()` from `openbbq.config.loader`.
- Existing tests pass, with new focused tests covering the extracted boundaries.
- The code-quality audit closure document marks config loader phase cleanup complete after implementation and verification.

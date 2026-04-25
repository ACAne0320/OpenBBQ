# Runtime settings boundary cleanup design

## Context

The runtime settings layer is part of the backend surface that desktop UI work will rely on for provider setup, cache location, model asset discovery, and diagnostic flows.

The current implementation works, but `src/openbbq/runtime/settings.py` owns several responsibilities at once:

- Resolving the user config path.
- Reading TOML from disk.
- Validating raw TOML tables, strings, provider names, provider types, secret references, and paths.
- Constructing Pydantic runtime models.
- Merging persisted user database provider profiles into file-backed provider profiles.
- Rendering runtime settings back to TOML.

`src/openbbq/runtime/models.py` already contains authoritative Pydantic validators for provider names, provider types, secret references, and runtime settings version. The loader duplicates parts of that validation to produce field-specific `ValidationError` messages while parsing raw TOML.

The goal of this cleanup is to make the settings boundary easier to understand before desktop UI integration, without changing behavior.

## Goals

- Keep the public runtime settings API stable:
  - `default_user_config_path()`
  - `load_runtime_settings()`
  - `runtime_settings_to_toml()`
  - `write_runtime_settings()`
  - `with_provider_profile()`
- Split raw file parsing and normalization out of `src/openbbq/runtime/settings.py`.
- Make `src/openbbq/runtime/settings.py` read as a small orchestration facade:
  - choose the config path,
  - load and parse file settings,
  - merge user database providers,
  - return validated `RuntimeSettings`.
- Keep Pydantic models as the final validation boundary for validated runtime objects.
- Preserve existing configuration format, defaults, provider precedence, and error messages where practical.
- Reuse the existing `openbbq.domain.base.model_payload()` helper for trivial public JSON payload methods.

## Non-goals

- Do not redesign runtime settings TOML.
- Do not change provider secret storage or resolution behavior.
- Do not change CLI output shapes.
- Do not change desktop API contracts from the existing backend readiness work.
- Do not introduce a new settings service or repository abstraction.
- Do not remove `public_dict()` methods from runtime models; keeping them avoids unnecessary CLI and application call-site churn.

## Proposed architecture

Add `src/openbbq/runtime/settings_parser.py`.

This module will own the raw parsing boundary:

- `load_toml_mapping(path: Path) -> JsonObject`
- `parse_runtime_settings(raw: JsonObject, *, config_path: Path, env: Mapping[str, str]) -> RuntimeSettings`
- private helpers for optional/required raw mappings, optional/required strings, user-path resolution, cache settings, model settings, and provider profile construction

`settings_parser.py` may keep a small amount of raw input validation before constructing Pydantic models. That validation exists to keep precise field-path errors for malformed TOML values, such as `providers.local.type` or `models.faster_whisper.cache_dir`. The Pydantic model validators remain the final authority for valid runtime model instances.

`src/openbbq/runtime/settings.py` will keep the public API and TOML writer. It will delegate TOML loading and file-backed settings parsing to `settings_parser.py`, then merge providers from `UserRuntimeDatabase`.

`src/openbbq/runtime/models.py` will keep existing model types and public methods. Repeated methods that only return `self.model_dump(mode="json")` will call `model_payload(self)` instead.

## Data flow

`load_runtime_settings()` will continue to work as follows:

1. Resolve the config path from the explicit argument or `OPENBBQ_USER_CONFIG`.
2. Read TOML into a raw mapping, returning an empty mapping when the file does not exist.
3. Parse file-backed settings into `RuntimeSettings`.
4. Read provider profiles from `UserRuntimeDatabase`.
5. Merge database providers over file providers, preserving the current precedence.
6. Return a new `RuntimeSettings` with the merged provider map.

The parser will not read from the user runtime database. That keeps parsing deterministic and directly testable.

## Error handling

Existing `openbbq.errors.ValidationError` remains the user-facing exception type for runtime settings load failures.

Malformed TOML still reports the config path.

Raw type errors still report the most specific available field path. Examples:

- `cache.root must be a string path.`
- `models.faster_whisper.default_model must be a non-empty string.`
- `providers.local must be a mapping.`
- `providers.local.api_key must use an env:, sqlite:, or keyring: secret reference.`

Pydantic validation failures will continue to be wrapped with `format_pydantic_error()` so callers receive a stable OpenBBQ validation error rather than a raw Pydantic exception.

## Testing

Add focused tests for the new parser boundary:

- Missing settings file still produces defaults through the public loader.
- Raw parser constructs runtime settings without reading or merging user database providers.
- Public loader still merges user database providers over file providers.
- Existing invalid version, provider type, provider name, literal API key, path, and TOML tests continue to pass.
- Public runtime model serialization methods return the same JSON-compatible payloads after switching to `model_payload()`.

Run the existing runtime test subset first, then the full suite:

- `uv run pytest tests/test_runtime_settings.py tests/test_runtime_context.py tests/test_runtime_cli.py tests/test_application_runtime_diagnostics.py`
- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`

## Acceptance criteria

- `src/openbbq/runtime/settings.py` no longer contains low-level raw TOML parsing helpers.
- `src/openbbq/runtime/settings_parser.py` contains the raw parsing and normalization helpers.
- Runtime settings public API and CLI behavior remain compatible with existing tests.
- Provider database profiles still override file-backed provider profiles when names collide.
- `public_dict()` methods no longer duplicate direct `model_dump(mode="json")` calls.
- Full verification passes.

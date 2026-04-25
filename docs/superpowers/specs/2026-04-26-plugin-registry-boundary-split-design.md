# Plugin registry boundary split design

## Purpose

`src/openbbq/plugins/registry.py` is the public plugin registry module, but it
currently owns several different concerns:

- Pydantic models for plugin, tool, invalid-plugin, and registry data.
- Plugin path discovery and manifest candidate selection.
- TOML manifest loading, validation, and conversion into `PluginSpec` and
  `ToolSpec`.
- Registry aggregation, duplicate plugin handling, invalid plugin collection,
  and warnings.
- Plugin module loading, builtin plugin module name resolution, entrypoint
  invocation, error normalization, and response validation.

This makes the plugin extension point harder to evolve for desktop-facing
metadata and diagnostics. The cleanup splits those responsibilities behind
small internal module boundaries while preserving the existing public imports
and runtime behavior.

## Scope

In scope:

- Split the implementation currently in `src/openbbq/plugins/registry.py` into
  focused modules under `src/openbbq/plugins/`.
- Keep `openbbq.plugins.registry` as the public compatibility module.
- Preserve the public `discover_plugins()` and `execute_plugin_tool()`
  functions.
- Preserve public model imports from `openbbq.plugins.registry`:
  `ToolSpec`, `PluginSpec`, `InvalidPlugin`, and `PluginRegistry`.
- Preserve `PluginRegistry.plugins`, `PluginRegistry.tools`,
  `PluginRegistry.invalid_plugins`, and `PluginRegistry.warnings` field names
  and value shapes.
- Preserve manifest parsing behavior, invalid plugin collection, duplicate
  plugin warning text, plugin execution error messages, and response
  validation behavior.
- Add focused characterization tests for the new module boundaries and
  compatibility imports.

Out of scope:

- Changing the plugin manifest schema or adding manifest fields.
- Changing `discover_plugins()` call sites.
- Changing workflow execution, plugin request payloads, or plugin response
  payloads.
- Changing API or CLI plugin list/info JSON shapes.
- Introducing a plugin cache or changing module import isolation.
- Rewriting built-in plugin implementations.

## Current code evidence

`src/openbbq/plugins/registry.py` currently combines:

- Model declarations:
  - `ToolSpec`
  - `PluginSpec`
  - `InvalidPlugin`
  - `PluginRegistry`
- Discovery:
  - `discover_plugins()`
  - `_candidate_manifests()`
  - `_load_manifest()`
- Manifest parsing and validation:
  - `_parse_plugin_manifest()`
  - `_parse_tool_manifest()`
  - `_parse_tool_inputs()`
  - `_parse_tool_outputs()`
  - `_parse_tool_runtime_requirements()`
  - `_parse_tool_ui()`
  - `_require_nonempty_string()`
  - `_require_string_list()`
  - `_format_schema_error()`
- Execution and module loading:
  - `execute_plugin_tool()`
  - `_load_plugin_module()`
  - `_builtin_module_name()`

The public module is imported broadly:

- `src/openbbq/cli/context.py` imports `PluginRegistry` and `discover_plugins`.
- `src/openbbq/application/plugins.py`, `application/workflows.py`, and
  `application/diagnostics.py` import `discover_plugins`.
- `src/openbbq/engine/validation.py`, `workflow/context.py`,
  `workflow/execution.py`, and `engine/service.py` import registry models.
- `src/openbbq/workflow/steps.py` imports `execute_plugin_tool`.
- Many tests import `discover_plugins`, `PluginRegistry`, or `ToolSpec` from
  `openbbq.plugins.registry`.

Relevant tests already cover behavior:

- `tests/test_plugins.py`
- `tests/test_application_projects_plugins.py`
- `tests/test_cli_integration.py`
- `tests/test_builtin_plugins.py`
- workflow and engine tests that call `discover_plugins()` before validation or
  execution
- runtime engine tests that monkeypatch `openbbq.workflow.steps.execute_plugin_tool`

## Design

Keep `src/openbbq/plugins/registry.py` as a narrow public compatibility module.
After the split, it should re-export models and delegate public functions:

- `ToolSpec`
- `PluginSpec`
- `InvalidPlugin`
- `PluginRegistry`
- `discover_plugins(plugin_paths)`
- `execute_plugin_tool(plugin, tool, request, redactor=None)`

Add focused internal modules:

- `src/openbbq/plugins/models.py`
  - Owns plugin registry Pydantic models:
    - `ToolSpec`
    - `PluginSpec`
    - `InvalidPlugin`
    - `PluginRegistry`
  - Imports plugin contract models and common domain base types.
  - Does not import discovery, manifest parsing, or execution modules.
- `src/openbbq/plugins/manifests.py`
  - Owns TOML manifest conversion and validation:
    - `parse_plugin_manifest(manifest_path, manifest)`
    - private helpers for tool parsing, inputs, outputs, runtime requirements,
      UI metadata, required fields, string lists, and JSON Schema errors
  - Imports `ToolSpec`, `PluginSpec`, and plugin contract models.
  - Does not read files and does not mutate a `PluginRegistry`.
- `src/openbbq/plugins/discovery.py`
  - Owns plugin path scanning and registry aggregation:
    - `discover_plugins(plugin_paths)`
    - private candidate-manifest discovery and manifest-file loading helpers
  - Reads TOML manifests from disk.
  - Calls `parse_plugin_manifest()`.
  - Owns duplicate plugin warning behavior and invalid plugin collection.
- `src/openbbq/plugins/execution.py`
  - Owns plugin module loading and tool invocation:
    - `execute_plugin_tool(plugin, tool, request, redactor=None)`
    - private module-loading and builtin-module-name helpers
  - Preserves unique module names for non-builtin plugins.
  - Preserves builtin plugin import by package module name.
  - Preserves redacted `PluginError` messages and `PluginResponse`
    validation.

The public `registry.py` module should import from these internal modules and
define no parsing, loading, or execution helpers of its own.

## Dependency direction

The plugin package should keep a simple dependency direction:

- `registry.py` imports from `models.py`, `discovery.py`, and `execution.py`.
- `discovery.py` imports `models.py` and `manifests.py`.
- `manifests.py` imports `models.py` and plugin contract models.
- `execution.py` imports `models.py` and plugin payload models.
- `models.py` does not import the other plugin implementation modules.

This avoids circular imports and keeps each implementation boundary readable in
isolation.

## Behavior preservation

The split must preserve:

- `discover_plugins([])` returning an empty `PluginRegistry`.
- Discovery from:
  - a direct plugin directory containing `openbbq.plugin.toml`;
  - a bundle directory with child plugin directories;
  - a manifest file path;
  - nonexistent paths returning no candidates.
- Manifest de-duplication by manifest path.
- Invalid manifest handling by appending `InvalidPlugin` records rather than
  raising.
- Duplicate plugin behavior:
  - first plugin wins;
  - later duplicate is ignored;
  - warning text remains the same.
- Manifest validation messages that existing tests inspect, including semantic
  version, runtime, entrypoint, duplicate tools, missing outputs, and JSON Schema
  details.
- Discovery not importing plugin code.
- `execute_plugin_tool()` behavior for:
  - missing entrypoint modules;
  - import failures;
  - non-callable entrypoints;
  - plugin function exceptions with optional redaction;
  - non-object responses;
  - invalid response payloads.

## Testing

Add focused tests before moving behavior:

- New module import coverage for:
  - `openbbq.plugins.models`
  - `openbbq.plugins.manifests`
  - `openbbq.plugins.discovery`
  - `openbbq.plugins.execution`
- Compatibility import coverage that asserts public objects still come from
  `openbbq.plugins.registry` and behave as before.
- Boundary characterization tests for:
  - `parse_plugin_manifest()` returning a `PluginSpec` without filesystem
    discovery;
  - `discover_plugins()` preserving invalid plugin collection and duplicate
    warning behavior;
  - `execute_plugin_tool()` preserving error normalization for a plugin
    exception and response validation.

Existing tests remain the main behavior contract and must continue to pass:

- `uv run pytest tests/test_plugins.py -q`
- `uv run pytest tests/test_application_projects_plugins.py tests/test_cli_integration.py -q`
- `uv run pytest tests/test_builtin_plugins.py tests/test_runtime_engine.py -q`
- `uv run pytest tests/test_engine_validate.py tests/test_workflow_bindings.py -q`

Final verification must include:

- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`

## Acceptance criteria

- `src/openbbq/plugins/registry.py` is a small public compatibility module.
- Models live in `src/openbbq/plugins/models.py`.
- Manifest parsing and validation live in `src/openbbq/plugins/manifests.py`.
- Discovery and registry aggregation live in `src/openbbq/plugins/discovery.py`.
- Plugin module loading and execution live in `src/openbbq/plugins/execution.py`.
- Existing imports from `openbbq.plugins.registry` continue to work.
- No public plugin, CLI, API, workflow, or storage behavior changes are
  introduced.
- Full tests and Ruff checks pass.
- After merging this slice, update
  `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md` to
  mark the plugin registry boundary split item done and set the next slice to
  built-in LLM helper extraction.

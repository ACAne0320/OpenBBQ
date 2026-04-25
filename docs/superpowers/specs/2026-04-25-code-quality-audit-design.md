# Code quality audit design

## Purpose

Before starting the desktop UI integration, record code-quality and robustness issues that would make the backend harder to extend, test, or maintain. This document is a fact-based audit register, not an implementation plan. Each item must point to code evidence and describe why the shape matters.

The immediate goal is to create a shared backlog for later cleanup. Follow-up work should use this register to create focused refactor plans with tests.

## Scope

In scope:

- Production code under `src/openbbq`.
- Test code under `tests`.
- Repeated logic, oversized modules, unclear boundaries, brittle adapters, weak error boundaries, and test maintainability problems.

Out of scope:

- Documentation structure outside this spec.
- Behavior changes.
- API contract changes unless a later plan explicitly approves them.
- Large rewrites that are not tied to a specific recorded issue.

## Audit method

Use a register with these fields:

- Issue: Short description of the quality problem.
- Evidence: Concrete files, functions, or repeated code patterns.
- Risk: Why this could make desktop UI integration or future backend work harder.
- Suggested direction: A conservative cleanup path that preserves behavior.
- Priority: `P1` for work that blocks or strongly affects desktop integration, `P2` for near-term maintainability, `P3` for lower-risk polish.

## Initial audit register

### P1: Repeated project context construction

Issue: Many application and API entry points repeat the same `load_project_config(...)` plus `ProjectStore(...)` construction logic.

Evidence:

- `src/openbbq/application/runs.py` repeatedly loads config and constructs `ProjectStore` in `create_run`, `get_run`, `list_project_runs`, `resume_run`, `_execute_run`, `_execute_resume`, and `_sync_run_from_workflow_state`.
- `src/openbbq/application/artifacts.py` has similar repeated config/store setup and a local `_store` helper.
- `src/openbbq/application/workflows.py`, `src/openbbq/application/plugins.py`, `src/openbbq/application/projects.py`, `src/openbbq/application/diagnostics.py`, and `src/openbbq/engine/service.py` each build project context independently.
- Tests repeat the same fixture project copy, config load, and store construction patterns.

Risk: Desktop API work will add more entry points. If project context setup stays scattered, config precedence, extra plugin paths, storage roots, and error mapping can diverge between CLI, API, and background execution.

Suggested direction: Introduce a small application-level project context helper that returns the resolved config and store from the same request fields already used today. Migrate call sites incrementally, starting with API-facing application services.

### P1: API route adapters duplicate request state and response mapping

Issue: API routes repeatedly retrieve app settings, validate active project assumptions, and rebuild API schemas from application models through `model_dump()`.

Evidence:

- `_settings(request)` appears in `src/openbbq/api/routes/quickstart.py`, `src/openbbq/api/routes/runs.py`, `src/openbbq/api/routes/artifacts.py`, and `src/openbbq/api/routes/workflows.py`.
- `src/openbbq/api/routes/runs.py` repeatedly returns `RunRecord(**run.model_dump())`.
- `src/openbbq/api/routes/workflows.py`, `src/openbbq/api/routes/projects.py`, `src/openbbq/api/routes/plugins.py`, `src/openbbq/api/routes/quickstart.py`, and `src/openbbq/api/routes/artifacts.py` use the same model-dump-and-rebuild adapter style.

Risk: Route-level glue will grow as the desktop UI adds endpoints. Repeating adapter code increases the chance of inconsistent validation, mismatched response fields, and avoidable route complexity.

Suggested direction: Add shared API helpers for active project settings and response adaptation, or align application return models with API schemas where contracts are intentionally identical. Keep route functions thin.

### P1: CLI module mixes too many responsibilities

Issue: `src/openbbq/cli/app.py` is the largest production module and combines command wiring, application calls, output formatting, artifact display/export, runtime settings commands, and subtitle quickstart orchestration.

Evidence:

- `src/openbbq/cli/app.py` is about 970 lines.
- The same module contains settings commands, artifact helpers, subtitle commands, output emitters, config loading, and project store construction.
- The subtitle CLI paths still perform local output handling while API quickstart currently creates jobs and returns run metadata.

Risk: The CLI remains important for backend verification while desktop UI work begins. A large mixed-responsibility module makes it harder to change application behavior without accidentally changing user-facing CLI output.

Suggested direction: Split command groups into small modules under `openbbq.cli`, keeping `app.py` as parser wiring and dispatch. Move reusable output and artifact rendering helpers behind narrow functions before making behavior changes.

### P1: Quickstart service combines workflow generation, template mutation, import, defaults, and run creation

Issue: `src/openbbq/application/quickstart.py` has grown into a broad orchestration module.

Evidence:

- The module defines request/result models, generated workflow models, template constants, local and YouTube job creation, workflow writing, YAML serialization, template loading, template mutation, provider defaults, and ID generation.
- Local subtitle job creation writes a temporary workflow, imports the source artifact, then writes the workflow again with the imported artifact selector.

Risk: Desktop UI will likely depend on quickstart flows. Mixing generation, persistence, defaults, and run dispatch makes it harder to test each step and reason about failure recovery.

Suggested direction: Keep public quickstart functions stable, but extract workflow-template rendering and generated-project persistence into dedicated helpers. Add tests around the extracted units before changing control flow.

### P2: Run execution has duplicated lifecycle paths and broad internal error handling

Issue: `_execute_run` and `_execute_resume` in `src/openbbq/application/runs.py` duplicate lifecycle state changes, config/store construction, workflow command execution, and failure marking.

Evidence:

- Both functions load config, construct `ProjectStore`, mark the run as running, execute a workflow command, catch `OpenBBQError`, catch generic `Exception`, then update final run state.
- Generic exceptions are converted to `internal_error` without a traceback or structured diagnostic record.

Risk: Background execution is central to desktop UX. Duplication between start and resume paths can cause status transitions, timestamps, latest event sequence, or error recording to drift.

Suggested direction: Extract a private lifecycle executor that accepts the workflow command as a callable. Keep broad exception-to-run-failure behavior for API robustness, but consider structured logging or a diagnostic artifact in a later plan.

### P2: Plugin registry has multiple responsibilities in one module

Issue: `src/openbbq/plugins/registry.py` handles plugin discovery, manifest parsing, schema validation, module loading, entrypoint execution, invalid plugin collection, and helper validation.

Evidence:

- The module is about 400 lines and includes models, registry lookup, tool execution, discovery, parsing, and validation helpers.
- It catches broad exceptions around module import and plugin execution to normalize plugin failures.

Risk: Plugin contracts are a key extension point. Keeping discovery, parsing, loading, and execution tightly coupled makes it harder to add desktop-facing plugin metadata or richer diagnostics without touching unrelated paths.

Suggested direction: Split manifest parsing and execution/loading boundaries into separate modules while keeping the public `discover_plugins` and registry API stable.

### P2: Built-in LLM plugins duplicate client and JSON-response plumbing

Issue: Transcript correction and translation plugins contain similar LLM invocation, chunking, glossary, completion-content, and JSON response parsing patterns.

Evidence:

- `src/openbbq/builtin_plugins/transcript/plugin.py` is about 600 lines and heavily uses `dict[str, Any]` segment payloads.
- `src/openbbq/builtin_plugins/translation/plugin.py` is about 490 lines and has similar LLM request and response handling.
- Both plugin areas also have local JSON helper modules.

Risk: LLM behavior changes, response validation, retry policy, or provider compatibility fixes may need to be applied twice. Large plugin modules also make it harder to isolate deterministic unit tests from provider-specific behavior.

Suggested direction: Extract shared LLM helpers inside `openbbq.builtin_plugins`, such as completion content extraction, JSON list parsing, chunking validation, and OpenAI-compatible client setup. Keep plugin tool contracts unchanged.

### P2: Runtime settings validation is split between model validators and loader helpers

Issue: Runtime provider validation lives partly in `src/openbbq/runtime/models.py` and partly in `src/openbbq/runtime/settings.py`.

Evidence:

- `ProviderProfile` validates provider type, base URL, environment variable, and keychain service in `runtime/models.py`.
- `runtime/settings.py` separately normalizes mappings, strings, paths, and provider configuration fields.
- CLI and application runtime commands call `public_dict()` methods that simply wrap `model_dump(mode="json")`.

Risk: Adding desktop settings screens will increase the number of configuration reads and writes. Split validation can make it unclear which layer owns normalization, defaults, and public serialization.

Suggested direction: Decide one boundary for raw settings parsing and one boundary for validated runtime models. Replace trivial `public_dict()` duplication with a shared serializer only if it improves call sites.

### P2: Config loader performs several phases in one file

Issue: `src/openbbq/config/loader.py` is responsible for YAML reading, path resolution, Pydantic model construction, workflow/step validation, plugin path handling, and input reference validation.

Evidence:

- The module is about 375 lines and contains both public loading behavior and low-level scalar/mapping validation helpers.

Risk: Desktop UI may need partial config inspection and better validation feedback. A monolithic loader makes it harder to expose precise errors or reuse only the parsing phase.

Suggested direction: Extract pure validation helpers or a small parser/normalizer layer after desktop-facing validation needs are clearer. Preserve current exception messages unless a plan explicitly updates tests and docs.

### P2: Storage database repository repeats serialization and upsert patterns

Issue: `src/openbbq/storage/database.py` repeats model serialization, JSON payload handling, and SQL upsert/read mapping patterns across run, workflow state, step run, event, artifact, and version records.

Evidence:

- Each record family has similar `model_dump(mode="json")`, JSON payload conversion, SQL write, and row-to-model reconstruction.

Risk: Desktop UI work is increasing storage reads and writes through the API. Repeated persistence patterns make schema changes more error-prone.

Suggested direction: Introduce small private helpers for common JSON serialization and upsert/read mapping where the SQL shape is already identical. Avoid abstracting away record-specific queries too early.

### P2: Test fixture setup is repeated across many files

Issue: Test files repeatedly define local `write_project(tmp_path, fixture_name)` helpers and local API client helpers.

Evidence:

- `write_project` appears in many test modules, including `tests/test_api_events.py`, `tests/test_engine_run_text.py`, `tests/test_phase1_acceptance.py`, `tests/test_cli_integration.py`, `tests/test_application_runs.py`, `tests/test_engine_rerun.py`, `tests/test_api_workflows_artifacts_runs.py`, `tests/test_engine_pause_resume.py`, `tests/test_cli_control_flow.py`, `tests/test_engine_abort.py`, `tests/test_runtime_engine.py`, and `tests/test_application_workflows.py`.
- `authed_client(project)` appears in API tests and is likely to grow as desktop API coverage grows.

Risk: Repeated fixture helpers make it harder to change canonical project setup, sidecar auth defaults, generated state cleanup, or fixture copy semantics in one place.

Suggested direction: Move common fixture-copy and API-client helpers into `tests/conftest.py` or a small `tests/helpers.py`. Migrate tests gradually to avoid obscuring behavior-specific setup.

### P2: Large test modules reduce failure locality

Issue: Some test modules are broad enough that unrelated behavior lives in the same file.

Evidence:

- `tests/test_builtin_plugins.py` is about 1,465 lines.
- `tests/test_storage.py`, `tests/test_engine_validate.py`, `tests/test_runtime_cli.py`, `tests/test_plugins.py`, and `tests/test_cli_quickstart.py` are also large compared with the focused production modules they exercise.

Risk: Large test modules make it slower to find the right test for a behavior change and increase merge friction during parallel backend and desktop work.

Suggested direction: Split only when touching related behavior. Prefer extracting shared setup first, then separate tests by plugin family or command group.

### P3: Dynamic payload typing is necessary at boundaries but sometimes leaks inward

Issue: `dict[str, Any]` and `Any` are common in plugin payloads, config parsing, artifact content, and workflow binding code.

Evidence:

- Boundary-heavy modules such as `builtin_plugins/transcript/plugin.py`, `builtin_plugins/translation/plugin.py`, `builtin_plugins/remote_video/plugin.py`, `plugins/registry.py`, `config/loader.py`, and `runtime/settings.py` use many dynamic payload helpers.

Risk: Dynamic typing is appropriate for plugin and JSON boundaries, but when it leaks into internal transformation logic, validation errors become later and less local.

Suggested direction: Do not eliminate dynamic payloads wholesale. Add typed internal models only where a payload is transformed in multiple steps or validated repeatedly, especially timed transcript segments and translation segment payloads.

### P3: File-not-found and missing-state errors are not uniformly domain-specific

Issue: Some repository APIs raise raw filesystem exceptions while application and API layers map selected errors.

Evidence:

- Storage repositories such as workflow and run readers can surface `FileNotFoundError`.
- API error handling maps `FileNotFoundError` to 404, but application and CLI paths may still expose lower-level errors depending on the caller.

Risk: Desktop flows need predictable error contracts. Raw filesystem exceptions can make errors inconsistent across CLI, API, and background operations.

Suggested direction: Record current behavior with targeted tests before changing it. Later, introduce domain-specific missing-resource errors at service boundaries rather than deep in all storage helpers.

## Follow-up planning order

Recommended order for later cleanup:

1. Extract shared test helpers for project fixtures and API clients. This lowers risk for subsequent refactors.
2. Add a project context helper and migrate application/API call sites.
3. Thin API route adapters around active project settings and response mapping.
4. Refactor run lifecycle duplication.
5. Split CLI command groups only after application/API boundaries are cleaner.
6. Tackle built-in plugin shared LLM helpers with focused tests.

## Testing expectations for future refactors

Each later implementation plan should include:

- Existing unit and integration tests relevant to the touched subsystem.
- New tests only where extraction reveals an untested edge or a bug is fixed.
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

## Acceptance criteria

- The audit register captures current code-quality findings with concrete evidence.
- Findings distinguish between desktop-readiness risks and lower-priority polish.
- The document does not authorize behavior changes by itself.
- The next step is a separate implementation plan, not direct refactoring.

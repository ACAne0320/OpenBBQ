# Code quality audit closure design

## Purpose

Close the code-quality audit register before continuing into broad desktop UI
integration. The earlier audit recorded backend maintainability risks with code
evidence. Several high-priority items have now been completed. This document
turns the remaining register into a tracked cleanup campaign with explicit
status, execution order, and completion criteria.

This is a tracking and sequencing spec. It does not authorize a single large
refactor. Each remaining cleanup must still get its own focused design, plan,
implementation branch, review, and verification.

## Scope

In scope:

- All items recorded in
  `docs/superpowers/specs/2026-04-25-code-quality-audit-design.md`.
- Status tracking for completed, remaining, and deferred audit items.
- A conservative execution order for the remaining cleanup slices.
- Shared rules for behavior preservation, testing, and tracking updates.

Out of scope:

- Direct code changes.
- Public API, CLI, config, storage, or plugin contract changes unless a
  subsequent focused spec explicitly approves them.
- Rewriting whole subsystems to satisfy style preferences.
- Treating dynamic JSON/plugin boundaries as a problem by themselves.

## Current status

### Done

These audit items are complete enough to mark as closed:

- **P2: Test fixture setup is repeated across many files**
  - Completed by shared test helpers in `tests/helpers.py`.
  - Remaining one-off helpers in media/plugin-heavy tests are intentional until
    those files are touched for related work.
- **P1: Repeated project context construction**
  - Completed by `src/openbbq/application/project_context.py` and migration of
    API-facing application services.
- **P1: API route adapters duplicate request state and response mapping**
  - Completed by `src/openbbq/api/context.py` and
    `src/openbbq/api/adapters.py`.
- **P2: Run execution has duplicated lifecycle paths and broad internal error
  handling**
  - Completed for lifecycle duplication by the private run lifecycle executor.
  - Structured diagnostics for unexpected background errors remain a future
    feature, not part of this audit closure.
- **P1: Quickstart service combines workflow generation, template mutation,
  import, defaults, and run creation**
  - Completed by `src/openbbq/application/quickstart_workflows.py` and the
    reduced quickstart orchestration facade.
- **P1: CLI module mixes too many responsibilities**
  - Completed by the CLI command split into focused modules under
    `src/openbbq/cli/`, with `src/openbbq/cli/app.py` retained as the thin entry
    point and parser/dispatch orchestrator.
- **P2: Plugin registry has multiple responsibilities in one module**
  - Completed by the plugin registry boundary split into focused model,
    manifest parsing, discovery, and execution modules under
    `src/openbbq/plugins/`, with `src/openbbq/plugins/registry.py` retained as
    the public compatibility module.
- **P2: Built-in LLM plugins duplicate client and JSON-response plumbing**
  - Completed by extracting shared OpenAI-compatible client setup, completion
    content extraction, indexed JSON response parsing, and segment chunking
    helpers into `src/openbbq/builtin_plugins/llm.py` while preserving
    transcript and translation plugin contracts.
- **P2: Runtime settings validation is split between model validators and
  loader helpers**
  - Completed by adding `src/openbbq/runtime/settings_parser.py` as the raw
    TOML parsing boundary, keeping `src/openbbq/runtime/settings.py` as the
    public load/write orchestration facade, preserving user database provider
    precedence, and reusing `model_payload()` for trivial runtime payload
    methods.
- **P2: Config loader performs several phases in one file**
  - Completed by splitting YAML/raw helpers into `src/openbbq/config/raw.py`,
    path and plugin path helpers into `src/openbbq/config/paths.py`, and
    workflow/step/input reference construction into
    `src/openbbq/config/workflows.py`, with `src/openbbq/config/loader.py`
    retained as the public `load_project_config()` orchestration facade.
- **P2: Storage database repository repeats serialization and upsert patterns**
  - Completed by extracting deterministic JSON serialization, nullable JSON
    serialization, row upsert, and record-json reconstruction into
    `src/openbbq/storage/database_records.py`, while keeping
    `ProjectDatabase` record-specific queries and column assignments explicit.

### Remaining

These items still need focused cleanup:

- **P2: Large test modules reduce failure locality**
- **P3: Dynamic payload typing is necessary at boundaries but sometimes leaks
  inward**
- **P3: File-not-found and missing-state errors are not uniformly
  domain-specific**

## Execution strategy

The remaining cleanup should happen as separate slices, in this order:

1. **Large test module split**
   - Split only files touched by the previous cleanup slices or files where
     failure locality clearly improves.
   - Prefer grouping by plugin family, CLI command group, or storage record
     family.
2. **Typed internal payloads**
   - Add typed internal models only where payloads are transformed repeatedly,
     especially transcript and translation segments.
   - Keep `dict[str, Any]` and JSON-like data at plugin, artifact, and config
     boundaries.
3. **Missing-state domain errors**
   - First add characterization tests for current `FileNotFoundError` and
     missing-state behavior.
   - Then introduce domain-specific errors at application/service boundaries
     where it improves CLI/API consistency.

## Per-slice rules

Each cleanup slice must:

- Preserve behavior by default.
- Keep public imports and CLI/API contracts stable unless that slice's spec
  explicitly approves a change.
- Add characterization tests before moving behavior.
- Add focused tests only for extracted boundaries or newly documented behavior.
- Avoid broad rewrites, global style churn, and unrelated formatting changes.
- End with:
  - `uv run pytest`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
- Update this tracking spec after the slice is merged.

## Deferred-with-reason policy

An audit item can be marked deferred only when a focused spec explains:

- what code evidence was rechecked;
- why implementing it now would add more risk than value;
- which future product or backend milestone should reopen it;
- what tests protect the current behavior meanwhile.

Deferred is not the same as ignored. Deferred items remain visible in this
tracking spec.

## Acceptance criteria

The audit register is considered fully closed when:

- Every original audit item is marked `Done` or `Deferred with reason`.
- Each `Done` item points to the implementation slice that closed it.
- Each `Deferred with reason` item has a focused rationale and a reopen trigger.
- `uv run pytest`, `uv run ruff check .`, and
  `uv run ruff format --check .` pass on `main`.
- No cleanup slice leaves untracked follow-up behavior changes hidden in code
  comments or undocumented follow-up notes.

## Next slice

The next implementation slice should be **Large test module split**. It should
split only files where failure locality clearly improves, starting with storage
tests that now cover both repository behavior and extracted database helpers.

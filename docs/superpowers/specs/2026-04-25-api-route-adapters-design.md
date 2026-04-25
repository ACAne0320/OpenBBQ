# API route adapter cleanup design

## Purpose

Before adding the desktop UI, keep the HTTP adapter layer small and consistent.
The current API routes already expose the required behavior, but several routes
repeat active-project validation and rebuild API response schemas from
application models inline. This cleanup centralizes that route glue without
changing public API behavior.

## Scope

In scope:

- Add shared API helpers for active project settings lookup.
- Add shared API helpers for adapting Pydantic application models into API
  schema models when the fields intentionally match.
- Migrate existing duplicated route code in `runs`, `artifacts`, `workflows`,
  `projects`, `plugins`, `quickstart`, and `runtime`.
- Add focused unit tests for the new helpers.
- Preserve all current endpoint paths, request models, response models, status
  codes, and error envelopes.

Out of scope:

- Changing API response shapes or adding new desktop endpoints.
- Moving business logic into the API package.
- Reusing API schema classes from the application layer.
- Refactoring application services, workflow execution, or storage behavior.

## Current code evidence

The audit register records the following duplication:

- Route-local `_settings(request)` functions exist in
  `src/openbbq/api/routes/quickstart.py`,
  `src/openbbq/api/routes/runs.py`,
  `src/openbbq/api/routes/artifacts.py`, and
  `src/openbbq/api/routes/workflows.py`.
- `src/openbbq/api/routes/projects.py`,
  `src/openbbq/api/routes/plugins.py`, and
  `src/openbbq/api/routes/runtime.py` inline the same
  `request.app.state.openbbq_settings` plus `project_root is None` validation.
- `src/openbbq/api/routes/runs.py` repeatedly maps storage run records with
  `RunRecord(**run.model_dump())`.
- `src/openbbq/api/routes/quickstart.py`,
  `src/openbbq/api/routes/projects.py`,
  `src/openbbq/api/routes/plugins.py`,
  `src/openbbq/api/routes/artifacts.py`, and
  `src/openbbq/api/routes/workflows.py` use the same
  model-dump-and-rebuild adapter style.

## Design

### Active project settings

Add `src/openbbq/api/context.py` with:

- `active_project_settings(request: Request) -> ApiAppSettings`

The helper reads `request.app.state.openbbq_settings`, checks that
`project_root` is configured, and raises the existing
`ValidationError("API sidecar does not have an active project root.")` when no
active project is available. Routes that need an active project use this helper
instead of local `_settings()` functions or inline checks.

The existing `app_settings(app: FastAPI)` helper remains in
`src/openbbq/api/app.py` for callers that only need raw app settings and do not
want active-project validation.

### Response adaptation

Add `src/openbbq/api/adapters.py` with:

- `api_model(schema_type: type[T], value: OpenBBQModel) -> T`
- `api_models(schema_type: type[T], values: Iterable[OpenBBQModel]) -> tuple[T, ...]`

These helpers use `schema_type.model_validate(value.model_dump())`. They are
only for intentional one-to-one field mappings between application/storage
models and API response schemas. They should not hide custom response assembly.
Routes still build explicit response data when field names differ, nested
content needs normalization, or only part of an application result is exposed.

This keeps route code concise while preserving the API schema boundary. The
application layer does not import API schemas.

### Route migration

Migrate duplicated active-project settings reads in:

- `src/openbbq/api/routes/runs.py`
- `src/openbbq/api/routes/artifacts.py`
- `src/openbbq/api/routes/workflows.py`
- `src/openbbq/api/routes/quickstart.py`
- `src/openbbq/api/routes/projects.py`
- `src/openbbq/api/routes/plugins.py`
- `src/openbbq/api/routes/runtime.py`

Migrate model-dump response adapters where fields intentionally match:

- Run records in `runs.py`
- Subtitle job data in `quickstart.py`
- Project init/current data in `projects.py`
- Plugin list data in `plugins.py`
- Artifact preview/export data in `artifacts.py`
- Workflow detail data in `workflows.py`

Do not migrate response assembly that has custom shape or content handling, such
as artifact show/version content normalization, artifact import version
selection, workflow event wrapping, and doctor result construction.

## Error handling

The active-project helper must preserve the exact existing validation error
message. FastAPI error handlers continue to map that `ValidationError` into the
existing API error envelope and HTTP 422 status.

The response adapter helpers should let Pydantic validation errors surface
during tests if an API schema and application model drift apart. They should not
catch or translate those errors.

## Testing

Add helper unit tests that cover:

- `active_project_settings()` returns configured API settings when
  `project_root` is present.
- `active_project_settings()` raises the existing `ValidationError` message when
  the sidecar has no active project.
- `api_model()` adapts a Pydantic model into an API schema with matching fields.
- `api_models()` returns a tuple of adapted schemas.

Run existing API tests to prove behavior preservation:

- `tests/test_api_workflows_artifacts_runs.py`
- `tests/test_api_events.py`
- `tests/test_api_projects_plugins_runtime.py`
- `tests/test_api_server.py`
- `tests/test_api_schemas.py`

Final verification must include:

- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`

## Acceptance criteria

- Route-local `_settings()` helpers are removed from migrated API route modules.
- Active-project validation in API routes goes through `active_project_settings()`.
- Repeated `Schema(**model.model_dump())` mappings are replaced where the mapping
  is intentionally one-to-one.
- No endpoint path, request model, response model, error envelope, or status code
  changes.
- Application modules do not import from `openbbq.api`.

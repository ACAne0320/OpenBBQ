# Quickstart workflow cleanup design

## Purpose

Generated subtitle quickstarts are part of the backend surface that the desktop
UI will depend on. The current application service preserves the needed
behavior, but it combines request models, runtime defaults, workflow template
rendering, generated project persistence, source artifact import, and run
creation in one module. This cleanup separates workflow generation from job
orchestration while keeping the public quickstart behavior stable.

## Scope

In scope:

- Extract quickstart workflow template rendering and generated project writing
  from `src/openbbq/application/quickstart.py`.
- Keep existing public quickstart entry points stable:
  `create_local_subtitle_job()`, `create_youtube_subtitle_job()`,
  `write_local_subtitle_workflow()`, and `write_youtube_subtitle_workflow()`.
- Keep CLI and API behavior unchanged.
- Add focused tests for the extracted workflow generation boundary.
- Preserve the existing generated project layout under
  `.openbbq/generated/<template-id>/<run-id>/openbbq.yaml`.

Out of scope:

- Changing subtitle workflow template YAML content.
- Changing quickstart request or response schemas.
- Moving CLI subtitle execution and output export into a shared application
  service.
- Changing run creation, background execution, artifact storage, or runtime
  settings behavior.
- Adding new quickstart templates or desktop-only endpoints.

## Current code evidence

`src/openbbq/application/quickstart.py` currently owns multiple responsibilities:

- Pydantic models for generated workflows and subtitle job requests/results.
- Runtime default lookup through `load_runtime_settings()`.
- Local subtitle job orchestration:
  1. write a generated local workflow with placeholder selector
     `project.art_source_video`;
  2. import the source video artifact into the generated project;
  3. rewrite the generated workflow with the imported artifact selector;
  4. create a run for the generated workflow.
- YouTube subtitle job orchestration:
  1. write a generated YouTube workflow;
  2. create a run for the generated workflow.
- Generated project directory creation and YAML writing.
- Workflow template loading from `openbbq.workflow_templates.*`.
- Template mutation for remote video download, audio extraction, ASR,
  correction, and translation step parameters.
- Generated run id creation.

The module is currently depended on at two public levels:

- API routes call `create_local_subtitle_job()` and
  `create_youtube_subtitle_job()`.
- CLI subtitle commands call `write_local_subtitle_workflow()` and
  `write_youtube_subtitle_workflow()` directly before executing the workflow and
  writing the output subtitle file.

This means the cleanup must preserve both public layers for now.

## Design

Add a focused workflow generation module:

- `src/openbbq/application/quickstart_workflows.py`

The new module owns:

- `GeneratedWorkflow`
- quickstart workflow constants:
  - `YOUTUBE_SUBTITLE_TEMPLATE_ID`
  - `YOUTUBE_SUBTITLE_WORKFLOW_ID`
  - `DEFAULT_YOUTUBE_QUALITY`
  - `LOCAL_SUBTITLE_TEMPLATE_ID`
  - `LOCAL_SUBTITLE_WORKFLOW_ID`
- public workflow writing functions:
  - `write_youtube_subtitle_workflow(...) -> GeneratedWorkflow`
  - `write_local_subtitle_workflow(...) -> GeneratedWorkflow`
- private template loading and rendering helpers:
  - `_youtube_subtitle_config(...)`
  - `_local_subtitle_config(...)`
  - `_load_youtube_subtitle_template()`
  - `_load_local_subtitle_template()`
  - `_load_template(...)`
  - `_steps_by_id(...)`
  - `_set_optional(...)`
  - `_new_run_id()`

Keep `src/openbbq/application/quickstart.py` as the orchestration facade. It
owns:

- `SubtitleJobResult`
- `LocalSubtitleJobRequest`
- `YouTubeSubtitleJobRequest`
- `create_local_subtitle_job(...)`
- `create_youtube_subtitle_job(...)`
- runtime default lookup for faster-whisper settings
- artifact import and run creation orchestration

To preserve current imports, `quickstart.py` should re-export the generated
workflow model, constants, and workflow writing functions from
`quickstart_workflows.py`. This keeps existing CLI, API tests, and any local
callers stable while making the implementation boundary explicit.

The local job flow should remain unchanged. It can still call
`write_local_subtitle_workflow()` twice with the same generated run id: once to
create a generated project that can receive the imported source video, and once
to persist the final workflow with the imported artifact selector.

## Behavior preservation

This cleanup must preserve:

- Generated YouTube workflows are written to
  `.openbbq/generated/youtube-subtitle/<run-id>/openbbq.yaml`.
- Generated local workflows are written to
  `.openbbq/generated/local-subtitle/<run-id>/openbbq.yaml`.
- `run_id` is generated when omitted and reused when provided.
- `write_youtube_subtitle_workflow()` returns workflow id `youtube-to-srt`.
- `write_local_subtitle_workflow()` returns workflow id `local-to-srt`.
- Optional YouTube `browser` and `browser_profile` parameters are omitted from
  rendered YAML when their values are `None`.
- Optional LLM `model` parameters are omitted from correction and translation
  steps when the value is `None`.
- Runtime faster-whisper defaults are still applied by job creation functions
  when request-level ASR settings are omitted.
- Local subtitle job creation still imports the source video and stores the
  imported artifact selector in the final generated workflow.
- API quickstart routes still return the same response shape.
- CLI subtitle commands still run generated workflows and write output files as
  before.

## Testing

Add focused coverage around the extracted workflow generation boundary:

- A test imports `write_youtube_subtitle_workflow()` from
  `openbbq.application.quickstart_workflows` and verifies generated project
  path, workflow id, rendered URL, language parameters, and omitted optional
  fields when optional values are `None`.
- A test imports `write_local_subtitle_workflow()` from
  `openbbq.application.quickstart_workflows` and verifies generated project
  path, workflow id, video selector, ASR parameters, and translation target.
- Existing tests continue to import through `openbbq.application.quickstart` to
  prove compatibility re-exports stay intact.

Run focused tests after the extraction:

- `uv run pytest tests/test_application_quickstart.py -q`
- `uv run pytest tests/test_cli_quickstart.py -q`
- `uv run pytest tests/test_api_projects_plugins_runtime.py -q`

Final verification must include:

- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`

## Acceptance criteria

- Workflow template rendering and generated project writing live in
  `src/openbbq/application/quickstart_workflows.py`.
- `src/openbbq/application/quickstart.py` no longer imports
  `importlib.resources`, `datetime`, `uuid4`, or `yaml` directly.
- `src/openbbq/application/quickstart.py` remains the public orchestration
  facade for quickstart job creation.
- Existing public imports from `openbbq.application.quickstart` continue to
  work.
- CLI and API quickstart behavior is unchanged.
- Tests cover both the new workflow generation module and compatibility through
  the existing quickstart facade.

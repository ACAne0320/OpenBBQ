# Large test module split design

## Context

The code-quality audit identifies large test modules as a P2 maintainability
risk because they reduce failure locality and increase merge friction before
desktop UI work. The current test size check shows two clear targets:

- `tests/test_builtin_plugins.py` is about 1,465 lines and mixes discovery,
  glossary, remote video, translation, transcript, subtitle, ffmpeg, and
  faster-whisper behavior.
- `tests/test_storage.py` is about 507 lines and now mixes database record
  helper tests, migration/table checks, artifact content, repository round
  trips, storage model tests, and `ProjectStore` behavior.

Other large files, such as config, engine validation, runtime CLI, plugin
registry, and CLI quickstart tests, are closer to 300-365 lines and currently
exercise cohesive command or subsystem surfaces. Splitting them now would add
more churn than locality.

## Goals

- Split only the modules where the boundaries are obvious and failure locality
  materially improves.
- Preserve every existing test assertion and behavior.
- Keep test helper code reusable without making helper modules collect as test
  files.
- Keep filenames aligned with the subsystem or plugin family under test.
- Avoid production code changes.
- Leave the full suite count and behavior unchanged except for pytest module
  names in output.

## Non-goals

- Do not refactor production code.
- Do not rewrite tests to change style or coverage.
- Do not introduce new fixtures unless they remove shared setup duplication
  created by the split.
- Do not split every file above an arbitrary line-count threshold.
- Do not rename tests for aesthetic reasons unless a name becomes misleading
  after the move.
- Do not change fixture paths, artifact shapes, plugin payloads, or runtime
  provider behavior.

## Proposed architecture

Split `tests/test_storage.py` into focused modules:

- `tests/test_storage_database_records.py`
  - SQLite table initialization, database record helper behavior, direct
    SQLite row facts, and `ProjectDatabase` upsert behavior.
- `tests/test_storage_artifact_content.py`
  - Artifact content store round trips for JSON, text, bytes, and copied files.
- `tests/test_storage_repositories.py`
  - Repository and `ProjectStore` round trips, event reads, artifact reads,
    ID generator injection, and persisted content behavior.
- `tests/test_storage_models.py`
  - Storage Pydantic model serialization and internal tuple behavior.

Keep `tests/test_storage_runs.py` as the dedicated run-record module created by
earlier work.

Split `tests/test_builtin_plugins.py` into plugin-family modules:

- `tests/builtin_plugin_fakes.py`
  - Shared fake OpenAI clients, fake downloaders, fake ffmpeg runner, and fake
    faster-whisper objects. This helper file intentionally does not start with
    `test_`.
- `tests/test_builtin_plugin_discovery.py`
  - Built-in plugin path discovery and shared project fixture setup.
- `tests/test_builtin_glossary.py`
  - Glossary replacement behavior.
- `tests/test_builtin_remote_video.py`
  - Remote video download behavior and dependency/error handling.
- `tests/test_builtin_translation.py`
  - Translation parameter validation, translation, batching, runtime provider,
    malformed JSON, and QA behavior.
- `tests/test_builtin_transcript.py`
  - Transcript parameter validation, correction, segmentation, runtime
    provider, and chunk mismatch behavior.
- `tests/test_builtin_subtitle.py`
  - Subtitle export behavior.
- `tests/test_builtin_ffmpeg.py`
  - FFmpeg command construction.
- `tests/test_builtin_faster_whisper.py`
  - Faster-whisper transcription backend, cache directory, and optional
    decoder controls.

Remove the original monolithic `tests/test_builtin_plugins.py` and
`tests/test_storage.py` once their tests have been moved.

## Testing

Use characterization before and after the split:

1. Run the current monolithic targets:
   - `uv run pytest tests/test_builtin_plugins.py tests/test_storage.py tests/test_storage_runs.py -q`
2. Split the files without changing assertions.
3. Run the new grouped targets:
   - `uv run pytest tests/test_builtin_*.py tests/test_storage_*.py -q`
4. Run full verification:
   - `uv run pytest`
   - `uv run ruff check .`
   - `uv run ruff format --check .`

## Acceptance criteria

- `tests/test_builtin_plugins.py` is removed and replaced with focused
  plugin-family modules plus a non-collected helper module.
- `tests/test_storage.py` is removed and replaced with focused storage modules.
- All moved tests keep their existing assertions and behavior.
- New helper modules are not collected as pytest test modules.
- The audit closure document marks the large test module split complete and
  documents why the remaining 300-line cohesive files are left in place for
  now.
- Full pytest and Ruff verification pass on the merged result.

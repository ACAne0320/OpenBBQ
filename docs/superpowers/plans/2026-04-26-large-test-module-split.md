# Large Test Module Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the largest monolithic test modules into focused files without changing test behavior.

**Architecture:** Move existing tests into subsystem- and plugin-family modules. Use one non-collected helper module for shared built-in plugin fakes. Do not change production code or assertions.

**Tech Stack:** Python 3.11, pytest, Ruff, uv.

---

## File Structure

- Delete `tests/test_storage.py` after moving its tests.
- Create `tests/test_storage_database_records.py`
  - `_sqlite_table_names()`, database record helper tests, project/user table
    initialization tests, direct SQLite row fact tests, and workflow-state
    upsert behavior.
- Create `tests/test_storage_artifact_content.py`
  - Artifact content store JSON/text/bytes/file round trip test.
- Create `tests/test_storage_repositories.py`
  - Repository and `ProjectStore` behavior from the old storage module.
- Create `tests/test_storage_models.py`
  - Storage model serialization and internal tuple behavior tests.
- Keep `tests/test_storage_runs.py`
  - Existing run-record tests remain there.
- Delete `tests/test_builtin_plugins.py` after moving its tests.
- Create `tests/builtin_plugin_fakes.py`
  - Shared fake OpenAI clients, fake downloaders, fake JS runtime helper, fake
    ffmpeg runner, and fake faster-whisper objects.
- Create focused built-in plugin modules:
  - `tests/test_builtin_plugin_discovery.py`
  - `tests/test_builtin_glossary.py`
  - `tests/test_builtin_remote_video.py`
  - `tests/test_builtin_translation.py`
  - `tests/test_builtin_transcript.py`
  - `tests/test_builtin_subtitle.py`
  - `tests/test_builtin_ffmpeg.py`
  - `tests/test_builtin_faster_whisper.py`
- Modify `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`
  only in the audit closure task.

---

### Task 1: Split Storage Tests

**Files:**
- Create: `tests/test_storage_database_records.py`
- Create: `tests/test_storage_artifact_content.py`
- Create: `tests/test_storage_repositories.py`
- Create: `tests/test_storage_models.py`
- Delete: `tests/test_storage.py`

- [ ] **Step 1: Run the storage baseline**

Run:

```bash
uv run pytest tests/test_storage.py tests/test_storage_runs.py -q
```

Expected: `28 passed`.

- [ ] **Step 2: Move database-record tests**

Create `tests/test_storage_database_records.py` with these imports from the old
module:

```python
import json
import sqlite3

from sqlalchemy.orm import sessionmaker

from openbbq.runtime.user_db import UserRuntimeDatabase
from openbbq.storage.database import ProjectDatabase
from openbbq.storage.database_records import (
    dump_json,
    dump_nullable_json,
    model_from_row,
    record_payload,
    upsert_row,
)
from openbbq.storage.models import WorkflowState
from openbbq.storage.orm import WorkflowStateRow
from openbbq.storage.project_store import ProjectStore
```

Move these exact functions from `tests/test_storage.py`:

```text
_sqlite_table_names
test_database_record_helpers_dump_deterministic_json
test_database_record_helpers_dump_model_payload
test_database_record_helpers_upsert_and_model_from_row
test_project_database_initializes_with_alembic_without_user_tables
test_user_runtime_database_initializes_with_alembic_without_project_tables
test_project_sqlite_records_workflow_state_step_run_event_and_artifact
test_project_database_updates_existing_workflow_state_row
```

- [ ] **Step 3: Move artifact content tests**

Create `tests/test_storage_artifact_content.py` with this import:

```python
from openbbq.storage.artifact_content import ArtifactContentStore
```

Move this exact function from `tests/test_storage.py`:

```text
test_artifact_content_store_round_trips_json_text_bytes_and_files
```

- [ ] **Step 4: Move repository and ProjectStore tests**

Create `tests/test_storage_repositories.py` with these imports:

```python
import sqlite3
from datetime import datetime

import pytest

from openbbq.storage.artifact_repository import ArtifactRepository
from openbbq.storage.database import ProjectDatabase
from openbbq.storage.event_repository import EventRepository
from openbbq.storage.project_store import ProjectStore
from openbbq.storage.workflow_repository import WorkflowRepository
```

Move these exact functions from `tests/test_storage.py`:

```text
test_storage_repositories_round_trip_without_project_store
test_write_artifact_version_round_trip
test_event_readers_return_typed_events_after_sequence
test_artifact_version_supports_direct_database_lookup_without_json_index
test_artifact_metadata_is_not_written_to_legacy_json_files
test_workflow_state_step_run_and_events_round_trip
test_project_store_keeps_facts_in_database_not_legacy_json_files
test_write_workflow_state_overrides_conflicting_id
test_write_step_run_overrides_conflicting_workflow_id
test_id_generator_injection_is_used_for_persisted_ids
test_write_artifact_version_round_trips_content_types
test_list_artifacts_and_read_artifact
```

Keep the `pytest.mark.parametrize` decorator attached to
`test_write_artifact_version_round_trips_content_types`.

- [ ] **Step 5: Move storage model tests**

Create `tests/test_storage_models.py` with these imports:

```python
from openbbq.storage.models import ArtifactRecord, OutputBinding, WorkflowState
```

Move these exact functions from `tests/test_storage.py`:

```text
test_storage_models_dump_to_current_json_shape
test_output_binding_is_typed
test_artifact_record_versions_are_tuple_for_internal_use
```

- [ ] **Step 6: Delete the old storage test module and verify**

Delete `tests/test_storage.py`.

Run:

```bash
uv run pytest tests/test_storage_*.py -q
uv run ruff check tests/test_storage_*.py
uv run ruff format --check tests/test_storage_*.py
```

Expected: storage tests pass, Ruff passes, and no `tests/test_storage.py`
remains.

- [ ] **Step 7: Commit**

```bash
git add tests/test_storage_database_records.py tests/test_storage_artifact_content.py tests/test_storage_repositories.py tests/test_storage_models.py
git rm tests/test_storage.py
git commit -m "test: Split storage test modules"
```

---

### Task 2: Split Built-In Plugin Tests

**Files:**
- Create: `tests/builtin_plugin_fakes.py`
- Create: `tests/test_builtin_plugin_discovery.py`
- Create: `tests/test_builtin_glossary.py`
- Create: `tests/test_builtin_remote_video.py`
- Create: `tests/test_builtin_translation.py`
- Create: `tests/test_builtin_transcript.py`
- Create: `tests/test_builtin_subtitle.py`
- Create: `tests/test_builtin_ffmpeg.py`
- Create: `tests/test_builtin_faster_whisper.py`
- Delete: `tests/test_builtin_plugins.py`

- [ ] **Step 1: Run the built-in plugin baseline**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py -q
```

Expected: `31 passed`.

- [ ] **Step 2: Create shared fake/helper module**

Create `tests/builtin_plugin_fakes.py` from the helper code currently in
`tests/test_builtin_plugins.py`. It should contain:

```text
runtime_provider_payload
FakeMessage
FakeChoice
FakeCompletion
RecordingChatCompletions
RecordingChat
RecordingOpenAIClient
RecordingOpenAIClientFactory
SequencedRecordingChatCompletions
SequencedRecordingChat
SequencedRecordingOpenAIClient
SequencedRecordingOpenAIClientFactory
RecordingDownloader
RecordingDownloaderFactory
NoOutputDownloader
FailingDownloader
CustomDownloaderFactory
BrowserCookieAwareDownloader
BrowserCookieAwareDownloaderFactory
_mock_js_runtime
RecordingRunner
FakeWord
FakeSegment
FakeInfo
FakeWhisperModel
```

Keep helper behavior unchanged. Import `Path` where the fake downloader needs
it.

- [ ] **Step 3: Move discovery tests**

Create `tests/test_builtin_plugin_discovery.py` with imports for `Path`,
`load_project_config`, and `discover_plugins`. Move:

```text
write_project
test_builtin_plugin_path_is_discovered_by_default
```

- [ ] **Step 4: Move glossary tests**

Create `tests/test_builtin_glossary.py` with:

```python
from openbbq.builtin_plugins.glossary import plugin as glossary_plugin
```

Move:

```text
test_glossary_replace_updates_segment_text_and_preserves_other_fields
```

- [ ] **Step 5: Move remote-video tests**

Create `tests/test_builtin_remote_video.py` with imports for `pytest`, the
remote video plugin, and the required fake classes from
`tests.builtin_plugin_fakes`. Move:

```text
test_remote_video_download_uses_yt_dlp_factory_and_returns_file_output
test_remote_video_download_falls_back_to_browser_cookies_for_youtube
test_remote_video_download_can_start_with_explicit_browser_cookies
test_remote_video_download_requires_url
test_remote_video_download_rejects_non_mp4_format
test_remote_video_download_rejects_unknown_auth_mode
test_remote_video_download_wraps_downloader_failures
test_remote_video_download_requires_expected_output_file
test_remote_video_download_missing_dependency_message
```

- [ ] **Step 6: Move translation tests**

Create `tests/test_builtin_translation.py` with imports for `json`, `pytest`,
the translation plugin, and the required OpenAI fakes plus
`runtime_provider_payload`. Move:

```text
test_translation_parameters_reject_empty_target_lang
test_translation_translate_uses_openai_client_and_returns_translation
test_translation_translate_uses_runtime_provider_profile
test_translation_translate_rejects_unconfigured_provider
test_translation_translate_rejects_missing_provider_parameter
test_translation_translate_rejects_malformed_model_json
test_translation_translate_batches_long_segments
test_translation_translate_splits_chunk_when_model_returns_too_few_segments
test_translation_qa_reports_term_number_and_readability_issues
```

- [ ] **Step 7: Move transcript tests**

Create `tests/test_builtin_transcript.py` with imports for `json`, `pytest`,
the transcript plugin, and the required OpenAI fakes plus
`runtime_provider_payload`. Move:

```text
test_segmentation_parameters_reject_zero_max_lines
test_transcript_correct_uses_openai_client_and_returns_corrected_transcript
test_transcript_correct_uses_runtime_provider_profile
test_transcript_correct_splits_chunk_when_model_returns_too_few_segments
test_transcript_segment_derives_subtitle_ready_units_from_word_timestamps
test_transcript_segment_wraps_lines_without_word_timestamps
```

- [ ] **Step 8: Move subtitle, ffmpeg, and faster-whisper tests**

Create `tests/test_builtin_subtitle.py` with the subtitle plugin import and
move:

```text
test_subtitle_export_writes_srt_from_transcript_segments
```

Create `tests/test_builtin_ffmpeg.py` with the ffmpeg plugin import and
`RecordingRunner` fake import, then move:

```text
test_ffmpeg_extract_audio_builds_command_and_returns_file_output
```

Create `tests/test_builtin_faster_whisper.py` with the faster-whisper plugin
import and fake whisper model imports, then move:

```text
test_faster_whisper_transcribe_uses_backend_and_returns_segments
test_faster_whisper_transcribe_uses_runtime_cache_dir
test_faster_whisper_transcribe_forwards_optional_decoder_controls
```

- [ ] **Step 9: Delete old built-in plugin module and verify**

Delete `tests/test_builtin_plugins.py`.

Run:

```bash
uv run pytest tests/test_builtin_plugin_discovery.py tests/test_builtin_glossary.py tests/test_builtin_remote_video.py tests/test_builtin_translation.py tests/test_builtin_transcript.py tests/test_builtin_subtitle.py tests/test_builtin_ffmpeg.py tests/test_builtin_faster_whisper.py -q
uv run ruff check tests/builtin_plugin_fakes.py tests/test_builtin_*.py
uv run ruff format --check tests/builtin_plugin_fakes.py tests/test_builtin_*.py
```

Expected: built-in plugin tests pass, Ruff passes, and no
`tests/test_builtin_plugins.py` remains.

- [ ] **Step 10: Commit**

```bash
git add tests/builtin_plugin_fakes.py tests/test_builtin_plugin_discovery.py tests/test_builtin_glossary.py tests/test_builtin_remote_video.py tests/test_builtin_translation.py tests/test_builtin_transcript.py tests/test_builtin_subtitle.py tests/test_builtin_ffmpeg.py tests/test_builtin_faster_whisper.py
git rm tests/test_builtin_plugins.py
git commit -m "test: Split built-in plugin test modules"
```

---

### Task 3: Verify And Close Audit Item

**Files:**
- Modify: `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`

- [ ] **Step 1: Update audit closure status**

Move `P2: Large test modules reduce failure locality` from `Remaining` to
`Done` with this text:

```markdown
- **P2: Large test modules reduce failure locality**
  - Completed by splitting `tests/test_builtin_plugins.py` into focused
    built-in plugin family modules with shared non-collected fakes in
    `tests/builtin_plugin_fakes.py`, and splitting `tests/test_storage.py`
    into focused database record, artifact content, repository, and storage
    model modules. Remaining ~300-line files are cohesive command or subsystem
    surfaces and should be revisited only when touched for related work.
```

Remove the same item from `Remaining`.

Update execution strategy numbering so `Typed internal payloads` is first and
`Missing-state domain errors` is second.

Change `## Next slice` to:

```markdown
The next implementation slice should be **Typed internal payloads**. It should
add typed internal models only where transcript or translation payloads are
transformed repeatedly, while keeping JSON-like data at plugin, artifact, and
config boundaries.
```

- [ ] **Step 2: Run final verification in the worktree**

Run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Expected: all commands pass.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md
git commit -m "docs: Track large test split completion"
```


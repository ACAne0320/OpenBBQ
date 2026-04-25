# Built-in LLM Helper Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract shared OpenAI-compatible client, completion-content, JSON list parsing, and chunking helpers used by the transcript correction and translation built-in plugins.

**Architecture:** Add a focused `openbbq.builtin_plugins.llm` helper module with generic LLM plumbing only. Keep plugin-specific prompt construction, payload construction, response semantics, and metadata in the existing transcript and translation plugin modules. Retain compatibility re-export modules and existing `_default_client_factory` monkeypatch points.

**Tech Stack:** Python 3.11, pytest, Ruff, Pydantic-adjacent OpenBBQ plugin payloads, OpenAI-compatible client factory.

---

## File Structure

- Create: `src/openbbq/builtin_plugins/llm.py`
  - Owns generic LLM helper functions:
    - `default_openai_client_factory()`
    - `completion_content()`
    - `segment_chunks()`
    - `parse_indexed_text_items()`
- Create: `tests/test_builtin_llm_helpers.py`
  - Covers shared helper behavior and the `llm_json.py` compatibility modules.
- Modify: `src/openbbq/builtin_plugins/translation/plugin.py`
  - Uses the shared helper for client factory, completion content, segment chunking, and indexed text response parsing.
  - Keeps translation-specific payload building, translation response shape, and QA behavior local.
- Modify: `src/openbbq/builtin_plugins/transcript/plugin.py`
  - Uses the shared helper for client factory, completion content, segment chunking, and common correction response validation.
  - Keeps correction-specific `status` and `uncertain_reason` validation local.
- Modify: `src/openbbq/builtin_plugins/transcript/llm_json.py`
  - Converts the broken compatibility re-export into a shim backed by `openbbq.builtin_plugins.llm`.
- Modify: `src/openbbq/builtin_plugins/translation/llm_json.py`
  - Converts the broken compatibility re-export into a shim backed by `openbbq.builtin_plugins.llm`.
- Modify: `tests/test_package_layout.py`
  - Adds import coverage for the shared helper and compatibility modules.
- Modify: `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`
  - Marks the built-in LLM helper extraction audit item done and advances the next slice to runtime settings boundary cleanup.

Do not change plugin manifests, workflow fixture YAML, prompts, model parameters, provider lookup, output payload shapes, or error message wording.

---

### Task 1: Add built-in LLM helper characterization tests

**Files:**
- Create: `tests/test_builtin_llm_helpers.py`

- [ ] **Step 1: Create the test file**

Create `tests/test_builtin_llm_helpers.py` with this content:

```python
from __future__ import annotations

import builtins
import importlib
import re
from typing import Any

import pytest


class FakeMessage:
    def __init__(self, content: Any) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: Any) -> None:
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content: Any) -> None:
        self.choices = [FakeChoice(content)]


def test_llm_json_compatibility_modules_import_and_parse_arrays() -> None:
    for module_name in (
        "openbbq.builtin_plugins.transcript.llm_json",
        "openbbq.builtin_plugins.translation.llm_json",
    ):
        module = importlib.import_module(module_name)

        assert module._parse_json_array(
            '[{"index": 0, "text": "Hello", "status": "corrected"}]',
            expected_count=1,
            error_prefix="transcript.correct",
            item_label="corrected segment",
        ) == [{"index": 0, "text": "Hello", "status": "corrected"}]


def test_completion_content_extracts_text_and_preserves_error_messages() -> None:
    llm = importlib.import_module("openbbq.builtin_plugins.llm")

    assert (
        llm.completion_content(
            FakeCompletion("Hello"),
            error_prefix="translation.translate",
        )
        == "Hello"
    )

    no_choices = type("NoChoicesCompletion", (), {"choices": []})()
    with pytest.raises(
        ValueError,
        match=re.escape("translation.translate received no choices from the model."),
    ):
        llm.completion_content(no_choices, error_prefix="translation.translate")

    with pytest.raises(
        ValueError,
        match=re.escape("translation.translate model response content must be a string."),
    ):
        llm.completion_content(FakeCompletion(None), error_prefix="translation.translate")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            "not json",
            "translation.translate model response was not valid JSON.",
        ),
        (
            '{"index": 0, "text": "Hello"}',
            "translation.translate model response must be an array.",
        ),
        (
            "[]",
            "translation.translate expected 1 translated segments, got 0.",
        ),
        (
            "[123]",
            "translation.translate translated segments must be objects.",
        ),
        (
            '[{"index": 1, "text": "Hello"}]',
            "translation.translate expected translated segment index 0, got 1.",
        ),
        (
            '[{"index": 0, "text": 123}]',
            "translation.translate translated segment text must be a string.",
        ),
    ],
)
def test_parse_indexed_text_items_preserves_translation_error_messages(
    content: str,
    message: str,
) -> None:
    llm = importlib.import_module("openbbq.builtin_plugins.llm")

    with pytest.raises(ValueError, match=re.escape(message)):
        llm.parse_indexed_text_items(
            content,
            expected_count=1,
            error_prefix="translation.translate",
            item_label="translated segment",
        )


def test_parse_indexed_text_items_preserves_extra_fields() -> None:
    llm = importlib.import_module("openbbq.builtin_plugins.llm")

    assert llm.parse_indexed_text_items(
        '[{"index": 0, "text": "Hello", "uncertain_reason": "low confidence"}]',
        expected_count=1,
        error_prefix="transcript.correct",
        item_label="corrected segment",
    ) == [{"index": 0, "text": "Hello", "uncertain_reason": "low confidence"}]


def test_segment_chunks_rejects_non_positive_size_with_prefix() -> None:
    llm = importlib.import_module("openbbq.builtin_plugins.llm")

    with pytest.raises(
        ValueError,
        match=re.escape("transcript.correct chunk size must be positive."),
    ):
        llm.segment_chunks([], 0, error_prefix="transcript.correct")


def test_default_openai_client_factory_preserves_missing_dependency_message(monkeypatch) -> None:
    llm = importlib.import_module("openbbq.builtin_plugins.llm")
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("missing openai")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(
        RuntimeError,
        match=re.escape(
            "openai is not installed. Install OpenBBQ with the llm optional dependencies."
        ),
    ):
        llm.default_openai_client_factory(api_key="sk-test", base_url=None)
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
uv run pytest tests/test_builtin_llm_helpers.py -q
```

Expected: FAIL because `openbbq.builtin_plugins.llm` does not exist and the two
existing `llm_json.py` modules cannot import `_parse_json_array`.

- [ ] **Step 3: Commit the failing characterization tests**

Run:

```bash
git add tests/test_builtin_llm_helpers.py
git commit -m "test: Cover built-in LLM helper boundaries"
```

---

### Task 2: Add the shared built-in LLM helper module

**Files:**
- Create: `src/openbbq/builtin_plugins/llm.py`
- Test: `tests/test_builtin_llm_helpers.py`

- [ ] **Step 1: Create `src/openbbq/builtin_plugins/llm.py`**

Create `src/openbbq/builtin_plugins/llm.py` with this content:

```python
from __future__ import annotations

import json
from typing import Any


def default_openai_client_factory(*, api_key: str, base_url: str | None):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai is not installed. Install OpenBBQ with the llm optional dependencies."
        ) from exc
    return OpenAI(api_key=api_key, base_url=base_url)


def completion_content(completion: Any, *, error_prefix: str) -> str:
    choices = getattr(completion, "choices", None)
    if not choices:
        raise ValueError(f"{error_prefix} received no choices from the model.")
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if not isinstance(content, str):
        raise ValueError(f"{error_prefix} model response content must be a string.")
    return content


def segment_chunks(
    segments: list[dict[str, Any]],
    chunk_size: int,
    *,
    error_prefix: str,
) -> list[list[dict[str, Any]]]:
    if chunk_size <= 0:
        raise ValueError(f"{error_prefix} chunk size must be positive.")
    return [segments[index : index + chunk_size] for index in range(0, len(segments), chunk_size)]


def parse_indexed_text_items(
    content: str,
    *,
    expected_count: int,
    error_prefix: str,
    item_label: str,
) -> list[dict[str, Any]]:
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{error_prefix} model response was not valid JSON.") from exc
    if not isinstance(raw, list):
        raise ValueError(f"{error_prefix} model response must be an array.")
    plural_label = f"{item_label}s"
    if len(raw) != expected_count:
        raise ValueError(
            f"{error_prefix} expected {expected_count} {plural_label}, got {len(raw)}."
        )

    parsed: list[dict[str, Any]] = []
    for expected_index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{error_prefix} {plural_label} must be objects.")
        if item.get("index") != expected_index:
            raise ValueError(
                f"{error_prefix} expected {item_label} index "
                f"{expected_index}, got {item.get('index')}."
            )
        text = item.get("text")
        if not isinstance(text, str):
            raise ValueError(f"{error_prefix} {item_label} text must be a string.")
        parsed_item = dict(item)
        parsed_item["index"] = expected_index
        parsed_item["text"] = text
        parsed.append(parsed_item)
    return parsed
```

- [ ] **Step 2: Run helper-focused tests**

Run:

```bash
uv run pytest tests/test_builtin_llm_helpers.py -k "not compatibility_modules" -q
```

Expected: PASS for helper behavior tests. The compatibility module import test
is still expected to fail until Task 5 updates `llm_json.py`.

- [ ] **Step 3: Run lint and commit**

Run:

```bash
uv run ruff check src/openbbq/builtin_plugins/llm.py tests/test_builtin_llm_helpers.py
uv run ruff format --check src/openbbq/builtin_plugins/llm.py tests/test_builtin_llm_helpers.py
```

Expected: both commands exit 0.

Commit:

```bash
git add src/openbbq/builtin_plugins/llm.py tests/test_builtin_llm_helpers.py
git commit -m "refactor: Add built-in LLM helper module"
```

---

### Task 3: Move translation plugin generic LLM plumbing to the helper

**Files:**
- Modify: `src/openbbq/builtin_plugins/translation/plugin.py`
- Test: `tests/test_builtin_plugins.py`
- Test: `tests/test_builtin_llm_helpers.py`
- Test: `tests/test_phase2_translation_slice.py`

- [ ] **Step 1: Add shared helper imports**

In `src/openbbq/builtin_plugins/translation/plugin.py`, add this import after
the existing glossary/runtime imports:

```python
from openbbq.builtin_plugins.llm import (
    completion_content,
    default_openai_client_factory,
    parse_indexed_text_items,
    segment_chunks,
)
```

- [ ] **Step 2: Preserve the monkeypatch point for the default client factory**

Replace the local `_default_client_factory()` function body with a module-level
alias:

```python
_default_client_factory = default_openai_client_factory
```

Keep all existing call sites that read `translation_plugin._default_client_factory`.

- [ ] **Step 3: Route translation chunking through `segment_chunks()`**

In `run_translation()`, replace the chunk loop:

```python
for chunk in _segment_chunks(
    segments, DEFAULT_MAX_SEGMENTS_PER_REQUEST, error_prefix=error_prefix
):
```

with:

```python
for chunk in segment_chunks(
    segments, DEFAULT_MAX_SEGMENTS_PER_REQUEST, error_prefix=error_prefix
):
```

Delete the local `_segment_chunks()` helper from `translation/plugin.py`.

- [ ] **Step 4: Route completion content extraction through `completion_content()`**

In `_translate_chunk_once()`, replace:

```python
translated_items = _parse_translation_response(
    _completion_content(completion, error_prefix=error_prefix),
    expected_count=len(chunk),
    error_prefix=error_prefix,
)
```

with:

```python
translated_items = _parse_translation_response(
    completion_content(completion, error_prefix=error_prefix),
    expected_count=len(chunk),
    error_prefix=error_prefix,
)
```

Delete the local `_completion_content()` helper from `translation/plugin.py`.

- [ ] **Step 5: Route indexed JSON validation through `parse_indexed_text_items()`**

Replace `_parse_translation_response()` with:

```python
def _parse_translation_response(
    content: str, *, expected_count: int, error_prefix: str
) -> list[dict[str, Any]]:
    return [
        {"index": item["index"], "text": item["text"]}
        for item in parse_indexed_text_items(
            content,
            expected_count=expected_count,
            error_prefix=error_prefix,
            item_label="translated segment",
        )
    ]
```

Keep `import json` because `_user_message()` still serializes request payloads.

- [ ] **Step 6: Run translation-focused tests**

Run:

```bash
uv run pytest \
  tests/test_builtin_plugins.py::test_translation_translate_uses_openai_client_and_returns_translation \
  tests/test_builtin_plugins.py::test_translation_translate_uses_runtime_provider_profile \
  tests/test_builtin_plugins.py::test_translation_translate_rejects_malformed_model_json \
  tests/test_builtin_plugins.py::test_translation_translate_batches_long_segments \
  tests/test_builtin_plugins.py::test_translation_translate_splits_chunk_when_model_returns_too_few_segments \
  tests/test_phase2_translation_slice.py \
  -q
```

Expected: PASS.

- [ ] **Step 7: Run lint and commit**

Run:

```bash
uv run ruff check src/openbbq/builtin_plugins/translation/plugin.py tests/test_builtin_llm_helpers.py tests/test_builtin_plugins.py tests/test_phase2_translation_slice.py
uv run ruff format --check src/openbbq/builtin_plugins/translation/plugin.py tests/test_builtin_llm_helpers.py tests/test_builtin_plugins.py tests/test_phase2_translation_slice.py
```

Expected: both commands exit 0.

Commit:

```bash
git add src/openbbq/builtin_plugins/translation/plugin.py
git commit -m "refactor: Reuse LLM helpers in translation plugin"
```

---

### Task 4: Move transcript correction generic LLM plumbing to the helper

**Files:**
- Modify: `src/openbbq/builtin_plugins/transcript/plugin.py`
- Test: `tests/test_builtin_plugins.py`
- Test: `tests/test_builtin_llm_helpers.py`
- Test: `tests/test_phase2_asr_correction_segmentation.py`

- [ ] **Step 1: Add shared helper imports**

In `src/openbbq/builtin_plugins/transcript/plugin.py`, add this import after the
existing glossary/runtime imports:

```python
from openbbq.builtin_plugins.llm import (
    completion_content,
    default_openai_client_factory,
    parse_indexed_text_items,
    segment_chunks,
)
```

- [ ] **Step 2: Preserve the monkeypatch point for the default client factory**

Replace the local `_default_client_factory()` function body with a module-level
alias:

```python
_default_client_factory = default_openai_client_factory
```

Keep all existing call sites that read `transcript_plugin._default_client_factory`.

- [ ] **Step 3: Route transcript correction chunking through `segment_chunks()`**

In `_run_correct()`, replace:

```python
for chunk in _segment_chunks(segments, max_segments_per_request):
```

with:

```python
for chunk in segment_chunks(
    segments,
    max_segments_per_request,
    error_prefix="transcript.correct",
):
```

Delete the local `_segment_chunks()` helper from `transcript/plugin.py`.

- [ ] **Step 4: Route completion content extraction through `completion_content()`**

In `_correct_chunk_once()`, replace:

```python
corrected_items = _parse_correction_response(
    _completion_content(completion),
    expected_count=len(chunk),
)
```

with:

```python
corrected_items = _parse_correction_response(
    completion_content(completion, error_prefix="transcript.correct"),
    expected_count=len(chunk),
)
```

Delete the local `_completion_content()` helper from `transcript/plugin.py`.

- [ ] **Step 5: Route common indexed JSON validation through `parse_indexed_text_items()`**

Replace `_parse_correction_response()` with:

```python
def _parse_correction_response(content: str, *, expected_count: int) -> list[dict[str, Any]]:
    raw_items = parse_indexed_text_items(
        content,
        expected_count=expected_count,
        error_prefix="transcript.correct",
        item_label="corrected segment",
    )
    parsed = []
    for expected_index, item in enumerate(raw_items):
        text = item["text"]
        status = item.get("status")
        if status is not None and status not in {"unchanged", "corrected", "uncertain"}:
            raise ValueError("transcript.correct corrected segment status is invalid.")
        reason = item.get("uncertain_reason")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("transcript.correct uncertain reason must be a string.")
        payload: dict[str, Any] = {"index": expected_index, "text": text}
        if status is not None:
            payload["status"] = status
        if reason is not None:
            payload["uncertain_reason"] = reason
        parsed.append(payload)
    return parsed
```

Keep `import json` because `_correction_user_message()` still serializes request
payloads.

- [ ] **Step 6: Add correction-specific helper tests**

Append these tests to `tests/test_builtin_llm_helpers.py`:

```python
def test_transcript_correction_response_accepts_correction_specific_fields() -> None:
    transcript_plugin = importlib.import_module("openbbq.builtin_plugins.transcript.plugin")

    assert transcript_plugin._parse_correction_response(
        '[{"index": 0, "text": "Hello", "status": "uncertain", "uncertain_reason": "noise"}]',
        expected_count=1,
    ) == [
        {
            "index": 0,
            "text": "Hello",
            "status": "uncertain",
            "uncertain_reason": "noise",
        }
    ]


def test_transcript_correction_response_rejects_invalid_status() -> None:
    transcript_plugin = importlib.import_module("openbbq.builtin_plugins.transcript.plugin")

    with pytest.raises(
        ValueError,
        match=re.escape("transcript.correct corrected segment status is invalid."),
    ):
        transcript_plugin._parse_correction_response(
            '[{"index": 0, "text": "Hello", "status": "bad"}]',
            expected_count=1,
        )
```

- [ ] **Step 7: Run transcript-focused tests**

Run:

```bash
uv run pytest \
  tests/test_builtin_plugins.py::test_transcript_correct_uses_openai_client_and_returns_corrected_transcript \
  tests/test_builtin_plugins.py::test_transcript_correct_uses_runtime_provider_profile \
  tests/test_builtin_plugins.py::test_transcript_correct_splits_chunk_when_model_returns_too_few_segments \
  tests/test_builtin_llm_helpers.py -k "not compatibility_modules" \
  tests/test_phase2_asr_correction_segmentation.py \
  -q
```

Expected: PASS for all selected tests except the compatibility import test when
the full helper file is not filtered.

- [ ] **Step 8: Run lint and commit**

Run:

```bash
uv run ruff check src/openbbq/builtin_plugins/transcript/plugin.py tests/test_builtin_llm_helpers.py tests/test_builtin_plugins.py tests/test_phase2_asr_correction_segmentation.py
uv run ruff format --check src/openbbq/builtin_plugins/transcript/plugin.py tests/test_builtin_llm_helpers.py tests/test_builtin_plugins.py tests/test_phase2_asr_correction_segmentation.py
```

Expected: both commands exit 0.

Commit:

```bash
git add src/openbbq/builtin_plugins/transcript/plugin.py tests/test_builtin_llm_helpers.py
git commit -m "refactor: Reuse LLM helpers in transcript plugin"
```

---

### Task 5: Repair the `llm_json.py` compatibility modules

**Files:**
- Modify: `src/openbbq/builtin_plugins/transcript/llm_json.py`
- Modify: `src/openbbq/builtin_plugins/translation/llm_json.py`
- Test: `tests/test_builtin_llm_helpers.py`

- [ ] **Step 1: Replace transcript compatibility module**

Replace `src/openbbq/builtin_plugins/transcript/llm_json.py` with:

```python
from __future__ import annotations

from typing import Any

from openbbq.builtin_plugins.llm import (
    completion_content as _completion_content,
    default_openai_client_factory as _default_client_factory,
    parse_indexed_text_items,
    segment_chunks as _segment_chunks,
)


def _parse_json_array(
    content: str,
    *,
    expected_count: int,
    error_prefix: str,
    item_label: str,
) -> list[dict[str, Any]]:
    return parse_indexed_text_items(
        content,
        expected_count=expected_count,
        error_prefix=error_prefix,
        item_label=item_label,
    )


__all__ = [
    "_completion_content",
    "_default_client_factory",
    "_parse_json_array",
    "_segment_chunks",
]
```

- [ ] **Step 2: Replace translation compatibility module**

Replace `src/openbbq/builtin_plugins/translation/llm_json.py` with the same
content, changing only the file path:

```python
from __future__ import annotations

from typing import Any

from openbbq.builtin_plugins.llm import (
    completion_content as _completion_content,
    default_openai_client_factory as _default_client_factory,
    parse_indexed_text_items,
    segment_chunks as _segment_chunks,
)


def _parse_json_array(
    content: str,
    *,
    expected_count: int,
    error_prefix: str,
    item_label: str,
) -> list[dict[str, Any]]:
    return parse_indexed_text_items(
        content,
        expected_count=expected_count,
        error_prefix=error_prefix,
        item_label=item_label,
    )


__all__ = [
    "_completion_content",
    "_default_client_factory",
    "_parse_json_array",
    "_segment_chunks",
]
```

- [ ] **Step 3: Run compatibility tests**

Run:

```bash
uv run pytest tests/test_builtin_llm_helpers.py -q
```

Expected: PASS.

- [ ] **Step 4: Run lint and commit**

Run:

```bash
uv run ruff check src/openbbq/builtin_plugins/llm.py src/openbbq/builtin_plugins/transcript/llm_json.py src/openbbq/builtin_plugins/translation/llm_json.py tests/test_builtin_llm_helpers.py
uv run ruff format --check src/openbbq/builtin_plugins/llm.py src/openbbq/builtin_plugins/transcript/llm_json.py src/openbbq/builtin_plugins/translation/llm_json.py tests/test_builtin_llm_helpers.py
```

Expected: both commands exit 0.

Commit:

```bash
git add src/openbbq/builtin_plugins/transcript/llm_json.py src/openbbq/builtin_plugins/translation/llm_json.py tests/test_builtin_llm_helpers.py
git commit -m "fix: Repair built-in LLM JSON compatibility modules"
```

---

### Task 6: Add package import coverage and update audit tracking

**Files:**
- Modify: `tests/test_package_layout.py`
- Modify: `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`
- Test: `tests/test_package_layout.py`
- Test: `tests/test_builtin_llm_helpers.py`

- [ ] **Step 1: Add built-in LLM helper modules to import coverage**

In `tests/test_package_layout.py`, add these module names to the `modules` list
in `test_new_package_modules_are_importable`:

```python
modules = [
    "openbbq.builtin_plugins.llm",
    "openbbq.builtin_plugins.transcript.llm_json",
    "openbbq.builtin_plugins.translation.llm_json",
    # existing module names continue below
]
```

Place them near the other package-level module imports before the CLI modules.

- [ ] **Step 2: Update the audit closure tracking spec**

In `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`,
move **P2: Built-in LLM plugins duplicate client and JSON-response plumbing**
from the Remaining section to the Done section. Add this bullet under
`### Done`:

```markdown
- **P2: Built-in LLM plugins duplicate client and JSON-response plumbing**
  - Completed by extracting shared OpenAI-compatible client setup, completion
    content extraction, indexed JSON response parsing, and segment chunking
    helpers into `src/openbbq/builtin_plugins/llm.py` while preserving
    transcript and translation plugin contracts.
```

Remove this bullet from `### Remaining`:

```markdown
- **P2: Built-in LLM plugins duplicate client and JSON-response plumbing**
```

In the `## Execution strategy` section, remove the completed
**Built-in LLM helper extraction** item from the remaining cleanup order and
renumber the remaining items.

In the `## Next slice` section, replace the current text with:

```markdown
The next implementation slice should be **Runtime settings boundary cleanup**.
It should make raw settings parsing and validated runtime model ownership
explicit while preserving configuration precedence and provider validation
messages.
```

- [ ] **Step 3: Run focused tests and lint**

Run:

```bash
uv run pytest tests/test_package_layout.py tests/test_builtin_llm_helpers.py -q
uv run ruff check tests/test_package_layout.py tests/test_builtin_llm_helpers.py docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md
uv run ruff format --check tests/test_package_layout.py tests/test_builtin_llm_helpers.py
uv run ruff format --preview --check docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md
```

Expected: all commands exit 0. Use `--preview` only for the Markdown format
check because Ruff 0.15.12 requires preview mode when formatting Markdown
directly.

- [ ] **Step 4: Commit package coverage and tracking update**

Run:

```bash
git add tests/test_package_layout.py docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md tests/test_builtin_llm_helpers.py
git commit -m "docs: Track built-in LLM helper extraction completion"
```

---

### Task 7: Focused built-in plugin verification

**Files:**
- No planned file changes.

- [ ] **Step 1: Run focused helper and built-in plugin tests**

Run:

```bash
uv run pytest tests/test_builtin_llm_helpers.py -q
uv run pytest tests/test_builtin_plugins.py -q
uv run pytest tests/test_phase2_asr_correction_segmentation.py tests/test_phase2_translation_slice.py -q
uv run pytest tests/test_phase2_contract_regressions.py -q
uv run pytest tests/test_cli_quickstart.py tests/test_runtime_cli.py -q
```

Expected: every command exits 0.

- [ ] **Step 2: Verify generic helper bodies are no longer duplicated**

Run:

```bash
rg -n "def _default_client_factory|def _completion_content|def _segment_chunks" src/openbbq/builtin_plugins/transcript/plugin.py src/openbbq/builtin_plugins/translation/plugin.py
rg -n "parse_indexed_text_items|completion_content|segment_chunks|default_openai_client_factory" src/openbbq/builtin_plugins/transcript/plugin.py src/openbbq/builtin_plugins/translation/plugin.py
```

Expected:

- The first command finds no local generic helper definitions in transcript or
  translation plugin modules.
- The second command shows both plugin modules importing or calling the shared
  helper functions.

- [ ] **Step 3: Verify compatibility modules import**

Run:

```bash
uv run python - <<'PY'
import importlib

for module_name in (
    "openbbq.builtin_plugins.llm",
    "openbbq.builtin_plugins.transcript.llm_json",
    "openbbq.builtin_plugins.translation.llm_json",
):
    module = importlib.import_module(module_name)
    print(module_name, "OK")
PY
```

Expected: all three module names print `OK`.

- [ ] **Step 4: Check git status**

Run:

```bash
git status -sb
```

Expected: no uncommitted changes.

---

### Task 8: Final verification

**Files:**
- No planned file changes.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
uv run pytest
```

Expected: PASS.

- [ ] **Step 2: Run full lint**

Run:

```bash
uv run ruff check .
```

Expected: PASS.

- [ ] **Step 3: Run full format check**

Run:

```bash
uv run ruff format --check .
```

Expected: PASS with all files already formatted.

- [ ] **Step 4: Inspect final branch state**

Run:

```bash
git status -sb
git log --oneline -10
```

Expected:

- Working tree is clean.
- The branch contains the built-in LLM helper extraction commits.

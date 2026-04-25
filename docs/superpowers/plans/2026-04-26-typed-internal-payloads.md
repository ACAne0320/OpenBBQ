# Typed Internal Payloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace repeated internal transcript/translation segment dictionaries with typed value objects while preserving plugin JSON boundaries.

**Architecture:** Add `openbbq.builtin_plugins.segments` for typed timed segments, timed words, segmentation units, and request-boundary parsing. Make LLM chunking generic. Refactor translation first, then transcript, so each step remains testable and behavior-preserving.

**Tech Stack:** Python 3.11, dataclasses, pytest, Ruff, uv.

---

## File Structure

- Create `src/openbbq/builtin_plugins/segments.py`
  - Internal dataclasses `TimedWord`, `TimedSegment`, and `SegmentUnit`.
  - Request parsing helpers `timed_segments_from_request()` and
    `timed_segments_from_any_input()`.
- Modify `src/openbbq/builtin_plugins/llm.py`
  - Make `segment_chunks()` generic over any sequence element type.
- Modify `src/openbbq/builtin_plugins/translation/plugin.py`
  - Use `TimedSegment` internally after input parsing.
- Modify `src/openbbq/builtin_plugins/transcript/plugin.py`
  - Use `TimedSegment`, `TimedWord`, and `SegmentUnit` internally after input
    parsing.
- Create `tests/test_builtin_segments.py`
  - Focused tests for typed segment boundary parsing and generic chunking.
- Modify `tests/test_package_layout.py`
  - Add import coverage for `openbbq.builtin_plugins.segments`.
- Modify `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`
  only in the audit closure task.

---

### Task 1: Add Typed Segment Boundary And Generic Chunking

**Files:**
- Create: `src/openbbq/builtin_plugins/segments.py`
- Modify: `src/openbbq/builtin_plugins/llm.py`
- Create: `tests/test_builtin_segments.py`
- Modify: `tests/test_package_layout.py`

- [ ] **Step 1: Write typed boundary tests**

Create `tests/test_builtin_segments.py`:

```python
import re

import pytest

from openbbq.builtin_plugins.llm import segment_chunks
from openbbq.builtin_plugins.segments import (
    SegmentUnit,
    TimedSegment,
    timed_segments_from_any_input,
    timed_segments_from_request,
)


def test_timed_segments_from_request_preserves_validation_messages():
    with pytest.raises(ValueError, match=re.escape("translation.qa requires translation content.")):
        timed_segments_from_request({}, input_name="translation", error_prefix="translation.qa")

    with pytest.raises(
        ValueError,
        match=re.escape("translation.qa translation content must be a list of objects."),
    ):
        timed_segments_from_request(
            {"inputs": {"translation": {"content": "bad"}}},
            input_name="translation",
            error_prefix="translation.qa",
        )

    with pytest.raises(
        ValueError,
        match=re.escape("translation.qa translation content must be a list of objects."),
    ):
        timed_segments_from_request(
            {"inputs": {"translation": {"content": [1]}}},
            input_name="translation",
            error_prefix="translation.qa",
        )

    with pytest.raises(
        ValueError,
        match=re.escape("translation.qa translation segments must include start and end."),
    ):
        timed_segments_from_request(
            {"inputs": {"translation": {"content": [{"start": 0.0, "text": "Hello"}]}}},
            input_name="translation",
            error_prefix="translation.qa",
        )


def test_timed_segment_normalizes_fields_and_preserves_payload_copy():
    payload = {
        "start": "0.5",
        "end": 1,
        "text": 123,
        "source_text": "source",
        "confidence": 0.75,
        "words": [
            {"start": 0.5, "end": 0.7, "text": "Hello", "confidence": 0.6},
            {"text": "loose"},
            "ignored",
        ],
    }

    segment = TimedSegment.from_payload(payload)
    copied = segment.copy_payload()
    copied["text"] = "changed"

    assert segment.start == 0.5
    assert segment.end == 1.0
    assert segment.text == "123"
    assert segment.source_text == "source"
    assert segment.confidence == 0.75
    assert [word.text for word in segment.words] == ["Hello", "loose"]
    assert segment.words[0].start == 0.5
    assert segment.words[0].end == 0.7
    assert segment.words[0].confidence == 0.6
    assert segment.words[1].start is None
    assert segment.copy_payload()["text"] == 123


def test_timed_segments_from_any_input_prefers_first_present_input():
    request = {
        "inputs": {
            "transcript": {"content": [{"start": 0.0, "end": 1.0, "text": "Transcript"}]},
            "subtitle_segments": {
                "content": [{"start": 2.0, "end": 3.0, "text": "Subtitle"}]
            },
        }
    }

    segments = timed_segments_from_any_input(
        request,
        input_names=("subtitle_segments", "transcript"),
        error_prefix="translation.translate",
    )

    assert [segment.text for segment in segments] == ["Subtitle"]


def test_segment_unit_materializes_source_indexes_as_list():
    unit = SegmentUnit(start=0.0, end=1.0, text="Hello", source_segment_indexes=(1, 2))

    assert unit.source_segment_indexes == (1, 2)


def test_segment_chunks_accepts_typed_sequences():
    segments = [
        TimedSegment.from_payload({"start": 0.0, "end": 1.0, "text": "a"}),
        TimedSegment.from_payload({"start": 1.0, "end": 2.0, "text": "b"}),
        TimedSegment.from_payload({"start": 2.0, "end": 3.0, "text": "c"}),
    ]

    chunks = segment_chunks(segments, 2, error_prefix="translation.translate")

    assert [[segment.text for segment in chunk] for chunk in chunks] == [["a", "b"], ["c"]]
```

Modify `tests/test_package_layout.py` by adding this module string to
`test_new_package_modules_are_importable()`:

```python
        "openbbq.builtin_plugins.segments",
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run:

```bash
uv run pytest tests/test_builtin_segments.py tests/test_package_layout.py::test_new_package_modules_are_importable -q
```

Expected: fail because `openbbq.builtin_plugins.segments` does not exist.

- [ ] **Step 3: Create typed segment module**

Create `src/openbbq/builtin_plugins/segments.py`:

```python
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TimedWord:
    text: str
    start: float | None = None
    end: float | None = None
    confidence: float | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TimedWord:
        start = payload.get("start")
        end = payload.get("end")
        confidence = payload.get("confidence")
        return cls(
            text=str(payload.get("text", "")),
            start=float(start) if isinstance(start, (int, float)) else None,
            end=float(end) if isinstance(end, (int, float)) else None,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
        )


@dataclass(frozen=True)
class TimedSegment:
    start: float
    end: float
    text: str
    payload: dict[str, Any]
    source_text: str | None = None
    confidence: float | None = None
    words: tuple[TimedWord, ...] = ()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TimedSegment:
        confidence = payload.get("confidence")
        words = payload.get("words")
        source_text = payload.get("source_text")
        return cls(
            start=float(payload["start"]),
            end=float(payload["end"]),
            text=str(payload.get("text", "")),
            payload=payload,
            source_text=str(source_text) if source_text is not None else None,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
            words=tuple(
                TimedWord.from_payload(word)
                for word in words
                if isinstance(words, list) and isinstance(word, dict)
            ),
        )

    def copy_payload(self) -> dict[str, Any]:
        return deepcopy(self.payload)


@dataclass(frozen=True)
class SegmentUnit:
    start: float
    end: float
    text: str
    source_segment_indexes: tuple[int, ...]


def timed_segments_from_request(
    request: dict[str, Any], *, input_name: str, error_prefix: str
) -> list[TimedSegment]:
    artifact = request.get("inputs", {}).get(input_name, {})
    if not isinstance(artifact, dict) or "content" not in artifact:
        raise ValueError(f"{error_prefix} requires {input_name} content.")
    content = artifact["content"]
    if not isinstance(content, list) or any(not isinstance(segment, dict) for segment in content):
        raise ValueError(f"{error_prefix} {input_name} content must be a list of objects.")
    for segment in content:
        if "start" not in segment or "end" not in segment:
            raise ValueError(f"{error_prefix} {input_name} segments must include start and end.")
    return [TimedSegment.from_payload(segment) for segment in content]


def timed_segments_from_any_input(
    request: dict[str, Any], *, input_names: tuple[str, ...], error_prefix: str
) -> list[TimedSegment]:
    for input_name in input_names:
        artifact = request.get("inputs", {}).get(input_name)
        if isinstance(artifact, dict) and "content" in artifact:
            return timed_segments_from_request(
                request, input_name=input_name, error_prefix=error_prefix
            )
    return timed_segments_from_request(
        request, input_name=input_names[0], error_prefix=error_prefix
    )
```

- [ ] **Step 4: Make chunking generic**

Modify `src/openbbq/builtin_plugins/llm.py`:

```python
from collections.abc import Sequence
...
from typing import Any, TypeVar

T = TypeVar("T")
...
def segment_chunks(
    segments: Sequence[T],
    chunk_size: int,
    *,
    error_prefix: str,
) -> list[list[T]]:
    if chunk_size <= 0:
        raise ValueError(f"{error_prefix} chunk size must be positive.")
    return [
        list(segments[index : index + chunk_size])
        for index in range(0, len(segments), chunk_size)
    ]
```

- [ ] **Step 5: Run targeted tests**

Run:

```bash
uv run pytest tests/test_builtin_segments.py tests/test_builtin_llm_helpers.py tests/test_package_layout.py::test_new_package_modules_are_importable -q
uv run ruff check src/openbbq/builtin_plugins/segments.py src/openbbq/builtin_plugins/llm.py tests/test_builtin_segments.py tests/test_package_layout.py
uv run ruff format --check src/openbbq/builtin_plugins/segments.py src/openbbq/builtin_plugins/llm.py tests/test_builtin_segments.py tests/test_package_layout.py
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/openbbq/builtin_plugins/segments.py src/openbbq/builtin_plugins/llm.py tests/test_builtin_segments.py tests/test_package_layout.py
git commit -m "refactor: Add typed builtin segment helpers"
```

---

### Task 2: Refactor Translation Plugin To Typed Segments

**Files:**
- Modify: `src/openbbq/builtin_plugins/translation/plugin.py`
- Modify: `tests/test_builtin_translation.py`

- [ ] **Step 1: Add a characterization test for fallback input behavior**

Add this test to `tests/test_builtin_translation.py` after
`test_translation_translate_uses_runtime_provider_profile()`:

```python
def test_translation_translate_falls_back_to_transcript_input():
    factory = RecordingOpenAIClientFactory('[{"index":0,"text":"Transcript zh"}]')

    response = translation_plugin.run(
        {
            "tool_name": "translate",
            "parameters": {
                "provider": "openai",
                "source_lang": "en",
                "target_lang": "zh-Hans",
                "model": "gpt-4o-mini",
            },
            "runtime": runtime_provider_payload(),
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [{"start": 0.0, "end": 1.0, "text": "Transcript"}],
                }
            },
        },
        client_factory=factory,
    )

    assert response["outputs"]["translation"]["content"] == [
        {"start": 0.0, "end": 1.0, "source_text": "Transcript", "text": "Transcript zh"}
    ]
```

- [ ] **Step 2: Run the new characterization test**

Run:

```bash
uv run pytest tests/test_builtin_translation.py::test_translation_translate_falls_back_to_transcript_input -q
```

Expected: pass before refactor.

- [ ] **Step 3: Refactor translation plugin types**

In `src/openbbq/builtin_plugins/translation/plugin.py`:

- Import `TimedSegment`, `timed_segments_from_any_input`, and
  `timed_segments_from_request` from `openbbq.builtin_plugins.segments`.
- Change `segments`, `_translate_chunk()`, `_translate_chunk_once()`,
  `_timed_segments()`, and `_timed_segments_any()` to use `list[TimedSegment]`.
- Replace dictionary reads in translation and QA code:
  - `segment["start"]` -> `segment.start`
  - `segment["end"]` -> `segment.end`
  - `segment.get("text", "")` -> `segment.text`
  - `segment.get("source_text", "")` -> `segment.source_text or ""`
- Keep output payload dictionaries unchanged.
- Replace local `_timed_segments()` body with:

```python
    return timed_segments_from_request(request, input_name=input_name, error_prefix=error_prefix)
```

- Replace local `_timed_segments_any()` body with:

```python
    return timed_segments_from_any_input(
        request, input_names=input_names, error_prefix=error_prefix
    )
```

- [ ] **Step 4: Run translation tests**

Run:

```bash
uv run pytest tests/test_builtin_translation.py tests/test_builtin_segments.py tests/test_builtin_llm_helpers.py -q
uv run ruff check src/openbbq/builtin_plugins/translation/plugin.py tests/test_builtin_translation.py
uv run ruff format --check src/openbbq/builtin_plugins/translation/plugin.py tests/test_builtin_translation.py
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/openbbq/builtin_plugins/translation/plugin.py tests/test_builtin_translation.py
git commit -m "refactor: Use typed segments in translation plugin"
```

---

### Task 3: Refactor Transcript Plugin To Typed Segments

**Files:**
- Modify: `src/openbbq/builtin_plugins/transcript/plugin.py`

- [ ] **Step 1: Refactor transcript correction types**

In `src/openbbq/builtin_plugins/transcript/plugin.py`:

- Import `SegmentUnit`, `TimedSegment`, and `timed_segments_from_request` from
  `openbbq.builtin_plugins.segments`.
- Change `_segments()` to return `list[TimedSegment]` using:

```python
    return timed_segments_from_request(
        request, input_name="transcript", error_prefix=error_prefix
    )
```

- Change `_correct_chunk()`, `_correct_chunk_once()`, and
  `_correction_segment_payload()` to accept `list[TimedSegment]` or
  `TimedSegment`.
- In `_correction_segment_payload()`, use `segment.start`, `segment.end`,
  `segment.text`, `segment.confidence`, and `segment.words`.
- For each `TimedWord`, include `text`, optional `start`, optional `end`, and
  optional `confidence`, preserving the low-confidence behavior.
- In `_correct_chunk_once()`, replace `deepcopy(segment)` with
  `segment.copy_payload()`, set `source_text` from `segment.text`, and keep the
  output dictionary fields unchanged.
- Remove the now-unused `deepcopy` import.

- [ ] **Step 2: Refactor transcript segmentation types**

Continue in `src/openbbq/builtin_plugins/transcript/plugin.py`:

- Change `_segment_transcript()` and `_segmentation_units()` to use
  `list[TimedSegment]`.
- Change `_segmentation_units()` to return `list[SegmentUnit]`.
- Use `SegmentUnit` instead of dictionaries inside `_run_text()`,
  `_should_break_before()`, and `_materialize_block()`.
- Keep `_materialize_block()` returning the same subtitle segment dictionary
  shape.

- [ ] **Step 3: Run transcript tests**

Run:

```bash
uv run pytest tests/test_builtin_transcript.py tests/test_builtin_segments.py tests/test_builtin_llm_helpers.py -q
uv run ruff check src/openbbq/builtin_plugins/transcript/plugin.py
uv run ruff format --check src/openbbq/builtin_plugins/transcript/plugin.py
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add src/openbbq/builtin_plugins/transcript/plugin.py
git commit -m "refactor: Use typed segments in transcript plugin"
```

---

### Task 4: Verify And Close Audit Item

**Files:**
- Modify: `docs/superpowers/specs/2026-04-25-code-quality-audit-closure-design.md`

- [ ] **Step 1: Update audit closure status**

Move `P3: Dynamic payload typing is necessary at boundaries but sometimes
leaks inward` from `Remaining` to `Done` with this text:

```markdown
- **P3: Dynamic payload typing is necessary at boundaries but sometimes leaks
  inward**
  - Completed for the repeated transcript and translation paths by adding
    typed internal segment helpers in `src/openbbq/builtin_plugins/segments.py`,
    making LLM chunking generic, and refactoring transcript/translation plugins
    to use typed segments after request-boundary validation while preserving
    JSON request/response and artifact boundaries.
```

Remove the same item from `Remaining`.

Update execution strategy so only `Missing-state domain errors` remains.

Change `## Next slice` to:

```markdown
The next implementation slice should be **Missing-state domain errors**. It
should first add characterization tests for current file-not-found and
missing-state behavior, then introduce domain-specific errors at
application/service boundaries where that improves CLI/API consistency.
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
git commit -m "docs: Track typed payload cleanup completion"
```


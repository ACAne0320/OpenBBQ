# Phase 2 Translation Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 2 Slice 2 so the CLI can run a translated local subtitle workflow with built-in glossary and OpenAI-compatible LLM translation plugins.

**Architecture:** Keep the workflow engine unchanged and add translation behavior through built-in plugins discovered by the existing plugin registry. `glossary.replace` is deterministic and local; `llm.translate` uses the OpenAI Python SDK through an injected client factory in tests and environment-backed credentials in real runs. Default tests remain deterministic and never call real media binaries, Whisper models, or LLM services.

**Tech Stack:** Python 3.11, uv, pytest, Ruff, OpenAI Python SDK as optional `llm` dependency, existing OpenBBQ plugin registry and artifact store.

---

## File Structure

- Modify `pyproject.toml`: add optional `llm` dependency and package data entries for new built-in manifests.
- Create `src/openbbq/builtin_plugins/glossary/__init__.py`: package marker.
- Create `src/openbbq/builtin_plugins/glossary/openbbq.plugin.toml`: manifest for `glossary.replace`.
- Create `src/openbbq/builtin_plugins/glossary/plugin.py`: deterministic transcript glossary replacement.
- Create `src/openbbq/builtin_plugins/llm/__init__.py`: package marker.
- Create `src/openbbq/builtin_plugins/llm/openbbq.plugin.toml`: manifest for `llm.translate`.
- Create `src/openbbq/builtin_plugins/llm/plugin.py`: OpenAI SDK translation plugin with fakeable client factory seam.
- Modify `tests/test_builtin_plugins.py`: discovery, glossary, and LLM plugin unit tests.
- Modify `tests/test_package_layout.py`: package data assertions for new manifests.
- Modify `tests/test_fixtures.py`: translated fixture validation.
- Create `tests/fixtures/projects/local-video-translate-subtitle/openbbq.yaml`: canonical translated local media workflow.
- Create `tests/test_phase2_translation_slice.py`: deterministic CLI end-to-end test for the full translated subtitle workflow.
- Modify `README.md`: document optional LLM setup and translated subtitle smoke flow.
- Modify `docs/Target-Workflows.md`: update Phase 2 availability after built-in translation plugins.
- Modify `docs/Roadmap.md`: align Phase 2 with real local media and translation plugins.

## Task 1: Built-In Plugin Manifests, Discovery, Package Data, and LLM Extra

**Files:**
- Modify: `pyproject.toml`
- Create: `src/openbbq/builtin_plugins/glossary/__init__.py`
- Create: `src/openbbq/builtin_plugins/glossary/openbbq.plugin.toml`
- Create: `src/openbbq/builtin_plugins/glossary/plugin.py`
- Create: `src/openbbq/builtin_plugins/llm/__init__.py`
- Create: `src/openbbq/builtin_plugins/llm/openbbq.plugin.toml`
- Create: `src/openbbq/builtin_plugins/llm/plugin.py`
- Modify: `tests/test_builtin_plugins.py`
- Modify: `tests/test_package_layout.py`

- [ ] **Step 1: Write failing discovery and package data tests**

Append these assertions to `test_builtin_plugin_path_is_discovered_by_default()` in `tests/test_builtin_plugins.py`:

```python
    assert "glossary.replace" in registry.tools
    assert "llm.translate" in registry.tools
```

Update `test_builtin_plugin_manifests_are_configured_as_package_data()` in `tests/test_package_layout.py` so the expected package set includes the new built-ins:

```python
    assert manifest_packages == {
        "openbbq.builtin_plugins.faster_whisper",
        "openbbq.builtin_plugins.ffmpeg",
        "openbbq.builtin_plugins.glossary",
        "openbbq.builtin_plugins.llm",
        "openbbq.builtin_plugins.subtitle",
    }
```

Add this test to `tests/test_package_layout.py`:

```python
def test_llm_extra_declares_openai_sdk_dependency() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["optional-dependencies"]["llm"] == ["openai>=1.0"]
```

- [ ] **Step 2: Run discovery tests to verify RED**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_builtin_plugin_path_is_discovered_by_default tests/test_package_layout.py -q
```

Expected: FAIL because `glossary.replace`, `llm.translate`, their package data entries, and `llm` extra do not exist.

- [ ] **Step 3: Add built-in package directories**

Create directories:

```bash
mkdir -p src/openbbq/builtin_plugins/glossary src/openbbq/builtin_plugins/llm
```

Create `src/openbbq/builtin_plugins/glossary/__init__.py`:

```python
"""Glossary built-in plugin."""
```

Create `src/openbbq/builtin_plugins/llm/__init__.py`:

```python
"""LLM translation built-in plugin."""
```

- [ ] **Step 4: Add glossary manifest and initial plugin**

Create `src/openbbq/builtin_plugins/glossary/openbbq.plugin.toml`:

```toml
name = "glossary"
version = "0.1.0"
runtime = "python"
entrypoint = "plugin:run"

[[tools]]
name = "replace"
description = "Apply deterministic glossary replacements to transcript segments."
input_artifact_types = ["asr_transcript"]
output_artifact_types = ["asr_transcript"]
effects = []

[tools.parameter_schema]
type = "object"
additionalProperties = false

[tools.parameter_schema.properties.rules]
type = "array"
default = []

[tools.parameter_schema.properties.rules.items]
type = "object"
additionalProperties = false
required = ["find", "replace"]

[tools.parameter_schema.properties.rules.items.properties.find]
type = "string"

[tools.parameter_schema.properties.rules.items.properties.replace]
type = "string"

[tools.parameter_schema.properties.rules.items.properties.is_regex]
type = "boolean"
default = false

[tools.parameter_schema.properties.rules.items.properties.case_sensitive]
type = "boolean"
default = false
```

Create `src/openbbq/builtin_plugins/glossary/plugin.py`:

```python
def run(request):
    raise RuntimeError("This built-in plugin has not been implemented yet.")
```

- [ ] **Step 5: Add LLM manifest and initial plugin**

Create `src/openbbq/builtin_plugins/llm/openbbq.plugin.toml`:

```toml
name = "llm"
version = "0.1.0"
runtime = "python"
entrypoint = "plugin:run"

[[tools]]
name = "translate"
description = "Translate transcript segments with an OpenAI-compatible chat completions API."
input_artifact_types = ["asr_transcript"]
output_artifact_types = ["translation"]
effects = ["network"]

[tools.parameter_schema]
type = "object"
additionalProperties = false
required = ["source_lang", "target_lang", "model"]

[tools.parameter_schema.properties.source_lang]
type = "string"

[tools.parameter_schema.properties.target_lang]
type = "string"

[tools.parameter_schema.properties.model]
type = "string"

[tools.parameter_schema.properties.temperature]
type = "number"
default = 0

[tools.parameter_schema.properties.system_prompt]
type = "string"

[tools.parameter_schema.properties.base_url]
type = "string"
```

Create `src/openbbq/builtin_plugins/llm/plugin.py`:

```python
def run(request):
    raise RuntimeError("This built-in plugin has not been implemented yet.")
```

- [ ] **Step 6: Add `llm` extra and package data**

Update `pyproject.toml`:

```toml
[project.optional-dependencies]
media = ["faster-whisper>=1.2"]
llm = ["openai>=1.0"]
```

Update `[tool.setuptools.package-data]`:

```toml
"openbbq.builtin_plugins.faster_whisper" = ["openbbq.plugin.toml"]
"openbbq.builtin_plugins.ffmpeg" = ["openbbq.plugin.toml"]
"openbbq.builtin_plugins.glossary" = ["openbbq.plugin.toml"]
"openbbq.builtin_plugins.llm" = ["openbbq.plugin.toml"]
"openbbq.builtin_plugins.subtitle" = ["openbbq.plugin.toml"]
```

- [ ] **Step 7: Run discovery tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_builtin_plugin_path_is_discovered_by_default tests/test_package_layout.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add pyproject.toml src/openbbq/builtin_plugins/glossary src/openbbq/builtin_plugins/llm tests/test_builtin_plugins.py tests/test_package_layout.py
git commit -m "feat: Add translation built-in plugin manifests"
```

## Task 2: `glossary.replace` Built-In Plugin

**Files:**
- Modify: `src/openbbq/builtin_plugins/glossary/plugin.py`
- Modify: `tests/test_builtin_plugins.py`

- [ ] **Step 1: Write failing glossary unit test**

Add this import to `tests/test_builtin_plugins.py`:

```python
from openbbq.builtin_plugins.glossary import plugin as glossary_plugin
```

Add this test:

```python
def test_glossary_replace_updates_segment_text_and_preserves_other_fields():
    response = glossary_plugin.run(
        {
            "tool_name": "replace",
            "parameters": {
                "rules": [
                    {
                        "find": "Open BBQ",
                        "replace": "OpenBBQ",
                        "is_regex": False,
                        "case_sensitive": False,
                    },
                    {
                        "find": r"frieren",
                        "replace": "Frieren",
                        "is_regex": True,
                        "case_sensitive": False,
                    },
                ]
            },
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {
                            "start": 0.0,
                            "end": 1.5,
                            "text": "open bbq talks about frieren",
                            "confidence": -0.1,
                            "words": [{"start": 0.0, "end": 0.4, "text": "open"}],
                        },
                        {"start": 1.5, "end": 2.0, "text": "No match"},
                    ],
                }
            },
        }
    )

    assert response["outputs"]["transcript"]["type"] == "asr_transcript"
    assert response["outputs"]["transcript"]["content"] == [
        {
            "start": 0.0,
            "end": 1.5,
            "text": "OpenBBQ talks about Frieren",
            "confidence": -0.1,
            "words": [{"start": 0.0, "end": 0.4, "text": "open"}],
        },
        {"start": 1.5, "end": 2.0, "text": "No match"},
    ]
    assert response["outputs"]["transcript"]["metadata"] == {
        "segment_count": 2,
        "word_count": 6,
        "rule_count": 2,
    }
```

- [ ] **Step 2: Run glossary test to verify RED**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_glossary_replace_updates_segment_text_and_preserves_other_fields -q
```

Expected: FAIL because `glossary.replace` still raises.

- [ ] **Step 3: Implement glossary plugin**

Replace `src/openbbq/builtin_plugins/glossary/plugin.py` with:

```python
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


def run(request: dict) -> dict:
    if request.get("tool_name") != "replace":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    segments = _segments(request)
    rules = request.get("parameters", {}).get("rules", [])
    updated = [_apply_rules(segment, rules) for segment in segments]
    return {
        "outputs": {
            "transcript": {
                "type": "asr_transcript",
                "content": updated,
                "metadata": {
                    "segment_count": len(updated),
                    "word_count": sum(len(str(segment.get("text", "")).split()) for segment in updated),
                    "rule_count": len(rules),
                },
            }
        }
    }


def _segments(request: dict) -> list[dict[str, Any]]:
    transcript = request.get("inputs", {}).get("transcript", {})
    if not isinstance(transcript, dict) or "content" not in transcript:
        raise ValueError("glossary.replace requires transcript content.")
    content = transcript["content"]
    if not isinstance(content, list) or any(not isinstance(segment, dict) for segment in content):
        raise ValueError("glossary.replace transcript content must be a list of objects.")
    return content


def _apply_rules(segment: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any]:
    next_segment = deepcopy(segment)
    text = str(next_segment.get("text", ""))
    for rule in rules:
        find = str(rule["find"])
        replace = str(rule["replace"])
        if rule.get("is_regex", False):
            flags = 0 if rule.get("case_sensitive", False) else re.IGNORECASE
            text = re.sub(find, replace, text, flags=flags)
            continue
        if rule.get("case_sensitive", False):
            text = text.replace(find, replace)
        else:
            text = re.sub(re.escape(find), replace, text, flags=re.IGNORECASE)
    next_segment["text"] = text
    return next_segment
```

- [ ] **Step 4: Run glossary tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_glossary_replace_updates_segment_text_and_preserves_other_fields -q
```

Expected: PASS.

- [ ] **Step 5: Run all built-in plugin tests**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/openbbq/builtin_plugins/glossary/plugin.py tests/test_builtin_plugins.py
git commit -m "feat: Add built-in glossary replacement plugin"
```

## Task 3: `llm.translate` Built-In Plugin With OpenAI SDK Seam

**Files:**
- Modify: `src/openbbq/builtin_plugins/llm/plugin.py`
- Modify: `tests/test_builtin_plugins.py`

- [ ] **Step 1: Write fake OpenAI SDK client helpers**

Add this import to `tests/test_builtin_plugins.py`:

```python
from openbbq.builtin_plugins.llm import plugin as llm_plugin
```

Add these helper classes to `tests/test_builtin_plugins.py`:

```python
class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class RecordingChatCompletions:
    def __init__(self, response_content):
        self.response_content = response_content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeCompletion(self.response_content)


class RecordingChat:
    def __init__(self, response_content):
        self.completions = RecordingChatCompletions(response_content)


class RecordingOpenAIClient:
    def __init__(self, response_content):
        self.chat = RecordingChat(response_content)


class RecordingOpenAIClientFactory:
    def __init__(self, response_content):
        self.response_content = response_content
        self.calls = []
        self.client = RecordingOpenAIClient(response_content)

    def __call__(self, *, api_key, base_url):
        self.calls.append({"api_key": api_key, "base_url": base_url})
        return self.client
```

- [ ] **Step 2: Write failing LLM success test**

Add this test to `tests/test_builtin_plugins.py`:

```python
def test_llm_translate_uses_openai_client_and_returns_translation(monkeypatch):
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "test-key")
    monkeypatch.setenv("OPENBBQ_LLM_BASE_URL", "https://llm.example/v1")
    factory = RecordingOpenAIClientFactory(
        '[{"index": 0, "text": "你好"}, {"index": 1, "text": "OpenBBQ"}]'
    )

    response = llm_plugin.run(
        {
            "tool_name": "translate",
            "parameters": {
                "source_lang": "en",
                "target_lang": "zh-Hans",
                "model": "gpt-4o-mini",
                "temperature": 0,
            },
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {"start": 0.0, "end": 1.5, "text": "Hello"},
                        {"start": 1.5, "end": 3.0, "text": "OpenBBQ"},
                    ],
                }
            },
        },
        client_factory=factory,
    )

    assert factory.calls == [{"api_key": "test-key", "base_url": "https://llm.example/v1"}]
    call = factory.client.chat.completions.calls[0]
    assert call["model"] == "gpt-4o-mini"
    assert call["temperature"] == 0
    assert "response_format" not in call
    assert len(call["messages"]) == 2
    assert "Return JSON only" in call["messages"][0]["content"]
    assert '"target_lang":"zh-Hans"' in call["messages"][1]["content"]

    assert response == {
        "outputs": {
            "translation": {
                "type": "translation",
                "content": [
                    {"start": 0.0, "end": 1.5, "source_text": "Hello", "text": "你好"},
                    {"start": 1.5, "end": 3.0, "source_text": "OpenBBQ", "text": "OpenBBQ"},
                ],
                "metadata": {
                    "source_lang": "en",
                    "target_lang": "zh-Hans",
                    "model": "gpt-4o-mini",
                    "segment_count": 2,
                },
            }
        }
    }
```

- [ ] **Step 3: Run LLM success test to verify RED**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_llm_translate_uses_openai_client_and_returns_translation -q
```

Expected: FAIL because `llm.translate` still raises or does not accept `client_factory`.

- [ ] **Step 4: Implement LLM plugin**

Replace `src/openbbq/builtin_plugins/llm/plugin.py` with:

```python
from __future__ import annotations

import json
import os
from typing import Any


DEFAULT_SYSTEM_PROMPT = (
    "You are a subtitle translation engine. Return JSON only. Preserve segment count, "
    "segment order, and index values. Translate only the text field. Return a JSON "
    'array, where every item has integer "index" and string "text".'
)


def run(request: dict, client_factory=None) -> dict:
    if request.get("tool_name") != "translate":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    parameters = request.get("parameters", {})
    source_lang = _required_string(parameters, "source_lang")
    target_lang = _required_string(parameters, "target_lang")
    model = _required_string(parameters, "model")
    temperature = float(parameters.get("temperature", 0))
    system_prompt = parameters.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    api_key = os.environ.get("OPENBBQ_LLM_API_KEY")
    if not api_key:
        raise RuntimeError("OPENBBQ_LLM_API_KEY is required for llm.translate.")
    base_url = parameters.get("base_url") or os.environ.get("OPENBBQ_LLM_BASE_URL")
    client_factory = _default_client_factory if client_factory is None else client_factory
    client = client_factory(api_key=api_key, base_url=base_url)
    segments = _segments(request)
    request_segments = [
        {
            "index": index,
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "text": str(segment.get("text", "")),
        }
        for index, segment in enumerate(segments)
    ]
    completion = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": _user_message(source_lang, target_lang, request_segments),
            },
        ],
    )
    translated_items = _parse_translation_response(
        _completion_content(completion), expected_count=len(segments)
    )
    translated_segments = [
        {
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "source_text": str(segment.get("text", "")),
            "text": translated_item["text"],
        }
        for segment, translated_item in zip(segments, translated_items, strict=True)
    ]
    return {
        "outputs": {
            "translation": {
                "type": "translation",
                "content": translated_segments,
                "metadata": {
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "model": model,
                    "segment_count": len(translated_segments),
                },
            }
        }
    }


def _default_client_factory(*, api_key: str, base_url: str | None):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai is not installed. Install OpenBBQ with the llm optional dependencies."
        ) from exc
    return OpenAI(api_key=api_key, base_url=base_url)


def _required_string(parameters: dict[str, Any], name: str) -> str:
    value = parameters.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"llm.translate parameter '{name}' must be a non-empty string.")
    return value


def _segments(request: dict) -> list[dict[str, Any]]:
    transcript = request.get("inputs", {}).get("transcript", {})
    if not isinstance(transcript, dict) or "content" not in transcript:
        raise ValueError("llm.translate requires transcript content.")
    content = transcript["content"]
    if not isinstance(content, list) or any(not isinstance(segment, dict) for segment in content):
        raise ValueError("llm.translate transcript content must be a list of objects.")
    for segment in content:
        if "start" not in segment or "end" not in segment:
            raise ValueError("llm.translate transcript segments must include start and end.")
    return content


def _user_message(
    source_lang: str, target_lang: str, segments: list[dict[str, Any]]
) -> str:
    payload = {
        "source_lang": source_lang,
        "target_lang": target_lang,
        "segments": segments,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _completion_content(completion: Any) -> str:
    choices = getattr(completion, "choices", None)
    if not choices:
        raise ValueError("llm.translate received no choices from the model.")
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if not isinstance(content, str):
        raise ValueError("llm.translate model response content must be a string.")
    return content


def _parse_translation_response(content: str, *, expected_count: int) -> list[dict[str, Any]]:
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("llm.translate model response was not valid JSON.") from exc
    if not isinstance(raw, list):
        raise ValueError("llm.translate model response must be an array.")
    raw_segments = raw
    if len(raw_segments) != expected_count:
        raise ValueError(
            f"llm.translate expected {expected_count} translated segments, got {len(raw_segments)}."
        )
    parsed = []
    for expected_index, item in enumerate(raw_segments):
        if not isinstance(item, dict):
            raise ValueError("llm.translate translated segments must be objects.")
        if item.get("index") != expected_index:
            raise ValueError(
                f"llm.translate expected translated segment index {expected_index}, got {item.get('index')}."
            )
        text = item.get("text")
        if not isinstance(text, str):
            raise ValueError("llm.translate translated segment text must be a string.")
        parsed.append({"index": expected_index, "text": text})
    return parsed
```

- [ ] **Step 5: Run LLM success test to verify GREEN**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_llm_translate_uses_openai_client_and_returns_translation -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/openbbq/builtin_plugins/llm/plugin.py tests/test_builtin_plugins.py
git commit -m "feat: Add built-in LLM translation plugin"
```

## Task 4: LLM Error Handling Tests

**Files:**
- Modify: `tests/test_builtin_plugins.py`

- [ ] **Step 1: Add missing API key test**

Add this test:

```python
def test_llm_translate_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENBBQ_LLM_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENBBQ_LLM_API_KEY"):
        llm_plugin.run(
            {
                "tool_name": "translate",
                "parameters": {
                    "source_lang": "en",
                    "target_lang": "zh-Hans",
                    "model": "gpt-4o-mini",
                },
                "inputs": {
                    "transcript": {
                        "type": "asr_transcript",
                        "content": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
                    }
                },
            },
            client_factory=RecordingOpenAIClientFactory("[]"),
        )
```

Ensure `tests/test_builtin_plugins.py` imports `pytest`:

```python
import pytest
```

- [ ] **Step 2: Add malformed response test**

Add this test:

```python
def test_llm_translate_rejects_malformed_model_json(monkeypatch):
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "test-key")
    factory = RecordingOpenAIClientFactory('[{"index": 1, "text": "错位"}]')

    with pytest.raises(ValueError, match="expected translated segment index 0"):
        llm_plugin.run(
            {
                "tool_name": "translate",
                "parameters": {
                    "source_lang": "en",
                    "target_lang": "zh-Hans",
                    "model": "gpt-4o-mini",
                },
                "inputs": {
                    "transcript": {
                        "type": "asr_transcript",
                        "content": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
                    }
                },
            },
            client_factory=factory,
        )
```

- [ ] **Step 3: Run error tests**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py::test_llm_translate_requires_api_key tests/test_builtin_plugins.py::test_llm_translate_rejects_malformed_model_json -q
```

Expected: PASS.

- [ ] **Step 4: Run all built-in plugin tests**

Run:

```bash
uv run pytest tests/test_builtin_plugins.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add tests/test_builtin_plugins.py
git commit -m "test: Cover LLM translation error paths"
```

## Task 5: Canonical Translated Subtitle Fixture

**Files:**
- Create: `tests/fixtures/projects/local-video-translate-subtitle/openbbq.yaml`
- Modify: `tests/test_fixtures.py`

- [ ] **Step 1: Create fixture file**

Create `tests/fixtures/projects/local-video-translate-subtitle/openbbq.yaml`:

```yaml
version: 1

project:
  id: local-video-translate-subtitle
  name: Local Video Translate Subtitle

workflows:
  local-video-translate-subtitle:
    name: Local Video Translate Subtitle
    steps:
      - id: extract_audio
        name: Extract Audio
        tool_ref: ffmpeg.extract_audio
        inputs:
          video: project.art_imported_video
        outputs:
          - name: audio
            type: audio
        parameters:
          format: wav
          sample_rate: 16000
          channels: 1
        on_error: abort
        max_retries: 0

      - id: transcribe
        name: Transcribe
        tool_ref: faster_whisper.transcribe
        inputs:
          audio: extract_audio.audio
        outputs:
          - name: transcript
            type: asr_transcript
        parameters:
          model: base
          device: cpu
          compute_type: int8
          word_timestamps: true
        on_error: abort
        max_retries: 0

      - id: glossary
        name: Apply Glossary
        tool_ref: glossary.replace
        inputs:
          transcript: transcribe.transcript
        outputs:
          - name: transcript
            type: asr_transcript
        parameters:
          rules:
            - find: Open BBQ
              replace: OpenBBQ
              is_regex: false
              case_sensitive: false
        on_error: abort
        max_retries: 0

      - id: translate
        name: Translate
        tool_ref: llm.translate
        inputs:
          transcript: glossary.transcript
        outputs:
          - name: translation
            type: translation
        parameters:
          source_lang: en
          target_lang: zh-Hans
          model: gpt-4o-mini
          temperature: 0
        on_error: abort
        max_retries: 0

      - id: subtitle
        name: Export Subtitle
        tool_ref: subtitle.export
        inputs:
          translation: translate.translation
        outputs:
          - name: subtitle
            type: subtitle
        parameters:
          format: srt
        on_error: abort
        max_retries: 0
```

- [ ] **Step 2: Add failing fixture validation test**

Append to `tests/test_fixtures.py`:

```python
def test_local_video_translate_subtitle_fixture_uses_builtin_plugins():
    config = load_project_config(FIXTURES / "projects/local-video-translate-subtitle")
    registry = discover_plugins(config.plugin_paths)

    assert "ffmpeg.extract_audio" in registry.tools
    assert "faster_whisper.transcribe" in registry.tools
    assert "glossary.replace" in registry.tools
    assert "llm.translate" in registry.tools
    assert "subtitle.export" in registry.tools
```

- [ ] **Step 3: Run fixture test**

Run:

```bash
uv run pytest tests/test_fixtures.py::test_local_video_translate_subtitle_fixture_uses_builtin_plugins -q
```

Expected: PASS after Tasks 1 through 4.

- [ ] **Step 4: Run fixture suite**

Run:

```bash
uv run pytest tests/test_fixtures.py tests/test_config.py tests/test_engine_validate.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add tests/fixtures/projects/local-video-translate-subtitle/openbbq.yaml tests/test_fixtures.py
git commit -m "docs: Add translated local video workflow fixture"
```

## Task 6: Deterministic CLI End-To-End Translation Workflow

**Files:**
- Create: `tests/test_phase2_translation_slice.py`

- [ ] **Step 1: Write deterministic E2E test**

Create `tests/test_phase2_translation_slice.py`:

```python
import json
from pathlib import Path

from openbbq.cli.app import main


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeChatCompletions:
    def create(self, **kwargs):
        user_content = kwargs["messages"][1]["content"]
        request = json.loads(user_content)
        translated = [
            {"index": segment["index"], "text": f"[zh-Hans] {segment['text']}"}
            for segment in request["segments"]
        ]
        return FakeCompletion(json.dumps(translated, ensure_ascii=False))


class FakeChat:
    completions = FakeChatCompletions()


class FakeOpenAIClient:
    chat = FakeChat()


def write_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path(
        "tests/fixtures/projects/local-video-translate-subtitle/openbbq.yaml"
    ).read_text(encoding="utf-8")
    (project / "openbbq.yaml").write_text(source, encoding="utf-8")
    return project


def test_cli_runs_local_video_translate_subtitle_with_fake_plugins(
    tmp_path, monkeypatch, capsys
):
    from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin
    from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin
    from openbbq.builtin_plugins.llm import plugin as llm_plugin

    def fake_runner(command):
        Path(command[-1]).write_bytes(b"audio")

    class FakeSegment:
        start = 0.0
        end = 1.0
        text = "Hello Open BBQ"
        avg_logprob = -0.1
        words = []

    class FakeInfo:
        language = "en"
        duration = 1.0

    class FakeWhisperModel:
        def __init__(self, model, device, compute_type):
            pass

        def transcribe(self, audio_path, language=None, word_timestamps=True, vad_filter=False):
            return [FakeSegment()], FakeInfo()

    def fake_client_factory(*, api_key, base_url):
        return FakeOpenAIClient()

    monkeypatch.setattr(ffmpeg_plugin, "_run_subprocess", fake_runner)
    monkeypatch.setattr(whisper_plugin, "_default_model_factory", FakeWhisperModel)
    monkeypatch.setattr(llm_plugin, "_default_client_factory", fake_client_factory)
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "test-key")
    monkeypatch.setenv("OPENBBQ_LLM_BASE_URL", "https://llm.example/v1")

    project = write_project(tmp_path)
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"video")

    assert (
        main(
            [
                "--project",
                str(project),
                "--json",
                "artifact",
                "import",
                str(video),
                "--type",
                "video",
                "--name",
                "source.video",
            ]
        )
        == 0
    )
    imported = json.loads(capsys.readouterr().out)
    artifact_id = imported["artifact"]["id"]

    config_path = project / "openbbq.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "project.art_imported_video", f"project.{artifact_id}"
        ),
        encoding="utf-8",
    )

    assert (
        main(["--project", str(project), "--json", "run", "local-video-translate-subtitle"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "completed"

    assert (
        main(
            [
                "--project",
                str(project),
                "--json",
                "artifact",
                "list",
                "--workflow",
                "local-video-translate-subtitle",
            ]
        )
        == 0
    )
    artifacts = json.loads(capsys.readouterr().out)["artifacts"]
    assert [artifact["name"] for artifact in artifacts] == [
        "extract_audio.audio",
        "transcribe.transcript",
        "glossary.transcript",
        "translate.translation",
        "subtitle.subtitle",
    ]

    subtitle_id = artifacts[-1]["id"]
    assert main(["--project", str(project), "--json", "artifact", "show", subtitle_id]) == 0
    subtitle = json.loads(capsys.readouterr().out)
    assert "[zh-Hans] Hello OpenBBQ" in subtitle["current_version"]["content"]
```

- [ ] **Step 2: Run E2E test**

Run:

```bash
uv run pytest tests/test_phase2_translation_slice.py -q
```

Expected: PASS after Tasks 1 through 5.

- [ ] **Step 3: Run related integration tests**

Run:

```bash
uv run pytest tests/test_phase2_translation_slice.py tests/test_phase2_local_video_subtitle.py tests/test_cli_integration.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

Run:

```bash
git add tests/test_phase2_translation_slice.py
git commit -m "test: Add deterministic translated subtitle workflow"
```

## Task 7: Documentation Updates

**Files:**
- Modify: `README.md`
- Modify: `docs/Target-Workflows.md`
- Modify: `docs/Roadmap.md`

- [ ] **Step 1: Update README**

Add this section after the Phase 2 local media preview section:

```markdown
## Phase 2 Translation Preview

Slice 2 adds deterministic glossary replacement and OpenAI-compatible LLM translation to the local video subtitle workflow. Install both optional dependency groups before running real local translated subtitle smoke tests:

```bash
uv sync --extra media --extra llm
export OPENBBQ_LLM_API_KEY=sk-your-key
export OPENBBQ_LLM_BASE_URL=https://api.openai.com/v1
cp -R tests/fixtures/projects/local-video-translate-subtitle ./demo-translate
uv run openbbq artifact import ./sample.mp4 --type video --name source.video --project ./demo-translate
# Replace project.art_imported_video in ./demo-translate/openbbq.yaml with the returned project.<artifact-id>.
uv run openbbq run local-video-translate-subtitle --project ./demo-translate
```

Default CI uses fake media and fake OpenAI clients; it does not require LLM credentials or network access.
```

- [ ] **Step 2: Update `docs/Roadmap.md` Phase 2**

Replace the current Phase 2 heading and goal with:

```markdown
## Phase 2 — Real Local Media and Translation Plugins

**Goal:** Make the CLI run real local media language workflows before adding an API or desktop surface.

- Local file import and file-backed media artifacts
- Built-in ffmpeg audio extraction
- Built-in faster-whisper transcription
- Built-in glossary replacement
- Built-in OpenAI-compatible LLM translation
- Built-in subtitle export
- Deterministic tests with optional local real-media and real-LLM smoke runs

> Agent and API surfaces move to a later phase after real CLI-driven workflows are stable.
```

- [ ] **Step 3: Update `docs/Target-Workflows.md` availability table**

Update the Phase Availability table to:

```markdown
| Step | Plugin | Phase |
|---|---|---|
| Retrieve YouTube video | `youtube.download` | Later phase |
| Convert to audio | `ffmpeg.extract_audio` | Phase 2 Slice 1 |
| ASR recognition | `faster_whisper.transcribe` | Phase 2 Slice 1 |
| Rule / glossary replacement | `glossary.replace` | Phase 2 Slice 2 |
| Translation (LLM) | `llm.translate` | Phase 2 Slice 2 |
| Export subtitle | `subtitle.export` | Phase 2 Slice 1 |
```

- [ ] **Step 4: Run docs-adjacent tests**

Run:

```bash
uv run pytest tests/test_fixtures.py tests/test_package_layout.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add README.md docs/Target-Workflows.md docs/Roadmap.md
git commit -m "docs: Document translated subtitle workflow"
```

## Task 8: Full Verification

**Files:**
- All files changed by Tasks 1 through 7.

- [ ] **Step 1: Sync default dependencies**

Run:

```bash
uv sync
```

Expected: command exits 0.

- [ ] **Step 2: Verify LLM optional dependencies can sync**

Run:

```bash
uv sync --extra llm
```

Expected: command exits 0 and installs `openai`.

- [ ] **Step 3: Run full test suite**

Run:

```bash
uv run pytest
```

Expected: all tests pass.

- [ ] **Step 4: Run lint**

Run:

```bash
uv run ruff check .
```

Expected: all checks pass.

- [ ] **Step 5: Run format check**

Run:

```bash
uv run ruff format --check .
```

Expected: all files already formatted.

- [ ] **Step 6: Run CLI validation smoke**

Run:

```bash
uv run openbbq validate text-demo --project tests/fixtures/projects/text-basic
```

Expected: `Workflow 'text-demo' is valid.`

- [ ] **Step 7: Validate translated fixture**

Run:

```bash
uv run openbbq validate local-video-translate-subtitle --project tests/fixtures/projects/local-video-translate-subtitle
```

Expected: `Workflow 'local-video-translate-subtitle' is valid.`

- [ ] **Step 8: Build wheel**

Run:

```bash
uv build --wheel --out-dir tmp/translation-wheel
```

Expected: command exits 0 and the build log includes both `openbbq/builtin_plugins/glossary/openbbq.plugin.toml` and `openbbq/builtin_plugins/llm/openbbq.plugin.toml`.

- [ ] **Step 9: Confirm git status**

Run:

```bash
git status --short
```

Expected: no uncommitted changes after all task commits.

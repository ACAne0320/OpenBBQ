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

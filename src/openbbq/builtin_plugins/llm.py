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

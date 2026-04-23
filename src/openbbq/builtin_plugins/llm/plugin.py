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


def _user_message(source_lang: str, target_lang: str, segments: list[dict[str, Any]]) -> str:
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
    if len(raw) != expected_count:
        raise ValueError(
            f"llm.translate expected {expected_count} translated segments, got {len(raw)}."
        )
    parsed = []
    for expected_index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("llm.translate translated segments must be objects.")
        if item.get("index") != expected_index:
            raise ValueError(
                "llm.translate expected translated segment index "
                f"{expected_index}, got {item.get('index')}."
            )
        text = item.get("text")
        if not isinstance(text, str):
            raise ValueError("llm.translate translated segment text must be a string.")
        parsed.append({"index": expected_index, "text": text})
    return parsed

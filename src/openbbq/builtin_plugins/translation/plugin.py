from __future__ import annotations

import json
import os
from typing import Any


DEFAULT_SYSTEM_PROMPT = (
    "You are a subtitle translation engine. Return JSON only. Preserve segment count, "
    "segment order, and index values. Translate only the text field. Return a JSON "
    'array, where every item has integer "index" and string "text".'
)
DEFAULT_MAX_SEGMENTS_PER_REQUEST = 20
DEFAULT_PROVIDER = "openai_compatible"


def run(request: dict, client_factory=None) -> dict:
    effective_client_factory = _default_client_factory if client_factory is None else client_factory
    return run_translation(
        request,
        client_factory=effective_client_factory,
        error_prefix="translation.translate",
        include_provider_metadata=True,
    )


def run_translation(
    request: dict,
    *,
    client_factory,
    error_prefix: str,
    include_provider_metadata: bool,
) -> dict:
    if request.get("tool_name") != "translate":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    parameters = request.get("parameters", {})
    provider = str(parameters.get("provider", DEFAULT_PROVIDER))
    if provider != DEFAULT_PROVIDER:
        raise ValueError(f"{error_prefix} parameter 'provider' must be '{DEFAULT_PROVIDER}'.")
    source_lang = _required_string(parameters, "source_lang", error_prefix=error_prefix)
    target_lang = _required_string(parameters, "target_lang", error_prefix=error_prefix)
    model = _required_string(parameters, "model", error_prefix=error_prefix)
    temperature = float(parameters.get("temperature", 0))
    system_prompt = parameters.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    api_key = os.environ.get("OPENBBQ_LLM_API_KEY")
    if not api_key:
        raise RuntimeError(f"OPENBBQ_LLM_API_KEY is required for {error_prefix}.")
    base_url = parameters.get("base_url") or os.environ.get("OPENBBQ_LLM_BASE_URL")
    client = client_factory(api_key=api_key, base_url=base_url)
    segments = _segments(request, error_prefix=error_prefix)
    translated_segments = []
    for chunk in _segment_chunks(
        segments, DEFAULT_MAX_SEGMENTS_PER_REQUEST, error_prefix=error_prefix
    ):
        translated_segments.extend(
            _translate_chunk(
                client=client,
                chunk=chunk,
                model=model,
                temperature=temperature,
                system_prompt=system_prompt,
                source_lang=source_lang,
                target_lang=target_lang,
                error_prefix=error_prefix,
            )
        )
    metadata = {
        "source_lang": source_lang,
        "target_lang": target_lang,
        "model": model,
        "segment_count": len(translated_segments),
    }
    if include_provider_metadata:
        metadata["provider"] = provider
    return {
        "outputs": {
            "translation": {
                "type": "translation",
                "content": translated_segments,
                "metadata": metadata,
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


def _translate_chunk(
    *,
    client: Any,
    chunk: list[dict[str, Any]],
    model: str,
    temperature: float,
    system_prompt: str,
    source_lang: str,
    target_lang: str,
    error_prefix: str,
) -> list[dict[str, Any]]:
    try:
        return _translate_chunk_once(
            client=client,
            chunk=chunk,
            model=model,
            temperature=temperature,
            system_prompt=system_prompt,
            source_lang=source_lang,
            target_lang=target_lang,
            error_prefix=error_prefix,
        )
    except ValueError:
        if len(chunk) <= 1:
            raise
    midpoint = len(chunk) // 2
    return _translate_chunk(
        client=client,
        chunk=chunk[:midpoint],
        model=model,
        temperature=temperature,
        system_prompt=system_prompt,
        source_lang=source_lang,
        target_lang=target_lang,
        error_prefix=error_prefix,
    ) + _translate_chunk(
        client=client,
        chunk=chunk[midpoint:],
        model=model,
        temperature=temperature,
        system_prompt=system_prompt,
        source_lang=source_lang,
        target_lang=target_lang,
        error_prefix=error_prefix,
    )


def _translate_chunk_once(
    *,
    client: Any,
    chunk: list[dict[str, Any]],
    model: str,
    temperature: float,
    system_prompt: str,
    source_lang: str,
    target_lang: str,
    error_prefix: str,
) -> list[dict[str, Any]]:
    request_segments = [
        {
            "index": index,
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "text": str(segment.get("text", "")),
        }
        for index, segment in enumerate(chunk)
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
        _completion_content(completion, error_prefix=error_prefix),
        expected_count=len(chunk),
        error_prefix=error_prefix,
    )
    return [
        {
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "source_text": str(segment.get("text", "")),
            "text": translated_item["text"],
        }
        for segment, translated_item in zip(chunk, translated_items, strict=True)
    ]


def _required_string(parameters: dict[str, Any], name: str, *, error_prefix: str) -> str:
    value = parameters.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{error_prefix} parameter '{name}' must be a non-empty string.")
    return value


def _segments(request: dict, *, error_prefix: str) -> list[dict[str, Any]]:
    transcript = request.get("inputs", {}).get("transcript", {})
    if not isinstance(transcript, dict) or "content" not in transcript:
        raise ValueError(f"{error_prefix} requires transcript content.")
    content = transcript["content"]
    if not isinstance(content, list) or any(not isinstance(segment, dict) for segment in content):
        raise ValueError(f"{error_prefix} transcript content must be a list of objects.")
    for segment in content:
        if "start" not in segment or "end" not in segment:
            raise ValueError(f"{error_prefix} transcript segments must include start and end.")
    return content


def _user_message(source_lang: str, target_lang: str, segments: list[dict[str, Any]]) -> str:
    payload = {
        "source_lang": source_lang,
        "target_lang": target_lang,
        "segments": segments,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _completion_content(completion: Any, *, error_prefix: str) -> str:
    choices = getattr(completion, "choices", None)
    if not choices:
        raise ValueError(f"{error_prefix} received no choices from the model.")
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if not isinstance(content, str):
        raise ValueError(f"{error_prefix} model response content must be a string.")
    return content


def _segment_chunks(
    segments: list[dict[str, Any]], chunk_size: int, *, error_prefix: str
) -> list[list[dict[str, Any]]]:
    if chunk_size <= 0:
        raise ValueError(f"{error_prefix} chunk size must be positive.")
    return [segments[index : index + chunk_size] for index in range(0, len(segments), chunk_size)]


def _parse_translation_response(
    content: str, *, expected_count: int, error_prefix: str
) -> list[dict[str, Any]]:
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{error_prefix} model response was not valid JSON.") from exc
    if not isinstance(raw, list):
        raise ValueError(f"{error_prefix} model response must be an array.")
    if len(raw) != expected_count:
        raise ValueError(
            f"{error_prefix} expected {expected_count} translated segments, got {len(raw)}."
        )
    parsed = []
    for expected_index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{error_prefix} translated segments must be objects.")
        if item.get("index") != expected_index:
            raise ValueError(
                f"{error_prefix} expected translated segment index {expected_index}, got {item.get('index')}."
            )
        text = item.get("text")
        if not isinstance(text, str):
            raise ValueError(f"{error_prefix} translated segment text must be a string.")
        parsed.append({"index": expected_index, "text": text})
    return parsed

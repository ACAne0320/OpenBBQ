from __future__ import annotations

import json
import re
from typing import Any

from openbbq.builtin_plugins.glossary.rules import normalize_rules, source_matches
from openbbq.runtime.provider import llm_provider_from_request


DEFAULT_SYSTEM_PROMPT = (
    "You are a subtitle translation engine. Return JSON only. Preserve segment count, "
    "segment order, and index values. Translate only the text field. Return a JSON "
    'array, where every item has integer "index" and string "text".'
)
DEFAULT_MAX_SEGMENTS_PER_REQUEST = 20
DEFAULT_PROVIDER = "openai_compatible"
DEFAULT_MAX_LINES = 2
DEFAULT_MAX_CHARS_PER_LINE = 42
DEFAULT_MAX_CHARS_PER_SECOND = 20.0
NUMBER_RE = re.compile(r"\d+(?:[.,:]\d+)*")
WHITESPACE_RE = re.compile(r"\s+")


def run(request: dict, client_factory=None) -> dict:
    tool_name = request.get("tool_name")
    if tool_name == "translate":
        effective_client_factory = (
            _default_client_factory if client_factory is None else client_factory
        )
        return run_translation(
            request,
            client_factory=effective_client_factory,
            error_prefix="translation.translate",
            include_provider_metadata=True,
            input_names=("subtitle_segments", "transcript"),
        )
    if tool_name == "qa":
        return run_qa(request)
    raise ValueError(f"Unsupported tool: {tool_name}")


def run_translation(
    request: dict,
    *,
    client_factory,
    error_prefix: str,
    include_provider_metadata: bool,
    input_names: tuple[str, ...],
) -> dict:
    if request.get("tool_name") != "translate":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    parameters = request.get("parameters", {})
    provider = llm_provider_from_request(request, error_prefix=error_prefix)
    source_lang = _required_string(parameters, "source_lang", error_prefix=error_prefix)
    target_lang = _required_string(parameters, "target_lang", error_prefix=error_prefix)
    model_value = parameters.get("model") or provider.model_default
    if not isinstance(model_value, str) or not model_value.strip():
        raise ValueError(f"{error_prefix} parameter 'model' must be a non-empty string.")
    model = model_value.strip()
    temperature = float(parameters.get("temperature", 0))
    system_prompt = parameters.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    glossary_rules = normalize_rules(
        parameters.get("glossary_rules", []),
        parameter_name="glossary_rules",
        tool_name=error_prefix,
    )
    client = client_factory(api_key=provider.api_key, base_url=provider.base_url)
    segments = _timed_segments_any(request, input_names=input_names, error_prefix=error_prefix)
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
                glossary_rules=glossary_rules,
                error_prefix=error_prefix,
            )
        )
    metadata = {
        "source_lang": source_lang,
        "target_lang": target_lang,
        "model": model,
        "segment_count": len(translated_segments),
        "glossary_rule_count": len(glossary_rules),
    }
    if include_provider_metadata:
        metadata["provider"] = provider.name
    return {
        "outputs": {
            "translation": {
                "type": "translation",
                "content": translated_segments,
                "metadata": metadata,
            }
        }
    }


def run_qa(request: dict) -> dict:
    if request.get("tool_name") != "qa":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    parameters = request.get("parameters", {})
    glossary_rules = normalize_rules(
        parameters.get("glossary_rules", []),
        parameter_name="glossary_rules",
        tool_name="translation.qa",
    )
    max_lines = _positive_int(parameters.get("max_lines", DEFAULT_MAX_LINES), "max_lines")
    max_chars_per_line = _positive_int(
        parameters.get("max_chars_per_line", DEFAULT_MAX_CHARS_PER_LINE),
        "max_chars_per_line",
    )
    max_chars_per_second = _positive_float(
        parameters.get("max_chars_per_second", DEFAULT_MAX_CHARS_PER_SECOND),
        "max_chars_per_second",
    )
    segments = _timed_segments(request, input_name="translation", error_prefix="translation.qa")
    issues: list[dict[str, Any]] = []
    issue_counts: dict[str, int] = {}
    segments_with_issues: set[int] = set()

    for index, segment in enumerate(segments):
        source_text = str(segment.get("source_text", ""))
        translated_text = str(segment.get("text", ""))
        duration_seconds = max(float(segment["end"]) - float(segment["start"]), 0.001)
        lines = translated_text.splitlines() or [translated_text]
        longest_line_length = max((len(line) for line in lines), default=0)
        chars_per_second = len(WHITESPACE_RE.sub("", translated_text)) / duration_seconds

        if len(lines) > max_lines:
            _add_issue(
                issues,
                issue_counts,
                segments_with_issues,
                segment_index=index,
                code="too_many_lines",
                message=(
                    f"Translated subtitle uses {len(lines)} lines; configured maximum is "
                    f"{max_lines}."
                ),
                details={"line_count": len(lines), "max_lines": max_lines},
            )
        if longest_line_length > max_chars_per_line:
            _add_issue(
                issues,
                issue_counts,
                segments_with_issues,
                segment_index=index,
                code="line_too_long",
                message=(
                    f"Translated subtitle line length {longest_line_length} exceeds the "
                    f"configured maximum of {max_chars_per_line}."
                ),
                details={
                    "longest_line_length": longest_line_length,
                    "max_chars_per_line": max_chars_per_line,
                },
            )
        if chars_per_second > max_chars_per_second:
            _add_issue(
                issues,
                issue_counts,
                segments_with_issues,
                segment_index=index,
                code="cps_too_high",
                message=(
                    f"Translated subtitle reads at {chars_per_second:.2f} chars/s; configured "
                    f"maximum is {max_chars_per_second:.2f}."
                ),
                details={
                    "chars_per_second": round(chars_per_second, 2),
                    "max_chars_per_second": max_chars_per_second,
                },
            )

        source_numbers = NUMBER_RE.findall(source_text)
        translated_numbers = NUMBER_RE.findall(translated_text)
        if source_numbers != translated_numbers:
            _add_issue(
                issues,
                issue_counts,
                segments_with_issues,
                segment_index=index,
                code="number_mismatch",
                message="Translated subtitle numbers do not match the source segment.",
                details={
                    "source_numbers": source_numbers,
                    "translated_numbers": translated_numbers,
                },
            )

        for rule in glossary_rules:
            if not source_text or not source_matches(source_text, rule):
                continue
            target_term = str(rule["target"])
            if _contains_term(
                translated_text, target_term, case_sensitive=rule.get("case_sensitive")
            ):
                continue
            _add_issue(
                issues,
                issue_counts,
                segments_with_issues,
                segment_index=index,
                code="term_mismatch",
                message=(
                    f"Translated subtitle did not preserve expected terminology '{target_term}'."
                ),
                details={
                    "source_term": rule["source"],
                    "expected_target": target_term,
                },
            )

    summary = {
        "segment_count": len(segments),
        "issue_count": len(issues),
        "segments_with_issues": len(segments_with_issues),
        "glossary_rule_count": len(glossary_rules),
    }
    for code, count in sorted(issue_counts.items()):
        summary[f"{code}_count"] = count
    return {
        "outputs": {
            "qa": {
                "type": "translation_qa",
                "content": {
                    "issues": issues,
                    "summary": summary,
                },
                "metadata": summary,
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
    glossary_rules: list[dict[str, Any]],
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
            glossary_rules=glossary_rules,
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
        glossary_rules=glossary_rules,
        error_prefix=error_prefix,
    ) + _translate_chunk(
        client=client,
        chunk=chunk[midpoint:],
        model=model,
        temperature=temperature,
        system_prompt=system_prompt,
        source_lang=source_lang,
        target_lang=target_lang,
        glossary_rules=glossary_rules,
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
    glossary_rules: list[dict[str, Any]],
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
                "content": _user_message(
                    source_lang,
                    target_lang,
                    request_segments,
                    glossary_rules=glossary_rules,
                ),
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


def _positive_int(value: Any, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"translation.qa parameter '{name}' must be positive.")
    return parsed


def _positive_float(value: Any, name: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise ValueError(f"translation.qa parameter '{name}' must be positive.")
    return parsed


def _timed_segments(request: dict, *, input_name: str, error_prefix: str) -> list[dict[str, Any]]:
    artifact = request.get("inputs", {}).get(input_name, {})
    if not isinstance(artifact, dict) or "content" not in artifact:
        raise ValueError(f"{error_prefix} requires {input_name} content.")
    content = artifact["content"]
    if not isinstance(content, list) or any(not isinstance(segment, dict) for segment in content):
        raise ValueError(f"{error_prefix} {input_name} content must be a list of objects.")
    for segment in content:
        if "start" not in segment or "end" not in segment:
            raise ValueError(f"{error_prefix} {input_name} segments must include start and end.")
    return content


def _timed_segments_any(
    request: dict, *, input_names: tuple[str, ...], error_prefix: str
) -> list[dict[str, Any]]:
    for input_name in input_names:
        artifact = request.get("inputs", {}).get(input_name)
        if isinstance(artifact, dict) and "content" in artifact:
            return _timed_segments(request, input_name=input_name, error_prefix=error_prefix)
    return _timed_segments(request, input_name=input_names[0], error_prefix=error_prefix)


def _user_message(
    source_lang: str,
    target_lang: str,
    segments: list[dict[str, Any]],
    *,
    glossary_rules: list[dict[str, Any]],
) -> str:
    payload: dict[str, Any] = {
        "source_lang": source_lang,
        "target_lang": target_lang,
        "segments": segments,
    }
    if glossary_rules:
        payload["glossary_rules"] = glossary_rules
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


def _contains_term(text: str, term: str, *, case_sensitive: bool | None) -> bool:
    if case_sensitive:
        return term in text
    return term.lower() in text.lower()


def _add_issue(
    issues: list[dict[str, Any]],
    issue_counts: dict[str, int],
    segments_with_issues: set[int],
    *,
    segment_index: int,
    code: str,
    message: str,
    details: dict[str, Any],
) -> None:
    issues.append(
        {
            "segment_index": segment_index,
            "code": code,
            "severity": "warning",
            "message": message,
            "details": details,
        }
    )
    issue_counts[code] = issue_counts.get(code, 0) + 1
    segments_with_issues.add(segment_index)

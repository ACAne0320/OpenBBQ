from __future__ import annotations

from copy import deepcopy
import json
import os
import re
from typing import Any

from openbbq.builtin_plugins.glossary.rules import normalize_rules


DEFAULT_CORRECTION_SYSTEM_PROMPT = (
    "You are a transcript correction engine. Return JSON only. Preserve segment count, "
    "segment order, and index values. Correct source-language transcript text only. "
    'Return a JSON array, where every item has integer "index", string "text", optional '
    'string "status", and optional string "uncertain_reason".'
)
DEFAULT_MAX_SEGMENTS_PER_REQUEST = 20
DEFAULT_MAX_DURATION_SECONDS = 6.0
DEFAULT_MIN_DURATION_SECONDS = 0.8
DEFAULT_MAX_LINES = 2
DEFAULT_MAX_CHARS_PER_LINE = 40
DEFAULT_MAX_CHARS_PER_SECOND = 20.0
DEFAULT_PAUSE_THRESHOLD_MS = 500
SENTENCE_BOUNDARY_RE = re.compile(r"[.!?;:。！？；：]$")


def run(request: dict, client_factory=None) -> dict:
    tool_name = request.get("tool_name")
    if tool_name == "correct":
        return _run_correct(request, client_factory=client_factory)
    if tool_name == "segment":
        return _run_segment(request)
    raise ValueError(f"Unsupported tool: {tool_name}")


def _run_correct(request: dict, *, client_factory=None) -> dict:
    parameters = request.get("parameters", {})
    source_lang = _required_string(parameters, "source_lang", tool_name="transcript.correct")
    model = _required_string(parameters, "model", tool_name="transcript.correct")
    temperature = float(parameters.get("temperature", 0))
    system_prompt = parameters.get("system_prompt") or DEFAULT_CORRECTION_SYSTEM_PROMPT
    max_segments_per_request = int(
        parameters.get("max_segments_per_request", DEFAULT_MAX_SEGMENTS_PER_REQUEST)
    )
    if max_segments_per_request <= 0:
        raise ValueError(
            "transcript.correct parameter 'max_segments_per_request' must be positive."
        )
    api_key = os.environ.get("OPENBBQ_LLM_API_KEY")
    if not api_key:
        raise RuntimeError("OPENBBQ_LLM_API_KEY is required for transcript.correct.")
    base_url = parameters.get("base_url") or os.environ.get("OPENBBQ_LLM_BASE_URL")
    domain_context = _optional_string(parameters.get("domain_context"))
    glossary_rules = _glossary_rules(parameters.get("glossary_rules", []))
    uncertainty_threshold = parameters.get("uncertainty_threshold")
    if uncertainty_threshold is not None:
        uncertainty_threshold = float(uncertainty_threshold)
    client_factory = _default_client_factory if client_factory is None else client_factory
    client = client_factory(api_key=api_key, base_url=base_url)
    segments = _segments(request, error_prefix="transcript.correct")
    corrected_segments: list[dict[str, Any]] = []
    for chunk in _segment_chunks(segments, max_segments_per_request):
        corrected_segments.extend(
            _correct_chunk(
                client=client,
                chunk=chunk,
                model=model,
                source_lang=source_lang,
                temperature=temperature,
                system_prompt=system_prompt,
                domain_context=domain_context,
                glossary_rules=glossary_rules,
                uncertainty_threshold=uncertainty_threshold,
            )
        )
    corrected_count = sum(
        1 for segment in corrected_segments if segment.get("correction_status") == "corrected"
    )
    uncertain_count = sum(
        1 for segment in corrected_segments if segment.get("correction_status") == "uncertain"
    )
    return {
        "outputs": {
            "transcript": {
                "type": "asr_transcript",
                "content": corrected_segments,
                "metadata": {
                    "source_lang": source_lang,
                    "model": model,
                    "segment_count": len(corrected_segments),
                    "corrected_segment_count": corrected_count,
                    "uncertain_segment_count": uncertain_count,
                },
            }
        }
    }


def _run_segment(request: dict) -> dict:
    parameters = request.get("parameters", {})
    max_duration_seconds = float(
        parameters.get("max_duration_seconds", DEFAULT_MAX_DURATION_SECONDS)
    )
    min_duration_seconds = float(
        parameters.get("min_duration_seconds", DEFAULT_MIN_DURATION_SECONDS)
    )
    max_lines = int(parameters.get("max_lines", DEFAULT_MAX_LINES))
    max_chars_per_line = int(parameters.get("max_chars_per_line", DEFAULT_MAX_CHARS_PER_LINE))
    max_chars_per_second = float(
        parameters.get("max_chars_per_second", DEFAULT_MAX_CHARS_PER_SECOND)
    )
    pause_threshold_ms = int(parameters.get("pause_threshold_ms", DEFAULT_PAUSE_THRESHOLD_MS))
    prefer_sentence_boundaries = bool(parameters.get("prefer_sentence_boundaries", True))
    segments = _segments(request, error_prefix="transcript.segment")
    subtitle_segments = _segment_transcript(
        segments=segments,
        max_duration_seconds=max_duration_seconds,
        min_duration_seconds=min_duration_seconds,
        max_lines=max_lines,
        max_chars_per_line=max_chars_per_line,
        max_chars_per_second=max_chars_per_second,
        pause_threshold_seconds=pause_threshold_ms / 1000.0,
        prefer_sentence_boundaries=prefer_sentence_boundaries,
    )
    duration_seconds = float(subtitle_segments[-1]["end"]) if subtitle_segments else 0.0
    return {
        "outputs": {
            "subtitle_segments": {
                "type": "subtitle_segments",
                "content": subtitle_segments,
                "metadata": {
                    "segment_count": len(subtitle_segments),
                    "duration_seconds": duration_seconds,
                    "max_duration_seconds": max_duration_seconds,
                    "max_chars_per_line": max_chars_per_line,
                    "max_lines": max_lines,
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


def _correct_chunk(
    *,
    client: Any,
    chunk: list[dict[str, Any]],
    model: str,
    source_lang: str,
    temperature: float,
    system_prompt: str,
    domain_context: str | None,
    glossary_rules: list[dict[str, Any]],
    uncertainty_threshold: float | None,
) -> list[dict[str, Any]]:
    try:
        return _correct_chunk_once(
            client=client,
            chunk=chunk,
            model=model,
            source_lang=source_lang,
            temperature=temperature,
            system_prompt=system_prompt,
            domain_context=domain_context,
            glossary_rules=glossary_rules,
            uncertainty_threshold=uncertainty_threshold,
        )
    except ValueError:
        if len(chunk) <= 1:
            raise
    midpoint = len(chunk) // 2
    return _correct_chunk(
        client=client,
        chunk=chunk[:midpoint],
        model=model,
        source_lang=source_lang,
        temperature=temperature,
        system_prompt=system_prompt,
        domain_context=domain_context,
        glossary_rules=glossary_rules,
        uncertainty_threshold=uncertainty_threshold,
    ) + _correct_chunk(
        client=client,
        chunk=chunk[midpoint:],
        model=model,
        source_lang=source_lang,
        temperature=temperature,
        system_prompt=system_prompt,
        domain_context=domain_context,
        glossary_rules=glossary_rules,
        uncertainty_threshold=uncertainty_threshold,
    )


def _correct_chunk_once(
    *,
    client: Any,
    chunk: list[dict[str, Any]],
    model: str,
    source_lang: str,
    temperature: float,
    system_prompt: str,
    domain_context: str | None,
    glossary_rules: list[dict[str, Any]],
    uncertainty_threshold: float | None,
) -> list[dict[str, Any]]:
    request_segments = [
        _correction_segment_payload(index, segment, uncertainty_threshold=uncertainty_threshold)
        for index, segment in enumerate(chunk)
    ]
    completion = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": _correction_user_message(
                    source_lang=source_lang,
                    domain_context=domain_context,
                    glossary_rules=glossary_rules,
                    segments=request_segments,
                ),
            },
        ],
    )
    corrected_items = _parse_correction_response(
        _completion_content(completion),
        expected_count=len(chunk),
    )
    output_segments: list[dict[str, Any]] = []
    for segment, corrected_item in zip(chunk, corrected_items, strict=True):
        next_segment = deepcopy(segment)
        source_text = str(segment.get("text", ""))
        corrected_text = corrected_item["text"]
        next_segment["source_text"] = source_text
        next_segment["text"] = corrected_text
        status = corrected_item.get("status")
        if status is None:
            status = "corrected" if corrected_text != source_text else "unchanged"
        next_segment["correction_status"] = status
        reason = corrected_item.get("uncertain_reason")
        if reason is not None:
            next_segment["uncertainty_reason"] = reason
        output_segments.append(next_segment)
    return output_segments


def _correction_user_message(
    *,
    source_lang: str,
    domain_context: str | None,
    glossary_rules: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> str:
    payload: dict[str, Any] = {
        "source_lang": source_lang,
        "segments": segments,
    }
    if domain_context is not None:
        payload["domain_context"] = domain_context
    if glossary_rules:
        payload["glossary_rules"] = glossary_rules
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _correction_segment_payload(
    index: int, segment: dict[str, Any], *, uncertainty_threshold: float | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "index": index,
        "start": float(segment["start"]),
        "end": float(segment["end"]),
        "text": str(segment.get("text", "")),
    }
    confidence = segment.get("confidence")
    if isinstance(confidence, (int, float)):
        payload["confidence"] = float(confidence)
    words = segment.get("words")
    if isinstance(words, list):
        compact_words = []
        low_confidence_words = []
        for word in words:
            if not isinstance(word, dict):
                continue
            entry: dict[str, Any] = {
                "text": str(word.get("text", "")),
            }
            if isinstance(word.get("start"), (int, float)):
                entry["start"] = float(word["start"])
            if isinstance(word.get("end"), (int, float)):
                entry["end"] = float(word["end"])
            if isinstance(word.get("confidence"), (int, float)):
                entry["confidence"] = float(word["confidence"])
                if (
                    uncertainty_threshold is not None
                    and float(word["confidence"]) < uncertainty_threshold
                ):
                    low_confidence_words.append(entry)
            compact_words.append(entry)
        if compact_words:
            payload["words"] = compact_words
        if low_confidence_words:
            payload["low_confidence_words"] = low_confidence_words
    if uncertainty_threshold is not None and isinstance(confidence, (int, float)):
        payload["below_uncertainty_threshold"] = float(confidence) < uncertainty_threshold
    return payload


def _parse_correction_response(content: str, *, expected_count: int) -> list[dict[str, Any]]:
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("transcript.correct model response was not valid JSON.") from exc
    if not isinstance(raw, list):
        raise ValueError("transcript.correct model response must be an array.")
    if len(raw) != expected_count:
        raise ValueError(
            f"transcript.correct expected {expected_count} corrected segments, got {len(raw)}."
        )
    parsed = []
    for expected_index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("transcript.correct corrected segments must be objects.")
        if item.get("index") != expected_index:
            raise ValueError(
                "transcript.correct expected corrected segment index "
                f"{expected_index}, got {item.get('index')}."
            )
        text = item.get("text")
        if not isinstance(text, str):
            raise ValueError("transcript.correct corrected segment text must be a string.")
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


def _glossary_rules(value: Any) -> list[dict[str, Any]]:
    return normalize_rules(
        value,
        parameter_name="glossary_rules",
        tool_name="transcript.correct",
    )


def _run_text(block_units: list[dict[str, Any]]) -> str:
    text = ""
    for unit in block_units:
        text = _append_token(text, unit["text"])
    return text.strip()


def _segment_transcript(
    *,
    segments: list[dict[str, Any]],
    max_duration_seconds: float,
    min_duration_seconds: float,
    max_lines: int,
    max_chars_per_line: int,
    max_chars_per_second: float,
    pause_threshold_seconds: float,
    prefer_sentence_boundaries: bool,
) -> list[dict[str, Any]]:
    units = _segmentation_units(segments)
    if not units:
        return []
    blocks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for unit in units:
        if not current:
            current = [unit]
            continue
        candidate = current + [unit]
        if _should_break_before(
            current=current,
            candidate=candidate,
            next_unit=unit,
            max_duration_seconds=max_duration_seconds,
            min_duration_seconds=min_duration_seconds,
            max_chars_per_line=max_chars_per_line,
            max_lines=max_lines,
            max_chars_per_second=max_chars_per_second,
            pause_threshold_seconds=pause_threshold_seconds,
            prefer_sentence_boundaries=prefer_sentence_boundaries,
        ):
            blocks.append(current)
            current = [unit]
            continue
        current.append(unit)
    if current:
        blocks.append(current)
    return [
        _materialize_block(
            block,
            max_chars_per_line=max_chars_per_line,
            max_lines=max_lines,
        )
        for block in blocks
    ]


def _segmentation_units(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(segments):
        words = segment.get("words")
        text = str(segment.get("text", "")).strip()
        source_text = segment.get("source_text")
        can_split_by_words = (
            isinstance(words, list) and words and (source_text is None or str(source_text) == text)
        )
        if can_split_by_words:
            for word in words:
                if not isinstance(word, dict):
                    continue
                word_text = str(word.get("text", "")).strip()
                if not word_text:
                    continue
                start = float(word.get("start", segment["start"]))
                end = float(word.get("end", start))
                units.append(
                    {
                        "start": start,
                        "end": end,
                        "text": word_text,
                        "source_segment_indexes": [segment_index],
                    }
                )
            if units:
                continue
        if text:
            units.append(
                {
                    "start": float(segment["start"]),
                    "end": float(segment["end"]),
                    "text": text,
                    "source_segment_indexes": [segment_index],
                }
            )
    return units


def _should_break_before(
    *,
    current: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    next_unit: dict[str, Any],
    max_duration_seconds: float,
    min_duration_seconds: float,
    max_chars_per_line: int,
    max_lines: int,
    max_chars_per_second: float,
    pause_threshold_seconds: float,
    prefer_sentence_boundaries: bool,
) -> bool:
    current_text = _run_text(current)
    current_duration = current[-1]["end"] - current[0]["start"]
    pause_gap = next_unit["start"] - current[-1]["end"]
    if pause_gap >= pause_threshold_seconds and current_duration >= min_duration_seconds:
        return True
    if prefer_sentence_boundaries and SENTENCE_BOUNDARY_RE.search(current_text):
        return True
    candidate_text = _run_text(candidate)
    candidate_duration = candidate[-1]["end"] - candidate[0]["start"]
    if candidate_duration > max_duration_seconds:
        return True
    if len(candidate_text) > max_chars_per_line * max_lines:
        return True
    if candidate_duration > 0 and (len(candidate_text) / candidate_duration) > max_chars_per_second:
        return True
    return False


def _materialize_block(
    block: list[dict[str, Any]], *, max_chars_per_line: int, max_lines: int
) -> dict[str, Any]:
    text = _wrap_lines(_run_text(block), max_chars_per_line=max_chars_per_line, max_lines=max_lines)
    source_indexes: list[int] = []
    for unit in block:
        for index in unit.get("source_segment_indexes", []):
            if index not in source_indexes:
                source_indexes.append(index)
    start = float(block[0]["start"])
    end = float(block[-1]["end"])
    duration = max(end - start, 0.001)
    return {
        "start": start,
        "end": end,
        "text": text,
        "source_segment_indexes": source_indexes,
        "word_count": sum(len(str(unit["text"]).split()) for unit in block),
        "line_count": len(text.splitlines()) if text else 1,
        "cps": round(len(text.replace("\n", "")) / duration, 3),
    }


def _wrap_lines(text: str, *, max_chars_per_line: int, max_lines: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars_per_line or max_lines <= 1:
        return normalized
    words = normalized.split(" ")
    lines = [""]
    for word in words:
        candidate = word if not lines[-1] else f"{lines[-1]} {word}"
        if len(candidate) <= max_chars_per_line or len(lines) >= max_lines:
            lines[-1] = candidate
            continue
        lines.append(word)
    if len(lines) > max_lines:
        head = lines[: max_lines - 1]
        tail = " ".join(lines[max_lines - 1 :])
        lines = [*head, tail]
    return "\n".join(lines)


def _append_token(current: str, token: str) -> str:
    if not current:
        return token
    if token.startswith(
        ("'", ".", ",", "!", "?", ";", ":", ")", "]", "}", "。", "，", "！", "？", "；", "：")
    ):
        return f"{current}{token}"
    if current.endswith(("(", "[", "{", '"')):
        return f"{current}{token}"
    return f"{current} {token}"


def _required_string(parameters: dict[str, Any], name: str, *, tool_name: str) -> str:
    value = parameters.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{tool_name} parameter '{name}' must be a non-empty string.")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "transcript.correct parameter 'domain_context' must be a non-empty string."
        )
    return value.strip()


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


def _completion_content(completion: Any) -> str:
    choices = getattr(completion, "choices", None)
    if not choices:
        raise ValueError("transcript.correct received no choices from the model.")
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if not isinstance(content, str):
        raise ValueError("transcript.correct model response content must be a string.")
    return content


def _segment_chunks(segments: list[dict[str, Any]], chunk_size: int) -> list[list[dict[str, Any]]]:
    if chunk_size <= 0:
        raise ValueError("transcript.correct chunk size must be positive.")
    return [segments[index : index + chunk_size] for index in range(0, len(segments), chunk_size)]

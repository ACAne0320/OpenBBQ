from __future__ import annotations

import json
import re
from typing import Any

from openbbq.builtin_plugins.llm import (
    completion_content,
    default_openai_client_factory,
    parse_indexed_text_items,
    segment_chunks,
)
from openbbq.builtin_plugins.glossary.rules import normalize_rules
from openbbq.builtin_plugins.segments import (
    SegmentUnit,
    TimedSegment,
    timed_segments_from_request,
)
from openbbq.builtin_plugins.transcript.models import SegmentationParameters
from openbbq.runtime.provider import llm_provider_from_request


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
DEFAULT_PAUSE_THRESHOLD_MS = 500
SENTENCE_BOUNDARY_RE = re.compile(r"[.!?;:。！？；：]$")
CLAUSE_BOUNDARY_RE = re.compile(r"[,，、]$")
SEGMENTATION_PROFILES: dict[str, dict[str, Any]] = {
    "default": {},
    "readable": {
        "max_duration_seconds": 5.0,
        "max_chars_per_line": 34,
        "pause_threshold_ms": 350,
        "prefer_clause_boundaries": True,
        "merge_short_segments": True,
    },
    "dense": {
        "max_duration_seconds": 7.0,
        "max_chars_per_line": 44,
        "pause_threshold_ms": 650,
    },
    "short_form": {
        "max_duration_seconds": 3.5,
        "max_chars_per_line": 28,
        "pause_threshold_ms": 250,
        "prefer_clause_boundaries": True,
        "merge_short_segments": True,
    },
}


def run(request: dict, client_factory=None) -> dict:
    tool_name = request.get("tool_name")
    if tool_name == "correct":
        return run_correct(request, client_factory=client_factory)
    if tool_name == "segment":
        return run_segment(request)
    raise ValueError(f"Unsupported tool: {tool_name}")


def run_correct(request: dict, client_factory=None) -> dict:
    return _run_correct(request, client_factory=client_factory)


def run_segment(request: dict) -> dict:
    return _run_segment(request)


def _run_correct(request: dict, *, client_factory=None) -> dict:
    parameters = request.get("parameters", {})
    source_lang = _required_string(parameters, "source_lang", tool_name="transcript.correct")
    provider = llm_provider_from_request(request, error_prefix="transcript.correct")
    model_value = parameters.get("model") or provider.model_default
    if not isinstance(model_value, str) or not model_value.strip():
        raise ValueError("transcript.correct parameter 'model' must be a non-empty string.")
    model = model_value.strip()
    temperature = float(parameters.get("temperature", 0))
    system_prompt = parameters.get("system_prompt") or DEFAULT_CORRECTION_SYSTEM_PROMPT
    max_segments_per_request = int(
        parameters.get("max_segments_per_request", DEFAULT_MAX_SEGMENTS_PER_REQUEST)
    )
    if max_segments_per_request <= 0:
        raise ValueError(
            "transcript.correct parameter 'max_segments_per_request' must be positive."
        )
    domain_context = _optional_string(parameters.get("domain_context"))
    glossary_rules = _glossary_rules(parameters.get("glossary_rules", []))
    uncertainty_threshold = parameters.get("uncertainty_threshold")
    if uncertainty_threshold is not None:
        uncertainty_threshold = float(uncertainty_threshold)
    client_factory = _default_client_factory if client_factory is None else client_factory
    client = client_factory(api_key=provider.api_key, base_url=provider.base_url)
    segments = _segments(request, error_prefix="transcript.correct")
    corrected_segments: list[dict[str, Any]] = []
    for chunk in segment_chunks(
        segments,
        max_segments_per_request,
        error_prefix="transcript.correct",
    ):
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
                    "provider": provider.name,
                    "model": model,
                    "segment_count": len(corrected_segments),
                    "corrected_segment_count": corrected_count,
                    "uncertain_segment_count": uncertain_count,
                },
            }
        }
    }


def _run_segment(request: dict) -> dict:
    parameters = _segmentation_parameters(request.get("parameters", {}))
    glossary_rules = _segmentation_glossary_rules(parameters.glossary_rules)
    segments = _segments(request, error_prefix="transcript.segment")
    subtitle_segments = _segment_transcript(
        segments=segments,
        parameters=parameters,
        glossary_rules=glossary_rules,
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
                    "profile": parameters.profile,
                    "language": parameters.language,
                    "max_duration_seconds": parameters.max_duration_seconds,
                    "min_duration_seconds": parameters.min_duration_seconds,
                    "max_chars_per_line": parameters.max_chars_per_line,
                    "max_chars_total": _max_chars_total(parameters),
                    "max_lines": parameters.max_lines,
                    "pause_threshold_ms": parameters.pause_threshold_ms,
                    "prefer_sentence_boundaries": parameters.prefer_sentence_boundaries,
                    "prefer_clause_boundaries": parameters.prefer_clause_boundaries,
                    "merge_short_segments": parameters.merge_short_segments,
                    "protect_terms": parameters.protect_terms,
                    "glossary_rule_count": len(glossary_rules),
                },
            }
        }
    }


_default_client_factory = default_openai_client_factory


def _correct_chunk(
    *,
    client: Any,
    chunk: list[TimedSegment],
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
    chunk: list[TimedSegment],
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
        completion_content(completion, error_prefix="transcript.correct"),
        expected_count=len(chunk),
    )
    output_segments: list[dict[str, Any]] = []
    for segment, corrected_item in zip(chunk, corrected_items, strict=True):
        next_segment = segment.copy_payload()
        source_text = segment.text
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
    index: int, segment: TimedSegment, *, uncertainty_threshold: float | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "index": index,
        "start": segment.start,
        "end": segment.end,
        "text": segment.text,
    }
    confidence = segment.confidence
    if confidence is not None:
        payload["confidence"] = confidence
    if segment.words:
        compact_words: list[dict[str, Any]] = []
        low_confidence_words: list[dict[str, Any]] = []
        for word in segment.words:
            entry: dict[str, Any] = {
                "text": word.text,
            }
            if word.start is not None:
                entry["start"] = word.start
            if word.end is not None:
                entry["end"] = word.end
            if word.confidence is not None:
                entry["confidence"] = word.confidence
                if uncertainty_threshold is not None and word.confidence < uncertainty_threshold:
                    low_confidence_words.append(entry)
            compact_words.append(entry)
        if compact_words:
            payload["words"] = compact_words
        if low_confidence_words:
            payload["low_confidence_words"] = low_confidence_words
    if uncertainty_threshold is not None and isinstance(confidence, (int, float)):
        payload["below_uncertainty_threshold"] = confidence < uncertainty_threshold
    return payload


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


def _glossary_rules(value: Any) -> list[dict[str, Any]]:
    return normalize_rules(
        value,
        parameter_name="glossary_rules",
        tool_name="transcript.correct",
    )


def _segmentation_parameters(value: Any) -> SegmentationParameters:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("transcript.segment parameters must be an object.")
    profile_name = value.get("profile", "default")
    if not isinstance(profile_name, str) or not profile_name.strip():
        raise ValueError("transcript.segment parameter 'profile' must be a non-empty string.")
    profile_name = profile_name.strip()
    if profile_name not in SEGMENTATION_PROFILES:
        profiles = ", ".join(sorted(SEGMENTATION_PROFILES))
        raise ValueError(f"transcript.segment parameter 'profile' must be one of: {profiles}.")
    merged = {
        "profile": profile_name,
        "max_duration_seconds": DEFAULT_MAX_DURATION_SECONDS,
        "min_duration_seconds": DEFAULT_MIN_DURATION_SECONDS,
        "max_lines": DEFAULT_MAX_LINES,
        "max_chars_per_line": DEFAULT_MAX_CHARS_PER_LINE,
        "pause_threshold_ms": DEFAULT_PAUSE_THRESHOLD_MS,
        **SEGMENTATION_PROFILES[profile_name],
        **value,
    }
    return SegmentationParameters.model_validate(merged)


def _segmentation_glossary_rules(value: Any) -> list[dict[str, Any]]:
    return normalize_rules(
        value,
        parameter_name="glossary_rules",
        tool_name="transcript.segment",
    )


def _max_chars_total(parameters: SegmentationParameters) -> int:
    if parameters.max_chars_total is not None:
        return parameters.max_chars_total
    return parameters.max_chars_per_line * parameters.max_lines


def _run_text(block_units: list[SegmentUnit]) -> str:
    text = ""
    for unit in block_units:
        text = _append_token(text, unit.text)
    return text.strip()


def _segment_transcript(
    *,
    segments: list[TimedSegment],
    parameters: SegmentationParameters,
    glossary_rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    units = _segmentation_units(segments)
    if not units:
        return []
    if parameters.protect_terms and glossary_rules:
        units = _protect_glossary_spans(units, glossary_rules)
    blocks: list[list[SegmentUnit]] = []
    current: list[SegmentUnit] = []
    for unit in units:
        if not current:
            current = [unit]
            continue
        candidate = current + [unit]
        if _should_break_before(
            current=current,
            candidate=candidate,
            next_unit=unit,
            parameters=parameters,
        ):
            blocks.append(current)
            current = [unit]
            continue
        current.append(unit)
    if current:
        blocks.append(current)
    if parameters.merge_short_segments:
        blocks = _merge_short_blocks(blocks, parameters=parameters)
    return [
        _materialize_block(
            index,
            block,
            max_chars_per_line=parameters.max_chars_per_line,
            max_lines=parameters.max_lines,
        )
        for index, block in enumerate(blocks)
    ]


def _segmentation_units(segments: list[TimedSegment]) -> list[SegmentUnit]:
    units: list[SegmentUnit] = []
    for segment_index, segment in enumerate(segments):
        text = segment.text.strip()
        source_text = segment.source_text
        can_split_by_words = bool(segment.words) and (source_text is None or source_text == text)
        if can_split_by_words:
            word_units: list[SegmentUnit] = []
            for word_index, word in enumerate(segment.words):
                word_text = word.text.strip()
                if not word_text:
                    continue
                start = word.start if word.start is not None else segment.start
                end = word.end if word.end is not None else start
                word_units.append(
                    SegmentUnit(
                        start=start,
                        end=end,
                        text=word_text,
                        source_segment_indexes=(segment_index,),
                        source_word_refs=(
                            {"segment_index": segment_index, "word_index": word_index},
                        ),
                    )
                )
            units.extend(word_units)
            if word_units:
                continue
        if text:
            units.append(
                SegmentUnit(
                    start=segment.start,
                    end=segment.end,
                    text=text,
                    source_segment_indexes=(segment_index,),
                )
            )
    return units


def _should_break_before(
    *,
    current: list[SegmentUnit],
    candidate: list[SegmentUnit],
    next_unit: SegmentUnit,
    parameters: SegmentationParameters,
) -> bool:
    current_text = _run_text(current)
    current_duration = current[-1].end - current[0].start
    pause_gap = next_unit.start - current[-1].end
    candidate_text = _run_text(candidate)
    candidate_duration = candidate[-1].end - candidate[0].start
    if _splits_protected_span(current[-1], next_unit):
        return False
    if (
        pause_gap >= parameters.pause_threshold_ms / 1000.0
        and current_duration >= parameters.min_duration_seconds
    ):
        return True
    if parameters.prefer_sentence_boundaries and SENTENCE_BOUNDARY_RE.search(current_text):
        return True
    if (
        parameters.prefer_clause_boundaries
        and current_duration >= parameters.min_duration_seconds
        and CLAUSE_BOUNDARY_RE.search(current_text)
    ):
        return True
    if candidate_duration > parameters.max_duration_seconds:
        return True
    if len(candidate_text) > _max_chars_total(parameters):
        return True
    return False


def _splits_protected_span(previous_unit: SegmentUnit, next_unit: SegmentUnit) -> bool:
    if previous_unit.protected_span_id is None:
        return False
    return previous_unit.protected_span_id == next_unit.protected_span_id


def _protect_glossary_spans(
    units: list[SegmentUnit], glossary_rules: list[dict[str, Any]]
) -> list[SegmentUnit]:
    protected_terms = _protected_term_tokens(glossary_rules)
    if not protected_terms:
        return units
    span_ids: list[int | None] = [None] * len(units)
    next_span_id = 1
    normalized_units = [_normalize_term_token(unit.text) for unit in units]
    for term_tokens in protected_terms:
        if not term_tokens or len(term_tokens) < 2:
            continue
        width = len(term_tokens)
        for start_index in range(0, len(units) - width + 1):
            if normalized_units[start_index : start_index + width] != term_tokens:
                continue
            for offset in range(width):
                if span_ids[start_index + offset] is None:
                    span_ids[start_index + offset] = next_span_id
            next_span_id += 1
    if all(span_id is None for span_id in span_ids):
        return units
    return [
        SegmentUnit(
            start=unit.start,
            end=unit.end,
            text=unit.text,
            source_segment_indexes=unit.source_segment_indexes,
            source_word_refs=unit.source_word_refs,
            protected_span_id=span_ids[index],
        )
        for index, unit in enumerate(units)
    ]


def _protected_term_tokens(glossary_rules: list[dict[str, Any]]) -> list[list[str]]:
    terms: list[list[str]] = []
    for rule in glossary_rules:
        if rule.get("protected") is not True:
            continue
        if rule.get("is_regex") is True:
            continue
        candidates = [rule.get("source"), rule.get("target")]
        aliases = rule.get("aliases")
        if isinstance(aliases, list):
            candidates.extend(aliases)
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            tokens = [
                _normalize_term_token(token)
                for token in candidate.split()
                if _normalize_term_token(token)
            ]
            if len(tokens) >= 2 and tokens not in terms:
                terms.append(tokens)
    return terms


def _normalize_term_token(value: str) -> str:
    return re.sub(r"^\W+|\W+$", "", value, flags=re.UNICODE).casefold()


def _merge_short_blocks(
    blocks: list[list[SegmentUnit]], *, parameters: SegmentationParameters
) -> list[list[SegmentUnit]]:
    if len(blocks) < 2 or parameters.min_duration_seconds <= 0:
        return blocks
    merged: list[list[SegmentUnit]] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        duration = block[-1].end - block[0].start
        if duration >= parameters.min_duration_seconds or len(blocks) == 1:
            merged.append(block)
            index += 1
            continue
        previous = merged[-1] if merged else None
        next_block = blocks[index + 1] if index + 1 < len(blocks) else None
        if next_block is not None and _can_merge_blocks(block + next_block, parameters=parameters):
            merged.append(block + next_block)
            index += 2
            continue
        if previous is not None and _can_merge_blocks(previous + block, parameters=parameters):
            merged[-1] = previous + block
            index += 1
            continue
        merged.append(block)
        index += 1
    return merged


def _can_merge_blocks(block: list[SegmentUnit], *, parameters: SegmentationParameters) -> bool:
    text = _run_text(block)
    duration = block[-1].end - block[0].start
    if duration > parameters.max_duration_seconds:
        return False
    if len(text) > _max_chars_total(parameters):
        return False
    if duration < parameters.min_duration_seconds:
        return True
    return True


def _materialize_block(
    block_index: int, block: list[SegmentUnit], *, max_chars_per_line: int, max_lines: int
) -> dict[str, Any]:
    text = _wrap_lines(_run_text(block), max_chars_per_line=max_chars_per_line, max_lines=max_lines)
    source_indexes: list[int] = []
    word_refs: list[dict[str, int]] = []
    for unit in block:
        for source_index in unit.source_segment_indexes:
            if source_index not in source_indexes:
                source_indexes.append(source_index)
        for ref in unit.source_word_refs:
            if ref not in word_refs:
                word_refs.append(ref)
    start = block[0].start
    end = block[-1].end
    duration = max(end - start, 0.001)
    payload: dict[str, Any] = {
        "id": f"seg_{block_index + 1:04d}",
        "start": start,
        "end": end,
        "text": text,
        "source_segment_indexes": source_indexes,
        "word_count": sum(len(unit.text.split()) for unit in block),
        "line_count": len(text.splitlines()) if text else 1,
        "duration_seconds": round(duration, 3),
        "cps": round(len(text.replace("\n", "")) / duration, 3),
    }
    if word_refs:
        payload["word_refs"] = word_refs
    return payload


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


def _segments(request: dict, *, error_prefix: str) -> list[TimedSegment]:
    return timed_segments_from_request(request, input_name="transcript", error_prefix=error_prefix)

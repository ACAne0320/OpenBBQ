from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Any

from openbbq.builtin_plugins.glossary.rules import normalize_rules, source_matches
from openbbq.builtin_plugins.llm import (
    completion_content,
    default_openai_client_factory,
    parse_indexed_text_items,
    segment_chunks,
)
from openbbq.builtin_plugins.segments import (
    TimedSegment,
    timed_segments_from_any_input,
    timed_segments_from_request,
)
from openbbq.runtime.provider import llm_provider_from_request


DEFAULT_SYSTEM_PROMPT = (
    "You are a subtitle translation engine. Return JSON only. Preserve segment count, "
    "segment order, and index values. Translate only the text field. Return a JSON "
    'array, where every item has integer "index" and string "text".'
)
DEFAULT_MAX_SEGMENTS_PER_REQUEST = 20
DEFAULT_MAX_CONCURRENCY = 1
DEFAULT_COMPLETION_RETRY_ROUNDS = 2
DEFAULT_MAX_LINES = 2
DEFAULT_MAX_CHARS_PER_LINE = 42
DEFAULT_MAX_CHARS_PER_SECOND = 20.0
CHECKPOINT_FILENAME = "translation-checkpoint.json"
NUMBER_RE = re.compile(r"\d+(?:[.,:]\d+)*")
WHITESPACE_RE = re.compile(r"\s+")


def run(request: dict, client_factory=None, progress=None) -> dict:
    tool_name = request.get("tool_name")
    if tool_name == "translate":
        if progress is None:
            return run_translate(request, client_factory=client_factory)
        return run_translate(request, client_factory=client_factory, progress=progress)
    if tool_name == "qa":
        return run_qa(request)
    raise ValueError(f"Unsupported tool: {tool_name}")


def run_translate(request: dict, client_factory=None, progress=None) -> dict:
    effective_client_factory = _default_client_factory if client_factory is None else client_factory
    return run_translation(
        request,
        client_factory=effective_client_factory,
        error_prefix="translation.translate",
        include_provider_metadata=True,
        input_names=("subtitle_segments", "transcript"),
        progress=progress,
    )


def run_translation(
    request: dict,
    *,
    client_factory,
    error_prefix: str,
    include_provider_metadata: bool,
    input_names: tuple[str, ...],
    progress=None,
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
    max_segments_per_request = _positive_int_parameter(
        parameters.get("max_segments_per_request", DEFAULT_MAX_SEGMENTS_PER_REQUEST),
        "max_segments_per_request",
        error_prefix=error_prefix,
    )
    max_concurrency = _positive_int_parameter(
        parameters.get("max_concurrency", DEFAULT_MAX_CONCURRENCY),
        "max_concurrency",
        error_prefix=error_prefix,
    )
    completion_retry_rounds = _non_negative_int_parameter(
        parameters.get("completion_retry_rounds", DEFAULT_COMPLETION_RETRY_ROUNDS),
        "completion_retry_rounds",
        error_prefix=error_prefix,
    )
    glossary_rules = normalize_rules(
        parameters.get("glossary_rules", []),
        parameter_name="glossary_rules",
        tool_name=error_prefix,
    )
    client = client_factory(api_key=provider.api_key, base_url=provider.base_url)
    segments = _timed_segments_any(request, input_names=input_names, error_prefix=error_prefix)
    total_segments = len(segments)
    checkpoint_path = _checkpoint_path(request)
    fingerprint = _translation_fingerprint(
        request=request,
        provider_name=provider.name,
        model=model,
        temperature=temperature,
        system_prompt=system_prompt,
        source_lang=source_lang,
        target_lang=target_lang,
        glossary_rules=glossary_rules,
        max_segments_per_request=max_segments_per_request,
        segments=segments,
    )
    completed_by_index = _load_checkpoint(
        checkpoint_path,
        fingerprint=fingerprint,
        segments=segments,
    )
    translated_count = len(completed_by_index)
    _report(
        progress,
        phase="translate",
        label="Translate",
        percent=(translated_count / total_segments) * 100 if total_segments else 0,
        current=translated_count,
        total=total_segments,
        unit="segments",
    )

    if total_segments:
        indexed_segments = list(enumerate(segments))
        primary_groups = [
            [(index, segment) for index, segment in group if index not in completed_by_index]
            for group in segment_chunks(
                indexed_segments,
                max_segments_per_request,
                error_prefix=error_prefix,
            )
        ]
        primary_groups = [group for group in primary_groups if group]
        failures = _translate_groups(
            primary_groups,
            client=client,
            model=model,
            temperature=temperature,
            system_prompt=system_prompt,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary_rules=glossary_rules,
            error_prefix=error_prefix,
            max_concurrency=max_concurrency,
            completed_by_index=completed_by_index,
            checkpoint_path=checkpoint_path,
            fingerprint=fingerprint,
            total_segments=total_segments,
            progress=progress,
        )

        for _round in range(completion_retry_rounds):
            missing_indexes = [
                index for index in range(total_segments) if index not in completed_by_index
            ]
            if not missing_indexes:
                break
            failures = _translate_groups(
                [[(index, segments[index])] for index in missing_indexes],
                client=client,
                model=model,
                temperature=temperature,
                system_prompt=system_prompt,
                source_lang=source_lang,
                target_lang=target_lang,
                glossary_rules=glossary_rules,
                error_prefix=error_prefix,
                max_concurrency=max_concurrency,
                completed_by_index=completed_by_index,
                checkpoint_path=checkpoint_path,
                fingerprint=fingerprint,
                total_segments=total_segments,
                progress=progress,
            )
    else:
        failures = []

    missing_indexes = [index for index in range(total_segments) if index not in completed_by_index]
    if missing_indexes:
        resume_hint = (
            " Resume the workflow to continue from the saved checkpoint."
            if checkpoint_path is not None
            else " Retry the workflow to try the missing segments again."
        )
        message = (
            f"{error_prefix} failed to translate {len(missing_indexes)} of "
            f"{total_segments} segments after completion retries. First missing segment "
            f"index: {missing_indexes[0]}."
        )
        if failures:
            message = f"{message} Last error: {failures[-1][1]}"
        message = f"{message}{resume_hint}"
        error_type = (
            ValueError if failures and isinstance(failures[-1][1], ValueError) else RuntimeError
        )
        raise error_type(message)

    translated_segments = [completed_by_index[index] for index in range(total_segments)]
    if total_segments == 0:
        _report(
            progress,
            phase="translate",
            label="Translate",
            percent=100,
            current=0,
            total=0,
            unit="segments",
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


def _translate_groups(
    groups: list[list[tuple[int, TimedSegment]]],
    *,
    client: Any,
    model: str,
    temperature: float,
    system_prompt: str,
    source_lang: str,
    target_lang: str,
    glossary_rules: list[dict[str, Any]],
    error_prefix: str,
    max_concurrency: int,
    completed_by_index: dict[int, dict[str, Any]],
    checkpoint_path: Path | None,
    fingerprint: str,
    total_segments: int,
    progress=None,
) -> list[tuple[tuple[int, ...], Exception]]:
    if not groups:
        return []
    lock = threading.Lock()
    failures: list[tuple[tuple[int, ...], Exception]] = []

    def translate_group(group: list[tuple[int, TimedSegment]]) -> dict[int, dict[str, Any]]:
        chunk = [segment for _index, segment in group]
        translated = _translate_chunk(
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
        return {
            index: {
                "start": segment.start,
                "end": segment.end,
                "source_text": segment.text,
                "text": translated_item["text"],
            }
            for (index, segment), translated_item in zip(group, translated, strict=True)
        }

    if max_concurrency == 1 or len(groups) == 1:
        for group in groups:
            try:
                translated_by_index = translate_group(group)
            except Exception as exc:
                failures.append((tuple(index for index, _segment in group), exc))
                continue
            _record_translated_segments(
                translated_by_index,
                completed_by_index=completed_by_index,
                checkpoint_path=checkpoint_path,
                fingerprint=fingerprint,
                total_segments=total_segments,
                progress=progress,
                lock=lock,
            )
        return failures

    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        future_groups = {executor.submit(translate_group, group): group for group in groups}
        for future in as_completed(future_groups):
            try:
                translated_by_index = future.result()
            except Exception as exc:
                group = future_groups[future]
                failures.append((tuple(index for index, _segment in group), exc))
                continue
            _record_translated_segments(
                translated_by_index,
                completed_by_index=completed_by_index,
                checkpoint_path=checkpoint_path,
                fingerprint=fingerprint,
                total_segments=total_segments,
                progress=progress,
                lock=lock,
            )
    return failures


def _checkpoint_path(request: dict) -> Path | None:
    work_dir = request.get("work_dir")
    if not isinstance(work_dir, str) or not work_dir.strip():
        return None
    path = Path(work_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return path / CHECKPOINT_FILENAME


def _translation_fingerprint(
    *,
    request: dict,
    provider_name: str,
    model: str,
    temperature: float,
    system_prompt: str,
    source_lang: str,
    target_lang: str,
    glossary_rules: list[dict[str, Any]],
    max_segments_per_request: int,
    segments: list[TimedSegment],
) -> str:
    inputs = request.get("inputs", {})
    input_versions = {
        name: value.get("artifact_version_id")
        for name, value in inputs.items()
        if isinstance(value, dict) and isinstance(value.get("artifact_version_id"), str)
    }
    payload = {
        "version": 1,
        "input_versions": input_versions,
        "provider": provider_name,
        "model": model,
        "temperature": temperature,
        "system_prompt": system_prompt,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "glossary_rules": glossary_rules,
        "max_segments_per_request": max_segments_per_request,
        "segments": [
            {"start": segment.start, "end": segment.end, "text": segment.text}
            for segment in segments
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _load_checkpoint(
    path: Path | None,
    *,
    fingerprint: str,
    segments: list[TimedSegment],
) -> dict[int, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    total_segments = len(segments)
    if raw.get("fingerprint") != fingerprint or raw.get("total_segments") != total_segments:
        return {}
    raw_segments = raw.get("segments")
    if not isinstance(raw_segments, dict):
        return {}
    completed: dict[int, dict[str, Any]] = {}
    for raw_index, raw_segment in raw_segments.items():
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= total_segments or not isinstance(raw_segment, dict):
            continue
        text = raw_segment.get("text")
        if not isinstance(text, str):
            continue
        source_segment = segments[index]
        completed[index] = {
            "start": source_segment.start,
            "end": source_segment.end,
            "source_text": source_segment.text,
            "text": text,
        }
    return completed


def _write_checkpoint(
    path: Path | None,
    *,
    fingerprint: str,
    total_segments: int,
    completed_by_index: dict[int, dict[str, Any]],
) -> None:
    if path is None:
        return
    payload = {
        "version": 1,
        "fingerprint": fingerprint,
        "total_segments": total_segments,
        "segments": {str(index): completed_by_index[index] for index in sorted(completed_by_index)},
    }
    temporary_path = path.with_name(f"{path.name}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError:
        return


def _record_translated_segments(
    translated_by_index: dict[int, dict[str, Any]],
    *,
    completed_by_index: dict[int, dict[str, Any]],
    checkpoint_path: Path | None,
    fingerprint: str,
    total_segments: int,
    progress=None,
    lock: threading.Lock,
) -> None:
    with lock:
        completed_by_index.update(translated_by_index)
        translated_count = len(completed_by_index)
        _write_checkpoint(
            checkpoint_path,
            fingerprint=fingerprint,
            total_segments=total_segments,
            completed_by_index=completed_by_index,
        )
        _report(
            progress,
            phase="translate",
            label="Translate",
            percent=(translated_count / total_segments) * 100 if total_segments else 100,
            current=translated_count,
            total=total_segments,
            unit="segments",
        )


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
        source_text = segment.source_text or ""
        translated_text = segment.text
        duration_seconds = max(segment.end - segment.start, 0.001)
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


_default_client_factory = default_openai_client_factory


def _report(
    progress,
    *,
    phase: str,
    label: str,
    percent: float,
    current=None,
    total=None,
    unit=None,
) -> None:
    if progress is None:
        return
    try:
        progress(
            phase=phase,
            label=label,
            percent=percent,
            current=current,
            total=total,
            unit=unit,
        )
    except Exception:
        return


def _translate_chunk(
    *,
    client: Any,
    chunk: list[TimedSegment],
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
    chunk: list[TimedSegment],
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
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
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
        completion_content(completion, error_prefix=error_prefix),
        expected_count=len(chunk),
        error_prefix=error_prefix,
    )
    return [
        {
            "start": segment.start,
            "end": segment.end,
            "source_text": segment.text,
            "text": translated_item["text"],
        }
        for segment, translated_item in zip(chunk, translated_items, strict=True)
    ]


def _required_string(parameters: dict[str, Any], name: str, *, error_prefix: str) -> str:
    value = parameters.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{error_prefix} parameter '{name}' must be a non-empty string.")
    return value


def _positive_int_parameter(value: Any, name: str, *, error_prefix: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{error_prefix} parameter '{name}' must be a positive integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{error_prefix} parameter '{name}' must be a positive integer.")
    return parsed


def _non_negative_int_parameter(value: Any, name: str, *, error_prefix: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{error_prefix} parameter '{name}' must be a non-negative integer."
        ) from exc
    if parsed < 0:
        raise ValueError(f"{error_prefix} parameter '{name}' must be a non-negative integer.")
    return parsed


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


def _timed_segments(request: dict, *, input_name: str, error_prefix: str) -> list[TimedSegment]:
    return timed_segments_from_request(request, input_name=input_name, error_prefix=error_prefix)


def _timed_segments_any(
    request: dict, *, input_names: tuple[str, ...], error_prefix: str
) -> list[TimedSegment]:
    return timed_segments_from_any_input(
        request, input_names=input_names, error_prefix=error_prefix
    )


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

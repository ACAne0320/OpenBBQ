"""Deterministic review of low-confidence ASR word occurrences.

The transcript remains canonical and immutable. Agent decisions live in a
workspace sidecar and are consumed as exact phrase corrections by segmentation.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from pydantic import ValidationError

from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    AsrAmendment,
    AsrDecision,
    AsrReview,
    Segment,
    Transcript,
    Word,
)

DEFAULT_MAX_PROB = 0.5
MAX_WORDS_PER_SECOND = 9.0
MIN_DENSE_WORDS = 8
MIN_REPEAT_SEGMENTS = 4
MIN_REPEAT_TOKENS = 6
MIN_REPEAT_SPAN_S = 5.0
MAX_DECISION_BATCH = 20
MIN_COLLAPSED_WORDS = 3
MIN_BOUNDARY_PILEUP_WORDS = 5
REFERENCE_RECOVERY_SIMILARITY = 0.72
_IDENTITY: Callable[[str], str] = lambda text: text  # noqa: E731


@dataclass(frozen=True)
class ContextWord:
    index: int
    word: str
    prob: float | None


@dataclass(frozen=True)
class Issue:
    id: str
    segment_id: int
    word_index: int
    word: str
    start: float
    end: float
    prob: float
    segment_text: str
    context: tuple[ContextWord, ...]


@dataclass(frozen=True)
class Anomaly:
    id: str
    code: Literal[
        "repeated_segment_run",
        "implausible_word_rate",
        "metadata_entity_conflict",
        "collapsed_word_timestamps",
        "reference_timeline_mismatch",
    ]
    severity: Literal["severe"]
    segment_ids: tuple[int, ...]
    start: float
    end: float
    text: str
    previous_text: str | None
    next_text: str | None
    words_per_second: float | None = None
    find: str | None = None
    replacement: str | None = None
    reference_text: str | None = None
    reference_words: tuple[Word, ...] = ()


@dataclass(frozen=True)
class ReferenceCaption:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class CheckReport:
    transcript_hash: str
    max_prob: float
    word_issues: list[Issue]
    anomalies: list[Anomaly]
    resolved_ids: list[str]
    unresolved_ids: list[str]
    stale: bool

    @property
    def issues(self) -> list[Issue | Anomaly]:
        return [*self.anomalies, *self.word_issues]

    @property
    def ready(self) -> bool:
        return not self.stale and not self.unresolved_ids


def _validate_max_prob(max_prob: float) -> float:
    if not 0.0 <= max_prob <= 1.0:
        raise OpenBBQError(
            "invalid_probability",
            max_prob=max_prob,
            fix="use a probability threshold from 0.0 to 1.0",
        )
    return max_prob


def transcript_hash(transcript: Transcript) -> str:
    payload = transcript.model_dump_json(exclude_none=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def extract_issues(
    transcript: Transcript,
    *,
    max_prob: float = DEFAULT_MAX_PROB,
    exclude_segment_ids: set[int] | None = None,
) -> list[Issue]:
    max_prob = _validate_max_prob(max_prob)
    excluded = exclude_segment_ids or set()
    issues: list[Issue] = []
    for segment in transcript.segments:
        if segment.id in excluded:
            continue
        words = segment.words or []
        for index, word in enumerate(words):
            if word.prob is None or word.prob >= max_prob:
                continue
            context_start = max(0, index - 2)
            context_end = min(len(words), index + 3)
            issues.append(
                Issue(
                    id=f"s{segment.id}:w{index}",
                    segment_id=segment.id,
                    word_index=index,
                    word=word.word,
                    start=word.start,
                    end=word.end,
                    prob=word.prob,
                    segment_text=segment.text,
                    context=tuple(
                        ContextWord(i, words[i].word, words[i].prob)
                        for i in range(context_start, context_end)
                    ),
                )
            )
    return issues


def _normalized_words(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[\w']+", text.casefold(), flags=re.UNICODE))


_VTT_TIMING_RE = re.compile(
    r"(?P<start>(?:\d+:)?\d{2}:\d{2}[.,]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d+:)?\d{2}:\d{2}[.,]\d{3})"
)
_VTT_TAG_RE = re.compile(r"<[^>]+>")
_VTT_INLINE_TIME_RE = re.compile(
    r"<(?P<time>(?:\d+:)?\d{2}:\d{2}[.,]\d{3})>"
)
_WORD_SPAN_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")


def _vtt_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _merge_rolling_texts(values: list[str]) -> str:
    """Collapse YouTube's cumulative/rolling caption lines by token overlap."""

    merged: list[str] = []
    for value in values:
        tokens = value.split()
        if not tokens:
            continue
        current = " ".join(merged)
        if value in current:
            continue
        if current and current in value:
            merged = tokens
            continue
        overlap = 0
        for size in range(min(len(merged), len(tokens)), 0, -1):
            if [token.casefold() for token in merged[-size:]] == [
                token.casefold() for token in tokens[:size]
            ]:
                overlap = size
                break
        merged.extend(tokens[overlap:])
    return " ".join(merged)


def parse_reference_captions(text: str) -> list[ReferenceCaption]:
    """Parse the timing/text subset shared by WebVTT subtitle variants."""

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues: list[ReferenceCaption] = []
    index = 0
    while index < len(lines):
        timing = _VTT_TIMING_RE.search(lines[index])
        if timing is None:
            index += 1
            continue
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index].strip():
            cleaned = html.unescape(_VTT_TAG_RE.sub("", lines[index])).strip()
            if cleaned:
                body.append(cleaned)
            index += 1
        caption_text = _merge_rolling_texts(body)
        if caption_text:
            cues.append(
                ReferenceCaption(
                    start=_vtt_seconds(timing.group("start")),
                    end=_vtt_seconds(timing.group("end")),
                    text=caption_text,
                )
            )
    return cues


def _timed_reference_chunk(
    text: str,
    *,
    start: float,
    end: float,
) -> list[Word]:
    cleaned = html.unescape(_VTT_TAG_RE.sub("", text)).strip()
    tokens = re.findall(r"\S+", cleaned)
    if not tokens:
        return []
    duration = max(end - start, 0.001)
    step = duration / len(tokens)
    return [
        Word(
            word=token,
            start=start + index * step,
            end=start + (index + 1) * step,
            prob=1.0,
        )
        for index, token in enumerate(tokens)
    ]


def parse_reference_words(text: str) -> list[Word]:
    """Extract word timing from YouTube's inline-timestamp WebVTT variant.

    Plain VTT cues remain useful as textual evidence, but they are deliberately
    not invented into word timings.  Only lines carrying YouTube's inline
    ``<hh:mm:ss.mmm>`` markers are returned here.
    """

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    words: list[Word] = []
    index = 0
    while index < len(lines):
        timing = _VTT_TIMING_RE.search(lines[index])
        if timing is None:
            index += 1
            continue
        cue_start = _vtt_seconds(timing.group("start"))
        cue_end = _vtt_seconds(timing.group("end"))
        index += 1
        while index < len(lines) and lines[index].strip():
            line = lines[index]
            markers = list(_VTT_INLINE_TIME_RE.finditer(line))
            if markers:
                first = markers[0]
                words.extend(
                    _timed_reference_chunk(
                        line[: first.start()],
                        start=cue_start,
                        end=_vtt_seconds(first.group("time")),
                    )
                )
                for marker_index, marker in enumerate(markers):
                    next_start = (
                        markers[marker_index + 1].start()
                        if marker_index + 1 < len(markers)
                        else len(line)
                    )
                    chunk_end = (
                        _vtt_seconds(markers[marker_index + 1].group("time"))
                        if marker_index + 1 < len(markers)
                        else cue_end
                    )
                    words.extend(
                        _timed_reference_chunk(
                            line[marker.end() : next_start],
                            start=_vtt_seconds(marker.group("time")),
                            end=chunk_end,
                        )
                    )
            index += 1

    deduplicated: list[Word] = []
    seen: set[tuple[int, str]] = set()
    for word in sorted(words, key=lambda item: (item.start, item.end, item.word)):
        key = (round(word.start * 1000), word.word.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(word)
    return deduplicated


def reference_caption_text(
    captions: list[ReferenceCaption],
    *,
    start: float,
    end: float,
) -> str | None:
    overlapping = [
        caption.text
        for caption in captions
        if caption.start < end and caption.end > start
    ]
    merged = _merge_rolling_texts(overlapping)
    return merged or None


def _metadata_entity_anomalies(
    transcript: Transcript,
    reference_texts: tuple[str, ...],
) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    seen: set[tuple[int, str, str]] = set()
    for reference in reference_texts:
        expected_tokens = list(_WORD_SPAN_RE.finditer(reference))
        for expected_first, expected_last in zip(
            expected_tokens, expected_tokens[1:], strict=False
        ):
            first_text = expected_first.group(0)
            last_text = expected_last.group(0)
            if (
                len(first_text) < 4
                or len(last_text) < 3
                or not first_text[0].isupper()
                or not last_text[0].isupper()
            ):
                continue
            for segment_index, segment in enumerate(transcript.segments):
                observed_tokens = list(_WORD_SPAN_RE.finditer(segment.text))
                for observed_first, observed_last in zip(
                    observed_tokens, observed_tokens[1:], strict=False
                ):
                    observed_first_text = observed_first.group(0)
                    observed_last_text = observed_last.group(0)
                    if (
                        not observed_first_text[0].isupper()
                        or not observed_last_text[0].isupper()
                        or observed_last_text.casefold() != last_text.casefold()
                        or observed_first_text.casefold() == first_text.casefold()
                    ):
                        continue
                    similarity = SequenceMatcher(
                        None,
                        observed_first_text.casefold(),
                        first_text.casefold(),
                    ).ratio()
                    if not 0.6 <= similarity < 0.95:
                        continue
                    find = segment.text[observed_first.start() : observed_last.end()]
                    replacement = reference[
                        expected_first.start() : expected_last.end()
                    ]
                    key = (segment.id, find.casefold(), replacement.casefold())
                    if key in seen:
                        continue
                    seen.add(key)
                    previous, next_text = _anomaly_context(
                        transcript, segment_index, segment_index
                    )
                    digest = hashlib.sha256(
                        f"{segment.id}|{find.casefold()}|{replacement.casefold()}".encode()
                    ).hexdigest()[:10]
                    anomalies.append(
                        Anomaly(
                            id=f"a:metadata:{segment.id}:{digest}",
                            code="metadata_entity_conflict",
                            severity="severe",
                            segment_ids=(segment.id,),
                            start=segment.start,
                            end=segment.end,
                            text=segment.text,
                            previous_text=previous,
                            next_text=next_text,
                            find=find,
                            replacement=replacement,
                            reference_text=reference,
                        )
                    )
    return anomalies


def _anomaly_context(
    transcript: Transcript, first_index: int, last_index: int
) -> tuple[str | None, str | None]:
    previous = transcript.segments[first_index - 1].text if first_index > 0 else None
    next_text = (
        transcript.segments[last_index + 1].text
        if last_index + 1 < len(transcript.segments)
        else None
    )
    return previous, next_text


def _reference_window(
    reference_words: tuple[Word, ...],
    *,
    start: float,
    end: float,
) -> tuple[Word, ...]:
    return tuple(
        word.model_copy(deep=True)
        for word in reference_words
        if word.start < end and word.end > start
    )


def _best_reference_match(
    segment: Segment,
    reference_words: tuple[Word, ...],
    *,
    padding: float = 3.0,
) -> tuple[tuple[Word, ...], float]:
    observed = _normalized_words(segment.text)
    candidates = tuple(
        word
        for word in reference_words
        if word.start < segment.end + padding and word.end > segment.start - padding
    )
    if not observed or not candidates:
        return (), 0.0
    candidate_keys = [
        " ".join(_normalized_words(word.word)) for word in candidates
    ]
    margin = max(2, min(8, len(observed) // 10))
    minimum = max(1, len(observed) - margin)
    maximum = min(len(candidates), len(observed) + margin)
    best: tuple[float, float, int, int] | None = None
    for length in range(minimum, maximum + 1):
        for start_index in range(0, len(candidates) - length + 1):
            end_index = start_index + length
            score = SequenceMatcher(
                None,
                observed,
                candidate_keys[start_index:end_index],
            ).ratio()
            timing_distance = abs(candidates[start_index].start - segment.start) + abs(
                candidates[end_index - 1].end - segment.end
            )
            candidate = (score, -timing_distance, start_index, end_index)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        return (), 0.0
    return candidates[best[2] : best[3]], best[0]


def _has_collapsed_timeline(segment: Segment) -> bool:
    words = segment.words or []
    if not words:
        return False
    collapsed = sum(word.end <= word.start + 1e-6 for word in words)
    boundary = sum(
        abs(word.start - segment.end) <= 0.005
        or abs(word.end - segment.end) <= 0.005
        for word in words
    )
    return collapsed >= max(MIN_COLLAPSED_WORDS, (len(words) + 4) // 5) or (
        boundary >= max(MIN_BOUNDARY_PILEUP_WORDS, (len(words) + 3) // 4)
    )


def _timeline_anomalies(
    transcript: Transcript,
    reference_words: tuple[Word, ...],
) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    recovering = False
    for index, segment in enumerate(transcript.segments):
        collapsed = _has_collapsed_timeline(segment)
        window_reference = _reference_window(
            reference_words,
            start=segment.start,
            end=segment.end,
        )
        matched_reference, match_score = _best_reference_match(
            segment,
            reference_words,
        )
        timed_reference = (
            matched_reference
            if match_score >= REFERENCE_RECOVERY_SIMILARITY
            else window_reference
        )
        code: Literal[
            "collapsed_word_timestamps", "reference_timeline_mismatch"
        ] | None = None
        if collapsed:
            code = "collapsed_word_timestamps"
            recovering = True
        elif recovering and (matched_reference or window_reference):
            if match_score >= REFERENCE_RECOVERY_SIMILARITY:
                recovering = False
            else:
                code = "reference_timeline_mismatch"
        if code is None:
            continue
        previous, next_text = _anomaly_context(transcript, index, index)
        reference_text = (
            " ".join(word.word for word in timed_reference)
            if timed_reference
            else None
        )
        evidence_digest = hashlib.sha256(
            f"{code}|{reference_text or 'none'}".encode("utf-8")
        ).hexdigest()[:10]
        anomalies.append(
            Anomaly(
                id=f"a:timeline:{segment.id}:{evidence_digest}",
                code=code,
                severity="severe",
                segment_ids=(segment.id,),
                start=segment.start,
                end=segment.end,
                text=segment.text,
                previous_text=previous,
                next_text=next_text,
                replacement=reference_text,
                reference_text=reference_text,
                reference_words=timed_reference,
            )
        )
    return anomalies


def extract_anomalies(
    transcript: Transcript,
    *,
    reference_texts: list[str] | tuple[str, ...] = (),
    reference_words: list[Word] | tuple[Word, ...] = (),
) -> list[Anomaly]:
    """Find high-precision segment failures that word probability misses.

    The thresholds deliberately target decoder artifacts, not ordinary spoken
    repetition: a repeated run must contain a substantial sentence, span at
    least five seconds, and occur four or more times consecutively. Implausible
    density is reported only outside such a run to avoid duplicate review work.
    """

    anomalies: list[Anomaly] = _timeline_anomalies(
        transcript, tuple(reference_words)
    )
    timeline_ids = {
        segment_id for issue in anomalies for segment_id in issue.segment_ids
    }
    repeated_ids: set[int] = set()
    segments = transcript.segments
    index = 0
    while index < len(segments):
        key = _normalized_words(segments[index].text)
        end = index + 1
        while end < len(segments) and _normalized_words(segments[end].text) == key:
            end += 1
        group = segments[index:end]
        span = group[-1].end - group[0].start
        if (
            len(key) >= MIN_REPEAT_TOKENS
            and len(group) >= MIN_REPEAT_SEGMENTS
            and span >= MIN_REPEAT_SPAN_S
        ):
            ids = tuple(segment.id for segment in group)
            repeated_ids.update(ids)
            previous, next_text = _anomaly_context(transcript, index, end - 1)
            anomalies.append(
                Anomaly(
                    id=f"a:repeat:{ids[0]}-{ids[-1]}",
                    code="repeated_segment_run",
                    severity="severe",
                    segment_ids=ids,
                    start=group[0].start,
                    end=group[-1].end,
                    text=group[0].text,
                    previous_text=previous,
                    next_text=next_text,
                )
            )
        index = end

    for index, segment in enumerate(segments):
        if segment.id in repeated_ids or segment.id in timeline_ids:
            continue
        word_count = len(segment.words or []) or len(_normalized_words(segment.text))
        duration = segment.end - segment.start
        rate = word_count / duration if duration > 0 else float("inf")
        if word_count < MIN_DENSE_WORDS or rate <= MAX_WORDS_PER_SECOND:
            continue
        previous, next_text = _anomaly_context(transcript, index, index)
        anomalies.append(
            Anomaly(
                id=f"a:density:{segment.id}",
                code="implausible_word_rate",
                severity="severe",
                segment_ids=(segment.id,),
                start=segment.start,
                end=segment.end,
                text=segment.text,
                previous_text=previous,
                next_text=next_text,
                words_per_second=round(rate, 3),
            )
        )
    anomalies.extend(_metadata_entity_anomalies(transcript, tuple(reference_texts)))
    return sorted(anomalies, key=lambda issue: (issue.start, issue.id))


def check(
    transcript: Transcript,
    review: AsrReview | None,
    *,
    max_prob: float | None = None,
    reference_texts: list[str] | tuple[str, ...] = (),
    reference_words: list[Word] | tuple[Word, ...] = (),
) -> CheckReport:
    threshold = (
        max_prob
        if max_prob is not None
        else review.max_prob
        if review is not None
        else DEFAULT_MAX_PROB
    )
    threshold = _validate_max_prob(threshold)
    fingerprint = transcript_hash(transcript)
    anomalies = extract_anomalies(
        transcript,
        reference_texts=reference_texts,
        reference_words=reference_words,
    )
    stale = review is not None and (
        review.transcript_hash != fingerprint or review.max_prob != threshold
    )
    decisions = {} if review is None or stale else review.decisions
    suppressed_segment_ids: set[int] = set()
    for anomaly in anomalies:
        decision = decisions.get(anomaly.id)
        if decision is None:
            continue
        if decision.action == "drop" or (
            decision.action == "replace" and decision.find is None
        ):
            suppressed_segment_ids.update(anomaly.segment_ids)
        elif decision.action == "keep_first":
            suppressed_segment_ids.update(anomaly.segment_ids[1:])
    word_issues = extract_issues(
        transcript,
        max_prob=threshold,
        exclude_segment_ids=suppressed_segment_ids,
    )
    issues: list[Issue | Anomaly] = [*anomalies, *word_issues]
    resolved_ids = [issue.id for issue in issues if issue.id in decisions]
    unresolved_ids = [issue.id for issue in issues if issue.id not in decisions]
    return CheckReport(
        transcript_hash=fingerprint,
        max_prob=threshold,
        word_issues=word_issues,
        anomalies=anomalies,
        resolved_ids=resolved_ids,
        unresolved_ids=unresolved_ids,
        stale=stale,
    )


def parse_decisions(text: str) -> dict[str, AsrDecision]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise OpenBBQError(
            "asr_decisions_invalid",
            detail="expected a JSON object keyed by ASR issue id",
        ) from error
    if not isinstance(raw, dict) or not raw:
        raise OpenBBQError(
            "asr_decisions_invalid",
            detail="expected a non-empty JSON object keyed by ASR issue id",
        )
    decisions: dict[str, AsrDecision] = {}
    try:
        for issue_id, value in raw.items():
            if not isinstance(issue_id, str):
                raise ValueError("issue ids must be strings")
            decisions[issue_id] = AsrDecision.model_validate(value)
    except (ValidationError, ValueError, TypeError) as error:
        raise OpenBBQError(
            "asr_decisions_invalid",
            detail=str(error),
        ) from error
    return decisions


def parse_amendments(text: str) -> list[AsrAmendment]:
    """Parse a bounded contextual-audit patch document.

    The wrapper keeps the format self-describing and leaves room for future
    audit metadata without changing the list of amendment fields.
    """

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise OpenBBQError(
            "asr_amendments_invalid",
            detail="expected a JSON object with a non-empty amendments array",
        ) from error
    values = raw.get("amendments") if isinstance(raw, dict) else None
    if not isinstance(values, list) or not values:
        raise OpenBBQError(
            "asr_amendments_invalid",
            detail="expected a JSON object with a non-empty amendments array",
        )
    if len(values) > MAX_DECISION_BATCH:
        raise OpenBBQError(
            "asr_amendments_too_large",
            count=len(values),
            max=MAX_DECISION_BATCH,
            fix="apply at most 20 contextual corrections at a time",
        )
    try:
        return [AsrAmendment.model_validate(value) for value in values]
    except (ValidationError, ValueError, TypeError) as error:
        raise OpenBBQError(
            "asr_amendments_invalid",
            detail=str(error),
        ) from error


def _text_key(text: str) -> str:
    return "".join(character for character in text.casefold() if character.isalnum())


_WORD_ISSUE_SEGMENT_RE = re.compile(r"^s(?P<segment>\d+):w(?P<word>\d+)$")
_MANUAL_SEGMENT_RE = re.compile(r"^m:s(?P<segment>\d+):")
_METADATA_SEGMENT_RE = re.compile(r"^a:metadata:(?P<segment>\d+):")


def _decision_segment_id(issue_id: str) -> int | None:
    """Return the occurrence scope encoded by phrase-replacement issue ids."""

    for pattern in (
        _WORD_ISSUE_SEGMENT_RE,
        _MANUAL_SEGMENT_RE,
        _METADATA_SEGMENT_RE,
    ):
        match = pattern.match(issue_id)
        if match is not None:
            return int(match.group("segment"))
    return None


def _decision_word_index(issue_id: str) -> int | None:
    match = _WORD_ISSUE_SEGMENT_RE.match(issue_id)
    return int(match.group("word")) if match is not None else None


def _validate_decision(issue: Issue | Anomaly, decision: AsrDecision) -> None:
    if isinstance(issue, Issue):
        if decision.action not in {"accept", "replace"}:
            raise OpenBBQError(
                "asr_decision_invalid",
                id=issue.id,
                detail="word issues only support accept or replace",
            )
        if decision.action != "replace":
            return
        find = decision.find or ""
        if not find:
            raise OpenBBQError(
                "asr_decision_invalid",
                id=issue.id,
                detail="word replacements require a find phrase",
            )
        if find.casefold() not in issue.segment_text.casefold():
            raise OpenBBQError(
                "asr_decision_invalid",
                id=issue.id,
                detail="find phrase is not present in the issue segment",
            )
        uncertain = _text_key(issue.word)
        if not uncertain or uncertain not in _text_key(find):
            raise OpenBBQError(
                "asr_decision_invalid",
                id=issue.id,
                detail="find phrase must include the uncertain word",
            )
        return

    if issue.code == "metadata_entity_conflict":
        if decision.action not in {"accept", "replace"}:
            raise OpenBBQError(
                "asr_decision_invalid",
                id=issue.id,
                detail="metadata entity conflicts only support accept or replace",
            )
        if decision.action == "replace":
            find = decision.find or ""
            if not find or find.casefold() not in issue.text.casefold():
                raise OpenBBQError(
                    "asr_decision_invalid",
                    id=issue.id,
                    detail="metadata replacement find phrase is not in the segment",
                )
        return

    if issue.code in {
        "collapsed_word_timestamps",
        "reference_timeline_mismatch",
    }:
        if decision.action not in {"replace", "drop"}:
            raise OpenBBQError(
                "asr_decision_invalid",
                id=issue.id,
                detail="timeline anomalies require a timed replacement or explicit drop",
            )
        if decision.action == "replace" and decision.find is not None:
            raise OpenBBQError(
                "asr_decision_invalid",
                id=issue.id,
                detail="timeline replacements use replacement without find",
            )
        return

    if decision.action == "replace" and decision.find is not None:
        raise OpenBBQError(
            "asr_decision_invalid",
            id=issue.id,
            detail="segment anomaly replacements use replacement without find",
        )


def merge_decisions(
    transcript: Transcript,
    review: AsrReview | None,
    decisions: Mapping[str, AsrDecision],
    *,
    max_prob: float = DEFAULT_MAX_PROB,
    reference_texts: list[str] | tuple[str, ...] = (),
    reference_words: list[Word] | tuple[Word, ...] = (),
) -> AsrReview:
    if len(decisions) > MAX_DECISION_BATCH:
        raise OpenBBQError(
            "asr_decisions_too_large",
            count=len(decisions),
            max=MAX_DECISION_BATCH,
            fix="review and apply one `openbbq asr batch --limit 20` page at a time",
        )
    max_prob = _validate_max_prob(max_prob)
    fingerprint = transcript_hash(transcript)
    issues: list[Issue | Anomaly] = [
        *extract_anomalies(
            transcript,
            reference_texts=reference_texts,
            reference_words=reference_words,
        ),
        *extract_issues(transcript, max_prob=max_prob),
    ]
    by_id = {issue.id: issue for issue in issues}
    unknown = sorted(set(decisions) - set(by_id))
    if unknown:
        raise OpenBBQError(
            "asr_decision_unknown_ids",
            ids=unknown[:20],
            fix="run `openbbq asr batch --limit 20` and use its issue ids",
        )
    for issue_id, decision in decisions.items():
        _validate_decision(by_id[issue_id], decision)

    current: dict[str, AsrDecision] = {}
    if (
        review is not None
        and review.transcript_hash == fingerprint
        and review.max_prob == max_prob
    ):
        current.update(
            (issue_id, decision)
            for issue_id, decision in review.decisions.items()
            if issue_id in by_id or issue_id.startswith("m:s")
        )
    current.update(decisions)
    replacements: dict[tuple[int | None, str], str] = {}
    for issue_id, decision in current.items():
        if decision.action != "replace" or not decision.find:
            continue
        find = (decision.find or "").casefold()
        key = (_decision_segment_id(issue_id), find)
        replacement = decision.replacement or ""
        previous = replacements.get(key)
        if previous is not None and previous != replacement:
            raise OpenBBQError(
                "asr_decision_conflict",
                id=issue_id,
                find=decision.find,
                replacements=[previous, replacement],
                fix="use one replacement for the same source phrase",
            )
        replacements[key] = replacement
    return AsrReview(
        transcript_hash=fingerprint,
        max_prob=max_prob,
        decisions=current,
    )


def _manual_amendment_id(amendment: AsrAmendment) -> str:
    digest = hashlib.sha256(
        f"{amendment.segment_id}|{amendment.find.casefold()}".encode()
    ).hexdigest()[:10]
    return f"m:s{amendment.segment_id}:{digest}"


def merge_amendments(
    transcript: Transcript,
    review: AsrReview | None,
    amendments: list[AsrAmendment],
    *,
    max_prob: float | None = None,
) -> tuple[AsrReview, list[str]]:
    """Merge agent-found corrections that are not tied to detector issue ids."""

    if not amendments or len(amendments) > MAX_DECISION_BATCH:
        raise OpenBBQError(
            "asr_amendments_too_large" if amendments else "asr_amendments_invalid",
            count=len(amendments),
            max=MAX_DECISION_BATCH,
            fix="apply from 1 to 20 contextual corrections at a time",
        )
    fingerprint = transcript_hash(transcript)
    threshold = _validate_max_prob(
        max_prob
        if max_prob is not None
        else review.max_prob
        if review is not None
        else DEFAULT_MAX_PROB
    )
    if review is not None and (
        review.transcript_hash != fingerprint or review.max_prob != threshold
    ):
        raise OpenBBQError(
            "asr_review_stale",
            fix="rerun `openbbq asr check` and resolve the current transcript first",
        )

    segments = {segment.id: segment for segment in transcript.segments}
    current = dict(review.decisions) if review is not None else {}
    applied_ids: list[str] = []
    existing_replacements = {
        (_decision_segment_id(issue_id), (decision.find or "").casefold()): (
            decision.replacement or ""
        )
        for issue_id, decision in current.items()
        if decision.action == "replace" and decision.find
    }
    for amendment in amendments:
        segment = segments.get(amendment.segment_id)
        if segment is None:
            raise OpenBBQError(
                "asr_amendment_unknown_segment",
                segment_id=amendment.segment_id,
                fix="use a segment_id returned by `openbbq glossary audit`",
            )
        active_segment_text = corrector(review, segment_id=segment.id)(segment.text)
        if (
            amendment.find.casefold() not in segment.text.casefold()
            and amendment.find.casefold() not in active_segment_text.casefold()
        ):
            raise OpenBBQError(
                "asr_amendment_find_missing",
                segment_id=amendment.segment_id,
                find=amendment.find,
                fix="copy the exact phrase from `openbbq glossary audit`",
            )
        issue_id = _manual_amendment_id(amendment)
        occurrence_text = segment.text if issue_id in current else active_segment_text
        active_matches = list(_phrase_pattern(amendment.find).finditer(occurrence_text))
        if len(active_matches) != 1:
            raise OpenBBQError(
                "asr_amendment_ambiguous_occurrence",
                segment_id=amendment.segment_id,
                find=amendment.find,
                matches=len(active_matches),
                fix="use a longer exact phrase that identifies one occurrence in the segment",
            )
        replacement_key = (amendment.segment_id, amendment.find.casefold())
        previous = existing_replacements.get(replacement_key)
        if (
            previous is not None
            and previous != amendment.replacement
            and issue_id not in current
        ):
            raise OpenBBQError(
                "asr_decision_conflict",
                find=amendment.find,
                replacements=[previous, amendment.replacement],
                fix="use one replacement for the same source phrase",
            )
        current[issue_id] = AsrDecision(
            action="replace",
            find=amendment.find,
            replacement=amendment.replacement,
            reason=amendment.reason,
        )
        existing_replacements[replacement_key] = amendment.replacement
        applied_ids.append(issue_id)

    return (
        AsrReview(
            transcript_hash=fingerprint,
            max_prob=threshold,
            decisions=current,
        ),
        applied_ids,
    )


def _phrase_pattern(find: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(find)}(?!\w)", re.IGNORECASE)


def _retime_replacement_words(
    segment: Segment,
    *,
    find: str,
    replacement: str,
    word_index: int | None = None,
) -> Segment:
    """Replace one scoped phrase while preserving unaffected word timestamps."""

    pattern = _phrase_pattern(find)
    matches = list(pattern.finditer(segment.text))
    if not matches:
        return segment
    match = matches[0]
    surfaces = list(re.finditer(r"\S+", segment.text))
    if (
        word_index is not None
        and segment.words
        and len(surfaces) == len(segment.words)
        and 0 <= word_index < len(surfaces)
    ):
        word_surface = surfaces[word_index]
        scoped = [
            candidate
            for candidate in matches
            if candidate.start() < word_surface.end()
            and candidate.end() > word_surface.start()
        ]
        if len(scoped) == 1:
            match = scoped[0]
    corrected = (
        segment.text[: match.start()] + replacement + segment.text[match.end() :]
    )
    if not segment.words:
        return segment.model_copy(update={"text": corrected, "words": None})

    if len(surfaces) != len(segment.words):
        tokens = re.findall(r"\S+", corrected)
        duration = max(segment.end - segment.start, 0.001)
        step = duration / max(len(tokens), 1)
        words = [
            Word(
                word=token,
                start=segment.start + index * step,
                end=segment.start + (index + 1) * step,
                prob=1.0,
            )
            for index, token in enumerate(tokens)
        ]
        return segment.model_copy(update={"text": corrected, "words": words})

    affected = [
        index
        for index, surface in enumerate(surfaces)
        if surface.start() < match.end() and surface.end() > match.start()
    ]
    if not affected:
        return segment.model_copy(update={"text": corrected, "words": segment.words})
    first, last = affected[0], affected[-1]
    first_surface = surfaces[first]
    last_surface = surfaces[last]
    replacement_surface = (
        segment.text[first_surface.start() : match.start()]
        + replacement
        + segment.text[match.end() : last_surface.end()]
    )
    tokens = re.findall(r"\S+", replacement_surface)
    start = segment.words[first].start
    end = segment.words[last].end
    duration = max(end - start, 0.001)
    step = duration / max(len(tokens), 1)
    replacement_words = [
        Word(
            word=token,
            start=start + index * step,
            end=start + (index + 1) * step,
            prob=1.0,
        )
        for index, token in enumerate(tokens)
    ]
    words = [*segment.words[:first], *replacement_words, *segment.words[last + 1 :]]
    return segment.model_copy(update={"text": corrected, "words": words})


def _replacement_segment(issue: Anomaly, replacement: str) -> Segment:
    tokens = re.findall(r"\S+", replacement)
    if not tokens:
        raise OpenBBQError(
            "asr_decision_invalid",
            id=issue.id,
            detail="segment anomaly replacement must contain text",
        )
    if issue.reference_words and _normalized_words(replacement) == tuple(
        token
        for word in issue.reference_words
        for token in _normalized_words(word.word)
    ):
        source_start = issue.reference_words[0].start
        source_end = issue.reference_words[-1].end
        source_duration = source_end - source_start
        target_duration = max(issue.end - issue.start, 0.001)
        if source_duration > 0:
            scale = target_duration / source_duration
            fitted_words = [
                word.model_copy(
                    update={
                        "start": issue.start
                        + (word.start - source_start) * scale,
                        "end": issue.start + (word.end - source_start) * scale,
                        "prob": 1.0,
                    },
                    deep=True,
                )
                for word in issue.reference_words
            ]
        else:
            step = target_duration / len(issue.reference_words)
            fitted_words = [
                word.model_copy(
                    update={
                        "start": issue.start + index * step,
                        "end": issue.start + (index + 1) * step,
                        "prob": 1.0,
                    },
                    deep=True,
                )
                for index, word in enumerate(issue.reference_words)
            ]
        return Segment(
            id=issue.segment_ids[0],
            start=issue.start,
            end=issue.end,
            text=replacement,
            words=fitted_words,
        )
    duration = issue.end - issue.start
    step = duration / len(tokens) if duration > 0 else 0.001
    words = [
        Word(
            word=token,
            start=issue.start + index * step,
            end=issue.start + (index + 1) * step,
            prob=1.0,
        )
        for index, token in enumerate(tokens)
    ]
    return Segment(
        id=issue.segment_ids[0],
        start=issue.start,
        end=issue.end,
        text=replacement,
        words=words,
    )


def apply_segment_decisions(
    transcript: Transcript,
    review: AsrReview | None,
    *,
    reference_texts: list[str] | tuple[str, ...] = (),
    reference_words: list[Word] | tuple[Word, ...] = (),
) -> Transcript:
    """Apply anomaly drop/keep/replace decisions without mutating transcript.json."""

    if review is None:
        return transcript
    anomalies = {
        issue.id: issue
        for issue in extract_anomalies(
            transcript,
            reference_texts=reference_texts,
            reference_words=reference_words,
        )
    }
    drop_ids: set[int] = set()
    replacements: dict[int, Segment] = {}
    for issue_id, decision in review.decisions.items():
        issue = anomalies.get(issue_id)
        if issue is None:
            continue
        if decision.action == "drop":
            drop_ids.update(issue.segment_ids)
        elif decision.action == "keep_first":
            drop_ids.update(issue.segment_ids[1:])
        elif decision.action == "replace" and decision.find is None:
            drop_ids.update(issue.segment_ids)
            replacements[issue.segment_ids[0]] = _replacement_segment(
                issue, decision.replacement or ""
            )

    segments: list[Segment] = []
    for segment in transcript.segments:
        replacement = replacements.get(segment.id)
        if replacement is not None:
            segments.append(replacement)
            continue
        if segment.id not in drop_ids:
            segments.append(segment)
    return transcript.model_copy(update={"segments": segments})


def corrector(
    review: AsrReview | None,
    downstream: Callable[[str], str] = _IDENTITY,
    *,
    segment_id: int,
) -> Callable[[str], str]:
    replacements = sorted(
        (
            (decision.find or "", decision.replacement or "")
            for issue_id, decision in (
                review.decisions.items() if review is not None else []
            )
            if decision.action == "replace"
            and decision.find
            and _decision_segment_id(issue_id) == segment_id
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    patterns = [
        (_phrase_pattern(find), replacement) for find, replacement in replacements
    ]

    def apply(text: str) -> str:
        corrected = text
        for pattern, replacement in patterns:
            corrected = pattern.sub(replacement, corrected)
        return downstream(corrected)

    return apply


def resolved_transcript(
    transcript: Transcript,
    review: AsrReview | None,
    *,
    reference_texts: list[str] | tuple[str, ...] = (),
    reference_words: list[Word] | tuple[Word, ...] = (),
) -> Transcript:
    """Return the current review view without mutating ``transcript.json``.

    Stale sidecars are deliberately ignored. Phrase replacements are scoped to
    their encoded segment occurrence; corrected tokens inherit the affected
    time span so downstream segmentation keeps word timing support.
    """

    if review is None or review.transcript_hash != transcript_hash(transcript):
        return transcript
    reviewed = apply_segment_decisions(
        transcript,
        review,
        reference_texts=reference_texts,
        reference_words=reference_words,
    )
    decisions_by_segment: dict[int, list[tuple[str, AsrDecision]]] = {}
    for issue_id, decision in review.decisions.items():
        segment_id = _decision_segment_id(issue_id)
        if segment_id is not None and decision.action == "replace" and decision.find:
            decisions_by_segment.setdefault(segment_id, []).append((issue_id, decision))

    segments: list[Segment] = []
    for segment in reviewed.segments:
        corrected = segment
        for issue_id, decision in sorted(
            decisions_by_segment.get(segment.id, []),
            key=lambda item: (
                _decision_word_index(item[0])
                if _decision_word_index(item[0]) is not None
                else -1,
                len(item[1].find or ""),
            ),
            reverse=True,
        ):
            corrected = _retime_replacement_words(
                corrected,
                find=decision.find or "",
                replacement=decision.replacement or "",
                word_index=_decision_word_index(issue_id),
            )
        segments.append(corrected)
    return reviewed.model_copy(update={"segments": segments})

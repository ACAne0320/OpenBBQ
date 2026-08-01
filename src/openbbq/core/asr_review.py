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
    Cue,
    Segment,
    Transcript,
    Word,
)

DEFAULT_MAX_PROB = 0.5
MIN_REPEAT_SEGMENTS = 4
MIN_REPEAT_TOKENS = 6
MIN_REPEAT_SPAN_S = 5.0
MAX_DECISION_BATCH = 20
MIN_COLLAPSED_WORDS = 3
MIN_BOUNDARY_PILEUP_WORDS = 5
REFERENCE_RECOVERY_SIMILARITY = 0.72
REFERENCE_RECOVERY_SEQUENCE_SIMILARITY = 0.65
REFERENCE_TIMING_REPAIR_MIN_SHIFT_S = 1.0
REFERENCE_TIMING_REPAIR_PADDING_S = 6.0
REFERENCE_TIMING_MAX_WORD_DURATION_S = 1.0
REFERENCE_EVIDENCE_MIN_SIMILARITY = 0.85
REFERENCE_EVIDENCE_MAX_DIFF_TOKENS = 3
REFERENCE_SPEECH_GAP_MIN_DURATION_S = 5.0
REFERENCE_SPEECH_GAP_MIN_WORDS = 6
_IDENTITY: Callable[[str], str] = lambda text: text  # noqa: E731

# Only anomalies that would make the generated subtitle draft structurally
# unreliable block segmentation. Low-confidence words and semantic suspicions
# remain available to reviewers, but do not require a decision on the default
# one-shot path.
BLOCKING_ANOMALY_CODES = frozenset(
    {
        "collapsed_word_timestamps",
        "reference_timeline_mismatch",
        "repeated_segment_run",
    }
)


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
class ReferenceDifference:
    source: str
    reference: str


@dataclass(frozen=True)
class ReferenceEvidence:
    reference_text: str
    differences: tuple[ReferenceDifference, ...]


@dataclass(frozen=True)
class ReferenceSpeechGap:
    start: float
    end: float
    word_count: int


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


def blocking_unresolved_ids(report: CheckReport) -> list[str]:
    """Return unresolved anomaly IDs that make segmentation unsafe."""

    unresolved = set(report.unresolved_ids)
    return [
        anomaly.id
        for anomaly in report.anomalies
        if anomaly.id in unresolved and anomaly.code in BLOCKING_ANOMALY_CODES
    ]


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
_VTT_INLINE_TIME_RE = re.compile(r"<(?P<time>(?:\d+:)?\d{2}:\d{2}[.,]\d{3})>")


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
        # Some YouTube word-timed VTT files insert an empty spacer directly
        # after the timing line. Skip it unless the next block has already
        # started; otherwise the real caption text would be silently lost.
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index < len(lines) and _VTT_TIMING_RE.search(lines[index]):
            continue
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


def _discard_rolling_prefix(existing: list[Word], chunk: list[Word]) -> list[Word]:
    """Remove carried words that a rolling caption repeats at a new timestamp."""

    existing_keys = [
        " ".join(_normalized_words(word.word)) or word.word.casefold()
        for word in existing
    ]
    chunk_keys = [
        " ".join(_normalized_words(word.word)) or word.word.casefold() for word in chunk
    ]
    for size in range(min(len(existing_keys), len(chunk_keys)), 0, -1):
        if existing_keys[-size:] == chunk_keys[:size]:
            return chunk[size:]
    return chunk


def parse_reference_words(text: str) -> list[Word]:
    """Extract word timing from YouTube's inline-timestamp WebVTT variant.

    Plain VTT cues remain useful as textual evidence, but they are deliberately
    not invented into word timings.  Only lines carrying YouTube's inline
    ``<hh:mm:ss.mmm>`` markers are returned here.
    """

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    words: list[Word] = []
    has_inline_timing = _VTT_INLINE_TIME_RE.search(text) is not None
    index = 0
    while index < len(lines):
        timing = _VTT_TIMING_RE.search(lines[index])
        if timing is None:
            index += 1
            continue
        cue_start = _vtt_seconds(timing.group("start"))
        cue_end = _vtt_seconds(timing.group("end"))
        index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index < len(lines) and _VTT_TIMING_RE.search(lines[index]):
            continue
        while index < len(lines) and lines[index].strip():
            line = lines[index]
            markers = list(_VTT_INLINE_TIME_RE.finditer(line))
            if markers:
                first = markers[0]
                prefix = _timed_reference_chunk(
                    line[: first.start()],
                    start=cue_start,
                    end=_vtt_seconds(first.group("time")),
                )
                words.extend(_discard_rolling_prefix(words, prefix))
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
            elif has_inline_timing:
                inferred = _timed_reference_chunk(
                    line,
                    start=cue_start,
                    end=cue_end,
                )
                words.extend(_discard_rolling_prefix(words, inferred))
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


def reference_speech_gaps(
    cues: list[Cue],
    reference_words: list[Word] | tuple[Word, ...],
    *,
    duration: float,
) -> list[ReferenceSpeechGap]:
    """Find long subtitle holes that contain substantial timed speech.

    Timed reference captions are supporting evidence, not canonical text. This
    check therefore does not compare wording and cannot rewrite cues; it only
    rejects a structurally empty span when the reference establishes that
    several spoken words occur there.
    """

    if not reference_words:
        return []
    ordered = sorted(cues, key=lambda cue: (cue.start, cue.end, cue.id))
    end = max(duration, max(word.end for word in reference_words))
    candidates: list[tuple[float, float]] = []
    cursor = 0.0
    for cue in ordered:
        if cue.start > cursor:
            candidates.append((cursor, cue.start))
        cursor = max(cursor, cue.end)
    if end > cursor:
        candidates.append((cursor, end))

    gaps: list[ReferenceSpeechGap] = []
    for start, stop in candidates:
        if stop - start < REFERENCE_SPEECH_GAP_MIN_DURATION_S:
            continue
        words = [
            word for word in reference_words if word.start < stop and word.end > start
        ]
        if len(words) < REFERENCE_SPEECH_GAP_MIN_WORDS:
            continue
        gaps.append(
            ReferenceSpeechGap(
                start=start,
                end=stop,
                word_count=len(words),
            )
        )
    return gaps


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
    candidate_keys = [" ".join(_normalized_words(word.word)) for word in candidates]
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


def reference_disagreement_evidence(
    text: str,
    *,
    start: float,
    end: float,
    reference_words: list[Word] | tuple[Word, ...],
) -> ReferenceEvidence | None:
    """Return compact advisory evidence for a well-aligned local substitution.

    Reference captions are useful hints, not canonical source.  Only short
    replacements inside an otherwise close timed alignment are exposed.  Cue
    boundary insertions/deletions and broadly divergent text stay hidden so an
    agent is not encouraged to chase caption drift or perform another ASR pass.
    """

    if not text.strip() or not reference_words:
        return None
    matched, similarity = _best_reference_match(
        Segment(id=0, start=start, end=end, text=text),
        tuple(reference_words),
    )
    if similarity < REFERENCE_EVIDENCE_MIN_SIMILARITY:
        return None
    source_tokens = _normalized_words(text)
    reference_tokens = tuple(
        token for word in matched for token in _normalized_words(word.word)
    )
    if not source_tokens or not reference_tokens:
        return None
    opcodes = SequenceMatcher(None, source_tokens, reference_tokens).get_opcodes()
    if any(tag in {"insert", "delete"} for tag, *_ in opcodes):
        return None
    differences: list[ReferenceDifference] = []
    for tag, source_start, source_end, reference_start, reference_end in opcodes:
        if tag == "equal":
            continue
        source_span = source_tokens[source_start:source_end]
        reference_span = reference_tokens[reference_start:reference_end]
        if (
            not source_span
            or not reference_span
            or len(source_span) > REFERENCE_EVIDENCE_MAX_DIFF_TOKENS
            or len(reference_span) > REFERENCE_EVIDENCE_MAX_DIFF_TOKENS
        ):
            return None
        differences.append(
            ReferenceDifference(
                source=" ".join(source_span),
                reference=" ".join(reference_span),
            )
        )
    if not differences:
        return None
    return ReferenceEvidence(
        reference_text=" ".join(word.word for word in matched),
        differences=tuple(differences),
    )


def align_exact_reference_timing(
    transcript: Transcript,
    reference_words: list[Word] | tuple[Word, ...],
) -> Transcript:
    """Repair large local ASR timing drift without borrowing reference text.

    Only a word-for-word normalized match is eligible. The ASR surfaces and
    confidence values remain canonical; the timed reference contributes start
    and end values only when the existing boundary differs by at least one
    second. This targets visible alignment failures while leaving ordinary
    sub-second decoder variance untouched.
    """

    reference = tuple(reference_words)
    if not reference:
        return transcript
    segments: list[Segment] = []
    for segment_index, segment in enumerate(transcript.segments):
        source_words = segment.words or []
        matched, _score = _best_reference_match(
            segment,
            reference,
            padding=REFERENCE_TIMING_REPAIR_PADDING_S,
        )
        if len(source_words) != len(matched) or not matched:
            segments.append(segment)
            continue
        if any(
            _normalized_words(source.word) != _normalized_words(timed.word)
            for source, timed in zip(source_words, matched, strict=True)
        ):
            segments.append(segment)
            continue
        if _normalized_words(segment.text) != tuple(
            token for word in matched for token in _normalized_words(word.word)
        ):
            segments.append(segment)
            continue
        safe_timing = [
            timed.model_copy(
                update={
                    "end": min(
                        timed.end,
                        timed.start + REFERENCE_TIMING_MAX_WORD_DURATION_S,
                    )
                }
            )
            for timed in matched
        ]
        boundary_shift = max(
            abs(source_words[0].start - safe_timing[0].start),
            abs(source_words[-1].end - safe_timing[-1].end),
        )
        if boundary_shift < REFERENCE_TIMING_REPAIR_MIN_SHIFT_S:
            segments.append(segment)
            continue
        if any(
            word.end <= word.start
            or (index and word.start < safe_timing[index - 1].start)
            for index, word in enumerate(safe_timing)
        ):
            segments.append(segment)
            continue
        retimed = [
            source.model_copy(update={"start": timed.start, "end": timed.end})
            for source, timed in zip(source_words, safe_timing, strict=True)
        ]
        previous = transcript.segments[segment_index - 1] if segment_index > 0 else None
        following = (
            transcript.segments[segment_index + 1]
            if segment_index + 1 < len(transcript.segments)
            else None
        )
        if (previous is not None and retimed[0].start < previous.end) or (
            following is not None and retimed[-1].end > following.start
        ):
            segments.append(segment)
            continue
        segments.append(
            segment.model_copy(
                update={
                    "start": retimed[0].start,
                    "end": retimed[-1].end,
                    "words": retimed,
                }
            )
        )
    return transcript.model_copy(update={"segments": segments})


def _has_collapsed_timeline(segment: Segment) -> bool:
    words = segment.words or []
    if not words:
        return False
    collapsed = sum(word.end <= word.start + 1e-6 for word in words)
    boundary = sum(
        abs(word.start - segment.end) <= 0.005 or abs(word.end - segment.end) <= 0.005
        for word in words
    )
    return collapsed >= max(MIN_COLLAPSED_WORDS, (len(words) + 4) // 5) or (
        boundary >= max(MIN_BOUNDARY_PILEUP_WORDS, (len(words) + 3) // 4)
    )


def _reference_word_keys(words: tuple[Word, ...]) -> list[str]:
    return [
        " ".join(_normalized_words(word.word)) or word.word.casefold() for word in words
    ]


def _text_word_keys(text: str) -> list[str]:
    return [
        " ".join(_normalized_words(word)) or word.casefold() for word in text.split()
    ]


def _trim_neighbor_overlap(
    words: tuple[Word, ...],
    transcript: Transcript,
    segment_index: int,
    *,
    radius: int = 3,
) -> tuple[Word, ...]:
    """Keep a structural replacement from borrowing nearby segment content."""

    trimmed = words
    for previous_index in range(
        segment_index - 1, max(-1, segment_index - radius - 1), -1
    ):
        keys = _reference_word_keys(trimmed)
        neighbor = _text_word_keys(transcript.segments[previous_index].text)
        for size in range(min(len(keys) - 1, len(neighbor)), 2, -1):
            if keys[:size] == neighbor[-size:]:
                trimmed = trimmed[size:]
                break
    for next_index in range(
        segment_index + 1,
        min(len(transcript.segments), segment_index + radius + 1),
    ):
        keys = _reference_word_keys(trimmed)
        neighbor = _text_word_keys(transcript.segments[next_index].text)
        for size in range(min(len(keys) - 1, len(neighbor)), 2, -1):
            if keys[-size:] == neighbor[:size]:
                trimmed = trimmed[:-size]
                break
    return trimmed


def _timeline_anomalies(
    transcript: Transcript,
    reference_words: tuple[Word, ...],
) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    recovering = False
    reference_cursor: float | None = None
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
        used_global_match = False
        semantic_threshold = REFERENCE_RECOVERY_SIMILARITY
        if (collapsed or recovering) and match_score < REFERENCE_RECOVERY_SIMILARITY:
            search_reference = (
                reference_words
                if reference_cursor is None
                else tuple(
                    word
                    for word in reference_words
                    if word.start >= reference_cursor - 0.1
                )
            )
            matched_reference, match_score = _best_reference_match(
                segment,
                search_reference,
                padding=max(transcript.duration, 60.0),
            )
            used_global_match = True
            if reference_cursor is not None:
                semantic_threshold = REFERENCE_RECOVERY_SEQUENCE_SIMILARITY
        semantic_reference = match_score >= semantic_threshold
        timed_reference = (
            matched_reference
            if semantic_reference
            else window_reference
            if reference_cursor is None
            else ()
        )
        if timed_reference:
            timed_reference = _trim_neighbor_overlap(
                tuple(timed_reference), transcript, index
            )
        code: (
            Literal["collapsed_word_timestamps", "reference_timeline_mismatch"] | None
        ) = None
        if collapsed:
            code = "collapsed_word_timestamps"
            recovering = True
        elif recovering and (matched_reference or window_reference):
            if not used_global_match and match_score >= REFERENCE_RECOVERY_SIMILARITY:
                recovering = False
                reference_cursor = None
            else:
                code = "reference_timeline_mismatch"
        if code is None:
            continue
        previous, next_text = _anomaly_context(transcript, index, index)
        reference_text = (
            " ".join(word.word for word in timed_reference) if timed_reference else None
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
        if semantic_reference and timed_reference:
            reference_cursor = timed_reference[-1].end
    return anomalies


def extract_anomalies(
    transcript: Transcript,
    *,
    reference_words: list[Word] | tuple[Word, ...] = (),
) -> list[Anomaly]:
    """Find high-precision structural failures that word probability misses.

    The thresholds deliberately target decoder artifacts, not ordinary spoken
    repetition: a repeated run must contain a substantial sentence, span at
    least five seconds, and occur four or more times consecutively.
    """

    timeline_anomalies = _timeline_anomalies(transcript, tuple(reference_words))
    repeated_anomalies: list[Anomaly] = []
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
            previous, next_text = _anomaly_context(transcript, index, end - 1)
            issue_end = group[-1].end
            next_boundary = (
                segments[end].start if end < len(segments) else transcript.duration
            )
            trailing_reference = _reference_window(
                tuple(reference_words),
                start=issue_end,
                end=next_boundary,
            )
            if len(trailing_reference) >= REFERENCE_SPEECH_GAP_MIN_WORDS:
                issue_end = next_boundary
            timed_reference = tuple(
                word.model_copy(deep=True)
                for word in reference_words
                if word.start >= group[0].start and word.end <= issue_end
            )
            reference_text = (
                " ".join(word.word for word in timed_reference)
                if timed_reference
                else None
            )
            repeated_anomalies.append(
                Anomaly(
                    id=f"a:repeat:{ids[0]}-{ids[-1]}",
                    code="repeated_segment_run",
                    severity="severe",
                    segment_ids=ids,
                    start=group[0].start,
                    end=issue_end,
                    text=group[0].text,
                    previous_text=previous,
                    next_text=next_text,
                    replacement=reference_text,
                    reference_text=reference_text,
                    reference_words=timed_reference,
                )
            )
        index = end
    repeated_ids = {
        segment_id for issue in repeated_anomalies for segment_id in issue.segment_ids
    }
    # A repeated run is the authoritative issue for its whole span. Keeping
    # nested per-segment timeline issues would ask the reviewer for overlapping
    # replacement/drop decisions and could create duplicate replacement cues.
    timeline_anomalies = [
        issue
        for issue in timeline_anomalies
        if repeated_ids.isdisjoint(issue.segment_ids)
    ]
    return sorted(
        [*timeline_anomalies, *repeated_anomalies],
        key=lambda issue: (issue.start, issue.id),
    )


def check(
    transcript: Transcript,
    review: AsrReview | None,
    *,
    max_prob: float | None = None,
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


def _decision_segment_id(issue_id: str) -> int | None:
    """Return the occurrence scope encoded by phrase-replacement issue ids."""

    for pattern in (
        _WORD_ISSUE_SEGMENT_RE,
        _MANUAL_SEGMENT_RE,
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
        # These timestamps came from the timed reference itself. Preserve them
        # rather than scaling each overlapping ASR window independently; the
        # latter turns one boundary word into two differently timed copies.
        fitted_words = [
            word.model_copy(update={"prob": 1.0}, deep=True)
            for word in issue.reference_words
        ]
        return Segment(
            id=issue.segment_ids[0],
            start=fitted_words[0].start,
            end=fitted_words[-1].end,
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


def _same_timed_reference_word(left: Word, right: Word) -> bool:
    return (
        _normalized_words(left.word) == _normalized_words(right.word)
        and abs(left.start - right.start) <= 0.005
        and abs(left.end - right.end) <= 0.005
    )


def _deduplicate_replacement_boundaries(
    segments: list[Segment],
    replacement_ids: set[int],
) -> list[Segment]:
    """Drop a shared timed-reference prefix from the later replacement.

    A reference word that straddles two ASR segment windows legitimately
    appears in both replacement candidates. Its identical word timestamps make
    it safe to remove from the later replacement without guessing from text.
    Ordinary repeated speech and non-reference segments are left untouched.
    """

    deduplicated: list[Segment] = []
    for segment in segments:
        current = segment
        if (
            deduplicated
            and deduplicated[-1].id in replacement_ids
            and current.id in replacement_ids
            and deduplicated[-1].words
            and current.words
        ):
            previous_words = deduplicated[-1].words or []
            current_words = current.words or []
            overlap = 0
            for size in range(min(len(previous_words), len(current_words)), 0, -1):
                if all(
                    _same_timed_reference_word(left, right)
                    for left, right in zip(
                        previous_words[-size:],
                        current_words[:size],
                        strict=True,
                    )
                ):
                    overlap = size
                    break
            if overlap:
                remaining = current_words[overlap:]
                if not remaining:
                    continue
                current = current.model_copy(
                    update={
                        "start": remaining[0].start,
                        "text": " ".join(word.word for word in remaining),
                        "words": remaining,
                    },
                    deep=True,
                )
        deduplicated.append(current)
    return deduplicated


def apply_segment_decisions(
    transcript: Transcript,
    review: AsrReview | None,
    *,
    reference_words: list[Word] | tuple[Word, ...] = (),
) -> Transcript:
    """Apply anomaly drop/keep/replace decisions without mutating transcript.json."""

    if review is None:
        return transcript
    anomalies = {
        issue.id: issue
        for issue in extract_anomalies(
            transcript,
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
    return transcript.model_copy(
        update={
            "segments": _deduplicate_replacement_boundaries(
                segments,
                set(replacements),
            )
        }
    )


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

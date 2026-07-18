"""Deterministic review of low-confidence ASR word occurrences.

The transcript remains canonical and immutable. Agent decisions live in a
workspace sidecar and are consumed as exact phrase corrections by segmentation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from pydantic import ValidationError

from openbbq.errors import OpenBBQError
from openbbq.schemas import AsrDecision, AsrReview, Segment, Transcript, Word

DEFAULT_MAX_PROB = 0.5
MAX_WORDS_PER_SECOND = 9.0
MIN_DENSE_WORDS = 8
MIN_REPEAT_SEGMENTS = 4
MIN_REPEAT_TOKENS = 6
MIN_REPEAT_SPAN_S = 5.0
MAX_DECISION_BATCH = 20
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
_WORD_SPAN_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")


def _vtt_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


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
            cleaned = _VTT_TAG_RE.sub("", lines[index]).strip()
            if cleaned and (not body or cleaned != body[-1]):
                body.append(cleaned)
            index += 1
        caption_text = " ".join(body).strip()
        if caption_text:
            cues.append(
                ReferenceCaption(
                    start=_vtt_seconds(timing.group("start")),
                    end=_vtt_seconds(timing.group("end")),
                    text=caption_text,
                )
            )
    return cues


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
    return " ".join(dict.fromkeys(overlapping)) if overlapping else None


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
                    find = segment.text[
                        observed_first.start() : observed_last.end()
                    ]
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
    previous = (
        transcript.segments[first_index - 1].text if first_index > 0 else None
    )
    next_text = (
        transcript.segments[last_index + 1].text
        if last_index + 1 < len(transcript.segments)
        else None
    )
    return previous, next_text


def extract_anomalies(
    transcript: Transcript,
    *,
    reference_texts: list[str] | tuple[str, ...] = (),
) -> list[Anomaly]:
    """Find high-precision segment failures that word probability misses.

    The thresholds deliberately target decoder artifacts, not ordinary spoken
    repetition: a repeated run must contain a substantial sentence, span at
    least five seconds, and occur four or more times consecutively. Implausible
    density is reported only outside such a run to avoid duplicate review work.
    """

    anomalies: list[Anomaly] = []
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
        if segment.id in repeated_ids:
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
    anomalies.extend(
        _metadata_entity_anomalies(transcript, tuple(reference_texts))
    )
    return sorted(anomalies, key=lambda issue: (issue.start, issue.id))


def check(
    transcript: Transcript,
    review: AsrReview | None,
    *,
    max_prob: float | None = None,
    reference_texts: list[str] | tuple[str, ...] = (),
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
    anomalies = extract_anomalies(transcript, reference_texts=reference_texts)
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


def _text_key(text: str) -> str:
    return "".join(character for character in text.casefold() if character.isalnum())


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
        *extract_anomalies(transcript, reference_texts=reference_texts),
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
            if issue_id in by_id
        )
    current.update(decisions)
    replacements: dict[str, str] = {}
    for issue_id, decision in current.items():
        if decision.action != "replace" or not decision.find:
            continue
        find = (decision.find or "").casefold()
        replacement = decision.replacement or ""
        previous = replacements.get(find)
        if previous is not None and previous != replacement:
            raise OpenBBQError(
                "asr_decision_conflict",
                id=issue_id,
                find=decision.find,
                replacements=[previous, replacement],
                fix="use one replacement for the same source phrase",
            )
        replacements[find] = replacement
    return AsrReview(
        transcript_hash=fingerprint,
        max_prob=max_prob,
        decisions=current,
    )


def _phrase_pattern(find: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(find)}(?!\w)", re.IGNORECASE)


def _replacement_segment(issue: Anomaly, replacement: str) -> Segment:
    tokens = re.findall(r"\S+", replacement)
    if not tokens:
        raise OpenBBQError(
            "asr_decision_invalid",
            id=issue.id,
            detail="segment anomaly replacement must contain text",
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
) -> Transcript:
    """Apply anomaly drop/keep/replace decisions without mutating transcript.json."""

    if review is None:
        return transcript
    anomalies = {
        issue.id: issue
        for issue in extract_anomalies(transcript, reference_texts=reference_texts)
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
) -> Callable[[str], str]:
    replacements = sorted(
        (
            (decision.find or "", decision.replacement or "")
            for decision in (review.decisions.values() if review is not None else [])
            if decision.action == "replace" and decision.find
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    patterns = [(_phrase_pattern(find), replacement) for find, replacement in replacements]

    def apply(text: str) -> str:
        corrected = text
        for pattern, replacement in patterns:
            corrected = pattern.sub(replacement, corrected)
        return downstream(corrected)

    return apply

"""Structured per-cue issues for the review workbench.

Rule issues are recomputed from canonical data on every snapshot and are never
persisted, so they can never go stale.  Agent issues project the pending
suggestions of the current language onto their cue.  Dismissed issues stay in
the payload (the UI collapses them) instead of being filtered out.

This module is additive: the legacy ``over_budget``/``time_warning``/
``term_warning`` booleans are computed separately and remain untouched.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from openbbq.core import segment as seg
from openbbq.core import translate as translatelib
from openbbq.schemas import (
    Cues,
    Review,
    Suggestions,
    SuggestionStatus,
    Transcript,
    Translation,
)

ASR_CONFIDENCE_THRESHOLD = 0.5


@dataclass(frozen=True)
class CueIssue:
    cue_id: int
    kind: str  # "term" | "timing" | "budget" | "asr_confidence" | "agent_note"
    severity: str  # "warning" | "info"
    message: str  # English; the frontend localizes from kind + detail
    detail: dict = field(default_factory=dict)
    source: str = "rule"  # "rule" | "agent"
    dismissed: bool = False
    suggestion_ids: list[str] = field(default_factory=list)


def compute_issues(
    cues: Cues,
    translation: Translation | None,
    review: Review,
    suggestions: Suggestions | None,
    transcript: Transcript | None,
) -> dict[int, list[CueIssue]]:
    """All issues for every cue, keyed by cue id (empty lists included)."""
    dismissed_by_cue = {
        item.id: {d.kind for d in item.dismissals} for item in review.items
    }
    issues: dict[int, list[CueIssue]] = {cue.id: [] for cue in cues.cues}

    source_profile, _ = seg.resolve_profile(cues.source_lang)
    target_profile = None
    term_issues = []
    if translation is not None:
        target_profile, _ = seg.resolve_profile(translation.target_lang)
        term_issues = translatelib.check(
            cues, translation, translation.target_lang
        ).term_issues

    cue_by_id = {cue.id: cue for cue in cues.cues}
    for term_issue in term_issues:
        cue = cue_by_id.get(term_issue.id)
        if cue is None:
            continue
        occurrences = [
            [m.start(), m.end()]
            for m in re.finditer(re.escape(term_issue.term), cue.source, re.IGNORECASE)
        ]
        issues[term_issue.id].append(
            CueIssue(
                cue_id=term_issue.id,
                kind="term",
                severity="warning",
                message=(
                    f'Term "{term_issue.term}" should be rendered as '
                    f'"{term_issue.expected}"'
                ),
                detail={
                    "term": term_issue.term,
                    "expected": term_issue.expected,
                    "occurrences": occurrences,
                },
            )
        )

    for cue in cues.cues:
        params = cues.params
        duration = round(cue.end - cue.start, 3)
        if duration < params.min_dur:
            issues[cue.id].append(
                CueIssue(
                    cue_id=cue.id,
                    kind="timing",
                    severity="warning",
                    message=(
                        f"Duration {duration}s is shorter than the minimum "
                        f"{params.min_dur}s"
                    ),
                    detail={
                        "duration": duration,
                        "min_duration": params.min_dur,
                        "max_duration": params.max_dur,
                    },
                )
            )
        if duration > params.max_dur:
            issues[cue.id].append(
                CueIssue(
                    cue_id=cue.id,
                    kind="timing",
                    severity="warning",
                    message=(
                        f"Duration {duration}s exceeds the maximum "
                        f"{params.max_dur}s"
                    ),
                    detail={
                        "duration": duration,
                        "min_duration": params.min_dur,
                        "max_duration": params.max_dur,
                    },
                )
            )
        cps = (
            round(seg.count_chars(cue.source, source_profile) / duration, 1)
            if duration > 0
            else math.inf
        )
        if cps > params.max_cps:
            issues[cue.id].append(
                CueIssue(
                    cue_id=cue.id,
                    kind="timing",
                    severity="warning",
                    message=(
                        f"Source reads at {cps} cps, above the maximum "
                        f"{params.max_cps} cps"
                    ),
                    detail={"cps": cps, "max_cps": params.max_cps},
                )
            )

        if translation is not None and target_profile is not None:
            item = next((i for i in translation.items if i.id == cue.id), None)
            if item is not None and translatelib.is_filled(item.target):
                used = seg.count_chars(item.target or "", target_profile)
                if used > item.budget.max_chars:
                    issues[cue.id].append(
                        CueIssue(
                            cue_id=cue.id,
                            kind="budget",
                            severity="warning",
                            message=(
                                f"Target uses {used} characters, over the "
                                f"budget of {item.budget.max_chars}"
                            ),
                            detail={"used": used, "limit": item.budget.max_chars},
                        )
                    )

        if transcript is not None:
            # Attribute each word to the cue containing its midpoint. Inclusive
            # overlap would flag boundary-touching words on cues whose text does
            # not contain them (e.g. a word ending exactly at the next cue's
            # start).
            low = [
                word
                for segment in transcript.segments
                for word in (segment.words or [])
                if cue.start <= (word.start + word.end) / 2 < cue.end
                and word.prob is not None
                and word.prob < ASR_CONFIDENCE_THRESHOLD
            ]
            if low:
                issues[cue.id].append(
                    CueIssue(
                        cue_id=cue.id,
                        kind="asr_confidence",
                        severity="info",
                        message=(
                            "Low-confidence ASR words: "
                            + ", ".join(word.word for word in low)
                        ),
                        detail={
                            "words": [
                                {"word": word.word, "prob": word.prob} for word in low
                            ],
                            "threshold": ASR_CONFIDENCE_THRESHOLD,
                        },
                    )
                )

    if suggestions is not None:
        for suggestion in suggestions.suggestions:
            if suggestion.status is not SuggestionStatus.PENDING:
                continue
            if suggestion.cue_id not in issues:
                continue
            issues[suggestion.cue_id].append(
                CueIssue(
                    cue_id=suggestion.cue_id,
                    kind="agent_note",
                    severity=suggestion.severity,
                    message=suggestion.message,
                    detail={
                        "suggestion_kind": suggestion.kind,
                        "content_hash": suggestion.content_hash,
                    },
                    source="agent",
                    suggestion_ids=[suggestion.id],
                )
            )

    return {
        cue_id: [
            CueIssue(
                cue_id=issue.cue_id,
                kind=issue.kind,
                severity=issue.severity,
                message=issue.message,
                detail=issue.detail,
                source=issue.source,
                dismissed=issue.kind in dismissed_by_cue.get(cue_id, set()),
                suggestion_ids=issue.suggestion_ids,
            )
            for issue in cue_issues
        ]
        for cue_id, cue_issues in issues.items()
    }

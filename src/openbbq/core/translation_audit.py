"""Risk-ranked, bounded review support for translation worksheets.

The heuristics prioritize where an agent should spend semantic attention. They
do not claim to prove translation correctness.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from pydantic import ValidationError

from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    Cues,
    Transcript,
    Translation,
    TranslationAudit,
    TranslationAuditDecision,
    TranslationAuditFlag,
    TranslationAuditFlagCode,
    TranslationAuditRecord,
    TranslationItem,
)

from . import asr_review
from . import translate as translatelib

_LATIN_WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
_SENTENCE_START_STOP = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "because",
    "but",
    "for",
    "hello",
    "hi",
    "how",
    "hmm",
    "huh",
    "i",
    "i'm",
    "i've",
    "if",
    "in",
    "it",
    "my",
    "no",
    "now",
    "so",
    "thank",
    "the",
    "then",
    "there",
    "this",
    "to",
    "we",
    "what",
    "when",
    "who",
    "why",
    "yes",
    "you",
}
_ENTITY_STOP = _SENTENCE_START_STOP | {
    "april",
    "august",
    "chinese",
    "december",
    "english",
    "february",
    "friday",
    "january",
    "july",
    "june",
    "march",
    "may",
    "monday",
    "november",
    "october",
    "saturday",
    "september",
    "sunday",
    "thursday",
    "tuesday",
    "wednesday",
}
_RISK_WEIGHTS = {
    "asr_uncertain": 100,
    "quality_gate": 95,
    "name_omission": 85,
    "budget_rewrite": 80,
    "shortened_translation": 75,
    "target_extra_latin": 70,
    "punctuation_mismatch": 60,
    "near_repeated_translation": 55,
    "semantic_review": 10,
}
MAX_DECISION_BATCH = 20


@dataclass(frozen=True)
class AuditContext:
    id: int
    source: str
    target: str


@dataclass(frozen=True)
class RiskItem:
    id: int
    source: str
    target: str
    used_chars: int
    max_chars: int
    risk_codes: tuple[str, ...]
    score: int
    previous: AuditContext | None = None
    next: AuditContext | None = None


@dataclass(frozen=True)
class ApplyReport:
    audit: TranslationAudit
    reviewed: int
    revised: int


def item_hash(item: TranslationItem) -> str:
    payload = json.dumps(
        {
            "id": item.id,
            "source": item.source,
            "target": item.target,
            "budget": item.budget.model_dump(mode="json"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def context_hash(worksheet: Translation, item_id: int, *, context: int = 1) -> str:
    indexes = {item.id: index for index, item in enumerate(worksheet.items)}
    if item_id not in indexes:
        raise OpenBBQError("unknown_cue_ids", ids=[item_id])
    index = indexes[item_id]
    low = max(0, index - context)
    high = min(len(worksheet.items), index + context + 1)
    payload = json.dumps(
        [item_hash(item) for item in worksheet.items[low:high]],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def empty(target_lang: str) -> TranslationAudit:
    return TranslationAudit(target_lang=target_lang)


def _word_key(word: str) -> str:
    return "".join(character for character in word if character.isalnum())


def _looks_named_occurrence(word: str, word_index: int) -> bool:
    key = _word_key(word)
    if not key or not key[0].isupper():
        return False
    if word_index == 0:
        return False
    return True


def uncertain_cue_ids(cues: Cues, transcript: Transcript | None) -> set[int]:
    if transcript is None:
        return set()
    intervals: list[tuple[float, float]] = [
        (issue.start, issue.end) for issue in asr_review.extract_issues(transcript)
    ]
    for segment in transcript.segments:
        for index, word in enumerate(segment.words or []):
            if (
                word.prob is not None
                and word.prob < 0.8
                and _looks_named_occurrence(word.word, index)
            ):
                intervals.append((word.start, word.end))
    return {
        cue.id
        for cue in cues.cues
        if any(start < cue.end and end > cue.start for start, end in intervals)
    }


def _source_entities(source: str) -> list[str]:
    entities: list[str] = []
    words = list(_LATIN_WORD_RE.finditer(source))
    index = 0
    while index < len(words):
        match = words[index]
        word = match.group(0)
        key = word.casefold()
        prefix = source[: match.start()].rstrip()
        starts_sentence = not prefix or prefix[-1] in ".?!"
        if (
            starts_sentence
            or len(word) < 2
            or not word[0].isupper()
            or key in _ENTITY_STOP
        ):
            index += 1
            continue
        end = index + 1
        while end < len(words):
            next_match = words[end]
            next_word = next_match.group(0)
            between = source[words[end - 1].end() : next_match.start()]
            if (
                not between.isspace()
                or not next_word[0].isupper()
                or next_word.casefold() in _ENTITY_STOP
            ):
                break
            end += 1
        entities.append(source[match.start() : words[end - 1].end()])
        index = end
    return entities


def _expected_entity_forms(worksheet: Translation, entity: str) -> set[str]:
    forms = {entity.casefold()}
    for ref in worksheet.glossary:
        if ref.source.casefold() != entity.casefold():
            continue
        if ref.keep:
            forms.add(ref.source.casefold())
        elif ref.target:
            forms.add(ref.target.casefold())
    return forms


def _has_name_omission(worksheet: Translation, item: TranslationItem) -> bool:
    target = (item.target or "").casefold()
    source_words = {
        word.casefold()
        for word in _LATIN_WORD_RE.findall(item.source)
        if len(word) >= 3
    }
    preserved_source_word = any(word in target for word in source_words)
    if not preserved_source_word:
        # Fully localized targets routinely translate places, nationalities, and
        # organization names. Without a glossary, only mixed preservation gives
        # us enough evidence to call a missing multi-word name suspicious.
        return False
    return any(
        " " in entity
        and not any(
            form in target for form in _expected_entity_forms(worksheet, entity)
        )
        for entity in _source_entities(item.source)
    )


def _is_abnormally_shortened(
    worksheet: Translation,
    item: TranslationItem,
) -> bool:
    """Conservative first-draft omission signal.

    Chinese can be much denser than English, so only extreme compression on a
    reasonably long source is surfaced.  This is a review hint, never a proof
    that the target is wrong.
    """

    if worksheet.target_lang.split("-", 1)[0].casefold() != "zh":
        return False
    source_words = _LATIN_WORD_RE.findall(item.source)
    if len(source_words) < 9:
        return False
    target_chars = translatelib.count_target_chars(worksheet, item.target or "")
    return target_chars <= max(2, int(len(source_words) * 0.35))


def _has_extra_latin(worksheet: Translation, item: TranslationItem) -> bool:
    base = worksheet.target_lang.split("-", 1)[0].casefold()
    if base not in {"zh", "ja", "ko"}:
        return False
    def forms(word: str) -> set[str]:
        key = word.casefold()
        variants = {key}
        if len(key) >= 4 and key.endswith("s") and not key.endswith("ss"):
            variants.add(key[:-1])
        elif len(key) >= 3:
            variants.add(key + "s")
        return variants

    allowed = {
        form
        for word in _LATIN_WORD_RE.findall(item.source)
        for form in forms(word)
    }
    for ref in worksheet.glossary:
        if ref.keep:
            for word in _LATIN_WORD_RE.findall(ref.source):
                allowed.update(forms(word))
        elif ref.target:
            for word in _LATIN_WORD_RE.findall(ref.target):
                allowed.update(forms(word))
    return any(
        len(word) >= 2 and word.casefold() not in allowed
        for word in _LATIN_WORD_RE.findall(item.target or "")
    )


def _punctuation_mismatch(source: str, target: str) -> bool:
    if "?" in source and not any(mark in target for mark in ("?", "？")):
        return True
    return "!" in source and not any(mark in target for mark in ("!", "！"))


def _near_repeated_target_ids(worksheet: Translation) -> set[int]:
    """Return conservative clusters of near-identical targets.

    A pair can be legitimate in conversational subtitles, so this only
    surfaces clusters of at least three distinct source cues. Exact duplicates
    remain covered by the existing deterministic translation check.
    """

    candidates = [
        (
            item.id,
            "".join(
                character
                for character in (item.target or "").casefold()
                if character.isalnum()
            ),
            "".join(
                character
                for character in item.source.casefold()
                if character.isalnum()
            ),
        )
        for item in worksheet.items
        if translatelib.is_filled(item.target)
    ]
    parents = list(range(len(candidates)))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(candidates)):
        _left_id, left_target, left_source = candidates[left]
        if len(left_target) < 6:
            continue
        for right in range(left + 1, len(candidates)):
            _right_id, right_target, right_source = candidates[right]
            if (
                len(right_target) < 6
                or left_target == right_target
                or left_source == right_source
            ):
                continue
            length_ratio = min(len(left_target), len(right_target)) / max(
                len(left_target), len(right_target)
            )
            if length_ratio < 0.75:
                continue
            if SequenceMatcher(None, left_target, right_target).ratio() >= 0.88:
                union(left, right)

    groups: dict[int, list[int]] = {}
    for index, (item_id, _target, _source) in enumerate(candidates):
        groups.setdefault(root(index), []).append(item_id)
    return {
        item_id
        for group in groups.values()
        if len(group) >= 3
        for item_id in group
    }


def risk_items(
    cues: Cues,
    worksheet: Translation,
    audit: TranslationAudit | None,
    *,
    uncertain_ids: set[int] | None = None,
) -> list[RiskItem]:
    uncertain_ids = uncertain_ids or set()
    quality_by_id: dict[int, list[str]] = {}
    for issue in translatelib.check(cues, worksheet, worksheet.target_lang).quality_issues:
        quality_by_id.setdefault(issue.id, []).append(issue.code)
    near_repeated_ids = _near_repeated_target_ids(worksheet)
    results: list[RiskItem] = []
    for index, item in enumerate(worksheet.items):
        if not translatelib.is_filled(item.target):
            continue
        target = item.target or ""
        used = translatelib.count_target_chars(worksheet, target)
        codes: set[str] = set()
        if item.id in uncertain_ids:
            codes.add("asr_uncertain")
        if quality_by_id.get(item.id):
            codes.add("quality_gate")
        if _has_name_omission(worksheet, item):
            codes.add("name_omission")
        if _is_abnormally_shortened(worksheet, item):
            codes.add("shortened_translation")
        if _has_extra_latin(worksheet, item):
            codes.add("target_extra_latin")
        if _punctuation_mismatch(item.source, target):
            codes.add("punctuation_mismatch")
        if item.id in near_repeated_ids:
            codes.add("near_repeated_translation")
        if audit is not None:
            flag = audit.flags.get(item.id)
            if flag is not None and flag.content_hash == item_hash(item):
                codes.update(flag.codes)
        if not codes:
            continue
        ordered = tuple(sorted(codes, key=lambda code: (-_RISK_WEIGHTS[code], code)))
        results.append(
            RiskItem(
                id=item.id,
                source=item.source,
                target=target,
                used_chars=used,
                max_chars=item.budget.max_chars,
                risk_codes=ordered,
                score=sum(_RISK_WEIGHTS[code] for code in codes),
                previous=_audit_context(worksheet.items[index - 1]) if index > 0 else None,
                next=(
                    _audit_context(worksheet.items[index + 1])
                    if index + 1 < len(worksheet.items)
                    else None
                ),
            )
        )
    return sorted(results, key=lambda item: (-item.score, item.id))


def _audit_context(item: TranslationItem) -> AuditContext:
    return AuditContext(
        id=item.id,
        source=item.source,
        target=item.target or "",
    )


def audit_items(
    cues: Cues,
    worksheet: Translation,
    audit: TranslationAudit | None,
    *,
    uncertain_ids: set[int] | None = None,
    coverage: Literal["risks", "all"] = "risks",
) -> list[RiskItem]:
    risks = risk_items(
        cues,
        worksheet,
        audit,
        uncertain_ids=uncertain_ids,
    )
    if coverage == "risks":
        return risks
    by_id = {item.id: item for item in risks}
    indexes = {item.id: index for index, item in enumerate(worksheet.items)}
    completed: list[RiskItem] = []
    for risk in risks:
        codes = (*risk.risk_codes, "semantic_review")
        completed.append(
            RiskItem(
                id=risk.id,
                source=risk.source,
                target=risk.target,
                used_chars=risk.used_chars,
                max_chars=risk.max_chars,
                risk_codes=codes,
                score=risk.score + _RISK_WEIGHTS["semantic_review"],
                previous=risk.previous,
                next=risk.next,
            )
        )
    for item in worksheet.items:
        if not translatelib.is_filled(item.target) or item.id in by_id:
            continue
        index = indexes[item.id]
        completed.append(
            RiskItem(
                id=item.id,
                source=item.source,
                target=item.target or "",
                used_chars=translatelib.count_target_chars(
                    worksheet, item.target or ""
                ),
                max_chars=item.budget.max_chars,
                risk_codes=("semantic_review",),
                score=_RISK_WEIGHTS["semantic_review"],
                previous=(
                    _audit_context(worksheet.items[index - 1]) if index > 0 else None
                ),
                next=(
                    _audit_context(worksheet.items[index + 1])
                    if index + 1 < len(worksheet.items)
                    else None
                ),
            )
        )
    return sorted(completed, key=lambda item: (-item.score, item.id))


def is_reviewed(
    item: TranslationItem,
    audit: TranslationAudit | None,
) -> bool:
    if audit is None:
        return False
    record = audit.reviews.get(item.id)
    return record is not None and record.content_hash == item_hash(item)


def is_reviewed_in_context(
    worksheet: Translation,
    item_id: int,
    audit: TranslationAudit | None,
) -> bool:
    if audit is None:
        return False
    by_id = {item.id: item for item in worksheet.items}
    item = by_id.get(item_id)
    if item is None:
        return False
    record = audit.reviews.get(item_id)
    return (
        record is not None
        and record.content_hash == item_hash(item)
        and record.context_hash == context_hash(worksheet, item_id)
    )


def pending_items(
    risks: list[RiskItem],
    worksheet: Translation,
    audit: TranslationAudit | None,
    *,
    require_context: bool = False,
) -> list[RiskItem]:
    by_id = {item.id: item for item in worksheet.items}
    return [
        risk
        for risk in risks
        if not (
            is_reviewed_in_context(worksheet, risk.id, audit)
            if require_context
            else is_reviewed(by_id[risk.id], audit)
        )
    ]


def record_overwrites(
    before: Translation,
    after: Translation,
    audit: TranslationAudit | None,
) -> TranslationAudit:
    if before.target_lang != after.target_lang:
        raise OpenBBQError("lang_mismatch", before=before.target_lang, after=after.target_lang)
    current = audit.model_copy(deep=True) if audit is not None else empty(after.target_lang)
    if current.target_lang != after.target_lang:
        raise OpenBBQError(
            "invalid_translation_audit",
            target_lang=current.target_lang,
            expected=after.target_lang,
        )
    old_by_id = {item.id: item for item in before.items}
    for item in after.items:
        old = old_by_id[item.id]
        if old.target == item.target:
            continue
        current.flags.pop(item.id, None)
        if not translatelib.is_filled(old.target) or not translatelib.is_filled(item.target):
            continue
        old_used = translatelib.count_target_chars(before, old.target or "")
        new_used = translatelib.count_target_chars(after, item.target or "")
        codes: list[TranslationAuditFlagCode] = []
        if old_used > old.budget.max_chars and new_used <= item.budget.max_chars:
            codes.append("budget_rewrite")
        if old_used > 0 and new_used <= old_used * 0.8:
            codes.append("shortened_translation")
        if codes:
            current.flags[item.id] = TranslationAuditFlag(
                content_hash=item_hash(item),
                codes=codes,
            )
    return current


def parse_decisions(text: str) -> dict[int, TranslationAuditDecision]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise OpenBBQError(
            "translation_audit_invalid",
            detail="expected a JSON object keyed by cue id",
        ) from error
    if not isinstance(raw, dict) or not raw:
        raise OpenBBQError(
            "translation_audit_invalid",
            detail="expected a non-empty JSON object keyed by cue id",
        )
    parsed: dict[int, TranslationAuditDecision] = {}
    try:
        for raw_id, value in raw.items():
            cue_id = int(raw_id)
            if str(cue_id) != str(raw_id):
                raise ValueError(f"invalid cue id: {raw_id}")
            if cue_id in parsed:
                raise ValueError(f"duplicate cue id: {cue_id}")
            parsed[cue_id] = TranslationAuditDecision.model_validate(value)
    except (ValidationError, ValueError, TypeError) as error:
        raise OpenBBQError("translation_audit_invalid", detail=str(error)) from error
    return parsed


def apply_decisions(
    cues: Cues,
    worksheet: Translation,
    audit: TranslationAudit | None,
    risks: list[RiskItem],
    decisions: Mapping[int, TranslationAuditDecision],
    *,
    coverage: Literal["risks", "all"] = "risks",
) -> ApplyReport:
    if len(decisions) > MAX_DECISION_BATCH:
        raise OpenBBQError(
            "translation_audit_batch_too_large",
            count=len(decisions),
            max=MAX_DECISION_BATCH,
            fix=(
                f"review and apply one `openbbq translate audit "
                f"{worksheet.target_lang} --limit 20` page at a time"
            ),
        )
    risk_ids = {risk.id for risk in risks}
    unknown = sorted(set(decisions) - risk_ids)
    if unknown:
        raise OpenBBQError(
            "translation_audit_unknown_ids",
            ids=unknown[:20],
            fix=f"run `openbbq translate audit {worksheet.target_lang} --limit 20`",
        )
    before = worksheet.model_copy(deep=True)
    replacements = {
        cue_id: decision.target or ""
        for cue_id, decision in decisions.items()
        if decision.action == "revise"
    }
    if replacements:
        candidate = worksheet.model_copy(deep=True)
        translatelib.apply_targets(candidate, replacements)
        report = translatelib.check(cues, candidate, candidate.target_lang)
        blocker_ids = set(report.over_budget) | set(report.zero_budget)
        blocker_ids.update(issue.id for issue in report.term_issues)
        blocker_ids.update(issue.id for issue in report.quality_issues)
        invalid = sorted(set(replacements) & blocker_ids)
        if invalid:
            raise OpenBBQError(
                "translation_audit_revision_invalid",
                ids=invalid,
                fix="revise these targets so deterministic translation checks pass",
            )
        worksheet.items = candidate.items
    current = record_overwrites(before, worksheet, audit)
    current.schema_ = "openbbq/translation-audit@2"
    current.coverage = coverage
    by_id = {item.id: item for item in worksheet.items}
    for cue_id, decision in decisions.items():
        current.reviews[cue_id] = TranslationAuditRecord(
            content_hash=item_hash(by_id[cue_id]),
            context_hash=context_hash(worksheet, cue_id),
            action=decision.action,
            reason=decision.reason,
        )
    return ApplyReport(
        audit=current,
        reviewed=len(decisions),
        revised=len(replacements),
    )

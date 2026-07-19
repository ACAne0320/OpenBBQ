"""Translation worksheet: build a per-language work file from cues + glossary,
and validate a filled one.

Source/target split, joined at export (DESIGN translate spec): ``cues.json`` is
the immutable source product; each target language gets a ``translation@1``
worksheet the Agent owns. ``build_worksheet`` prepares it (budget per cue +
glossary map and translation brief), ``apply_targets`` merges an id→target batch into it (how the
Agent fills at scale without ad hoc scripts), ``check`` validates a filled one
(integrity hard-fails; status is reported). Pure domain logic — no cli/output;
failures surface as OpenBBQError. Legacy ``translation@1`` documents stay
readable; the agent facade migrates them to ``translation@2`` in place.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass

from openbbq.core import glossary as gl
from openbbq.core import segment as seg
from openbbq.core import translation_rules
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    Budget,
    Cues,
    Glossary,
    GlossaryRef,
    SegmentParams,
    Translation,
    TranslationItem,
)


def is_filled(target: str | None) -> bool:
    """A target counts as translated only when non-None and non-blank (DESIGN
    translate spec 决策 12: a stray ``""`` / whitespace is still "untranslated").
    """
    return target is not None and bool(target.strip())


# --- build (translate init) ---------------------------------------------------


def _snapshot(profile: seg.LanguageProfile) -> SegmentParams:
    """Freeze the target-side profile into params so worksheet budgets stay
    stable even if the profile constants later change.
    """
    return SegmentParams(
        max_cps=profile.max_cps,
        max_chars_per_line=profile.max_chars_per_line,
        max_lines=profile.max_lines,
        min_dur=profile.min_dur,
        max_dur=profile.max_dur,
        min_gap=profile.min_gap,
        pause_threshold=profile.pause_threshold,
    )


def _budget(start: float, end: float, params: SegmentParams) -> Budget:
    dur = round(end - start, 3)
    max_chars = math.floor(
        min(params.max_cps * dur, params.max_chars_per_line * params.max_lines)
    )
    return Budget(max_chars=max(max_chars, 0), seconds=dur)


def budget_for_cue(start: float, end: float, params: SegmentParams) -> Budget:
    """Public review/export seam for recomputing a worksheet-owned budget."""
    return _budget(start, end, params)


def _glossary_refs(g: Glossary | None) -> list[GlossaryRef]:
    """All terms are useful context, including pending note-only entries."""
    if g is None:
        return []
    return [
        GlossaryRef(source=t.source, target=t.target, note=t.note, keep=t.keep)
        for t in g.terms
    ]


def build_worksheet(
    cues: Cues,
    glossary: Glossary | None,
    target_lang: str,
    *,
    max_cps: float | None = None,
    max_chars_per_line: int | None = None,
    max_lines: int | None = None,
    title: str | None = None,
    author: str | None = None,
) -> tuple[Translation, bool]:
    """Prepare a worksheet for ``target_lang``. Returns (doc, generic_profile)."""
    profile, generic = seg.resolve_profile(target_lang)
    overrides = {
        "max_cps": max_cps,
        "max_chars_per_line": max_chars_per_line,
        "max_lines": max_lines,
    }
    invalid = {name: value for name, value in overrides.items() if value is not None and value <= 0}
    if invalid:
        raise OpenBBQError(
            "invalid_translation_profile",
            values=invalid,
            fix="use positive target-side budget overrides",
        )
    profile = seg.apply_overrides(profile, **overrides)
    params = _snapshot(profile)
    items = [
        TranslationItem(
            id=c.id,
            source=c.source,
            budget=_budget(c.start, c.end, params),
            target=None,
        )
        for c in cues.cues
    ]
    doc = Translation(
        schema_="openbbq/translation@2",
        source_lang=cues.source_lang,
        target_lang=target_lang,
        params=params,
        glossary=_glossary_refs(glossary),
        brief=translation_rules.build_brief(
            cues.source_lang,
            target_lang,
            title=title,
            author=author,
            glossary_context=None if glossary is None else glossary.context,
        ),
        items=items,
    )
    return doc, generic


# --- apply (translate apply) ---------------------------------------------------

_TARGETS_FIX = (
    'write a JSON object mapping cue id to translated text: {"1": "译文", "2": "..."}'
)


@dataclass(frozen=True)
class ApplyReport:
    applied: int  # targets merged this call
    overwritten: int  # of those, how many replaced an already-filled target
    filled: int  # worksheet-wide filled count after the merge
    total: int


def parse_targets(text: str) -> dict[int, str]:
    """Parse a targets batch: a JSON object mapping cue id → translated text.

    The minimal shape an Agent can Write without touching worksheet structure
    (DESIGN §9 长视频分批). Keys are ids (JSON object keys arrive as strings);
    values must be non-blank strings — a blank here is a mistake, not progress.
    """
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise OpenBBQError(
            "targets_invalid", detail=f"not valid JSON: {e}", fix=_TARGETS_FIX
        ) from e
    if not isinstance(raw, dict):
        raise OpenBBQError(
            "targets_invalid",
            detail="top level must be a JSON object",
            fix=_TARGETS_FIX,
        )
    if not raw:
        raise OpenBBQError(
            "targets_invalid", detail="object is empty", fix=_TARGETS_FIX
        )
    targets: dict[int, str] = {}
    bad: list[str] = []
    for key, value in raw.items():
        try:
            id_ = int(key)
        except ValueError:
            bad.append(key)
            continue
        if not isinstance(value, str) or not value.strip() or id_ in targets:
            bad.append(key)
            continue
        targets[id_] = value
    if bad:
        raise OpenBBQError(
            "targets_invalid",
            keys=bad[:15],
            detail="keys must be cue ids, values non-blank strings",
            fix=_TARGETS_FIX,
        )
    return targets


def apply_targets(worksheet: Translation, targets: dict[int, str]) -> ApplyReport:
    """Merge a targets batch into the worksheet, in place. Partial batches are
    fine (untouched ids keep their state); unknown ids hard-fail before any
    mutation so a bad batch never half-applies.
    """
    known = {it.id for it in worksheet.items}
    unknown = sorted(set(targets) - known)
    if unknown:
        raise OpenBBQError(
            "unknown_ids",
            ids=unknown[:15],
            fix="use cue ids from the worksheet; re-read translation.<lang>.json",
        )
    applied = overwritten = 0
    for it in worksheet.items:
        if it.id in targets:
            if is_filled(it.target):
                overwritten += 1
            it.target = targets[it.id]
            applied += 1
    filled = sum(1 for it in worksheet.items if is_filled(it.target))
    return ApplyReport(
        applied=applied,
        overwritten=overwritten,
        filled=filled,
        total=len(worksheet.items),
    )


# --- check (translate check) --------------------------------------------------


@dataclass(frozen=True)
class TermIssue:
    id: int
    term: str
    expected: str


@dataclass(frozen=True)
class QualityIssue:
    id: int
    code: str
    detail: str


@dataclass(frozen=True)
class CheckReport:
    total: int
    filled: int
    missing: list[int]  # ids still untranslated (None or blank)
    over_budget: list[int]  # filled ids whose target exceeds budget.max_chars
    zero_budget: list[int]  # ids whose timing leaves no target-language capacity
    term_warnings: int
    term_issues: list[TermIssue]
    quality_warnings: int
    quality_issues: list[QualityIssue]

    @property
    def ready(self) -> bool:
        """True only when deterministic translation gates are all clear."""
        return not (
            self.missing
            or self.over_budget
            or self.zero_budget
            or self.term_issues
            or self.quality_issues
        )


def verify_integrity(cues: Cues, worksheet: Translation, lang: str) -> None:
    """Hard-fail when an editable worksheet no longer matches its cues."""
    if worksheet.target_lang != lang:
        raise OpenBBQError(
            "lang_mismatch",
            worksheet=worksheet.target_lang,
            filename=lang,
            fix="rename or re-init: `openbbq translate init <lang> --force`",
        )
    if worksheet.source_lang != cues.source_lang:
        raise OpenBBQError(
            "lang_mismatch",
            source=worksheet.source_lang,
            cues=cues.source_lang,
            fix="worksheet doesn't match these cues; re-init",
        )
    ids = [it.id for it in worksheet.items]
    if len(ids) != len(set(ids)):
        raise OpenBBQError(
            "id_mismatch",
            detail="duplicate item ids",
            fix="re-init the worksheet (--force)",
        )
    if set(ids) != {c.id for c in cues.cues}:
        raise OpenBBQError(
            "id_mismatch", fix="cues changed; re-init the worksheet (--force)"
        )
    source_of = {c.id: c.source for c in cues.cues}
    for it in worksheet.items:
        if it.source != source_of[it.id]:
            raise OpenBBQError(
                "source_drift", id=it.id, fix="don't edit source; re-init (--force)"
            )


def check(cues: Cues, worksheet: Translation, lang: str) -> CheckReport:
    """Validate a worksheet against its cues. Hard integrity violations raise;
    completeness + term warnings are returned (the Agent's progress signal).
    """
    verify_integrity(cues, worksheet, lang)

    # --- soft status ---
    missing = [it.id for it in worksheet.items if not is_filled(it.target)]
    over_budget = _over_budget(worksheet)
    zero_budget = [it.id for it in worksheet.items if it.budget.max_chars <= 0]
    term_issues = _term_issues(worksheet)
    quality_issues = _quality_issues(worksheet)
    return CheckReport(
        total=len(worksheet.items),
        filled=len(worksheet.items) - len(missing),
        missing=missing,
        over_budget=over_budget,
        zero_budget=zero_budget,
        term_warnings=len(term_issues),
        term_issues=term_issues,
        quality_warnings=len(quality_issues),
        quality_issues=quality_issues,
    )


def _worksheet_profile(worksheet: Translation) -> seg.LanguageProfile:
    """Rehydrate target params, borrowing only cjk-ness from the lang profile."""
    cjk_profile, _ = seg.resolve_profile(worksheet.target_lang)
    params = worksheet.params
    return seg.LanguageProfile(
        max_cps=params.max_cps,
        max_chars_per_line=params.max_chars_per_line,
        max_lines=params.max_lines,
        min_dur=params.min_dur,
        max_dur=params.max_dur,
        min_gap=params.min_gap,
        pause_threshold=params.pause_threshold,
        cjk=cjk_profile.cjk,
    )


def count_target_chars(worksheet: Translation, text: str) -> int:
    return seg.count_chars(text, _worksheet_profile(worksheet))


_CJK_WRAP_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['’.-][A-Za-z0-9]+)*|[^\s]")
_LATIN_WRAP_TOKEN_RE = re.compile(r"^[A-Za-z0-9]+(?:['’.-][A-Za-z0-9]+)*$")


def wrap_target_lines(worksheet: Translation, text: str) -> list[str]:
    """Deterministically reflow target text without dropping or rewriting it."""
    profile = _worksheet_profile(worksheet)
    if profile.cjk:
        raw_tokens = _CJK_WRAP_TOKEN_RE.findall(text)
        tokens: list[str] = []
        previous_latin = False
        for token in raw_tokens:
            latin = _LATIN_WRAP_TOKEN_RE.match(token) is not None
            tokens.append(f" {token}" if latin and previous_latin else token)
            previous_latin = latin
    else:
        tokens = text.split()
    return [line.strip() for line in seg.pack_lines(tokens, profile)]


def _over_budget(worksheet: Translation) -> list[int]:
    profile = _worksheet_profile(worksheet)
    return [
        it.id
        for it in worksheet.items
        if is_filled(it.target)
        and seg.count_chars(it.target or "", profile) > it.budget.max_chars
    ]


def _term_issues(worksheet: Translation) -> list[TermIssue]:
    """Filled cues whose source carries a glossary term but whose target dropped
    the mapped translation (keep → source verbatim). Substring-level lint, soft.
    """
    if not worksheet.glossary:
        return []
    issues: list[TermIssue] = []
    for it in worksheet.items:
        if not is_filled(it.target):
            continue
        target = it.target or ""
        target_fold = target.casefold()
        for ref in worksheet.glossary:
            if not gl.contains_term(it.source, ref.source):
                continue
            expect = ref.source if ref.keep else ref.target
            if expect and expect.casefold() not in target_fold:
                issues.append(TermIssue(id=it.id, term=ref.source, expected=expect))
    return issues


_ASCII_WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
_ZH_JA_SCRIPT_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff]")
_KO_SCRIPT_RE = re.compile(r"[\uac00-\ud7af]")


def _quality_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in normalized if ch.isalnum())


def _kept_source_only(worksheet: Translation, source: str) -> bool:
    source_key = _quality_key(source)
    return any(
        ref.keep and _quality_key(ref.source) == source_key
        for ref in worksheet.glossary
    )


def _expected_script_present(lang: str, text: str) -> bool | None:
    base = lang.split("-", 1)[0].casefold()
    if base in {"zh", "ja"}:
        return bool(_ZH_JA_SCRIPT_RE.search(text))
    if base == "ko":
        return bool(_KO_SCRIPT_RE.search(text))
    return None


def _quality_issues(worksheet: Translation) -> list[QualityIssue]:
    """Conservative deterministic lint for failure patterns seen in agent runs.

    This deliberately does not claim semantic correctness. It catches copied
    source text, clearly wrong target script, and long duplicate runs so those
    artifacts cannot be mistaken for a completed translation.
    """
    issues: list[QualityIssue] = []
    filled = [item for item in worksheet.items if is_filled(item.target)]

    if worksheet.source_lang.casefold() != worksheet.target_lang.casefold():
        for item in filled:
            target = item.target or ""
            lines = wrap_target_lines(worksheet, target)
            profile = _worksheet_profile(worksheet)
            if len(lines) > profile.max_lines or any(
                seg.count_chars(line, profile) > profile.max_chars_per_line
                for line in lines
            ):
                issues.append(
                    QualityIssue(
                        id=item.id,
                        code="line_capacity",
                        detail=(
                            f"target needs {len(lines)} line(s); profile allows "
                            f"{profile.max_lines} × {profile.max_chars_per_line} chars"
                        ),
                    )
                )
            if _quality_key(item.source) == _quality_key(
                target
            ) and not _kept_source_only(worksheet, item.source):
                issues.append(
                    QualityIssue(
                        id=item.id,
                        code="source_copy",
                        detail="target matches source",
                    )
                )
                continue

            expected = _expected_script_present(worksheet.target_lang, target)
            if expected is False:
                source_words = _ASCII_WORD_RE.findall(item.source)
                target_words = _ASCII_WORD_RE.findall(target)
                if len(source_words) >= 2 and len(target_words) >= 2:
                    issues.append(
                        QualityIssue(
                            id=item.id,
                            code="target_script",
                            detail=f"target does not contain {worksheet.target_lang} script",
                        )
                    )

    by_target: dict[str, list[TranslationItem]] = {}
    for item in filled:
        key = _quality_key(item.target or "")
        if len(key) >= 6:
            by_target.setdefault(key, []).append(item)
    for group in by_target.values():
        if len(group) < 3 or len({_quality_key(item.source) for item in group}) < 3:
            continue
        count = len(group)
        for item in group:
            issues.append(
                QualityIssue(
                    id=item.id,
                    code="repeated_target",
                    detail=f"same target is used for {count} distinct cues",
                )
            )

    return sorted(issues, key=lambda issue: (issue.id, issue.code))


# --- bounded Agent read (translate batch) ------------------------------------


@dataclass(frozen=True)
class BatchItem:
    id: int
    source: str
    target: str | None
    budget: Budget
    selected: bool


@dataclass(frozen=True)
class BatchReport:
    selected_ids: list[int]
    items: list[BatchItem]
    glossary: list[GlossaryRef]
    next_from: int | None
    remaining: int


def select_batch(
    worksheet: Translation,
    *,
    start: int = 1,
    limit: int = 20,
    only_missing: bool = False,
    context: int = 1,
) -> BatchReport:
    """Return a bounded worksheet slice plus nearby context for an Agent."""
    if start < 1 or not 1 <= limit <= 200 or not 0 <= context <= 5:
        raise OpenBBQError(
            "invalid_batch_range",
            start=start,
            limit=limit,
            context=context,
            fix="use --from >= 1, --limit 1..200, and --context 0..5",
        )

    candidates = [
        (index, item)
        for index, item in enumerate(worksheet.items)
        if item.id >= start and (not only_missing or not is_filled(item.target))
    ]
    selected = candidates[:limit]
    selected_indexes = {index for index, _item in selected}
    included_indexes: set[int] = set()
    for index in selected_indexes:
        low = max(0, index - context)
        high = min(len(worksheet.items), index + context + 1)
        included_indexes.update(range(low, high))

    items = [
        BatchItem(
            id=worksheet.items[index].id,
            source=worksheet.items[index].source,
            target=worksheet.items[index].target,
            budget=worksheet.items[index].budget,
            selected=index in selected_indexes,
        )
        for index in sorted(included_indexes)
    ]
    # Terms in neighbor cues are part of the semantic context too.  In
    # particular a pending note-only term may explain the selected cue even
    # when the literal spelling occurs just outside the selected range.
    included_sources = [item.source for item in items]
    relevant_glossary = [
        ref
        for ref in worksheet.glossary
        if any(gl.contains_term(source, ref.source) for source in included_sources)
    ]
    return BatchReport(
        selected_ids=[item.id for _index, item in selected],
        items=items,
        glossary=relevant_glossary,
        next_from=candidates[limit][1].id if len(candidates) > limit else None,
        remaining=max(len(candidates) - limit, 0),
    )

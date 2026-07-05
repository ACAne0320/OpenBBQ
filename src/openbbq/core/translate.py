"""Translation worksheet: build a per-language work file from cues + glossary,
and validate a filled one.

Source/target split, joined at export (DESIGN translate spec): ``cues.json`` is
the immutable source product; each target language gets a ``translation@1``
worksheet the Agent owns. ``build_worksheet`` prepares it (budget per cue +
glossary map), ``apply_targets`` merges an id→target batch into it (how the
Agent fills at scale without ad hoc scripts), ``check`` validates a filled one
(integrity hard-fails; status is reported). Pure domain logic — no cli/output;
failures surface as OpenBBQError.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from openbbq.core import glossary as gl
from openbbq.core import segment as seg
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


def _glossary_refs(g: Glossary | None) -> list[GlossaryRef]:
    """Terms that carry translation guidance (a target or keep) → the worksheet map."""
    if g is None:
        return []
    return [
        GlossaryRef(source=t.source, target=t.target, note=t.note, keep=t.keep)
        for t in g.terms
        if t.target is not None or t.keep
    ]


def build_worksheet(
    cues: Cues, glossary: Glossary | None, target_lang: str
) -> tuple[Translation, bool]:
    """Prepare a worksheet for ``target_lang``. Returns (doc, generic_profile)."""
    profile, generic = seg.resolve_profile(target_lang)
    params = _snapshot(profile)
    items = [
        TranslationItem(
            id=c.id, source=c.source, budget=_budget(c.start, c.end, params), target=None
        )
        for c in cues.cues
    ]
    doc = Translation(
        source_lang=cues.source_lang,
        target_lang=target_lang,
        params=params,
        glossary=_glossary_refs(glossary),
        items=items,
    )
    return doc, generic


# --- apply (translate apply) ---------------------------------------------------

_TARGETS_FIX = 'write a JSON object mapping cue id to translated text: {"1": "译文", "2": "..."}'


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
            "targets_invalid", detail="top level must be a JSON object", fix=_TARGETS_FIX
        )
    if not raw:
        raise OpenBBQError("targets_invalid", detail="object is empty", fix=_TARGETS_FIX)
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
        applied=applied, overwritten=overwritten, filled=filled, total=len(worksheet.items)
    )


# --- check (translate check) --------------------------------------------------


@dataclass(frozen=True)
class TermIssue:
    id: int
    term: str
    expected: str


@dataclass(frozen=True)
class CheckReport:
    total: int
    filled: int
    missing: list[int]  # ids still untranslated (None or blank)
    over_budget: list[int]  # filled ids whose target exceeds budget.max_chars
    term_warnings: int
    term_issues: list[TermIssue]


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
            "id_mismatch", detail="duplicate item ids", fix="re-init the worksheet (--force)"
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
    term_issues = _term_issues(worksheet)
    return CheckReport(
        total=len(worksheet.items),
        filled=len(worksheet.items) - len(missing),
        missing=missing,
        over_budget=over_budget,
        term_warnings=len(term_issues),
        term_issues=term_issues,
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

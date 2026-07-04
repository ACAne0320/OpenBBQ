"""Translation worksheet: build a per-language work file from cues + glossary,
and validate a filled one.

Source/target split, joined at export (DESIGN translate spec): ``cues.json`` is
the immutable source product; each target language gets a ``translation@1``
worksheet the Agent owns. ``build_worksheet`` prepares it (budget per cue +
glossary map), ``check`` validates a filled one (integrity hard-fails; status is
reported). Pure domain logic — no cli/output; failures surface as OpenBBQError.
"""

from __future__ import annotations

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


# --- check (translate check) --------------------------------------------------


@dataclass(frozen=True)
class CheckReport:
    total: int
    filled: int
    missing: list[int]  # ids still untranslated (None or blank)
    term_warnings: int


def check(cues: Cues, worksheet: Translation, lang: str) -> CheckReport:
    """Validate a worksheet against its cues. Hard integrity violations raise;
    completeness + term warnings are returned (the Agent's progress signal).
    """
    # --- hard integrity (worksheet is Agent-editable) ---
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

    # --- soft status ---
    missing = [it.id for it in worksheet.items if not is_filled(it.target)]
    return CheckReport(
        total=len(worksheet.items),
        filled=len(worksheet.items) - len(missing),
        missing=missing,
        term_warnings=_term_warnings(worksheet),
    )


def _term_warnings(worksheet: Translation) -> int:
    """Filled cues whose source carries a glossary term but whose target dropped
    the mapped translation (keep → source verbatim). Substring-level lint, soft.
    """
    if not worksheet.glossary:
        return 0
    warnings = 0
    for it in worksheet.items:
        if not is_filled(it.target):
            continue
        target = it.target or ""
        for ref in worksheet.glossary:
            if not gl.contains_term(it.source, ref.source):
                continue
            expect = ref.source if ref.keep else ref.target
            if expect and expect not in target:
                warnings += 1
    return warnings

"""Glossary library: a global named-entity dictionary per series/topic,
stored at ``$OPENBBQ_HOME/glossaries/<name>.json``.

The single place that knows the library layout. It loads/validates into the
``glossary@1`` schema and derives deterministic ASR **bias**, ``alias -> source``
**correction**, candidate **suggestion**, atomic term patching, and correction
effect reports. Pure domain logic — no cli/output; failures surface as
``OpenBBQError``. Authoring the terms themselves is semantic and stays with the
agent.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from openbbq.core.workspace import write_text_atomic
from openbbq.errors import OpenBBQError
from openbbq.schemas import Glossary, Term, Transcript

MAX_GLOSSARY_PATCH = 20

# --- library layout -----------------------------------------------------------


def library_dir() -> Path:
    """``$OPENBBQ_HOME/glossaries`` (default ``~/.openbbq/glossaries``)."""
    home = Path(os.environ.get("OPENBBQ_HOME", "~/.openbbq")).expanduser()
    return home / "glossaries"


def glossary_path(name: str) -> Path:
    return library_dir() / f"{name}.json"


def list_names() -> list[str]:
    """Named glossaries in the library (empty when the dir doesn't exist)."""
    d = library_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def load(name: str) -> Glossary:
    """Load + validate one glossary, mapping failures to domain errors.

    Same gate as ``workspace.read_transcript``: a missing file is a distinct,
    fixable condition; a malformed/incompatible one surfaces structured.
    """
    path = glossary_path(name)
    if not path.is_file():
        raise OpenBBQError(
            "glossary_not_found", name=name, fix=f"openbbq glossary new {name}"
        )
    try:
        return Glossary.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise OpenBBQError(
            "invalid_glossary",
            name=name,
            path=str(path),
            fix="glossary is malformed or from an incompatible schema version",
        ) from e


def load_optional(name: str | None) -> Glossary | None:
    """Resolve a bound/overridden glossary name, or None when unset (always optional)."""
    return load(name) if name else None


def scaffold(name: str, context: str | None = None) -> Path:
    """Write a valid skeleton glossary; ``context`` declares its scope at birth."""
    path = glossary_path(name)
    if path.exists():
        raise OpenBBQError(
            "glossary_exists",
            name=name,
            path=str(path),
            fix="edit the existing glossary or choose another name",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    skeleton = Glossary(name=name, context=context, terms=[])
    write_text_atomic(path, skeleton.model_dump_json(indent=2, exclude_none=True))
    return path


def save(glossary: Glossary) -> Path:
    """Validate and atomically persist a glossary in its canonical location."""

    path = glossary_path(glossary.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    validated = Glossary.model_validate(glossary.model_dump(by_alias=True))
    write_text_atomic(
        path,
        validated.model_dump_json(indent=2, exclude_none=True) + "\n",
    )
    return path


@dataclass(frozen=True)
class PatchReport:
    added: tuple[str, ...]
    updated: tuple[str, ...]
    unchanged: tuple[str, ...]
    aliases_added: int


def parse_term_patch(text: str) -> list[Term]:
    """Parse ``{"terms": [...]}`` for one bounded, atomic glossary update."""

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise OpenBBQError(
            "glossary_patch_invalid",
            detail="expected a JSON object with a non-empty terms array",
        ) from error
    values = raw.get("terms") if isinstance(raw, dict) else None
    if not isinstance(values, list) or not values:
        raise OpenBBQError(
            "glossary_patch_invalid",
            detail="expected a JSON object with a non-empty terms array",
        )
    if len(values) > MAX_GLOSSARY_PATCH:
        raise OpenBBQError(
            "glossary_patch_too_large",
            count=len(values),
            max=MAX_GLOSSARY_PATCH,
            fix="apply at most 20 glossary terms at a time",
        )
    try:
        terms = [Term.model_validate(value) for value in values]
    except (ValidationError, ValueError, TypeError) as error:
        raise OpenBBQError("glossary_patch_invalid", detail=str(error)) from error
    for term in terms:
        provided = set(term.model_fields_set)
        term.source = term.source.strip()
        if not term.source:
            raise OpenBBQError(
                "glossary_patch_invalid",
                detail="term source must not be blank",
            )
        term.aliases = [alias.strip() for alias in term.aliases if alias.strip()]
        if "target" in provided:
            term.target = term.target.strip() if term.target is not None else None
        if "note" in provided:
            term.note = term.note.strip() if term.note is not None else None
        term.model_fields_set.intersection_update(provided)
    return terms


def _validate_form_ownership(terms: list[Term]) -> None:
    owners: dict[str, str] = {}
    for term in terms:
        owner = term.source.casefold()
        for form in (term.source, *term.aliases):
            key = form.casefold()
            previous = owners.get(key)
            if previous is not None and previous != owner:
                raise OpenBBQError(
                    "glossary_form_conflict",
                    form=form,
                    sources=sorted({previous, owner}),
                    fix="keep each canonical spelling or alias owned by one term",
                )
            owners[key] = owner


def upsert_terms(
    glossary: Glossary, patches: list[Term]
) -> tuple[Glossary, PatchReport]:
    """Merge validated terms in memory; callers save only after the whole batch passes."""

    terms = [term.model_copy(deep=True) for term in glossary.terms]
    by_source = {term.source.casefold(): index for index, term in enumerate(terms)}
    added: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    aliases_added = 0

    for patch in patches:
        key = patch.source.casefold()
        index = by_source.get(key)
        if index is None:
            aliases = list(
                dict.fromkeys(
                    alias for alias in patch.aliases if alias.casefold() != key
                )
            )
            term = patch.model_copy(update={"aliases": aliases})
            terms.append(term)
            by_source[key] = len(terms) - 1
            added.append(term.source)
            aliases_added += len(aliases)
            continue

        current = terms[index]
        before = current.model_dump()
        aliases = list(current.aliases)
        known_aliases = {alias.casefold() for alias in aliases}
        for alias in patch.aliases:
            alias_key = alias.casefold()
            if alias_key == key or alias_key in known_aliases:
                continue
            aliases.append(alias)
            known_aliases.add(alias_key)
            aliases_added += 1
        changes: dict[str, object] = {"aliases": aliases}
        if "target" in patch.model_fields_set:
            changes["target"] = patch.target
        if "note" in patch.model_fields_set:
            changes["note"] = patch.note
        if "keep" in patch.model_fields_set:
            changes["keep"] = patch.keep
        merged = current.model_copy(update=changes)
        terms[index] = merged
        if merged.model_dump() == before:
            unchanged.append(current.source)
        else:
            updated.append(current.source)

    _validate_form_ownership(terms)
    result = glossary.model_copy(update={"terms": terms})
    Glossary.model_validate(result.model_dump(by_alias=True))
    return result, PatchReport(
        added=tuple(added),
        updated=tuple(updated),
        unchanged=tuple(unchanged),
        aliases_added=aliases_added,
    )


# --- touchpoint 1: ASR biasing ------------------------------------------------


def bias_terms(g: Glossary) -> list[str]:
    """Canonical source surface forms for ASR context biasing (deduped, ordered)."""
    seen: dict[str, None] = {}
    for t in g.terms:
        s = t.source.strip()
        if s:
            seen.setdefault(s, None)
    return list(seen)


# --- touchpoint 2: deterministic alias -> source correction -------------------


def _boundaried(alias: str) -> str:
    """Escaped alias guarded so it matches as a whole token where it has ASCII
    edges; CJK/punctuation-edged aliases fall back to a plain substring match
    (``\\b`` doesn't fire between two CJK word chars).
    """
    left = r"(?<![A-Za-z0-9])" if alias[:1].isascii() and alias[:1].isalnum() else ""
    right = r"(?![A-Za-z0-9])" if alias[-1:].isascii() and alias[-1:].isalnum() else ""
    return left + re.escape(alias) + right


def contains_term(text: str, term: str) -> bool:
    """Whole-token, case-insensitive membership of ``term`` in ``text`` — the
    public form of the alias boundary logic, shared by correction and by
    ``translate``'s term_warnings (DESIGN translate spec P3).
    """
    return bool(term) and re.search(_boundaried(term), text, re.IGNORECASE) is not None


def correction_map(g: Glossary) -> list[tuple[re.Pattern[str], str]]:
    """Compiled ``alias -> source`` replacements, case-insensitive, longest alias
    first so multi-word forms win over a contained shorter one.
    """
    pairs: list[tuple[str, str]] = []
    for t in g.terms:
        for alias in t.aliases:
            a = alias.strip()
            if a and a.lower() != t.source.lower():
                pairs.append((a, t.source))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return [(re.compile(_boundaried(a), re.IGNORECASE), src) for a, src in pairs]


def corrector(g: Glossary | None) -> Callable[[str], str]:
    """A text->text fixer for a glossary (identity when there's nothing to fix).

    Suitable to inject into ``segment.build_cues`` so corrections apply to the
    reconstructed ``cue.source`` before CPS/warning counting.
    """
    cmap = correction_map(g) if g is not None else []
    if not cmap:
        return lambda s: s

    def fix(text: str) -> str:
        for pat, src in cmap:
            text = pat.sub(src, text)
        return text

    return fix


@dataclass(frozen=True)
class AliasApplication:
    source: str
    alias: str
    count: int


class CorrectionTracker:
    """Callable glossary corrector that also records whether the binding mattered."""

    def __init__(self, glossary: Glossary | None):
        self.glossary = glossary
        self.matched_terms: set[str] = set()
        self._applications: dict[tuple[str, str], int] = {}
        self._forms: list[tuple[str, str]] = []
        self._aliases: list[tuple[re.Pattern[str], str, str]] = []
        if glossary is None:
            return
        for term in glossary.terms:
            for form in (term.source, *term.aliases):
                clean = form.strip()
                if clean:
                    self._forms.append((clean, term.source))
            for alias in term.aliases:
                clean = alias.strip()
                if clean and clean.casefold() != term.source.casefold():
                    self._aliases.append(
                        (
                            re.compile(_boundaried(clean), re.IGNORECASE),
                            term.source,
                            clean,
                        )
                    )
        self._forms.sort(key=lambda pair: len(pair[0]), reverse=True)
        self._aliases.sort(key=lambda item: len(item[2]), reverse=True)

    def __call__(self, text: str) -> str:
        for form, source in self._forms:
            if contains_term(text, form):
                self.matched_terms.add(source)
        for pattern, source, alias in self._aliases:
            text, count = pattern.subn(source, text)
            if count:
                key = (source, alias)
                self._applications[key] = self._applications.get(key, 0) + count
                self.matched_terms.add(source)
        return text

    @property
    def alias_applications(self) -> list[AliasApplication]:
        return [
            AliasApplication(source=source, alias=alias, count=count)
            for (source, alias), count in sorted(self._applications.items())
        ]


def matched_terms(glossary: Glossary | None, text: str) -> list[str]:
    """Canonical terms whose source or aliases occur in one text span."""

    if glossary is None:
        return []
    return [
        term.source
        for term in glossary.terms
        if any(contains_term(text, form) for form in (term.source, *term.aliases))
    ]


# --- touchpoint 3 helper + suggest: known forms / candidate mining ------------


def known_forms(g: Glossary) -> set[str]:
    """Lowercased sources + aliases — what ``suggest`` should not re-surface."""
    forms: set[str] = set()
    for t in g.terms:
        forms.add(t.source.lower())
        forms.update(a.lower() for a in t.aliases)
    return forms


@dataclass(frozen=True)
class Candidate:
    surface: str
    count: int
    avg_prob: float | None  # None when the transcript carries no word probabilities
    example: str  # a segment text containing the surface, for human review


def _strip_edges(token: str) -> str:
    """Drop leading/trailing non-word chars (keeps CJK, drops ,.!?\"…)."""
    return re.sub(r"^\W+|\W+$", "", token, flags=re.UNICODE)


def _looks_proper(surface: str) -> bool:
    """Proper-noun-shaped: an initial uppercase letter that isn't all-caps."""
    return surface[:1].isupper() and not surface.isupper()


def _surface_tokens(transcript: Transcript) -> Iterator[tuple[str, float | None, str]]:
    """(surface, prob, example) over the transcript: word-level where available
    (gives prob), else tokenized segment text (prob None) — the no-words fallback.
    """
    for seg in transcript.segments:
        if seg.words:
            for w in seg.words:
                surface = _strip_edges(w.word)
                if surface:
                    yield surface, w.prob, seg.text.strip()
        else:
            for tok in seg.text.split():
                surface = _strip_edges(tok)
                if surface:
                    yield surface, None, seg.text.strip()


def suggest_candidates(
    transcript: Transcript,
    *,
    known: set[str] | None = None,
    max_prob: float = 0.6,
    min_count: int = 1,
    limit: int = 30,
) -> list[Candidate]:
    """Mine likely glossary terms: low-confidence and/or proper-noun-shaped,
    recurring, not already known. Deterministic extraction feeding the agent's
    semantic curation (DESIGN glossary spec §6.4).
    """
    known = known or set()
    counts: dict[str, int] = {}
    prob_sum: dict[str, float] = {}
    prob_n: dict[str, int] = {}
    example: dict[str, str] = {}

    for surface, prob, ex in _surface_tokens(transcript):
        if surface.lower() in known or surface.isdigit() or len(surface) < 2:
            continue
        counts[surface] = counts.get(surface, 0) + 1
        if prob is not None:
            prob_sum[surface] = prob_sum.get(surface, 0.0) + prob
            prob_n[surface] = prob_n.get(surface, 0) + 1
        example.setdefault(surface, ex)

    candidates: list[Candidate] = []
    for surface, count in counts.items():
        if count < min_count:
            continue
        avg = prob_sum[surface] / prob_n[surface] if prob_n.get(surface) else None
        proper = _looks_proper(surface)
        recurring = count >= 2
        if avg is not None:
            keep = avg < max_prob and (recurring or proper)
        else:  # no probabilities: lean on casing + frequency
            keep = proper and recurring
        if keep:
            candidates.append(Candidate(surface, count, avg, example[surface]))

    # Most suspicious first: lowest confidence, then most frequent.
    candidates.sort(
        key=lambda c: (c.avg_prob if c.avg_prob is not None else 1.0, -c.count)
    )
    return candidates[:limit]

"""Workspace-local glossary learning and conflict-safe publication."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from openbbq.core import glossary as glossarylib
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    AgentGlossaryUpdate,
    AgentCueSourceFix,
    AgentSourceFix,
    AgentWarning,
    Glossary,
    GlossaryCandidate,
    GlossaryOverlay,
    GlossaryOverlayEntry,
    Term,
)

_OVERLAY_PATH = Path(".openbbq") / "glossary-overlay.json"
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def validate_name(name: str) -> str:
    if not _SAFE_NAME_RE.fullmatch(name):
        raise OpenBBQError(
            "invalid_glossary_name",
            name=name,
            fix="use 1-80 letters, numbers, dots, underscores, or hyphens",
        )
    return name


def path(workspace: Path) -> Path:
    return workspace / _OVERLAY_PATH


def read_optional(workspace: Path) -> GlossaryOverlay | None:
    overlay_path = path(workspace)
    if not overlay_path.is_file():
        return None
    try:
        return GlossaryOverlay.model_validate_json(
            overlay_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise OpenBBQError(
            "invalid_glossary_overlay",
            path=str(overlay_path),
            fix="restore or remove the workspace glossary overlay, then run openbbq agent next",
        ) from error


def write(workspace: Path, overlay: GlossaryOverlay) -> Path:
    overlay_path = path(workspace)
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    ws.write_text_atomic(overlay_path, overlay.model_dump_json(indent=2) + "\n")
    return overlay_path


def initialize(
    workspace: Path,
    *,
    base_name: str | None,
    context: str | None = None,
) -> GlossaryOverlay:
    base: Glossary | None = None
    if base_name is not None:
        validate_name(base_name)
        candidate = glossarylib.glossary_path(base_name)
        if candidate.is_file():
            base = glossarylib.load(base_name)
            if context is None:
                context = base.context
    overlay = GlossaryOverlay(
        base_name=base_name,
        context=context,
    )
    write(workspace, overlay)
    return overlay


def rebind(workspace: Path, base: Glossary) -> GlossaryOverlay:
    """Move an existing task overlay to an explicitly selected base glossary.

    Learned entries are preserved only when they merge cleanly with the new
    base. Validation happens before the sidecar is replaced, so a conflicting
    explicit selection cannot leave manifest and overlay ownership split.
    """

    overlay = read_optional(workspace)
    if overlay is None:
        return initialize(
            workspace,
            base_name=base.name,
            context=base.context,
        )
    candidate = overlay.model_copy(
        update={
            "base_name": validate_name(base.name),
            "context": base.context or overlay.context,
        }
    )
    merged_overlay(workspace, candidate, base.name)
    write(workspace, candidate)
    return candidate


def _base_for_overlay(overlay: GlossaryOverlay) -> Glossary:
    if overlay.base_name is None:
        return Glossary(name="workspace", context=overlay.context, terms=[])
    candidate = glossarylib.glossary_path(overlay.base_name)
    if candidate.is_file():
        return glossarylib.load(overlay.base_name)
    return Glossary(name=overlay.base_name, context=overlay.context, terms=[])


def merged(workspace: Path, base_name: str | None = None) -> Glossary | None:
    """Return base + task-local reusable patches without publishing them."""

    overlay = read_optional(workspace)
    if overlay is None:
        return glossarylib.load_optional(base_name)
    return merged_overlay(workspace, overlay, base_name)


def merged_overlay(
    workspace: Path,
    overlay: GlossaryOverlay,
    base_name: str | None = None,
) -> Glossary | None:
    """Resolve an in-memory overlay candidate against its effective base."""

    if base_name is not None and overlay.base_name != base_name:
        raise OpenBBQError(
            "glossary_overlay_binding_mismatch",
            overlay=overlay.base_name,
            manifest=base_name,
            fix="run openbbq agent next to repair the glossary selection",
        )
    if overlay.base_name is None and overlay.context is None and not overlay.entries:
        return None
    base = _base_for_overlay(overlay)
    if overlay.context is not None:
        base = base.model_copy(update={"context": overlay.context})
    if not overlay.entries:
        return base
    result, _ = glossarylib.upsert_terms(
        base,
        [_entry_patch(entry) for entry in overlay.entries],
    )
    return result


def prepare_updates(
    workspace: Path,
    updates: list[AgentGlossaryUpdate],
) -> tuple[GlossaryOverlay, list[str]]:
    """Validate and merge updates without writing the overlay sidecar.

    Agent batch applies use this to commit the overlay together with source
    and translation documents, so a later file-write failure cannot leak a
    partially learned global alias into the workspace.
    """

    overlay = read_optional(workspace) or GlossaryOverlay()
    reusable = [update for update in updates if update.reusable]
    ignored = [update.source for update in updates if not update.reusable]
    if not reusable:
        return overlay, ignored

    evidence_by_source = {
        entry.term.source.casefold(): list(entry.evidence) for entry in overlay.entries
    }
    fields_by_source = {
        entry.term.source.casefold(): set(entry.update_fields)
        for entry in overlay.entries
    }
    local = Glossary(name="overlay", terms=[entry.term for entry in overlay.entries])
    local, _ = glossarylib.upsert_terms(local, [update.term() for update in reusable])
    for update in reusable:
        evidence = evidence_by_source.setdefault(update.source.casefold(), [])
        if update.evidence not in evidence:
            evidence.append(update.evidence)
        fields_by_source.setdefault(update.source.casefold(), set()).update(
            field
            for field in ("target", "note", "keep")
            if field in update.model_fields_set
        )
    entries = [
        GlossaryOverlayEntry(
            term=term,
            evidence=evidence_by_source.get(term.source.casefold(), []),
            update_fields=sorted(fields_by_source.get(term.source.casefold(), set())),
        )
        for term in local.terms
    ]
    updated = overlay.model_copy(update={"entries": entries})
    # Validate against the effective base before replacing the sidecar.  This
    # catches alias ownership conflicts without leaving a half-applied overlay.
    base = _base_for_overlay(updated)
    glossarylib.upsert_terms(base, [_entry_patch(entry) for entry in updated.entries])
    return updated, ignored


def prepare_updates_with_candidates(
    workspace: Path,
    updates: list[AgentGlossaryUpdate],
    source_fixes: Sequence[AgentSourceFix | AgentCueSourceFix],
    *,
    origin: Literal["review_source", "translate"],
) -> tuple[GlossaryOverlay, list[str], int]:
    """Turn every non-deletion source fix into an auditable glossary candidate.

    The agent makes only the semantic reuse decision on the source fix itself.
    OpenBBQ derives the canonical term and alias, promotes reusable candidates
    into the task overlay immediately, and still defers global publication to
    successful delivery.
    """

    if origin not in {"review_source", "translate"}:
        raise ValueError(f"unsupported glossary candidate origin: {origin}")
    generated_updates: list[AgentGlossaryUpdate] = []
    candidates: list[GlossaryCandidate] = []
    for fix in source_fixes:
        if not fix.replacement:
            continue
        item_id = fix.segment_id if isinstance(fix, AgentSourceFix) else fix.cue_id
        digest = hashlib.sha256(
            f"{origin}\0{item_id}\0{fix.find}\0{fix.replacement}".encode("utf-8")
        ).hexdigest()[:16]
        candidates.append(
            GlossaryCandidate(
                id=f"gc:{digest}",
                source=fix.replacement,
                alias=fix.find,
                evidence=fix.evidence,
                origin=origin,
                item_id=item_id,
                reusable=fix.reusable,
            )
        )
        if fix.reusable:
            generated_updates.append(
                AgentGlossaryUpdate(
                    source=fix.replacement,
                    aliases=[fix.find],
                    reusable=True,
                    evidence=fix.evidence,
                )
            )

    updated, ignored = prepare_updates(workspace, [*updates, *generated_updates])
    if candidates:
        by_id = {candidate.id: candidate for candidate in updated.candidates}
        for candidate in candidates:
            by_id[candidate.id] = candidate
        updated = updated.model_copy(update={"candidates": list(by_id.values())})
    return updated, ignored, len(candidates)


def _entry_patch(entry: GlossaryOverlayEntry) -> Term:
    values: dict[str, object] = {
        "source": entry.term.source,
        "aliases": entry.term.aliases,
    }
    for field in entry.update_fields:
        values[field] = getattr(entry.term, field)
    return Term.model_validate(values)


@dataclass(frozen=True)
class PublishReport:
    published: bool
    terms: tuple[str, ...]
    warnings: tuple[AgentWarning, ...]


def _owners(terms: list[Term]) -> dict[str, str]:
    owners: dict[str, str] = {}
    for term in terms:
        for form in (term.source, *term.aliases):
            owners[form.casefold()] = term.source.casefold()
    return owners


def publish(workspace: Path) -> PublishReport:
    """Publish every non-conflicting reusable entry without overwriting data."""

    overlay = read_optional(workspace)
    if overlay is None or not overlay.entries:
        return PublishReport(published=True, terms=(), warnings=())
    retry = ["openbbq", "agent", "finish", "--workspace", str(workspace)]
    if overlay.base_name is None:
        return PublishReport(
            published=False,
            terms=(),
            warnings=(
                AgentWarning(
                    code="glossary_publish_unbound",
                    detail="reusable terms remain in the workspace overlay because no global glossary was selected",
                    retry_argv=retry,
                ),
            ),
        )

    name = validate_name(overlay.base_name)
    candidate = glossarylib.glossary_path(name)
    try:
        current = (
            glossarylib.load(name)
            if candidate.is_file()
            else Glossary(name=name, context=overlay.context, terms=[])
        )
    except OpenBBQError as error:
        return PublishReport(
            published=False,
            terms=(),
            warnings=(
                AgentWarning(
                    code="glossary_publish_failed",
                    detail=f"could not read global glossary {name}: {error.code}",
                    retry_argv=retry,
                ),
            ),
        )

    terms = [term.model_copy(deep=True) for term in current.terms]
    by_source = {term.source.casefold(): index for index, term in enumerate(terms)}
    published: list[str] = []
    conflicts: list[str] = []
    for entry in overlay.entries:
        patch = entry.term
        key = patch.source.casefold()
        owners = _owners(terms)
        foreign_form = next(
            (
                form
                for form in (patch.source, *patch.aliases)
                if owners.get(form.casefold()) not in {None, key}
            ),
            None,
        )
        index = by_source.get(key)
        if foreign_form is not None:
            conflicts.append(f"{patch.source} (form {foreign_form})")
            continue
        if index is None:
            terms.append(patch.model_copy(deep=True))
            by_source[key] = len(terms) - 1
            published.append(patch.source)
            continue

        old = terms[index]
        semantic_conflict = (
            patch.target is not None
            and old.target is not None
            and patch.target != old.target
        ) or (patch.keep and not old.keep and old.target is not None)
        if semantic_conflict:
            conflicts.append(patch.source)
            continue
        aliases = list(old.aliases)
        known = {alias.casefold() for alias in aliases}
        aliases.extend(
            alias for alias in patch.aliases if alias.casefold() not in known
        )
        terms[index] = old.model_copy(
            update={
                "aliases": aliases,
                "target": old.target if old.target is not None else patch.target,
                "note": old.note if old.note is not None else patch.note,
                "keep": old.keep or patch.keep,
            }
        )
        published.append(patch.source)

    result = current.model_copy(
        update={
            "context": current.context or overlay.context,
            "terms": terms,
        }
    )
    try:
        # The no-op upsert performs the complete form-ownership validation.
        result, _ = glossarylib.upsert_terms(result, [])
        glossarylib.save(result)
    except (OpenBBQError, OSError) as error:
        return PublishReport(
            published=False,
            terms=(),
            warnings=(
                AgentWarning(
                    code="glossary_publish_failed",
                    detail=f"could not write global glossary {name}: {error}",
                    retry_argv=retry,
                ),
            ),
        )

    warnings: list[AgentWarning] = []
    if conflicts:
        warnings.append(
            AgentWarning(
                code="glossary_publish_conflict",
                detail=(
                    "kept existing global entries; unresolved workspace terms: "
                    + ", ".join(conflicts)
                ),
                retry_argv=retry,
            )
        )
    return PublishReport(
        published=not conflicts,
        terms=tuple(published),
        warnings=tuple(warnings),
    )

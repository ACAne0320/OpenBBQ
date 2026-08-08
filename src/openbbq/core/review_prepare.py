"""Agent-driven review pre-analysis (``openbbq review --prepare``).

A two-step flow fitting the external-agent protocol: build an analysis
payload for the agent, then apply the agent's response as pending review
suggestions.  Neither step opens a review session, takes the review lock, or
touches agent leases/freshness hashes — the default pipeline is unaffected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError, model_validator

from openbbq.core import review as reviewlib
from openbbq.core import review_issues
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    Cues,
    Manifest,
    OpenBBQModel,
    Review,
    ReviewItem,
    Stage,
    StageStatus,
    SuggestionDraft,
    Transcript,
    Translation,
)

MAX_PREPARE_SUGGESTIONS = 100


class _PrepareResponse(OpenBBQModel):
    suggestions: list[SuggestionDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_size(self) -> _PrepareResponse:
        if len(self.suggestions) > MAX_PREPARE_SUGGESTIONS:
            raise ValueError(
                f"at most {MAX_PREPARE_SUGGESTIONS} suggestions are allowed"
            )
        return self


def _worksheet_for(path: Path, lang: str | None) -> Translation | None:
    if lang is None:
        return None
    worksheet_path = ws.worksheet_path(path, lang)
    if not worksheet_path.is_file():
        raise OpenBBQError(
            "translation_not_found", lang=lang, fix=f"openbbq translate init {lang}"
        )
    return ws.read_translation(worksheet_path)


def _review_for(path: Path, lang: str | None, cues: Cues) -> Review:
    review_file = reviewlib.review_path(path, lang)
    if review_file.is_file():
        return ws.read_review(review_file)
    # No review yet: an in-memory empty document so dismissals simply have no
    # effect on rule-issue computation.
    return Review(
        source_lang=cues.source_lang,
        target_lang=lang,
        next_cue_id=max((cue.id for cue in cues.cues), default=0) + 1,
        items=[ReviewItem(id=cue.id) for cue in cues.cues],
    )


def _transcript_for(path: Path, manifest: Manifest) -> Transcript | None:
    state = manifest.stages.get(Stage.TRANSCRIBE)
    if state is None or state.status is not StageStatus.DONE or not state.artifact:
        return None
    artifact = Path(state.artifact)
    artifact = artifact if artifact.is_absolute() else path / artifact
    return ws.read_transcript(artifact)


def _load_context(
    path: Path, lang: str | None
) -> tuple[Manifest, Cues, Translation | None]:
    manifest = ws.read_manifest(path)
    cues_path = ws.require_artifact(path, manifest, Stage.SEGMENT, fix="openbbq segment")
    cues = ws.read_cues(cues_path)
    return manifest, cues, _worksheet_for(path, lang)


def build_prepare_payload(path: Path, lang: str | None) -> dict[str, Any]:
    """The analysis payload an agent answers with review suggestions.

    ``rule_issues`` ships the deterministic check results (plus already-pending
    suggestions) so the agent does not duplicate what OpenBBQ already knows.
    """
    manifest, cues, translation = _load_context(path, lang)
    suggestions_path = reviewlib.suggestions_path(path, lang)
    suggestions_doc = (
        ws.read_suggestions(suggestions_path) if suggestions_path.is_file() else None
    )
    issues = review_issues.compute_issues(
        cues,
        translation,
        _review_for(path, lang, cues),
        suggestions_doc,
        _transcript_for(path, manifest),
    )
    targets = (
        {item.id: item.target for item in translation.items}
        if translation is not None
        else {}
    )
    apply_argv = [
        "openbbq",
        "--json",
        "review",
        "--prepare",
        "--apply",
        "<response.json>",
        "--workspace",
        str(path),
    ]
    if lang is not None:
        apply_argv += ["--to", lang]
    return {
        "workspace": str(path),
        "title": manifest.source.title or path.name,
        "source_lang": cues.source_lang,
        "target_lang": lang,
        "items": [
            {
                "cue_id": cue.id,
                "start": cue.start,
                "end": cue.end,
                "source": cue.source,
                "target": targets.get(cue.id),
                "rule_issues": sorted({issue.kind for issue in issues[cue.id]}),
            }
            for cue in cues.cues
        ],
        "response_schema": {
            "suggestions": [
                {
                    "cue_id": "existing cue id",
                    "message": "concise suspicion a reviewer can act on",
                    "patch": "candidate fix with at least one of source/target/start/end",
                    "severity": "optional warning|info (default info)",
                    "kind": "optional category (default agent_note)",
                }
            ]
        },
        "max_suggestions": MAX_PREPARE_SUGGESTIONS,
        "apply_argv": apply_argv,
        "note": (
            "applying bumps the review revision; a live review client reloads "
            "on the resulting conflict"
        ),
    }


def apply_prepare_response(path: Path, lang: str | None, raw: str) -> dict[str, Any]:
    """Validate an agent's pre-analysis response and archive it as pending
    suggestions (create-or-merge; existing entries and statuses preserved).
    """
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise OpenBBQError(
            "agent_response_invalid", detail=f"not valid JSON: {error}"
        ) from error
    try:
        response = _PrepareResponse.model_validate(value)
    except ValidationError as error:
        raise OpenBBQError(
            "agent_response_invalid", detail=str(error)
        ) from error
    _manifest, cues, translation = _load_context(path, lang)
    unknown = sorted(
        {draft.cue_id for draft in response.suggestions}
        - {cue.id for cue in cues.cues}
    )
    if unknown:
        raise OpenBBQError(
            "agent_response_invalid",
            detail="suggestions reference unknown cue ids",
            ids=unknown,
        )
    doc = reviewlib.merge_suggestion_drafts(
        path,
        lang,
        cues,
        translation,
        response.suggestions,
        id_prefix="prep",
    )
    file = reviewlib.suggestions_path(path, lang)
    ws.write_text_atomic(file, doc.model_dump_json(indent=2) + "\n")
    return {
        "written": len(response.suggestions),
        "path": str(file),
        "suggestions_total": len(doc.suggestions),
    }

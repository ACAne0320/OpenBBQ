"""Read-only aggregation of the hard artifact-delivery contracts.

This module checks only structural ASR safety, worksheet/evidence integrity,
provenance, and the existence of a fresh bilingual subtitle and non-empty
burned video.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from openbbq.core import asr_review as asrlib
from openbbq.core import agent_workflow
from openbbq.core import export as exportlib
from openbbq.core import media as medialib
from openbbq.core import review as reviewlib
from openbbq.core import segment as segmentlib
from openbbq.core import translate as translatelib
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import Cues, Manifest, Stage, Transcript, Translation


@dataclass(frozen=True)
class DeliveryIssue:
    code: str
    gate: str
    detail: str
    fix: str

    def payload(self) -> dict[str, str]:
        return {
            "code": self.code,
            "gate": self.gate,
            "detail": self.detail,
            "fix": self.fix,
        }


@dataclass(frozen=True)
class DeliveryAssessment:
    lang: str | None
    gates: dict[str, bool]
    issues: tuple[DeliveryIssue, ...]
    human_reviewed: bool = False

    @property
    def ready(self) -> bool:
        return not self.issues and all(self.gates.values())

    @property
    def artifact_ready(self) -> bool:
        return self.ready

    @property
    def quality(self) -> Literal["draft", "human-reviewed"]:
        return "human-reviewed" if self.human_reviewed else "draft"

    @property
    def next(self) -> str | None:
        return self.issues[0].fix if self.issues else None


def _resolved_lang(
    path: Path, lang: str | None
) -> tuple[str | None, DeliveryIssue | None]:
    if lang is not None:
        try:
            return ws.validate_lang(lang), None
        except OpenBBQError as error:
            return None, DeliveryIssue(
                code=error.code,
                gate="translation",
                detail=f"invalid target language: {lang}",
                fix=error.fix or "use a BCP-47 language code such as zh",
            )
    available = ws.find_worksheets(path)
    if len(available) == 1:
        inferred = available[0]
        try:
            return ws.validate_lang(inferred), None
        except OpenBBQError as error:
            return None, DeliveryIssue(
                code=error.code,
                gate="translation",
                detail=f"invalid inferred target language filename: {inferred}",
                fix="rename the worksheet with a BCP-47 language code",
            )
    if not available:
        return None, DeliveryIssue(
            code="translation_not_found",
            gate="translation",
            detail="no target-language worksheet exists",
            fix="openbbq translate init <lang>",
        )
    return None, DeliveryIssue(
        code="translation_lang_ambiguous",
        gate="translation",
        detail=f"multiple worksheets exist: {', '.join(available)}",
        fix="rerun with --to <lang>",
    )


def _artifact(
    path: Path,
    manifest: Manifest,
    stage: Stage,
    *,
    fix: str,
    issues: list[DeliveryIssue],
) -> Path | None:
    try:
        return ws.require_artifact(path, manifest, stage, fix=fix)
    except OpenBBQError as error:
        issues.append(
            DeliveryIssue(
                code=f"missing_{stage.value}",
                gate=stage.value,
                detail=f"{stage.value} artifact is not available",
                fix=error.fix or fix,
            )
        )
        return None


def _read_error(
    issues: list[DeliveryIssue],
    *,
    gate: str,
    error: OpenBBQError,
    fix: str,
) -> None:
    issues.append(
        DeliveryIssue(
            code=error.code,
            gate=gate,
            detail=f"{gate} input is invalid or unavailable",
            fix=error.fix or fix,
        )
    )


def _translation_evidence(
    path: Path,
    manifest: Manifest,
    cues: Cues,
    translation: Translation,
    lang: str,
) -> tuple[bool, bool, DeliveryIssue | None]:
    """Return (ready, human-reviewed, issue) for the two legal evidence paths."""

    review_path = reviewlib.review_path(path, lang)
    if review_path.is_file():
        try:
            reviewlib.require_complete_review(path, cues, translation, lang)
        except OpenBBQError as error:
            return (
                False,
                False,
                DeliveryIssue(
                    code=error.code,
                    gate="translation_evidence",
                    detail="human review is incomplete or stale",
                    fix=error.fix or f"openbbq review --workspace {path} --to {lang}",
                ),
            )
        return True, True, None

    try:
        session = ws.read_agent_session_optional(path, lang)
    except OpenBBQError as error:
        return (
            False,
            False,
            DeliveryIssue(
                code=error.code,
                gate="translation_evidence",
                detail="agent translation evidence is invalid",
                fix=error.fix or f"openbbq agent init --workspace {path}",
            ),
        )
    if session is None:
        return (
            False,
            False,
            DeliveryIssue(
                code="translation_evidence_missing",
                gate="translation_evidence",
                detail="translation has neither complete human review nor current agent evidence",
                fix=f"openbbq agent next --workspace {path}",
            ),
        )

    try:
        stale_ids = agent_workflow.stale_translation_evidence_ids(
            path, manifest, session, translation
        )
    except OpenBBQError as error:
        return (
            False,
            False,
            DeliveryIssue(
                code=error.code,
                gate="translation_evidence",
                detail="agent translation evidence is invalid",
                fix=error.fix or f"openbbq agent next --workspace {path}",
            ),
        )
    if stale_ids:
        return (
            False,
            False,
            DeliveryIssue(
                code="agent_session_stale",
                gate="translation_evidence",
                detail=(
                    "draft agent evidence is incomplete or stale: "
                    f"{list(stale_ids[:20])}"
                ),
                fix=f"openbbq agent next --workspace {path}",
            ),
        )
    return True, False, None


def assess_delivery(
    path: Path,
    manifest: Manifest,
    *,
    lang: str | None = None,
) -> DeliveryAssessment:
    """Evaluate every hard gate without mutating the workspace.

    Ordinary incomplete-workflow failures are accumulated rather than raised,
    giving an agent one deterministic list of what remains.  The command layer
    turns a non-ready assessment into the process-level failure contract.
    """

    issues: list[DeliveryIssue] = []
    gates = {
        "asr": False,
        "segment": False,
        "translation": False,
        "translation_evidence": False,
        "export": False,
        "burn": False,
    }
    resolved_lang, lang_issue = _resolved_lang(path, lang)
    if lang_issue is not None:
        issues.append(lang_issue)

    transcript: Transcript | None = None
    transcript_path = _artifact(
        path,
        manifest,
        Stage.TRANSCRIBE,
        fix="openbbq transcribe",
        issues=issues,
    )
    if transcript_path is not None:
        try:
            transcript = ws.read_transcript(transcript_path)
        except OpenBBQError as error:
            _read_error(
                issues,
                gate="asr",
                error=error,
                fix="openbbq transcribe",
            )
        else:
            try:
                asr_review = ws.read_asr_review_optional(path)
            except OpenBBQError as error:
                _read_error(
                    issues,
                    gate="asr",
                    error=error,
                    fix="remove the invalid ASR review and rerun openbbq asr check",
                )
            else:
                caption_source = ws.read_reference_caption_optional(path)
                reference_words = (
                    asrlib.parse_reference_words(caption_source)
                    if caption_source is not None
                    else []
                )
                asr = asrlib.check(
                    transcript,
                    asr_review,
                    reference_words=reference_words,
                )
                blocking = asrlib.blocking_unresolved_ids(asr)
                if not blocking:
                    gates["asr"] = True
                else:
                    issues.append(
                        DeliveryIssue(
                            code="asr_review_incomplete",
                            gate="asr",
                            detail=(
                                f"{len(blocking)} unresolved structural ASR issue(s): "
                                + ", ".join(blocking[:10])
                            ),
                            fix=f"openbbq agent next --workspace {path}",
                        )
                    )

    cues: Cues | None = None
    cues_path = _artifact(
        path,
        manifest,
        Stage.SEGMENT,
        fix="openbbq segment",
        issues=issues,
    )
    if cues_path is not None:
        try:
            cues = ws.read_cues(cues_path)
        except OpenBBQError as error:
            _read_error(
                issues,
                gate="segment",
                error=error,
                fix="openbbq segment",
            )
        else:
            invalid_cues = segmentlib.invalid_cue_ids(cues.cues)
            media_end: float | None = None
            try:
                source_media = ws.media_input(manifest, path)
            except OpenBBQError:
                source_media = None
            if source_media is not None:
                media_end = medialib.media_duration(source_media)
            beyond_media = (
                []
                if media_end is None
                else [cue.id for cue in cues.cues if cue.end > media_end + 0.5]
            )
            if invalid_cues:
                issues.append(
                    DeliveryIssue(
                        code="invalid_cue_timeline",
                        gate="segment",
                        detail=(
                            "segmented subtitles contain non-positive cue durations: "
                            + ", ".join(str(cue_id) for cue_id in invalid_cues[:20])
                        ),
                        fix="openbbq segment",
                    )
                )
            if beyond_media:
                issues.append(
                    DeliveryIssue(
                        code="cues_exceed_media_duration",
                        gate="segment",
                        detail=(
                            f"source media ends at {media_end:.3f}s but subtitle cue(s) "
                            "extend past it: "
                            + ", ".join(str(cue_id) for cue_id in beyond_media[:20])
                        ),
                        fix="openbbq extract-audio, then continue with openbbq agent next",
                    )
                )
            if not invalid_cues and not beyond_media:
                try:
                    ws.require_fresh_artifact(path, cues_path, Stage.SEGMENT)
                except OpenBBQError as error:
                    issues.append(
                        DeliveryIssue(
                            code=f"segment_{error.code}",
                            gate="segment",
                            detail="segmented source subtitles or their reviewed inputs changed",
                            fix="openbbq segment",
                        )
                    )
                else:
                    gates["segment"] = True

    translation: Translation | None = None
    human_reviewed = False
    if resolved_lang is not None:
        translation_path = ws.worksheet_path(path, resolved_lang)
        if not translation_path.is_file():
            issues.append(
                DeliveryIssue(
                    code="translation_not_found",
                    gate="translation",
                    detail=f"translation worksheet for {resolved_lang} does not exist",
                    fix=f"openbbq translate init {resolved_lang}",
                )
            )
        else:
            try:
                translation = ws.read_translation(translation_path)
            except OpenBBQError as error:
                _read_error(
                    issues,
                    gate="translation",
                    error=error,
                    fix=f"openbbq translate init {resolved_lang} --force",
                )

    if cues is not None and translation is not None and resolved_lang is not None:
        try:
            report = translatelib.check(cues, translation, resolved_lang)
        except OpenBBQError as error:
            _read_error(
                issues,
                gate="translation",
                error=error,
                fix=f"openbbq translate init {resolved_lang} --force",
            )
        else:
            if report.missing:
                issues.append(
                    DeliveryIssue(
                        code="translation_incomplete",
                        gate="translation",
                        detail=f"missing target text for cue(s): {report.missing[:20]}",
                        fix=f"openbbq agent next --workspace {path}",
                    )
                )
            else:
                gates["translation"] = True
                evidence_ready, human_reviewed, evidence_issue = _translation_evidence(
                    path,
                    manifest,
                    cues,
                    translation,
                    resolved_lang,
                )
                gates["translation_evidence"] = evidence_ready
                if evidence_issue is not None:
                    issues.append(evidence_issue)

    export_path = _artifact(
        path,
        manifest,
        Stage.EXPORT,
        fix=(
            f"openbbq export --to {resolved_lang} --mode bilingual --format ass"
            if resolved_lang is not None
            else "openbbq export --to <lang> --mode bilingual --format ass"
        ),
        issues=issues,
    )
    if export_path is not None:
        try:
            ws.require_fresh_artifact(path, export_path, Stage.EXPORT)
        except OpenBBQError as error:
            issues.append(
                DeliveryIssue(
                    code=f"export_{error.code}",
                    gate="export",
                    detail="exported subtitle or one of its reviewed inputs changed",
                    fix="openbbq export --format ass --mode bilingual",
                )
            )
        else:
            if (
                cues is None
                or translation is None
                or export_path.suffix.lower() != ".ass"
            ):
                bilingual = False
            else:
                try:
                    content = export_path.read_text(encoding="utf-8")
                except OSError:
                    bilingual = False
                else:
                    bilingual = exportlib.is_bilingual_ass(content, cues, translation)
            if bilingual:
                gates["export"] = True
            else:
                issues.append(
                    DeliveryIssue(
                        code="export_not_bilingual_ass",
                        gate="export",
                        detail="final subtitle artifact is not the reviewed bilingual ASS",
                        fix=(
                            f"openbbq export --to {resolved_lang} --mode bilingual "
                            "--format ass"
                            if resolved_lang is not None
                            else "openbbq export --to <lang> --mode bilingual --format ass"
                        ),
                    )
                )

    burn_path = _artifact(
        path,
        manifest,
        Stage.BURN,
        fix="openbbq burn",
        issues=issues,
    )
    if burn_path is not None:
        try:
            ws.require_fresh_artifact(path, burn_path, Stage.BURN)
        except OpenBBQError as error:
            issues.append(
                DeliveryIssue(
                    code=f"burn_{error.code}",
                    gate="burn",
                    detail="burned video or one of its inputs changed",
                    fix="openbbq burn",
                )
            )
        else:
            try:
                nonempty = burn_path.stat().st_size > 0
            except OSError:
                nonempty = False
            if nonempty:
                gates["burn"] = True
            else:
                issues.append(
                    DeliveryIssue(
                        code="invalid_burn_output",
                        gate="burn",
                        detail="burned video is empty or unreadable",
                        fix="openbbq burn",
                    )
                )

    return DeliveryAssessment(
        lang=resolved_lang,
        gates=gates,
        issues=tuple(issues),
        human_reviewed=human_reviewed,
    )

"""Read-only aggregation of the independent delivery quality gates.

The individual domains remain authoritative for ASR, translation, provenance,
and QA.  This module only coordinates their workspace inputs so ``status`` and
``delivery check`` cannot disagree about whether a video is ready to ship.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openbbq.core import asr_review as asrlib
from openbbq.core import agent_workflow
from openbbq.core import export as exportlib
from openbbq.core import segment as segmentlib
from openbbq.core import translate as translatelib
from openbbq.core import translation_audit as auditlib
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

    @property
    def ready(self) -> bool:
        return not self.issues and all(self.gates.values())

    @property
    def next(self) -> str | None:
        return self.issues[0].fix if self.issues else None


def _resolved_lang(path: Path, lang: str | None) -> tuple[str | None, DeliveryIssue | None]:
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
        "translation_audit": False,
        "export": False,
        "burn": False,
        "qa_mechanical": False,
    }
    resolved_lang, lang_issue = _resolved_lang(path, lang)
    if lang_issue is not None:
        issues.append(lang_issue)

    transcript: Transcript | None = None
    use_legacy_translation_gate = False
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
                    reference_texts=[
                        text
                        for text in (manifest.source.title, manifest.source.author)
                        if manifest.source.type == "url" and text
                    ],
                    reference_words=reference_words,
                )
                if asr.ready:
                    gates["asr"] = True
                else:
                    issues.append(
                        DeliveryIssue(
                            code="asr_review_incomplete",
                            gate="asr",
                            detail=(
                                f"{len(asr.unresolved_ids)} unresolved ASR issue(s): "
                                + ", ".join(asr.unresolved_ids[:10])
                            ),
                            fix="openbbq asr batch --limit 20",
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
            else:
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
            agent_session = ws.read_agent_session_optional(path, resolved_lang)
        except OpenBBQError as error:
            _read_error(
                issues,
                gate="translation_audit",
                error=error,
                fix=f"openbbq agent next --workspace {path}",
            )
            agent_session = None
            has_agent_session = True
        else:
            has_agent_session = agent_session is not None

        if agent_session is not None:
            try:
                balanced = agent_workflow.balanced_gate(
                    path,
                    manifest,
                    agent_session,
                    cues,
                    translation,
                )
            except OpenBBQError as error:
                _read_error(
                    issues,
                    gate="translation_audit",
                    error=error,
                    fix=f"openbbq agent next --workspace {path}",
                )
            else:
                if balanced.ready:
                    gates["translation"] = True
                    gates["translation_audit"] = True
                else:
                    issues.append(
                        DeliveryIssue(
                            code="agent_session_stale",
                            gate="translation_audit",
                            detail="balanced agent evidence is incomplete or stale: "
                            + "; ".join(balanced.problems),
                            fix=f"openbbq agent next --workspace {path}",
                        )
                    )

        if has_agent_session:
            # The balanced session is authoritative.  Never fall back to the
            # weaker legacy all-cue audit when it exists but is stale.
            use_legacy_translation_gate = False
        else:
            use_legacy_translation_gate = True

    if (
        cues is not None
        and translation is not None
        and resolved_lang is not None
        and use_legacy_translation_gate
    ):
        try:
            legacy_report = translatelib.check(cues, translation, resolved_lang)
        except OpenBBQError as error:
            _read_error(
                issues,
                gate="translation",
                error=error,
                fix=f"openbbq translate init {resolved_lang} --force",
            )
        else:
            if legacy_report.ready:
                gates["translation"] = True
            else:
                problem_ids = set(legacy_report.missing)
                problem_ids.update(legacy_report.over_budget)
                problem_ids.update(legacy_report.zero_budget)
                problem_ids.update(issue.id for issue in legacy_report.term_issues)
                problem_ids.update(issue.id for issue in legacy_report.quality_issues)
                issues.append(
                    DeliveryIssue(
                        code="translation_quality_failed",
                        gate="translation",
                        detail="deterministic translation checks failed for cue(s): "
                        + ", ".join(str(item) for item in sorted(problem_ids)[:15]),
                        fix=f"openbbq translate check {resolved_lang}",
                    )
                )

        try:
            audit = ws.read_translation_audit_optional(path, resolved_lang)
            audit_items = auditlib.audit_items(
                cues,
                translation,
                audit,
                uncertain_ids=auditlib.uncertain_cue_ids(cues, transcript),
                coverage="all",
            )
            pending = auditlib.pending_items(
                audit_items,
                translation,
                audit,
                require_context=True,
            )
        except OpenBBQError as error:
            _read_error(
                issues,
                gate="translation_audit",
                error=error,
                fix=f"openbbq translate audit {resolved_lang} --coverage all",
            )
        else:
            if not pending:
                gates["translation_audit"] = True
            else:
                issues.append(
                    DeliveryIssue(
                        code="translation_audit_incomplete",
                        gate="translation_audit",
                        detail=(
                            f"{len(pending)} cue(s) need contextual semantic review: "
                            + ", ".join(str(item.id) for item in pending[:15])
                        ),
                        fix=(
                            f"openbbq translate audit {resolved_lang} "
                            "--coverage all --limit 20"
                        ),
                    )
                )

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
            if cues is None or translation is None or export_path.suffix.lower() != ".ass":
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
            gates["burn"] = True
            try:
                nonempty = burn_path.stat().st_size > 0
            except OSError:
                nonempty = False
            if nonempty and gates["segment"]:
                gates["qa_mechanical"] = True
            elif not nonempty:
                issues.append(
                    DeliveryIssue(
                        code="invalid_burn_output",
                        gate="qa_mechanical",
                        detail="burned video is empty or unreadable",
                        fix="openbbq burn",
                    )
                )

    return DeliveryAssessment(
        lang=resolved_lang,
        gates=gates,
        issues=tuple(issues),
    )

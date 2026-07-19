from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer

from ...core import export as exp
from ...core import agent_workflow
from ...core import review as reviewlib
from ...core import segment as segmentlib
from ...core import translate as translatelib
from ...core import translation_audit as auditlib
from ...core import workspace as ws
from ...errors import OpenBBQError
from ...schemas import Progress, Stage, StageState, StageStatus
from ..output import Output
from ..results import Result


# --- contract layer -----------------------------------------------------------
class ExportResult(Result):
    artifact: str  # relative to the workspace, or the given --output
    mode: str  # source | target | bilingual
    format: str  # subtitle format (srt | ass)
    ass_preset: str | None = None  # ASS style preset when format=ass
    cues: int
    elapsed_s: float

    def render(self) -> str:
        detail = f"{self.cues} cues · {self.format} · {self.mode}"
        if self.ass_preset is not None:
            detail = f"{detail} · {self.ass_preset}"
        return f"[green]✓[/] exported: {self.artifact}\n  {detail}"


# --- shell layer --------------------------------------------------------------
def export(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    to: Annotated[
        str | None,
        typer.Option("--to", help="target language worksheet to render (e.g. zh)"),
    ] = None,
    mode: Annotated[
        exp.ExportMode | None,
        typer.Option(
            "--mode",
            help="source | target | bilingual (default: source, or target with --to)",
        ),
    ] = None,
    fmt: Annotated[
        str, typer.Option("--format", help="subtitle format (srt | ass)")
    ] = "srt",
    output: Annotated[
        str | None,
        typer.Option(
            "--output",
            help="output path; relative paths are inside workspace (default: out/<lang>.<format>)",
        ),
    ] = None,
    ass_preset: Annotated[
        exp.AssPreset,
        typer.Option(
            "--ass-preset",
            help="ASS style preset: default | fansub | fansub-compact | mobile",
        ),
    ] = exp.AssPreset.DEFAULT,
    allow_missing: Annotated[
        bool,
        typer.Option(
            "--allow-missing", help="fall back to source for untranslated cues"
        ),
    ] = False,
    allow_unreviewed: Annotated[
        bool,
        typer.Option(
            "--allow-unreviewed",
            help="export even when an existing review file is incomplete",
        ),
    ] = False,
    allow_quality_warnings: Annotated[
        bool,
        typer.Option(
            "--allow-quality-warnings",
            help="export a deliberate draft despite budget, term, timing, or quality warnings",
        ),
    ] = False,
) -> None:
    """Render cues into a subtitle file."""
    output_obj: Output = ctx.obj
    started = time.monotonic()
    if fmt not in exp.SUPPORTED_FORMATS:
        raise OpenBBQError(
            "unsupported_format", format=fmt, fix="use --format srt or ass"
        )
    if fmt != "ass" and ass_preset != exp.AssPreset.DEFAULT:
        raise OpenBBQError(
            "ass_preset_requires_ass",
            preset=ass_preset.value,
            format=fmt,
            fix="use --format ass, or remove --ass-preset",
        )

    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    cpath = ws.require_artifact(path, manifest, Stage.SEGMENT, fix="openbbq segment")
    doc = ws.read_cues(cpath)
    segmentlib.require_valid_cue_timeline(doc.cues)

    translation = None
    translation_lang = None
    translation_audit_path: Path | None = None
    translation_ready = False
    wpath: Path | None = None
    resolved = mode or exp.default_mode(to)
    if resolved is not exp.ExportMode.SOURCE:
        if to is None:
            raise OpenBBQError(
                "translation_required", mode=resolved.value, fix="pass --to <lang>"
            )
        translation_lang = to
        wpath = ws.worksheet_path(path, to)  # validates lang
        if not wpath.is_file():
            raise OpenBBQError(
                "translation_not_found", lang=to, fix=f"openbbq translate init {to}"
            )
        translation = ws.read_translation(wpath)

        agent_session = ws.read_agent_session_optional(path, to)
        balanced_ready = False
        if agent_session is not None:
            gate = agent_workflow.balanced_gate(
                path,
                manifest,
                agent_session,
                doc,
                translation,
            )
            if not gate.ready:
                raise OpenBBQError(
                    "agent_session_stale",
                    problems=list(gate.problems),
                    fix=f"run `openbbq agent next --workspace {path}`",
                )
            balanced_ready = True

        report = translatelib.check(doc, translation, to)
        if not balanced_ready and not allow_quality_warnings and (
            report.over_budget
            or report.zero_budget
            or report.term_issues
            or report.quality_issues
        ):
            raise OpenBBQError(
                "translation_quality_failed",
                over_budget=report.over_budget[:15],
                zero_budget=report.zero_budget[:15],
                term_ids=sorted({issue.id for issue in report.term_issues})[:15],
                quality_ids=sorted({issue.id for issue in report.quality_issues})[:15],
                fix=(
                    f"run `openbbq translate check {to}` and fix warnings; "
                    "use --allow-quality-warnings only for an intentional draft"
                ),
            )

        pending_audit = []
        if not balanced_ready:
            audit_state = ws.read_translation_audit_optional(path, to)
            transcript = None
            transcribe_state = manifest.stages.get(Stage.TRANSCRIBE)
            if (
                transcribe_state is not None
                and transcribe_state.status is StageStatus.DONE
                and transcribe_state.artifact
            ):
                transcript_path = Path(transcribe_state.artifact)
                if not transcript_path.is_absolute():
                    transcript_path = path / transcript_path
                if transcript_path.is_file():
                    transcript = ws.read_transcript(transcript_path)
            risks = auditlib.audit_items(
                doc,
                translation,
                audit_state,
                uncertain_ids=auditlib.uncertain_cue_ids(doc, transcript),
                coverage="all",
            )
            pending_audit = auditlib.pending_items(
                risks,
                translation,
                audit_state,
                require_context=True,
            )
            if pending_audit and not allow_quality_warnings:
                raise OpenBBQError(
                    "translation_audit_incomplete",
                    ids=[item.id for item in pending_audit[:15]],
                    total=len(pending_audit),
                    fix=(
                        f"run `openbbq translate audit {to} --coverage all --limit 20` "
                        "and review every cue; "
                        "use --allow-quality-warnings only for an intentional draft"
                    ),
                )
        candidate_audit_path = ws.translation_audit_path(path, to)
        if candidate_audit_path.is_file():
            translation_audit_path = candidate_audit_path
        translation_ready = balanced_ready or (report.ready and not pending_audit)

    if not allow_unreviewed:
        review_lang = (
            translation_lang if resolved is not exp.ExportMode.SOURCE else None
        )
        reviewlib.require_complete_review(path, doc, translation, review_lang)

    if translation is not None and wpath is not None and translation_ready:
        ws.record_stage(
            path,
            manifest,
            Stage.TRANSLATE,
            StageState(
                status=StageStatus.DONE,
                artifact=wpath.name,
                progress=Progress(done=len(translation.items), total=len(translation.items)),
                updated_at=datetime.now(timezone.utc),
            ),
            preserve_later={Stage.REVIEW},
        )

    if fmt == "ass":
        content = exp.render_ass(
            doc,
            resolved,
            translation=translation,
            allow_missing=allow_missing,
            preset=ass_preset,
            translation_lang=translation_lang,
        )
    else:
        content = exp.render_srt(
            doc,
            resolved,
            translation=translation,
            allow_missing=allow_missing,
            translation_lang=translation_lang,
        )

    lang = exp.output_lang(doc, translation, resolved)
    dest = Path(output) if output else Path("out") / f"{lang}.{fmt}"
    if not dest.is_absolute():
        dest = path / dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    ws.write_text_atomic(dest, content)

    provenance_inputs = [cpath]
    if wpath is not None:
        provenance_inputs.append(wpath)
    if translation_audit_path is not None:
        provenance_inputs.append(translation_audit_path)
    review_lang = translation_lang if resolved is not exp.ExportMode.SOURCE else None
    review_path = reviewlib.review_path(path, review_lang)
    if review_path.is_file():
        provenance_inputs.append(review_path)
    ws.record_artifact_provenance(
        path,
        dest,
        Stage.EXPORT,
        inputs=provenance_inputs,
    )

    # record the artifact relative to the workspace when it lives inside it
    try:
        artifact = str(dest.relative_to(path))
    except ValueError:
        artifact = str(dest)
    ws.record_stage(
        path,
        manifest,
        Stage.EXPORT,
        StageState(
            status=StageStatus.DONE,
            artifact=artifact,
            updated_at=datetime.now(timezone.utc),
        ),
    )
    output_obj.emit(
        ExportResult(
            artifact=artifact,
            mode=resolved.value,
            format=fmt,
            ass_preset=ass_preset.value if fmt == "ass" else None,
            cues=len(doc.cues),
            elapsed_s=round(time.monotonic() - started, 2),
            next="openbbq burn",
        )
    )

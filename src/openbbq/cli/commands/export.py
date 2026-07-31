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
    quality_warnings: list[dict[str, object]]
    elapsed_s: float

    def render(self) -> str:
        detail = f"{self.cues} cues · {self.format} · {self.mode}"
        if self.ass_preset is not None:
            detail = f"{detail} · {self.ass_preset}"
        if self.quality_warnings:
            detail = f"{detail} · {len(self.quality_warnings)} warning(s)"
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
            help="export an uncertified draft without human or agent evidence",
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
    translation_ready = False
    quality_warnings: list[dict[str, object]] = []
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
        report = translatelib.check(doc, translation, to)
        quality_warnings = agent_workflow.draft_warnings(doc, translation)
        if report.missing and not allow_missing:
            raise OpenBBQError(
                "incomplete_translation",
                missing=report.missing,
                fix="translate the missing cues, or pass --allow-missing",
            )
        review_path = reviewlib.review_path(path, to)
        if review_path.is_file():
            if not allow_unreviewed:
                reviewlib.require_complete_review(path, doc, translation, to)
                translation_ready = True
        elif not allow_unreviewed:
            agent_session = ws.read_agent_session_optional(path, to)
            if agent_session is None:
                raise OpenBBQError(
                    "translation_evidence_missing",
                    lang=to,
                    fix=(
                        f"run `openbbq agent next --workspace {path}`, complete "
                        f"`openbbq review --workspace {path} --to {to}`, or pass "
                        "--allow-unreviewed for an uncertified export"
                    ),
                )
            stale_ids = agent_workflow.stale_translation_evidence_ids(
                path, manifest, agent_session, translation
            )
            if stale_ids:
                raise OpenBBQError(
                    "agent_session_stale",
                    cue_ids=list(stale_ids[:20]),
                    fix=f"run `openbbq agent next --workspace {path}`",
                )
            translation_ready = True
    elif not allow_unreviewed:
        reviewlib.require_complete_review(path, doc, None, None)

    if translation is not None and wpath is not None and translation_ready:
        ws.record_stage(
            path,
            manifest,
            Stage.TRANSLATE,
            StageState(
                status=StageStatus.DONE,
                artifact=wpath.name,
                progress=Progress(
                    done=len(translation.items), total=len(translation.items)
                ),
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
            quality_warnings=quality_warnings,
            elapsed_s=round(time.monotonic() - started, 2),
            next="openbbq burn",
        )
    )

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated

import typer

from ...core import glossary as glossarylib
from ...core import translate as translatelib
from ...core import workspace as ws
from ...errors import OpenBBQError
from ...schemas import Stage, StageState, StageStatus
from ..output import Output
from ..results import Result

app = typer.Typer(no_args_is_help=True)


# --- init ---------------------------------------------------------------------
class TranslateInitResult(Result):
    artifact: str  # worksheet path, relative to the workspace
    cues: int
    target_lang: str
    generic_profile: bool  # True when the latin fallback profile was used
    elapsed_s: float

    def render(self) -> str:
        gloss = "" if not self.generic_profile else "  (generic latin profile)"
        return (
            f"[green]✓[/] translation worksheet: {self.artifact}\n"
            f"  {self.cues} cues · {self.target_lang}{gloss}\n"
            f"  fill the `target` fields, then: openbbq translate check {self.target_lang}"
        )


# --- check --------------------------------------------------------------------
class TranslateCheckResult(Result):
    lang: str
    filled: int
    total: int
    missing: list[int]
    term_warnings: int

    def render(self) -> str:
        done = self.filled == self.total
        head = "[green]✓[/] complete" if done else "[yellow]·[/] in progress"
        line = f"{head}: {self.filled}/{self.total} cues · {self.lang}"
        if self.missing:
            shown = ", ".join(str(i) for i in self.missing[:15])
            more = "" if len(self.missing) <= 15 else f" (+{len(self.missing) - 15})"
            line += f"\n  missing: {shown}{more}"
        if self.term_warnings:
            line += f"\n  [yellow]term warnings: {self.term_warnings}[/]"
        return line


@app.command()
def init(
    ctx: typer.Context,
    lang: Annotated[str, typer.Argument(help="target language code, e.g. zh")],
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    glossary: Annotated[
        str | None,
        typer.Option("--glossary", help="glossary name (overrides the manifest binding)"),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="overwrite an existing worksheet (loses filled targets)")
    ] = False,
) -> None:
    """Prepare a translation worksheet for LANG from cues + glossary."""
    output: Output = ctx.obj
    started = time.monotonic()
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    cpath = ws.require_artifact(path, manifest, Stage.SEGMENT, fix="openbbq segment")
    cues = ws.read_cues(cpath)

    wpath = ws.worksheet_path(path, lang)  # validates lang
    if wpath.exists() and not force:
        raise OpenBBQError(
            "translation_exists",
            path=str(wpath.relative_to(path)),
            fix="edit it, or pass --force to regenerate (discards filled targets)",
        )

    gloss = glossarylib.load_optional(glossary or manifest.glossary)
    doc, generic = translatelib.build_worksheet(cues, gloss, lang)
    # no exclude_none: the Agent needs to see `"target": null` fields to fill them
    wpath.write_text(doc.model_dump_json(indent=2))

    artifact = wpath.name
    ws.record_stage(
        path,
        manifest,
        Stage.TRANSLATE,
        StageState(
            status=StageStatus.DONE,
            artifact=artifact,
            updated_at=datetime.now(timezone.utc),
        ),
    )
    output.emit(
        TranslateInitResult(
            artifact=artifact,
            cues=len(doc.items),
            target_lang=lang,
            generic_profile=generic,
            elapsed_s=round(time.monotonic() - started, 2),
        )
    )


def _resolve_lang(path, manifest, explicit: str | None) -> str:
    """Explicit lang, else infer when exactly one worksheet is present."""
    if explicit is not None:
        return explicit
    present = ws.find_worksheets(path)
    if not present:
        raise OpenBBQError(
            "translation_not_found", fix="openbbq translate init <lang>"
        )
    if len(present) > 1:
        raise OpenBBQError(
            "ambiguous_lang", langs=present, fix="pass the language, e.g. translate check zh"
        )
    return present[0]


@app.command()
def check(
    ctx: typer.Context,
    lang: Annotated[
        str | None, typer.Argument(help="target language (inferred if only one worksheet)")
    ] = None,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
) -> None:
    """Validate a worksheet against its cues; report completeness + term warnings."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    cpath = ws.require_artifact(path, manifest, Stage.SEGMENT, fix="openbbq segment")
    cues = ws.read_cues(cpath)

    resolved = _resolve_lang(path, manifest, lang)
    wpath = ws.worksheet_path(path, resolved)
    if not wpath.is_file():
        raise OpenBBQError(
            "translation_not_found",
            lang=resolved,
            fix=f"openbbq translate init {resolved}",
        )
    worksheet = ws.read_translation(wpath)
    report = translatelib.check(cues, worksheet, resolved)
    output.emit(
        TranslateCheckResult(
            lang=resolved,
            filled=report.filled,
            total=report.total,
            missing=report.missing,
            term_warnings=report.term_warnings,
        )
    )

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated

import typer

from ...core import glossary as glossarylib
from ...core import segment as seg
from ...core import workspace as ws
from ...schemas import Cues, SegmentParams, Stage, StageState, StageStatus
from ..output import Output
from ..results import Result

CUES_REL = "cues.json"  # derived artifact, relative to the workspace


# --- contract layer -----------------------------------------------------------
class SegmentResult(Result):
    artifact: str  # relative to the workspace
    cues: int  # number of cues produced
    over_cps: int  # cues exceeding max_cps (readability warning)
    over_cap: int  # cues that couldn't fit the line budget
    source_lang: str
    generic_profile: bool  # True when the latin fallback was used (no language profile)
    elapsed_s: float

    def render(self) -> str:
        return (
            f"[green]✓[/] segmented: {self.artifact}\n"
            f"  {self.cues} cues · {self.source_lang} · "
            f"{self.over_cps} over-CPS · {self.over_cap} over-width"
        )


# --- shell layer --------------------------------------------------------------
def segment(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    lang: Annotated[
        str | None,
        typer.Option("--lang", help="force source language, overriding the transcript"),
    ] = None,
    glossary: Annotated[
        str | None,
        typer.Option("--glossary", help="glossary name (overrides the manifest binding)"),
    ] = None,
    max_cps: Annotated[
        float | None, typer.Option("--max-cps", help="max characters per second")
    ] = None,
    max_chars_per_line: Annotated[
        int | None, typer.Option("--max-chars-per-line", help="max characters per line")
    ] = None,
    max_lines: Annotated[
        int | None, typer.Option("--max-lines", help="max lines per cue")
    ] = None,
    min_dur: Annotated[
        float | None, typer.Option("--min-dur", help="min cue duration, seconds")
    ] = None,
    max_dur: Annotated[
        float | None, typer.Option("--max-dur", help="max cue duration, seconds")
    ] = None,
    min_gap: Annotated[
        float | None, typer.Option("--min-gap", help="min gap between cues, seconds")
    ] = None,
    pause_threshold: Annotated[
        float | None,
        typer.Option("--pause-threshold", help="natural-pause split threshold, seconds"),
    ] = None,
) -> None:
    """Split the transcript into subtitle cues (source side, deterministic)."""
    output: Output = ctx.obj
    started = time.monotonic()
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)

    tpath = ws.require_artifact(
        path, manifest, Stage.TRANSCRIBE, fix="openbbq transcribe"
    )
    transcript = ws.read_transcript(tpath)

    source_lang = lang or transcript.language
    profile, generic = seg.resolve_profile(source_lang)
    profile = seg.apply_overrides(
        profile,
        max_cps=max_cps,
        max_chars_per_line=max_chars_per_line,
        max_lines=max_lines,
        min_dur=min_dur,
        max_dur=max_dur,
        min_gap=min_gap,
        pause_threshold=pause_threshold,
    )

    gloss = glossarylib.load_optional(glossary or manifest.glossary)
    outcome = seg.build_cues(transcript, profile, glossarylib.corrector(gloss))

    doc = Cues(
        source_lang=source_lang,
        params=SegmentParams(
            max_cps=profile.max_cps,
            max_chars_per_line=profile.max_chars_per_line,
            max_lines=profile.max_lines,
            min_dur=profile.min_dur,
            max_dur=profile.max_dur,
            min_gap=profile.min_gap,
            pause_threshold=profile.pause_threshold,
        ),
        cues=outcome.cues,
    )
    (path / CUES_REL).write_text(doc.model_dump_json(indent=2, exclude_none=True))
    ws.record_stage(
        path,
        manifest,
        Stage.SEGMENT,
        StageState(
            status=StageStatus.DONE,
            artifact=CUES_REL,
            updated_at=datetime.now(timezone.utc),
        ),
    )
    output.emit(
        SegmentResult(
            artifact=CUES_REL,
            cues=len(outcome.cues),
            over_cps=outcome.over_cps,
            over_cap=outcome.over_cap,
            source_lang=source_lang,
            generic_profile=generic,
            elapsed_s=round(time.monotonic() - started, 2),
        )
    )

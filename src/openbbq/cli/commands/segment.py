from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated

import typer

from ...core import asr_review as asr_reviewlib
from ...core import glossary as glossarylib
from ...core import segment as seg
from ...core import workspace as ws
from ...schemas import Cues, OpenBBQModel, SegmentParams, Stage, StageState, StageStatus
from ...errors import OpenBBQError
from ..output import Output
from ..results import Result

CUES_REL = "cues.json"  # derived artifact, relative to the workspace


# --- contract layer -----------------------------------------------------------
class GlossaryAliasApplicationReport(OpenBBQModel):
    source: str
    alias: str
    count: int


class SegmentResult(Result):
    artifact: str  # relative to the workspace
    cues: int  # number of cues produced
    over_cps: int  # cues exceeding max_cps (readability warning)
    over_cap: int  # cues that couldn't fit the line budget
    source_lang: str
    generic_profile: bool  # True when the latin fallback was used (no language profile)
    glossary: str | None = None
    glossary_matched_terms: list[str] = []
    glossary_aliases_applied: list[GlossaryAliasApplicationReport] = []
    glossary_no_effect: bool | None = None
    elapsed_s: float

    def render(self) -> str:
        glossary = ""
        if self.glossary is not None:
            glossary = (
                f"\n  glossary {self.glossary}: "
                f"{len(self.glossary_matched_terms)} term(s) matched · "
                f"{sum(item.count for item in self.glossary_aliases_applied)} alias correction(s)"
            )
        return (
            f"[green]✓[/] segmented: {self.artifact}\n"
            f"  {self.cues} cues · {self.source_lang} · "
            f"{self.over_cps} over-CPS · {self.over_cap} over-width"
            f"{glossary}"
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
        typer.Option(
            "--glossary", help="glossary name (overrides the manifest binding)"
        ),
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
        typer.Option(
            "--pause-threshold", help="natural-pause split threshold, seconds"
        ),
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
    asr_review = ws.read_asr_review_optional(path)
    reference_texts = [
        text
        for text in (manifest.source.title, manifest.source.author)
        if manifest.source.type == "url" and text
    ]
    asr_report = asr_reviewlib.check(
        transcript,
        asr_review,
        reference_texts=reference_texts,
    )
    if not asr_report.ready:
        raise OpenBBQError(
            "asr_review_incomplete",
            stale=asr_report.stale,
            unresolved=asr_report.unresolved_ids[:20],
            fix="run `openbbq asr batch --limit 20`, then `openbbq asr apply <decisions.json>`",
        )

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

    glossary_name = glossary or manifest.glossary
    gloss = glossarylib.load_optional(glossary_name)
    glossary_tracker = glossarylib.CorrectionTracker(gloss)
    correct = asr_reviewlib.corrector(asr_review, glossary_tracker)
    reviewed_transcript = asr_reviewlib.apply_segment_decisions(
        transcript,
        asr_review,
        reference_texts=reference_texts,
    )
    outcome = seg.build_cues(reviewed_transcript, profile, correct)

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
    cues_path = path / CUES_REL
    ws.write_text_atomic(cues_path, doc.model_dump_json(indent=2, exclude_none=True))
    provenance_inputs = [tpath]
    asr_review_path = ws.asr_review_path(path)
    if asr_review_path.is_file():
        provenance_inputs.append(asr_review_path)
    if glossary or manifest.glossary:
        provenance_inputs.append(
            glossarylib.glossary_path(glossary or manifest.glossary or "")
        )
    ws.record_artifact_provenance(
        path,
        cues_path,
        Stage.SEGMENT,
        inputs=provenance_inputs,
    )
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
            glossary=glossary_name,
            glossary_matched_terms=sorted(glossary_tracker.matched_terms),
            glossary_aliases_applied=[
                GlossaryAliasApplicationReport(
                    source=item.source,
                    alias=item.alias,
                    count=item.count,
                )
                for item in glossary_tracker.alias_applications
            ],
            glossary_no_effect=(
                not glossary_tracker.matched_terms if gloss is not None else None
            ),
            elapsed_s=round(time.monotonic() - started, 2),
            next=(
                "openbbq translate init <lang> "
                "(or openbbq export for source-only subtitles)"
            ),
        )
    )

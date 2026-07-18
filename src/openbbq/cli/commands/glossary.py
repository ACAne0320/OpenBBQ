from __future__ import annotations

import shlex
from pathlib import Path
from typing import Annotated

import typer
from rich.console import RenderableType
from rich.table import Table

from ...core import asr_review as asr_reviewlib
from ...core import glossary as glossarylib
from ...core import workspace as ws
from ...errors import OpenBBQError
from ...schemas import OpenBBQModel, Stage, Term
from ..output import Output
from ..results import Result

app = typer.Typer(no_args_is_help=True)


# --- list ---------------------------------------------------------------------
class GlossaryEntry(OpenBBQModel):
    name: str
    terms: int | None = None  # None when the file is malformed
    path: str


class GlossaryListResult(Result):
    glossaries: list[GlossaryEntry]

    @classmethod
    def of(cls) -> GlossaryListResult:
        entries: list[GlossaryEntry] = []
        for name in glossarylib.list_names():
            path = glossarylib.glossary_path(name)
            try:
                terms: int | None = len(glossarylib.load(name).terms)
            except OpenBBQError:
                terms = None  # malformed — surfaced as "?"
            entries.append(GlossaryEntry(name=name, terms=terms, path=str(path)))
        return cls(glossaries=entries)

    def render(self) -> RenderableType:
        if not self.glossaries:
            return (
                "[dim]no glossaries — create one with `openbbq glossary new <name>`[/]"
            )
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("name")
        table.add_column("terms", justify="right")
        table.add_column("path", style="dim")
        for g in self.glossaries:
            table.add_row(g.name, "?" if g.terms is None else str(g.terms), g.path)
        return table


# --- show ---------------------------------------------------------------------
class GlossaryShowResult(Result):
    name: str
    context: str | None = None
    terms: list[Term]

    def render(self) -> RenderableType:
        table = Table(show_header=True, header_style="bold", box=None, title=self.name)
        table.add_column("source")
        table.add_column("target")
        table.add_column("aliases", style="dim")
        table.add_column("keep", justify="center")
        for t in self.terms:
            table.add_row(
                t.source,
                t.target or ("[dim]—[/]" if not t.keep else "[dim](keep)[/]"),
                ", ".join(t.aliases),
                "✓" if t.keep else "",
            )
        return table


# --- new ----------------------------------------------------------------------
class GlossaryNewResult(Result):
    name: str
    path: str

    def render(self) -> str:
        return f"[green]✓[/] glossary created: {self.name}\n  path: {self.path}"


# --- use ----------------------------------------------------------------------
class GlossaryUseResult(Result):
    name: str
    workspace: str

    def render(self) -> str:
        return f"[green]✓[/] glossary bound: {self.name}\n  workspace: {self.workspace}"


# --- suggest ------------------------------------------------------------------
class CandidateReport(OpenBBQModel):
    surface: str
    count: int
    avg_prob: float | None = None
    example: str


class GlossarySuggestResult(Result):
    candidates: list[CandidateReport]

    def render(self) -> RenderableType:
        if not self.candidates:
            return "[dim]no candidate terms found[/]"
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("candidate")
        table.add_column("count", justify="right")
        table.add_column("avg_prob", justify="right")
        table.add_column("example", style="dim")
        for c in self.candidates:
            prob = "—" if c.avg_prob is None else f"{c.avg_prob:.2f}"
            table.add_row(c.surface, str(c.count), prob, c.example)
        return table


# --- audit --------------------------------------------------------------------
class AuditWordReport(OpenBBQModel):
    index: int
    word: str
    prob: float | None = None


class GlossaryAuditItem(OpenBBQModel):
    segment_id: int
    start: float
    end: float
    source: str
    raw_source: str | None = None
    after_glossary: str | None = None
    previous: str | None = None
    next_segment: str | None = None
    words: list[AuditWordReport]
    min_prob: float | None = None
    reference_caption: str | None = None
    glossary_terms: list[str]


class GlossaryAuditResult(Result):
    transcript_hash: str
    glossary: str | None = None
    offset: int
    total: int
    items: list[GlossaryAuditItem]
    next_offset: int | None = None
    remaining: int
    asr_ready: bool
    asr_review_stale: bool
    reference_caption_available: bool

    def render(self) -> RenderableType:
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("segment")
        table.add_column("time", justify="right")
        table.add_column("min prob", justify="right")
        table.add_column("source")
        table.add_column("reference", style="dim")
        for item in self.items:
            table.add_row(
                str(item.segment_id),
                f"{item.start:.2f}s",
                "—" if item.min_prob is None else f"{item.min_prob:.2f}",
                item.source,
                item.reference_caption or "—",
            )
        return table


# --- apply --------------------------------------------------------------------
class GlossaryApplyResult(Result):
    name: str
    path: str
    added: list[str]
    updated: list[str]
    unchanged: list[str]
    aliases_added: int
    total_terms: int
    workspace_invalidated: str | None = None

    def render(self) -> str:
        changed = len(self.added) + len(self.updated)
        return (
            f"[green]✓[/] glossary updated: {self.name}\n"
            f"  {changed} changed · {self.aliases_added} aliases added · "
            f"{self.total_terms} total terms"
        )


@app.command(name="list")
def list_glossaries(ctx: typer.Context) -> None:
    """List glossaries in the library with term counts."""
    output: Output = ctx.obj
    output.emit(GlossaryListResult.of())


@app.command()
def show(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="glossary name")],
) -> None:
    """Print a glossary's terms."""
    output: Output = ctx.obj
    g = glossarylib.load(name)
    output.emit(GlossaryShowResult(name=g.name, context=g.context, terms=g.terms))


@app.command()
def new(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="glossary name, e.g. frieren")],
    context: Annotated[
        str | None,
        typer.Option(
            "--context", help="series/topic background that scopes this glossary"
        ),
    ] = None,
) -> None:
    """Scaffold a new glossary (optionally declaring its scope via --context)."""
    output: Output = ctx.obj
    path = glossarylib.scaffold(name, context)
    output.emit(GlossaryNewResult(name=name, path=str(path)))


@app.command()
def use(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="glossary name to bind")],
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
) -> None:
    """Bind a glossary to the current workspace (writes manifest.glossary)."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    glossarylib.load(name)  # validate it exists / is well-formed before binding
    ws.record_glossary_binding(path, manifest, name)
    output.emit(GlossaryUseResult(name=name, workspace=str(path)))


@app.command()
def suggest(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    glossary: Annotated[
        str | None,
        typer.Option("--glossary", help="exclude terms already known to this glossary"),
    ] = None,
    max_prob: Annotated[
        float,
        typer.Option(
            "--max-prob", help="only surface words below this avg probability"
        ),
    ] = 0.6,
    min_count: Annotated[
        int, typer.Option("--min-count", help="minimum occurrences to surface")
    ] = 1,
    limit: Annotated[int, typer.Option("--max", help="max candidates to return")] = 30,
) -> None:
    """Mine the transcript for candidate glossary terms (deterministic; agent curates)."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    tpath = ws.require_artifact(
        path, manifest, Stage.TRANSCRIBE, fix="openbbq transcribe"
    )
    transcript = ws.read_transcript(tpath)

    review = ws.read_asr_review_optional(path)
    reference_texts = [
        text
        for text in (manifest.source.title, manifest.source.author)
        if manifest.source.type == "url" and text
    ]
    transcript = asr_reviewlib.resolved_transcript(
        transcript,
        review,
        reference_texts=reference_texts,
    )

    gloss = glossarylib.load_optional(glossary or manifest.glossary)
    known = glossarylib.known_forms(gloss) if gloss is not None else set()
    candidates = glossarylib.suggest_candidates(
        transcript, known=known, max_prob=max_prob, min_count=min_count, limit=limit
    )
    output.emit(
        GlossarySuggestResult(
            candidates=[
                CandidateReport(
                    surface=c.surface,
                    count=c.count,
                    avg_prob=c.avg_prob,
                    example=c.example,
                )
                for c in candidates
            ],
            next=(
                "openbbq glossary audit --workspace "
                f"{shlex.quote(str(path))} --limit 20"
            ),
        )
    )


@app.command()
def audit(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    glossary: Annotated[
        str | None,
        typer.Option("--glossary", help="glossary name (overrides manifest binding)"),
    ] = None,
    offset: Annotated[
        int, typer.Option("--offset", help="zero-based segment offset")
    ] = 0,
    limit: Annotated[
        int, typer.Option("--limit", help="segments returned per page")
    ] = 20,
) -> None:
    """Read every resolved transcript segment with evidence for agent judgment."""

    if offset < 0 or not 1 <= limit <= 20:
        raise OpenBBQError(
            "invalid_batch",
            offset=offset,
            limit=limit,
            fix="use --offset >= 0 and --limit from 1 to 20",
        )
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    tpath = ws.require_artifact(
        path, manifest, Stage.TRANSCRIBE, fix="openbbq transcribe"
    )
    raw_transcript = ws.read_transcript(tpath)
    review = ws.read_asr_review_optional(path)
    reference_texts = [
        text
        for text in (manifest.source.title, manifest.source.author)
        if manifest.source.type == "url" and text
    ]
    report = asr_reviewlib.check(
        raw_transcript,
        review,
        reference_texts=reference_texts,
    )
    resolved = asr_reviewlib.resolved_transcript(
        raw_transcript,
        review,
        reference_texts=reference_texts,
    )
    caption_source = ws.read_reference_caption_optional(path)
    captions = (
        asr_reviewlib.parse_reference_captions(caption_source)
        if caption_source is not None
        else []
    )
    glossary_name = glossary or manifest.glossary
    gloss = glossarylib.load_optional(glossary_name)
    raw_by_id = {segment.id: segment for segment in raw_transcript.segments}
    selected = resolved.segments[offset : offset + limit]
    workspace_arg = shlex.quote(str(path))
    glossary_arg = (
        f" --glossary {shlex.quote(glossary)}" if glossary is not None else ""
    )
    items: list[GlossaryAuditItem] = []
    for index, segment in enumerate(selected, start=offset):
        raw_segment = raw_by_id.get(segment.id)
        words = raw_segment.words if raw_segment is not None else None
        probabilities = [word.prob for word in words or [] if word.prob is not None]
        glossary_source = glossarylib.corrector(gloss)(segment.text)
        items.append(
            GlossaryAuditItem(
                segment_id=segment.id,
                start=segment.start,
                end=segment.end,
                source=segment.text,
                raw_source=(
                    raw_segment.text
                    if raw_segment is not None and raw_segment.text != segment.text
                    else None
                ),
                after_glossary=(
                    glossary_source if glossary_source != segment.text else None
                ),
                previous=(resolved.segments[index - 1].text if index > 0 else None),
                next_segment=(
                    resolved.segments[index + 1].text
                    if index + 1 < len(resolved.segments)
                    else None
                ),
                words=[
                    AuditWordReport(index=word_index, word=word.word, prob=word.prob)
                    for word_index, word in enumerate(words or [])
                ],
                min_prob=min(probabilities) if probabilities else None,
                reference_caption=asr_reviewlib.reference_caption_text(
                    captions,
                    start=segment.start,
                    end=segment.end,
                ),
                glossary_terms=glossarylib.matched_terms(gloss, segment.text),
            )
        )
    next_offset = (
        offset + len(selected)
        if offset + len(selected) < len(resolved.segments)
        else None
    )
    output.emit(
        GlossaryAuditResult(
            transcript_hash=report.transcript_hash,
            glossary=glossary_name,
            offset=offset,
            total=len(resolved.segments),
            items=items,
            next_offset=next_offset,
            remaining=max(len(resolved.segments) - offset - len(selected), 0),
            asr_ready=report.ready,
            asr_review_stale=report.stale,
            reference_caption_available=bool(captions),
            next=(
                f"openbbq glossary audit --workspace {workspace_arg}{glossary_arg} "
                f"--offset {next_offset} --limit {limit}"
                if next_offset is not None
                else f"openbbq glossary apply --workspace {workspace_arg} <terms.json>"
            ),
        )
    )


@app.command(name="apply")
def apply_patch(
    ctx: typer.Context,
    changes: Annotated[
        str,
        typer.Argument(help="JSON file with a terms array to add or update"),
    ],
    workspace: Annotated[
        str | None,
        typer.Option(
            "--workspace", "-w", help="workspace whose bound glossary is updated"
        ),
    ] = None,
    glossary: Annotated[
        str | None,
        typer.Option("--glossary", help="glossary name (default: workspace binding)"),
    ] = None,
) -> None:
    """Atomically add or update up to 20 curated glossary terms."""

    output: Output = ctx.obj
    path = (
        ws.resolve_workspace(workspace)
        if workspace is not None or glossary is None
        else None
    )
    manifest = ws.read_manifest(path) if path is not None else None
    name = glossary or (manifest.glossary if manifest is not None else None)
    if not name:
        raise OpenBBQError(
            "glossary_not_bound",
            fix="pass --glossary <name> or bind one with `openbbq glossary use`",
        )
    existing = glossarylib.load(name)
    changes_path = Path(changes).expanduser()
    try:
        raw = changes_path.read_text(encoding="utf-8")
    except OSError as error:
        raise OpenBBQError(
            "glossary_patch_not_found",
            path=str(changes_path),
            fix="write the glossary patch JSON and try again",
        ) from error
    patches = glossarylib.parse_term_patch(raw)
    updated, report = glossarylib.upsert_terms(existing, patches)
    changed = bool(report.added or report.updated)
    saved = glossarylib.save(updated) if changed else glossarylib.glossary_path(name)

    invalidated: str | None = None
    if (
        changed
        and path is not None
        and manifest is not None
        and manifest.glossary == name
    ):
        transcribe_state = manifest.stages.get(Stage.TRANSCRIBE)
        if transcribe_state is not None:
            ws.record_stage(path, manifest, Stage.TRANSCRIBE, transcribe_state)
            invalidated = str(path)
    output.emit(
        GlossaryApplyResult(
            name=name,
            path=str(saved),
            added=list(report.added),
            updated=list(report.updated),
            unchanged=list(report.unchanged),
            aliases_added=report.aliases_added,
            total_terms=len(updated.terms),
            workspace_invalidated=invalidated,
            next=(
                f"openbbq segment --workspace {shlex.quote(str(path))}"
                if invalidated is not None
                else None
            ),
        )
    )

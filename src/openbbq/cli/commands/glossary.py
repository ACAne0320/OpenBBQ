from __future__ import annotations

from typing import Annotated

import typer
from rich.console import RenderableType
from rich.table import Table

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
            return "[dim]no glossaries — create one with `openbbq glossary new <name>`[/]"
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
        typer.Option("--context", help="series/topic background that scopes this glossary"),
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
        float, typer.Option("--max-prob", help="only surface words below this avg probability")
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
    tpath = ws.require_artifact(path, manifest, Stage.TRANSCRIBE, fix="openbbq transcribe")
    transcript = ws.read_transcript(tpath)

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
            ]
        )
    )

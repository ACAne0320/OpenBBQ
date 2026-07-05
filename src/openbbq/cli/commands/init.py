from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ...core import glossary as glossarylib
from ...core import workspace as ws
from ...schemas import Manifest
from ..output import Output
from ..results import Result


# --- contract layer: init's stdout shape + how it renders ---------------------
class InitResult(Result):
    workspace: str  # durable handle the agent reuses for later commands
    source_type: str
    glossary: str | None = None  # bound glossary name, when given

    @classmethod
    def of(cls, path: Path, manifest: Manifest) -> InitResult:
        return cls(
            workspace=str(path),
            source_type=manifest.source.type,
            glossary=manifest.glossary,
            next="openbbq fetch"
            if manifest.source.type == "url"
            else "openbbq extract-audio",
        )

    def render(self) -> str:
        gloss = f"\n  glossary: {self.glossary}" if self.glossary else ""
        return (
            f"[green]✓[/] workspace ready: {self.workspace}\n"
            f"  source: {self.source_type}{gloss}"
        )


# --- shell layer: typer binding only ------------------------------------------
def init(
    ctx: typer.Context,
    source: Annotated[
        str, typer.Argument(help="URL, or path to a local video/audio file")
    ],
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (use '.' for the current dir)"),
    ] = None,
    glossary: Annotated[
        str | None,
        typer.Option("--glossary", help="bind a glossary from the library (must exist)"),
    ] = None,
) -> None:
    """Create a workspace for SOURCE (records the source only)."""
    output: Output = ctx.obj
    if glossary is not None:
        glossarylib.load(glossary)  # fail fast if the named glossary is missing/invalid
    path, manifest = ws.init_workspace(source, workspace=workspace, glossary=glossary)
    output.emit(InitResult.of(path, manifest))

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Group, RenderableType
from rich.table import Table

from ...core import workspace as ws
from ...schemas import Manifest, Stage, StageState
from ..output import Output
from ..results import Result


# --- contract layer: status's stdout shape + how it renders -------------------
class StatusResult(Result):
    workspace: str
    source_type: str
    title: str | None = None
    author: str | None = None
    thumbnail: str | None = None
    stages: dict[Stage, StageState]  # the work log — only stages actually run

    @classmethod
    def of(cls, path: Path, manifest: Manifest) -> StatusResult:
        return cls(
            workspace=str(path),
            source_type=manifest.source.type,
            title=manifest.source.title,
            author=manifest.source.author,
            thumbnail=manifest.source.thumbnail,
            stages=manifest.stages,
        )

    def render(self) -> RenderableType:
        head = f"workspace: {self.workspace}\n  source: {self.source_type}"
        if self.title is not None:
            head += f"\n  title: {self.title}"
        if self.author is not None:
            head += f"\n  author: {self.author}"
        if self.thumbnail is not None:
            head += f"\n  cover: {self.thumbnail}"
        if not self.stages:
            return f"{head}\n  (no stages run yet)"
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("stage")
        table.add_column("status")
        table.add_column("")
        for stage, st in self.stages.items():
            label = {
                "running": "[yellow]running[/]",
                "failed": "[red]failed[/]",
                "done": "[green]done[/]",
            }.get(st.status.value, st.status.value)
            detail = ""
            if st.progress is not None:
                if (
                    st.progress.label is not None
                    and st.progress.total is None
                    and st.progress.done == 0
                ):
                    detail = st.progress.label
                else:
                    total = st.progress.total if st.progress.total is not None else "?"
                    bytes_done = f"{st.progress.done}/{total}"
                    detail = (
                        f"{st.progress.label}  {bytes_done}"
                        if st.progress.label
                        else bytes_done
                    )
            elif st.error is not None:
                detail = f"[dim]{st.error}[/]"
            table.add_row(stage.value, label, detail)
        return Group(head, table)


# --- shell layer: typer binding only ------------------------------------------
def status(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
) -> None:
    """Report what's been run in the workspace (the work log)."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    output.emit(StatusResult.of(path, manifest))

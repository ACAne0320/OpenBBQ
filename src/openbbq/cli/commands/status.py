from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Group, RenderableType
from rich.table import Table

from ...core import workspace as ws
from ...schemas import (
    Manifest,
    OpenBBQModel,
    SourceType,
    Stage,
    StageState,
    StageStatus,
)
from ..delivery import assess_delivery
from ..output import Output
from ..results import Result


# --- contract layer: status's stdout shape + how it renders -------------------
class StatusSource(OpenBBQModel):
    type: SourceType
    ref: str


class StatusStage(StageState):
    stale: bool | None = None

    @classmethod
    def of(cls, state: StageState, now: datetime) -> StatusStage:
        stale = None
        if state.status is StageStatus.RUNNING and state.updated_at is not None:
            updated_at = state.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if now - updated_at > timedelta(seconds=60):
                stale = True
        return cls(**state.model_dump(), stale=stale)


class StatusResult(Result):
    workspace: str
    source: StatusSource
    glossary: str | None = None
    title: str | None = None
    author: str | None = None
    thumbnail: str | None = None
    worksheets: list[str]
    stages: dict[Stage, StatusStage]  # the work log — only stages actually run
    artifact_ready: bool
    quality: Literal["draft", "human-reviewed"]
    human_reviewed: bool
    delivery_lang: str | None = None
    delivery_issues: list[str]

    @classmethod
    def of(cls, path: Path, manifest: Manifest) -> StatusResult:
        now = datetime.now(timezone.utc)
        delivery = assess_delivery(path, manifest)
        return cls(
            workspace=str(path),
            source=StatusSource(type=manifest.source.type, ref=manifest.source.ref),
            glossary=manifest.glossary,
            title=manifest.source.title,
            author=manifest.source.author,
            thumbnail=manifest.source.thumbnail,
            worksheets=ws.find_worksheets(path),
            stages={
                stage: StatusStage.of(state, now)
                for stage, state in manifest.stages.items()
            },
            artifact_ready=delivery.artifact_ready,
            quality=delivery.quality,
            human_reviewed=delivery.human_reviewed,
            delivery_lang=delivery.lang,
            delivery_issues=[issue.code for issue in delivery.issues],
        )

    def render(self) -> RenderableType:
        head = f"workspace: {self.workspace}\n  source: {self.source.type} {self.source.ref}"
        head += f"\n  glossary: {self.glossary or '(none)'}"
        worksheets = ", ".join(self.worksheets) if self.worksheets else "(none)"
        head += f"\n  worksheets: {worksheets}"
        if self.title is not None:
            head += f"\n  title: {self.title}"
        if self.author is not None:
            head += f"\n  author: {self.author}"
        if self.thumbnail is not None:
            head += f"\n  cover: {self.thumbnail}"
        delivery = "ready" if self.artifact_ready else "blocked"
        if self.delivery_lang is not None:
            delivery += f" · {self.delivery_lang}"
        if self.artifact_ready:
            delivery += f" · {self.quality}"
        head += f"\n  delivery: {delivery}"
        if self.delivery_issues:
            head += f"\n  delivery issues: {', '.join(self.delivery_issues[:5])}"
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
            if st.stale:
                label += " [red](stale)[/]"
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

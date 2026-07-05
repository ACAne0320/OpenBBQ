from __future__ import annotations

import time
from typing import Annotated

import typer
from rich.console import RenderableType
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from ...core.asr import ASRBackend, all_backends
from ...errors import OpenBBQError
from ...schemas import OpenBBQModel
from ..output import Output
from ..results import Result

app = typer.Typer(no_args_is_help=True)


def _human_size(mb: float) -> str:
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


def _human_bytes(size: int) -> str:
    mb = size / 1024 / 1024
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.1f} MB"


def _machine_progress_line(done: int, total: int) -> str:
    if total:
        percent = int(done / total * 100)
        return (
            f"openbbq: downloaded {_human_bytes(done)}/{_human_bytes(total)} "
            f"({percent}%)"
        )
    return f"openbbq: downloaded {_human_bytes(done)}"


class ModelReport(OpenBBQModel):
    name: str
    provider: str
    size_mb: float
    cached: bool


class ModelsResult(Result):
    models: list[ModelReport]

    @classmethod
    def of(cls) -> ModelsResult:
        return cls(
            models=[
                ModelReport(
                    name=m.name,
                    provider=m.provider,
                    size_mb=m.size_mb,
                    cached=backend.has_model(m.name),
                )
                for backend in all_backends()
                for m in backend.available_models()
            ]
        )

    def render(self) -> RenderableType:
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("model")
        table.add_column("provider", style="dim")
        table.add_column("size", justify="right")
        table.add_column("cached", justify="center")
        for m in self.models:
            mark = "[green]✓[/]" if m.cached else ""
            table.add_row(m.name, m.provider, _human_size(m.size_mb), mark)
        return table


class ModelPullResult(Result):
    model: str
    path: str
    size_mb: float
    elapsed_s: float

    def render(self) -> str:
        return (
            f"[green]✓[/] model ready: {self.model}\n"
            f"  path: {self.path}\n"
            f"  size: {self.size_mb:.1f} MB   elapsed: {self.elapsed_s:.1f}s"
        )


@app.command(name="list")
def list_models(ctx: typer.Context) -> None:
    """List ASR models with provider, size, and cache state."""
    output: Output = ctx.obj
    output.emit(ModelsResult.of())


def _backend_for(name: str) -> ASRBackend:
    """The registered backend whose catalog offers ``name`` (else model_missing)."""
    for backend in all_backends():
        if any(m.name == name for m in backend.available_models()):
            return backend
    raise OpenBBQError("model_missing", model=name, fix="openbbq models list")


@app.command(name="pull")
def pull_model(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="model name, e.g. base or large-v3")],
) -> None:
    """Download a model into the OpenBBQ cache."""
    output: Output = ctx.obj
    started = time.monotonic()
    backend = _backend_for(name)
    if output.json_mode:  # machine: no bar — stdout is reserved for the JSON result
        typer.echo(
            f"openbbq: pulling model {name}; download progress is on stderr",
            err=True,
        )
        last_report = 0.0

        def cb(done: int, total: int) -> None:
            nonlocal last_report
            now = time.monotonic()
            if done != total and last_report and now - last_report < 1.0:
                return
            last_report = now
            typer.echo(_machine_progress_line(done, total), err=True)

        path = backend.pull(name, on_progress=cb)
    else:
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
        ) as progress:
            task = progress.add_task(f"pull {name}", total=None)

            def cb(done: int, total: int) -> None:
                progress.update(task, completed=done, total=total or None)

            path = backend.pull(name, on_progress=cb)
    output.emit(
        ModelPullResult(
            model=name,
            path=str(path),
            size_mb=round(path.stat().st_size / 1024 / 1024, 1),
            elapsed_s=round(time.monotonic() - started, 2),
        )
    )

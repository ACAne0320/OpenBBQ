from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import RenderableType
from rich.text import Text

from ...core import skill as skilllib
from ..output import Output
from ..results import Result

app = typer.Typer(no_args_is_help=True)


class SkillInstallResult(Result):
    path: str
    files: int

    @classmethod
    def of(cls, install: skilllib.SkillInstall) -> SkillInstallResult:
        return cls(path=str(install.path), files=install.files)

    def render(self) -> str:
        return (
            f"[green]✓[/] agent skill installed: {self.path}\n"
            "  next: run `openbbq doctor` to verify Claude Code can discover it"
        )


class SkillShowResult(Result):
    path: str
    content: str

    @classmethod
    def packaged(cls) -> SkillShowResult:
        return cls(
            path=skilllib.packaged_skill_path(),
            content=skilllib.packaged_skill_content(),
        )

    def render(self) -> RenderableType:
        return Text(self.content)


@app.command()
def install(
    ctx: typer.Context,
    target: Annotated[
        Path | None,
        typer.Option(
            "--target",
            help="directory that will contain openbbq-subtitles/ (default: ~/.claude/skills)",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="overwrite an existing installed skill"),
    ] = False,
) -> None:
    """Install the packaged OpenBBQ agent skill for Claude Code."""
    output: Output = ctx.obj
    output.emit(SkillInstallResult.of(skilllib.install(target, force=force)))


@app.command()
def show(ctx: typer.Context) -> None:
    """Print the packaged OpenBBQ agent skill markdown."""
    output: Output = ctx.obj
    result = SkillShowResult.packaged()
    if output.json_mode:
        output.emit(result)
        return
    typer.echo(result.content, nl=False)

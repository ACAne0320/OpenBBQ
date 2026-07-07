from __future__ import annotations

from pathlib import Path
from typing import Annotated, Sequence

import typer
from rich.console import RenderableType
from rich.text import Text

from ...core import skill as skilllib
from ...errors import OpenBBQError
from ...schemas import OpenBBQModel
from ..output import Output
from ..results import Result

app = typer.Typer(no_args_is_help=True)


class SkillInstallEntry(OpenBBQModel):
    path: str
    files: int
    language: str


class SkillInstallResult(Result):
    path: str | None = None
    files: int | None = None
    language: str | None = None
    installs: list[SkillInstallEntry] | None = None

    @classmethod
    def of(cls, install: skilllib.SkillInstall) -> SkillInstallResult:
        return cls(
            path=str(install.path),
            files=install.files,
            language=install.language.value,
        )

    @classmethod
    def of_many(cls, installs: Sequence[skilllib.SkillInstall]) -> SkillInstallResult:
        if len(installs) == 1:
            return cls.of(installs[0])
        return cls(
            installs=[
                SkillInstallEntry(
                    path=str(install.path),
                    files=install.files,
                    language=install.language.value,
                )
                for install in installs
            ]
        )

    def render(self) -> str:
        next_step = "  next: run `openbbq doctor` to verify agent skill discovery"
        if self.installs is not None:
            lines = ["[green]✓[/] agent skill installed:"]
            lines.extend(
                f"  - {install.path} ({install.language})"
                for install in self.installs
            )
            lines.append(next_step)
            return "\n".join(lines)
        return (
            f"[green]✓[/] agent skill installed: {self.path} ({self.language})"
            f"\n{next_step}"
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
    agent: Annotated[
        skilllib.SkillAgent,
        typer.Option(
            "--agent",
            help="agent target to install for: claude, codex, agents, or all",
        ),
    ] = skilllib.SkillAgent.AGENTS,
    target: Annotated[
        Path | None,
        typer.Option(
            "--target",
            help="custom directory that will contain the installed skill folder",
        ),
    ] = None,
    name: Annotated[
        skilllib.SkillName,
        typer.Option(
            "--name",
            help="packaged skill to install",
        ),
    ] = skilllib.SkillName.SUBTITLES,
    force: Annotated[
        bool,
        typer.Option("--force", help="overwrite an existing installed skill"),
    ] = False,
    language: Annotated[
        skilllib.SkillLanguage,
        typer.Option(
            "--language",
            help="skill language to install: en or zh-CN",
        ),
    ] = skilllib.SkillLanguage.EN,
) -> None:
    """Install the packaged OpenBBQ agent skill."""
    output: Output = ctx.obj
    if target is not None:
        if agent is not skilllib.SkillAgent.AGENTS:
            raise OpenBBQError(
                "invalid_skill_options",
                fix="use either --agent or --target, not both",
            )
        output.emit(
            SkillInstallResult.of(
                skilllib.install(
                    target, name=name, force=force, language=language
                )
            )
        )
        return
    output.emit(
        SkillInstallResult.of_many(
            skilllib.install_for_agent(
                agent, name=name, force=force, language=language
            )
        )
    )


@app.command()
def show(
    ctx: typer.Context,
    name: Annotated[
        skilllib.SkillName,
        typer.Option(
            "--name",
            help="packaged skill to show",
        ),
    ] = skilllib.SkillName.SUBTITLES,
    language: Annotated[
        skilllib.SkillLanguage,
        typer.Option(
            "--language",
            help="skill language to show: en or zh-CN",
        ),
    ] = skilllib.SkillLanguage.EN,
) -> None:
    """Print the packaged OpenBBQ agent skill markdown."""
    output: Output = ctx.obj
    result = SkillShowResult(
        path=skilllib.packaged_skill_path(language, name=name),
        content=skilllib.packaged_skill_content(language, name=name),
    )
    if output.json_mode:
        output.emit(result)
        return
    typer.echo(result.content, nl=False)

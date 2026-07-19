from __future__ import annotations

from typing import Annotated

import typer

from .. import __version__
from .commands.auth import app as auth_app
from .commands.asr import app as asr_app
from .commands.agent import app as agent_app
from .commands.burn import burn
from .commands.delivery import app as delivery_app
from .commands.doctor import doctor
from .commands.export import export
from .commands.extract_audio import extract_audio
from .commands.fetch import fetch
from .commands.glossary import app as glossary_app
from .commands.init import init
from .commands.models import app as models_app
from .commands.qa import app as qa_app
from .commands.review import review
from .commands.segment import segment
from .commands.skill import app as skill_app
from .commands.status import status
from .commands.transcribe import transcribe
from .commands.translate import app as translate_app
from .output import Output
from .results import Result

app = typer.Typer(no_args_is_help=True)


class VersionResult(Result):
    version: str

    def render(self) -> str:
        return f"openbbq {self.version}"


def _version_callback(ctx: typer.Context, value: bool) -> None:
    if not value:
        return
    output = ctx.obj if isinstance(ctx.obj, Output) else Output.detect(False)
    output.emit(VersionResult(version=__version__))
    raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    json: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON")
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the OpenBBQ version and exit",
        ),
    ] = False,
) -> None:
    if isinstance(ctx.obj, Output) and ctx.obj.json_mode:
        return
    ctx.obj = Output.detect(json)


app.command()(doctor)
app.command()(init)
app.command()(status)
app.command()(fetch)
app.command(name="extract-audio")(extract_audio)
app.command()(transcribe)
app.command()(segment)
app.add_typer(translate_app, name="translate")
app.command()(review)
app.command()(export)
app.command()(burn)
app.add_typer(models_app, name="models")
app.add_typer(glossary_app, name="glossary")
app.add_typer(auth_app, name="auth")
app.add_typer(asr_app, name="asr")
app.add_typer(agent_app, name="agent")
app.add_typer(qa_app, name="qa")
app.add_typer(delivery_app, name="delivery")
app.add_typer(skill_app, name="skill")

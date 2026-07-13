from __future__ import annotations

from typing import Annotated

import typer

from .commands.auth import app as auth_app
from .commands.burn import burn
from .commands.doctor import doctor
from .commands.export import export
from .commands.extract_audio import extract_audio
from .commands.fetch import fetch
from .commands.glossary import app as glossary_app
from .commands.init import init
from .commands.models import app as models_app
from .commands.review import review
from .commands.segment import segment
from .commands.skill import app as skill_app
from .commands.status import status
from .commands.transcribe import transcribe
from .commands.translate import app as translate_app
from .output import Output

app = typer.Typer(no_args_is_help=True)


@app.callback()
def _root(
    ctx: typer.Context,
    json: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON")
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
app.add_typer(skill_app, name="skill")

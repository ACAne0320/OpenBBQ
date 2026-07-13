from __future__ import annotations

import secrets
import socket
import threading
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

from ...core import review as reviewlib
from ...core import workspace as ws
from ...errors import OpenBBQError
from ..output import Output
from ..results import Result


class ReviewResult(Result):
    workspace: str
    target_lang: str | None = None
    url: str

    def render(self) -> str:
        language = self.target_lang or "source"
        return (
            f"[green]✓[/] review server: {self.url}\n"
            f"  workspace: {self.workspace}\n"
            f"  language: {language}\n"
            "  press Ctrl-C to stop"
        )


def _available_port(requested: int) -> int:
    if requested:
        return requested
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_review_server(path: Path, lang: str | None, secret: str, port: int) -> None:
    try:
        import uvicorn

        from openbbq.review_server.app import create_app
    except ImportError as e:
        raise OpenBBQError(
            "review_dependency_missing",
            fix="uv tool install 'openbbq[review]' --force",
        ) from e
    app = create_app(path, lang, secret=secret)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    uvicorn.Server(config).run()


def review(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    to: Annotated[
        str | None,
        typer.Option("--to", help="initial target language worksheet (e.g. zh)"),
    ] = None,
    port: Annotated[
        int,
        typer.Option(
            "--port", min=0, max=65535, help="local port (0 picks a free port)"
        ),
    ] = 0,
    no_open: Annotated[
        bool,
        typer.Option("--no-open", help="do not open the browser automatically"),
    ] = False,
) -> None:
    """Open the local visual subtitle review and editing workspace."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    selected_port = _available_port(port)
    secret = secrets.token_urlsafe(32)
    public_url = f"http://127.0.0.1:{selected_port}/"
    launch_url = f"{public_url}#secret={secret}"
    with reviewlib.ReviewLock(path):
        # Opening a session may recover or reconcile review files, so it must
        # happen only after excluding another live review server.
        session = reviewlib.ReviewSession.open(path, to)
        session.snapshot()
        output.emit(
            ReviewResult(
                workspace=str(path),
                target_lang=to,
                url=launch_url,
                next="review in the browser; press Ctrl-C when finished",
            )
        )
        if not no_open:
            threading.Timer(0.4, webbrowser.open, args=(launch_url,)).start()
        run_review_server(path, to, secret, selected_port)

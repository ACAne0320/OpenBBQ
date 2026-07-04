from __future__ import annotations

from datetime import datetime
from typing import Annotated

import typer

from ...core.auth import browser
from ...core.auth import sites
from ...core.auth import store as auth_store
from ..output import Output
from ..results import Result

app = typer.Typer(no_args_is_help=True)


class AuthStatusResult(Result):
    site: str
    configured: bool
    cookie_count: int = 0
    auth_cookie_count: int = 0
    expires_at: datetime | None = None

    @classmethod
    def of(cls, status: auth_store.AuthStatus) -> AuthStatusResult:
        return cls(
            site=status.site,
            configured=status.configured,
            cookie_count=status.cookie_count,
            auth_cookie_count=status.auth_cookie_count,
            expires_at=status.expires_at,
        )

    def render(self) -> str:
        if not self.configured:
            return f"{self.site}: not configured"
        expiry = f"\n  expires: {self.expires_at.isoformat()}" if self.expires_at else ""
        return (
            f"[green]✓[/] {self.site} auth configured\n"
            f"  cookies: {self.cookie_count} ({self.auth_cookie_count} auth){expiry}"
        )


class AuthClearResult(Result):
    site: str

    def render(self) -> str:
        return f"[green]✓[/] cleared auth: {self.site}"


def _stderr(message: str) -> None:
    typer.echo(message, err=True)


@app.command(name="browser-login")
def browser_login(
    ctx: typer.Context,
    site: Annotated[str, typer.Argument(help="site key, currently: youtube")],
) -> None:
    """Open a browser login window and save site cookies for later use."""
    output: Output = ctx.obj
    policy = sites.require_policy(site)

    def wait_for_user() -> None:
        _stderr("Complete login in the opened browser window.")
        _stderr("Then close that browser window, return here, and press Enter.")
        input()

    raw = browser.browser_login(
        policy.key,
        wait_for_user=wait_for_user,
        on_message=_stderr,
    )
    status = auth_store.save_cookies(policy.key, raw)
    output.emit(AuthStatusResult.of(status))


@app.command()
def status(
    ctx: typer.Context,
    site: Annotated[str, typer.Argument(help="site key, currently: youtube")],
) -> None:
    """Show whether a site app session is configured."""
    output: Output = ctx.obj
    output.emit(AuthStatusResult.of(auth_store.status(site)))


@app.command()
def clear(
    ctx: typer.Context,
    site: Annotated[str, typer.Argument(help="site key, currently: youtube")],
) -> None:
    """Remove saved cookies for a site app session."""
    output: Output = ctx.obj
    policy = sites.require_policy(site)
    auth_store.clear(policy.key)
    output.emit(AuthClearResult(site=policy.key))

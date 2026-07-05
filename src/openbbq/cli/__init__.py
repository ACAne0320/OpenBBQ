from __future__ import annotations

from collections.abc import Mapping
import sys
import traceback
from typing import Protocol, cast

import typer
from typer._click import ClickException  # typer >=0.26 bundles click privately
from typer._click.exceptions import Abort
from typer.main import get_command

from ..errors import OpenBBQError
from .app import app
from .output import Output

__all__ = ["app", "main"]


class _NoArgsHelpCommand(Protocol):
    no_args_is_help: bool


def _strip_json_flag(args: list[str]) -> list[str]:
    # main() already chose machine mode from this flag; strip it so any position works.
    return [arg for arg in args if arg != "--json"]


def _disable_no_args_help(command: object) -> None:
    if hasattr(command, "no_args_is_help"):
        cast(_NoArgsHelpCommand, command).no_args_is_help = False
    children = getattr(command, "commands", None)
    if isinstance(children, Mapping):
        for child in children.values():
            _disable_no_args_help(child)


def main() -> None:
    """Console entry point, split by audience.

    Human (TTY): typer renders everything natively — help, Rich usage panels,
    completion, exit codes — and we only translate ``OpenBBQError``.
    Machine (``--json`` / non-TTY): a single chokepoint emits compact JSON for
    success, domain errors (exit 1) and usage errors (exit 2) alike, so
    ``--json`` is honored uniformly.
    """
    if "--json" not in sys.argv and sys.stdout.isatty():
        try:
            app()
        except OpenBBQError as err:
            Output(json_mode=False).error(err)
            raise SystemExit(1) from err
        return

    output = Output(json_mode=True)
    command = get_command(app)
    _disable_no_args_help(command)
    try:
        rv = command(
            args=_strip_json_flag(sys.argv[1:]),
            prog_name="openbbq",
            standalone_mode=False,
            obj=output,
        )
    except OpenBBQError as err:
        output.error(err)
        raise SystemExit(1) from err
    except typer.Exit as err:
        raise SystemExit(err.exit_code) from err
    except Abort as err:
        raise SystemExit(130) from err
    except ClickException as err:  # missing/bad arg, unknown command, no command
        output.usage_error(err)
        raise SystemExit(err.exit_code) from err
    except Exception as err:
        traceback.print_exception(type(err), err, err.__traceback__, file=sys.stderr)
        output.internal_error(err)
        raise SystemExit(1) from err
    raise SystemExit(rv if isinstance(rv, int) else 0)

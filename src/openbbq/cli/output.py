from __future__ import annotations

import json
import sys
from dataclasses import dataclass

from rich.console import Console
from typer._click import ClickException  # typer >=0.26 bundles click privately

from ..errors import OpenBBQError
from .results import Result

_out = Console()
_err = Console(stderr=True)


def _compact(data: object) -> str:
    # ensure_ascii=False keeps CJK readable for both humans and agents
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


@dataclass
class Output:
    """Human/machine dual-mode emitter.

    Decides *where* a result goes and in *which* mode; the result itself owns
    *what* the payload/text is. Machine mode (``--json`` or a non-TTY stdout):
    one compact JSON object on stdout — success or error — distinguished by exit
    code. Human mode: Rich to the terminal, errors on stderr to keep stdout clean.
    """

    json_mode: bool

    @classmethod
    def detect(cls, json_flag: bool) -> Output:
        return cls(json_mode=json_flag or not sys.stdout.isatty())

    def emit(self, result: Result) -> None:
        """Success path: a command's Result, dispatched by mode."""
        if self.json_mode:
            print(_compact(result.payload()))
        else:
            _out.print(result.render())

    def usage_error(self, err: ClickException) -> None:
        """Render a typer/Click usage error (exit 2) as machine JSON.

        Machine-mode only by construction: human mode lets typer render usage
        errors natively (see ``cli.main``).
        """
        message = err.format_message() or "no command given"
        print(_compact({"error": "usage", "message": message}))

    def error(self, err: OpenBBQError) -> None:
        if self.json_mode:
            print(_compact(err.payload()))
            return
        line = f"[bold red]error[/]: {err.code}"
        for key, value in err.context.items():
            line += f"  {key}={value}"
        _err.print(line)
        if err.fix is not None:
            _err.print(f"[dim]fix:[/] {err.fix}")

    def internal_error(self, err: Exception) -> None:
        message = str(err) or err.__class__.__name__
        print(_compact({"error": "internal", "message": message}))

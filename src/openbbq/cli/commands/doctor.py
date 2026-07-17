from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import RenderableType
from rich.table import Table

from ...core import doctor as core
from ... import __version__
from ...schemas import OpenBBQModel
from ..output import Output
from ..results import Result


# --- contract layer: doctor's stdout shape + how it renders -------------------
class CheckReport(OpenBBQModel):
    name: str
    ok: bool
    detail: str
    fix: str | None = None

    @classmethod
    def of(cls, c: core.Check) -> CheckReport:
        return cls(name=c.name, ok=c.ok, detail=c.detail, fix=c.fix)


class DoctorResult(Result):
    version: str
    executable: str
    healthy: bool  # all probes green (distinct from `ok` = the command ran)
    checks: list[CheckReport]

    @classmethod
    def of(cls, checks: list[core.Check]) -> DoctorResult:
        return cls(
            version=__version__,
            executable=str(Path(sys.argv[0]).expanduser().resolve()),
            healthy=all(c.ok or not c.required for c in checks),
            checks=[CheckReport.of(c) for c in checks],
        )

    def render(self) -> RenderableType:
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("check")
        table.add_column("status")
        table.add_column("detail")
        for c in self.checks:
            mark = "[green]✓[/]" if c.ok else "[red]✗[/]"
            detail = (
                c.detail
                if c.ok or c.fix is None
                else f"{c.detail}\n[dim]fix:[/] {c.fix}"
            )
            table.add_row(c.name, mark, detail)
        return table


# --- shell layer: typer binding only ------------------------------------------
def doctor(ctx: typer.Context) -> None:
    """Probe the environment for required tools (read-only, idempotent)."""
    output: Output = ctx.obj
    output.emit(DoctorResult.of(core.run_checks()))

from __future__ import annotations

from typing import Annotated

import typer

from ...core import workspace as ws
from ...errors import OpenBBQError
from ...schemas import OpenBBQModel
from ..delivery import DeliveryIssue, assess_delivery
from ..output import Output
from ..results import Result

app = typer.Typer(no_args_is_help=True)


class DeliveryIssueResult(OpenBBQModel):
    code: str
    gate: str
    detail: str
    fix: str

    @classmethod
    def of(cls, issue: DeliveryIssue) -> DeliveryIssueResult:
        return cls(
            code=issue.code,
            gate=issue.gate,
            detail=issue.detail,
            fix=issue.fix,
        )


class DeliveryCheckResult(Result):
    ready: bool
    workspace: str
    lang: str | None = None
    gates: dict[str, bool]
    issues: list[DeliveryIssueResult]

    def render(self) -> str:
        if self.ready:
            return "[green]✓[/] delivery ready: every quality gate passed"
        lines = ["[red]delivery blocked[/]"]
        lines.extend(f"  {issue.gate}: {issue.detail}" for issue in self.issues)
        return "\n".join(lines)


@app.command()
def check(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    to: Annotated[
        str | None,
        typer.Option("--to", help="target language (inferred when exactly one exists)"),
    ] = None,
) -> None:
    """Hard delivery gate: non-zero exit until every quality check passes."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    assessment = assess_delivery(path, ws.read_manifest(path), lang=to)
    issues = [DeliveryIssueResult.of(issue) for issue in assessment.issues]
    if not assessment.ready:
        raise OpenBBQError(
            "delivery_not_ready",
            ready=False,
            workspace=str(path),
            lang=assessment.lang,
            gates=assessment.gates,
            issues=[issue.payload() for issue in assessment.issues],
            fix=assessment.next,
        )
    output.emit(
        DeliveryCheckResult(
            ready=True,
            workspace=str(path),
            lang=assessment.lang,
            gates=assessment.gates,
            issues=issues,
        )
    )

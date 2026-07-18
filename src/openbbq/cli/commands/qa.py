from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

import typer

from ...core import media
from ...core import qa as qalib
from ...core import workspace as ws
from ...errors import OpenBBQError
from ...schemas import OpenBBQModel, QaReport, QaVisualIssue, QaVisualIssueCode, Stage
from ..output import Output
from ..results import Result

app = typer.Typer(no_args_is_help=True)


class QaFrameResult(OpenBBQModel):
    path: str
    cue_id: int
    at: float
    sha256: str
    reasons: list[str]


class QaResult(Result):
    workspace: str
    artifact: str
    artifact_sha256: str
    artifact_bytes: int
    duration_s: float
    frames: list[QaFrameResult]
    mechanical_status: Literal["pass", "stale"]
    mechanical_issues: list[str]
    visual_status: Literal["not_performed", "pass", "fail", "stale"]
    visual_reason: str | None = None
    visual_issues: list[QaVisualIssue]

    def render(self) -> str:
        visual = self.visual_status.replace("_", " ")
        return (
            f"QA mechanical: {self.mechanical_status}\n"
            f"QA visual: {visual}\n"
            f"  {len(self.frames)} rendered frame(s) · {self.artifact_bytes} bytes"
        )


def _result(
    *,
    path: Path,
    report: QaReport,
    mechanical_status: Literal["pass", "stale"],
    issues: list[str],
) -> QaResult:
    visual_status: Literal["not_performed", "pass", "fail", "stale"] = (
        report.visual_status if mechanical_status == "pass" else "stale"
    )
    if mechanical_status == "stale":
        next_step = "openbbq qa render"
    elif visual_status == "not_performed":
        next_step = (
            "inspect every rendered frame, then run openbbq qa attest "
            "--result pass|fail --reason <observation>"
        )
    elif visual_status == "fail":
        issue_codes = {issue.code for issue in report.visual_issues}
        if QaVisualIssueCode.CONTENT_ERROR in issue_codes:
            next_step = (
                "fix ASR/translation content, rerun translation audit, export, burn, "
                "and qa render"
            )
        elif issue_codes:
            next_step = (
                "openbbq export --format ass --mode bilingual "
                "--ass-preset fansub-compact; then rerun burn and qa render"
            )
        else:
            next_step = "fix the reported visual issue, then rerun export, burn, and qa"
    else:
        next_step = None
    return QaResult(
        workspace=str(path),
        artifact=report.artifact,
        artifact_sha256=report.artifact_sha256,
        artifact_bytes=report.artifact_bytes,
        duration_s=report.duration_s,
        frames=[
            QaFrameResult(
                path=frame.path,
                cue_id=frame.cue_id,
                at=frame.at,
                sha256=frame.sha256,
                reasons=frame.reasons,
            )
            for frame in report.frames
        ],
        mechanical_status=mechanical_status,
        mechanical_issues=issues,
        visual_status=visual_status,
        visual_reason=report.visual_reason,
        visual_issues=report.visual_issues,
        next=next_step,
    )


def _load_assessment(path: Path) -> tuple[QaReport, Literal["pass", "stale"], list[str]]:
    manifest = ws.read_manifest(path)
    artifact_path = ws.require_artifact(
        path, manifest, Stage.BURN, fix="openbbq burn"
    )
    artifact = manifest.stages[Stage.BURN].artifact
    assert artifact is not None
    report = ws.read_qa_optional(path)
    if report is None:
        raise OpenBBQError("qa_not_found", fix="openbbq qa render")
    assessment = qalib.assess(
        report,
        artifact=artifact,
        artifact_path=artifact_path,
        workspace=path,
    )
    issues = list(assessment.issues)
    try:
        ws.require_fresh_artifact(path, artifact_path, Stage.BURN)
    except OpenBBQError as error:
        issues.append(f"burn_{error.code}")
    status: Literal["pass", "stale"] = "stale" if issues else "pass"
    return report, status, issues


@app.command()
def render(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    count: Annotated[
        int,
        typer.Option("--count", help="number of subtitle-bearing frames (1..9)"),
    ] = 7,
    ffmpeg: Annotated[
        str | None,
        typer.Option("--ffmpeg", help="ffmpeg executable used to render frames"),
    ] = None,
) -> None:
    """Render mechanical QA evidence; this does not perform visual inspection."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    artifact_path = ws.require_artifact(
        path, manifest, Stage.BURN, fix="openbbq burn"
    )
    ws.require_fresh_artifact(path, artifact_path, Stage.BURN)
    artifact = manifest.stages[Stage.BURN].artifact
    assert artifact is not None
    cues_path = ws.require_artifact(
        path, manifest, Stage.SEGMENT, fix="openbbq segment"
    )
    cues = ws.read_cues(cues_path)
    translation = None
    languages = ws.find_worksheets(path)
    if len(languages) == 1:
        translation = ws.read_translation(ws.worksheet_path(path, languages[0]))
    points = qalib.select_frame_points(
        cues,
        count=count,
        translation=translation,
    )
    # A fresh directory keeps the previous report valid if rendering fails
    # halfway through. The qa.json pointer moves only after every frame passes.
    frame_dir = path / ".openbbq" / "qa" / "frames" / uuid4().hex[:12]
    evidence: list[qalib.FrameEvidence] = []
    for position, point in enumerate(points, start=1):
        frame_path = frame_dir / f"frame-{position:02d}-cue-{point.cue_id}.png"
        media.render_video_frame(
            artifact_path,
            frame_path,
            at_s=point.at,
            ffmpeg=ffmpeg,
        )
        evidence.append(
            qalib.FrameEvidence(
                path=str(frame_path.relative_to(path)),
                cue_id=point.cue_id,
                at=point.at,
                file=frame_path,
                reasons=point.reasons,
            )
        )
    duration = (
        media.media_duration(artifact_path, ffmpeg=Path(ffmpeg).expanduser())
        if ffmpeg is not None
        else media.media_duration(artifact_path)
    )
    if duration is None:
        raise OpenBBQError(
            "invalid_burn_output",
            artifact=artifact,
            fix="verify the MP4 with ffprobe or rerun openbbq burn",
        )
    report = qalib.create_report(
        artifact=artifact,
        artifact_path=artifact_path,
        duration_s=duration,
        frames=evidence,
    )
    ws.write_qa(path, report)
    output.emit(_result(path=path, report=report, mechanical_status="pass", issues=[]))


@app.command()
def check(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
) -> None:
    """Read-only verification of current MP4/frame hashes and visual status."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    report, status, issues = _load_assessment(path)
    output.emit(_result(path=path, report=report, mechanical_status=status, issues=issues))


@app.command()
def attest(
    ctx: typer.Context,
    result: Annotated[
        Literal["pass", "fail"],
        typer.Option("--result", help="observed visual result after inspecting every frame"),
    ],
    reason: Annotated[
        str,
        typer.Option("--reason", help="concise visual observation, not a file-existence claim"),
    ],
    issue: Annotated[
        list[QaVisualIssueCode] | None,
        typer.Option(
            "--issue",
            help="structured failure issue; repeat for multiple issues",
        ),
    ] = None,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
) -> None:
    """Record a visual observation only after the rendered images were inspected."""
    output: Output = ctx.obj
    path = ws.resolve_workspace(workspace)
    report, status, issues = _load_assessment(path)
    if status != "pass":
        raise OpenBBQError(
            "qa_stale",
            issues=issues,
            fix="openbbq qa render",
        )
    report = qalib.attest(report, result=result, reason=reason, issues=issue)
    ws.write_qa(path, report)
    output.emit(_result(path=path, report=report, mechanical_status="pass", issues=[]))

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Group, RenderableType
from rich.progress import (
    BarColumn,
    Progress as RichProgress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.style import Style
from rich.table import Table
from rich.text import Text

from ...core import media
from ...core import workspace as ws
from ...errors import OpenBBQError
from ...schemas import Manifest, Progress, Stage, StageState, StageStatus
from ..output import Output
from ..results import Result


class BurnResult(Result):
    workspace: str
    artifact: str
    subtitle: str
    duration_s: float | None
    elapsed_s: float
    ffmpeg: str

    def _artifact_text(self, artifact: str) -> Text:
        path = Path(artifact)
        resolved = path if path.is_absolute() else Path(self.workspace) / path
        return Text(
            artifact, style=Style(color="cyan", link=resolved.resolve().as_uri())
        )

    def _workspace_text(self) -> Text:
        uri = Path(self.workspace).resolve().as_uri()
        return Text(self.workspace, style=Style(color="cyan", link=uri))

    def render(self) -> RenderableType:
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right", style="dim", no_wrap=True)
        table.add_column(ratio=1)
        table.add_row("workspace", self._workspace_text())
        table.add_row("file", self._artifact_text(self.artifact))
        table.add_row("subtitle", self._artifact_text(self.subtitle))
        if self.duration_s is not None:
            table.add_row("length", Text(_clock(self.duration_s)))
        table.add_row("elapsed", Text(f"{self.elapsed_s:.1f}s"))
        return Group(Text.assemble(("✓", "green"), (" video burned", "bold")), table)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clock(seconds: float) -> str:
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _relative_to_workspace(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _resolve_path(value: str, workspace: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else workspace / path


def _inside_workspace(path: Path, workspace: Path) -> bool:
    try:
        path.resolve().relative_to(workspace.resolve())
    except ValueError:
        return False
    return True


def _resolve_subtitle(
    workspace: Path, manifest: Manifest, subtitle: str | None
) -> Path:
    if subtitle is not None:
        path = _resolve_path(subtitle, workspace)
        if not path.exists():
            raise OpenBBQError(
                "missing_input",
                subtitle=subtitle,
                fix="check --subtitle, or run openbbq export --format ass",
            )
    else:
        path = ws.require_artifact(
            workspace,
            manifest,
            Stage.EXPORT,
            fix="openbbq export --format ass",
        )
    if path.suffix.lower() != ".ass":
        raise OpenBBQError(
            "unsupported_subtitle_format",
            artifact=_relative_to_workspace(path, workspace),
            format=path.suffix.lower() or "(none)",
            fix="openbbq export --format ass",
        )
    return path


def _default_output(subtitle: Path) -> Path:
    return subtitle.with_name(f"{subtitle.stem}-burned.mp4")


def _record_running(
    workspace: Path, manifest: Manifest, progress: media.BurnProgress
) -> None:
    ws.record_stage(
        workspace,
        manifest,
        Stage.BURN,
        StageState(
            status=StageStatus.RUNNING,
            progress=Progress(
                done=progress.done,
                total=progress.total,
                label="burn subtitles",
            ),
            updated_at=_now(),
        ),
    )


def burn(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    subtitle: Annotated[
        str | None,
        typer.Option(
            "--subtitle",
            help="ASS subtitle file to burn (default: last export artifact)",
        ),
    ] = None,
    output: Annotated[
        str | None,
        typer.Option(
            "--output",
            help="output mp4 path; relative paths are inside workspace (default: beside ASS)",
        ),
    ] = None,
    ffmpeg: Annotated[
        str | None,
        typer.Option("--ffmpeg", help="ffmpeg executable with libass support"),
    ] = None,
    allow_stale: Annotated[
        bool,
        typer.Option(
            "--allow-stale",
            help="burn an intentional untracked or stale workspace subtitle",
        ),
    ] = False,
) -> None:
    """Hard-burn an exported ASS subtitle file into an MP4 video."""
    output_obj: Output = ctx.obj
    started = time.monotonic()
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    src = ws.media_input(manifest, path)
    if src.suffix.lower() in ws.AUDIO_EXTS:
        raise OpenBBQError(
            "video_unavailable",
            source=str(src),
            fix="use a video source, or fetch media from the URL first",
        )
    sub = _resolve_subtitle(path, manifest, subtitle)
    if not allow_stale and (subtitle is None or _inside_workspace(sub, path)):
        ws.require_fresh_artifact(path, sub, Stage.EXPORT)
    dest = _resolve_path(output, path) if output else _default_output(sub)

    last_write = 0.0

    def heartbeat(progress: media.BurnProgress) -> None:
        nonlocal last_write
        now = time.monotonic()
        if not (
            now - last_write >= 1.0
            or progress.done == 0
            or progress.done == progress.total
        ):
            return
        _record_running(path, manifest, progress)
        last_write = now

    try:
        if output_obj.json_mode:
            typer.echo(
                "openbbq: burning subtitles; poll progress with "
                f"`openbbq --json status --workspace {path}`",
                err=True,
            )
            outcome = media.burn_subtitles(
                src, sub, dest, ffmpeg=ffmpeg, on_progress=heartbeat
            )
        else:
            progress_bar = RichProgress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                transient=True,
            )
            with progress_bar:
                task = progress_bar.add_task("Burning subtitles", total=None)

                def cb(progress: media.BurnProgress) -> None:
                    progress_bar.update(
                        task,
                        completed=progress.done,
                        total=progress.total,
                    )
                    heartbeat(progress)

                outcome = media.burn_subtitles(
                    src, sub, dest, ffmpeg=ffmpeg, on_progress=cb
                )
    except BaseException as err:
        ws.record_stage(
            path,
            manifest,
            Stage.BURN,
            StageState(
                status=StageStatus.FAILED,
                error="interrupted" if isinstance(err, KeyboardInterrupt) else str(err),
                updated_at=_now(),
            ),
        )
        raise

    artifact = _relative_to_workspace(dest, path)
    subtitle_artifact = _relative_to_workspace(sub, path)
    ws.record_artifact_provenance(
        path,
        dest,
        Stage.BURN,
        inputs=[src, sub],
    )
    ws.record_stage(
        path,
        manifest,
        Stage.BURN,
        StageState(
            status=StageStatus.DONE,
            artifact=artifact,
            updated_at=_now(),
        ),
    )
    output_obj.emit(
        BurnResult(
            workspace=str(path),
            artifact=artifact,
            subtitle=subtitle_artifact,
            duration_s=outcome.duration_s,
            elapsed_s=round(time.monotonic() - started, 2),
            ffmpeg=outcome.ffmpeg,
            next="openbbq qa render",
        )
    )

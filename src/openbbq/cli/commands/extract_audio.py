from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated

import typer

from ...core import media
from ...core import workspace as ws
from ...errors import OpenBBQError
from ...schemas import Stage, StageState, StageStatus
from ..output import Output
from ..results import Result
from ..stage_execution import run_stage_once

AUDIO_REL = "media/audio.16k.wav"  # derived artifact, relative to the workspace
_MIN_DURATION_TOLERANCE_S = 2.0
_DURATION_TOLERANCE_RATIO = 0.01


def _clock(seconds: float) -> str:
    """Seconds → m:ss (or h:mm:ss) — human-readable media length."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


# --- contract layer -----------------------------------------------------------
class ExtractAudioResult(Result):
    artifact: str  # relative to the workspace
    duration_s: float  # audio content length, seconds
    elapsed_s: float  # command runtime, seconds

    def render(self) -> str:
        return (
            f"[green]✓[/] audio extracted: {self.artifact}\n"
            f"  length: {_clock(self.duration_s)}   elapsed: {self.elapsed_s:.1f}s"
        )


# --- shell layer --------------------------------------------------------------
@run_stage_once(Stage.EXTRACT_AUDIO)
def extract_audio(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
) -> None:
    """Normalize the source media to 16 kHz mono WAV (what ASR needs)."""
    output: Output = ctx.obj
    started = time.monotonic()
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)
    src = ws.media_input(manifest, path)
    source_duration = media.media_duration(src)
    media.extract_audio(src, path / AUDIO_REL)
    duration = media.wav_duration(path / AUDIO_REL)
    if source_duration is not None:
        tolerance = max(
            _MIN_DURATION_TOLERANCE_S,
            source_duration * _DURATION_TOLERANCE_RATIO,
        )
        if abs(duration - source_duration) > tolerance:
            detail = (
                f"normalized audio is {duration:.3f}s but source media is "
                f"{source_duration:.3f}s"
            )
            ws.record_stage(
                path,
                manifest,
                Stage.EXTRACT_AUDIO,
                StageState(
                    status=StageStatus.FAILED,
                    error=detail,
                    updated_at=datetime.now(timezone.utc),
                ),
            )
            raise OpenBBQError(
                "media_duration_mismatch",
                source_duration_s=round(source_duration, 3),
                audio_duration_s=duration,
                tolerance_s=round(tolerance, 3),
                fix="rerun openbbq extract-audio after confirming only one process uses this workspace",
            )
    ws.record_stage(
        path,
        manifest,
        Stage.EXTRACT_AUDIO,
        StageState(
            status=StageStatus.DONE,
            artifact=AUDIO_REL,
            updated_at=datetime.now(timezone.utc),
        ),
    )
    output.emit(
        ExtractAudioResult(
            artifact=AUDIO_REL,
            duration_s=duration,
            elapsed_s=round(time.monotonic() - started, 2),
            next="openbbq transcribe",
        )
    )

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated

import typer

from ...core import media
from ...core import workspace as ws
from ...schemas import Stage, StageState, StageStatus
from ..output import Output
from ..results import Result

AUDIO_REL = "media/audio.16k.wav"  # derived artifact, relative to the workspace


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
    media.extract_audio(src, path / AUDIO_REL)
    duration = media.wav_duration(path / AUDIO_REL)
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
        )
    )

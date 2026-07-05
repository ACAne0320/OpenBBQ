from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated

import typer
from rich.progress import BarColumn, Progress as RichProgress, TextColumn, TimeElapsedColumn

from ...core import glossary as glossarylib
from ...core import media
from ...core import workspace as ws
from ...core.asr import Capability, get_backend
from ...errors import OpenBBQError
from ...schemas import ASRInfo, Progress, Stage, StageState, StageStatus, Transcript
from ..output import Output
from ..results import Result

TRANSCRIPT_REL = "transcript.json"


def _clock(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class TranscribeResult(Result):
    artifact: str
    segments: int
    language: str
    backend: str
    model: str
    duration_s: float
    elapsed_s: float

    def render(self) -> str:
        return (
            f"[green]✓[/] transcribed: {self.artifact}\n"
            f"  {self.segments} segments · {self.language} · {self.backend} {self.model}\n"
            f"  length: {_clock(self.duration_s)}   elapsed: {self.elapsed_s:.1f}s"
        )


def transcribe(
    ctx: typer.Context,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", "-w", help="workspace dir (default: cwd upward)"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="cached model name or direct ggml .bin path"),
    ] = None,
    backend: Annotated[
        str, typer.Option("--backend", help="ASR backend (currently auto/whisper.cpp)")
    ] = "auto",
    language: Annotated[
        str | None, typer.Option("--language", help="force language code, e.g. en")
    ] = None,
    prompt: Annotated[
        str | None, typer.Option("--prompt", help="initial prompt for ASR")
    ] = None,
    glossary: Annotated[
        str | None,
        typer.Option("--glossary", help="glossary name (overrides the manifest binding)"),
    ] = None,
    use_gpu: Annotated[
        bool,
        typer.Option("--gpu/--cpu", help="use backend GPU acceleration when available"),
    ] = True,
    auto_download: Annotated[
        bool, typer.Option("--auto-download", help="download a missing named model first")
    ] = False,
) -> None:
    """Transcribe normalized audio to transcript.json."""
    output: Output = ctx.obj
    started = time.monotonic()
    path = ws.resolve_workspace(workspace)
    manifest = ws.read_manifest(path)

    audio = ws.require_artifact(
        path, manifest, Stage.EXTRACT_AUDIO, fix="openbbq extract-audio"
    )
    asr = get_backend(backend)
    name = model or asr.default_model()
    if name is None:
        raise OpenBBQError("model_missing", fix="openbbq models pull large-v3")
    if auto_download and not asr.has_model(name):
        asr.pull(name)
    if not asr.has_model(name):
        raise OpenBBQError(
            "model_missing", model=name, fix=f"openbbq models pull {name}"
        )
    if not asr.is_available():
        raise OpenBBQError(
            "missing_dependency", dep=asr.name, fix=asr.install_hint
        )

    # Glossary biasing: canonical term sources go in as `bias` (backend-agnostic);
    # the prose `context` rides the initial_prompt alongside any explicit --prompt.
    gloss = glossarylib.load_optional(glossary or manifest.glossary)
    bias = (
        glossarylib.bias_terms(gloss)
        if gloss is not None and Capability.BIASING in asr.capabilities
        else None
    ) or None
    prompt_text = (
        " ".join(p for p in (prompt, gloss.context if gloss else None) if p) or None
    )

    duration = media.wav_duration(audio)
    total = max(1, int(duration))
    ws.record_stage(
        path,
        manifest,
        Stage.TRANSCRIBE,
        StageState(
            status=StageStatus.RUNNING,
            updated_at=datetime.now(timezone.utc),
            progress=Progress(done=0, total=total),
        ),
    )

    last_write = time.monotonic()

    def heartbeat(done: int, total: int) -> None:
        nonlocal last_write
        now = time.monotonic()
        if now - last_write < 1.0:
            return
        ws.record_stage(
            path,
            manifest,
            Stage.TRANSCRIBE,
            StageState(
                status=StageStatus.RUNNING,
                updated_at=datetime.now(timezone.utc),
                progress=Progress(done=min(done, total), total=total),
            ),
        )
        last_write = now

    try:
        if output.json_mode:
            result = asr.transcribe(
                audio,
                model=name,
                language=language,
                bias=bias,
                initial_prompt=prompt_text,
                use_gpu=use_gpu,
                on_progress=heartbeat,
            )
        else:
            with RichProgress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed:.0f}/{task.total:.0f}s"),
                TimeElapsedColumn(),
            ) as bar:
                task = bar.add_task("transcribing", total=total)

                def cb(done: int, total: int) -> None:
                    bar.update(task, completed=min(done, total))
                    heartbeat(done, total)

                result = asr.transcribe(
                    audio,
                    model=name,
                    language=language,
                    bias=bias,
                    initial_prompt=prompt_text,
                    use_gpu=use_gpu,
                    on_progress=cb,
                )
        transcript = Transcript(
            language=result.language,
            duration=duration,
            asr=ASRInfo(
                backend=asr.name,
                model=name,
                created_at=datetime.now(timezone.utc),
            ),
            segments=result.segments,
        )
        ws.write_text_atomic(
            path / TRANSCRIPT_REL,
            transcript.model_dump_json(indent=2, exclude_none=True),
        )
        ws.record_stage(
            path,
            manifest,
            Stage.TRANSCRIBE,
            StageState(
                status=StageStatus.DONE,
                artifact=TRANSCRIPT_REL,
                updated_at=datetime.now(timezone.utc),
            ),
        )
    except BaseException as e:
        ws.record_stage(
            path,
            manifest,
            Stage.TRANSCRIBE,
            StageState(
                status=StageStatus.FAILED,
                updated_at=datetime.now(timezone.utc),
                error="interrupted" if isinstance(e, KeyboardInterrupt) else str(e),
            ),
        )
        raise

    output.emit(
        TranscribeResult(
            artifact=TRANSCRIPT_REL,
            segments=len(result.segments),
            language=result.language,
            backend=asr.name,
            model=name,
            duration_s=duration,
            elapsed_s=round(time.monotonic() - started, 2),
            next="openbbq segment",
        )
    )

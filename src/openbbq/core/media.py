"""ffmpeg / ffprobe primitives. Deterministic media ops over plain paths — no
manifest or workspace knowledge.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from openbbq.errors import OpenBBQError


@dataclass(frozen=True)
class BurnProgress:
    done: int  # milliseconds of media time processed
    total: int | None  # milliseconds, if ffprobe could determine duration


@dataclass(frozen=True)
class BurnOutcome:
    duration_s: float | None
    ffmpeg: str


BurnProgressCallback = Callable[[BurnProgress], None]

_HOMEBREW_FFMPEG_FULL = (
    Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"),
    Path("/usr/local/opt/ffmpeg-full/bin/ffmpeg"),
)
_TIME_RE = re.compile(r"^(?P<h>\d+):(?P<m>\d{2}):(?P<s>\d{2})(?:\.(?P<frac>\d+))?$")


def _require(tool: str) -> None:
    if shutil.which(tool) is None:
        raise OpenBBQError(
            "missing_dependency",
            dep=tool,
            fix=f"install {tool} (e.g. brew install {tool})",
        )


def _last_line(text: str, fallback: str) -> str:
    return (text.strip().splitlines() or [fallback])[-1]


def _resolve_executable(tool: str | Path) -> Path | None:
    path = Path(tool).expanduser()
    if path.parent != Path("."):
        return path if path.exists() else None
    found = shutil.which(str(tool))
    return Path(found) if found else None


def _has_ass_filter(ffmpeg: Path) -> bool:
    proc = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "ass":
            return True
    return False


def ass_capable_ffmpeg(explicit: str | None = None) -> Path:
    """Return an ffmpeg executable with the ASS subtitle filter available."""
    if explicit is not None:
        candidate = _resolve_executable(explicit)
        if candidate is None:
            raise OpenBBQError(
                "missing_dependency",
                dep=explicit,
                fix="check --ffmpeg, or install an ffmpeg build with libass",
            )
        if _has_ass_filter(candidate):
            return candidate
        raise OpenBBQError(
            "missing_dependency",
            dep="ffmpeg with libass",
            ffmpeg=str(candidate),
            fix="install an ffmpeg build with libass, or pass --ffmpeg to one",
        )

    candidates: list[Path] = []
    path_ffmpeg = shutil.which("ffmpeg")
    if path_ffmpeg is not None:
        candidates.append(Path(path_ffmpeg))
    candidates.extend(p for p in _HOMEBREW_FFMPEG_FULL if p.exists())

    saw_ffmpeg = False
    for candidate in candidates:
        saw_ffmpeg = True
        if _has_ass_filter(candidate):
            return candidate

    if saw_ffmpeg:
        raise OpenBBQError(
            "missing_dependency",
            dep="ffmpeg with libass",
            fix=(
                "install an ffmpeg build with libass (e.g. ffmpeg-full), "
                "or pass --ffmpeg"
            ),
        )
    raise OpenBBQError(
        "missing_dependency",
        dep="ffmpeg",
        fix="install ffmpeg, preferably a build with libass subtitle support",
    )


def _matching_ffprobe(ffmpeg: Path) -> str:
    sibling = ffmpeg.with_name("ffprobe")
    if sibling.exists():
        return str(sibling)
    return shutil.which("ffprobe") or "ffprobe"


def media_duration(path: Path, *, ffmpeg: Path | None = None) -> float | None:
    """Container duration in seconds via ffprobe; None means progress is unknown."""
    ffprobe = _matching_ffprobe(ffmpeg) if ffmpeg is not None else "ffprobe"
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        duration = float(proc.stdout.strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def _escape_filter_filename(path: Path) -> str:
    text = str(path)
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\\'")
    text = text.replace(":", "\\:")
    text = text.replace(",", "\\,")
    text = text.replace("[", "\\[")
    text = text.replace("]", "\\]")
    text = text.replace(";", "\\;")
    return f"filename='{text}'"


def _parse_progress_time(line: str, duration_s: float | None) -> int | None:
    key, sep, value = line.partition("=")
    if not sep:
        return None
    if key in {"out_time_us", "out_time_ms"}:
        try:
            seconds = int(value) / 1_000_000
        except ValueError:
            return None
    elif key == "out_time":
        match = _TIME_RE.match(value)
        if match is None:
            return None
        seconds = (
            int(match.group("h")) * 3600
            + int(match.group("m")) * 60
            + int(match.group("s"))
        )
        frac = match.group("frac")
        if frac:
            seconds += int(frac) / (10 ** len(frac))
    else:
        return None
    if duration_s is not None:
        seconds = min(seconds, duration_s)
    return max(0, int(seconds * 1000))


def extract_audio(src: Path, dst: Path) -> None:
    """Transcode src to 16 kHz mono PCM-s16 WAV at dst (what ASR wants).

    Deterministic + idempotent: re-running yields the same normalized wav.
    """
    _require("ffmpeg")
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(dst),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise OpenBBQError(
            "ffmpeg_failed", detail=_last_line(proc.stderr, "ffmpeg failed")
        )


def burn_subtitles(
    src: Path,
    subtitle: Path,
    dst: Path,
    *,
    ffmpeg: str | None = None,
    on_progress: BurnProgressCallback | None = None,
) -> BurnOutcome:
    """Hard-burn an ASS subtitle file into a broadly playable MP4."""
    if subtitle.suffix.lower() != ".ass":
        raise OpenBBQError(
            "unsupported_subtitle_format",
            format=subtitle.suffix.lower() or "(none)",
            fix="export ASS first: openbbq export --format ass",
        )
    exe = ass_capable_ffmpeg(ffmpeg)
    duration = media_duration(src, ffmpeg=exe)
    total = int(duration * 1000) if duration is not None else None
    dst.parent.mkdir(parents=True, exist_ok=True)
    if on_progress is not None:
        on_progress(BurnProgress(done=0, total=total))
    proc = subprocess.Popen(
        [
            str(exe),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vf",
            f"ass={_escape_filter_filename(subtitle)}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            str(dst),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        done = _parse_progress_time(line.strip(), duration)
        if done is not None and on_progress is not None:
            on_progress(BurnProgress(done=done, total=total))
    stderr = proc.stderr.read() if proc.stderr is not None else ""
    code = proc.wait()
    if code != 0:
        dst.unlink(missing_ok=True)
        raise OpenBBQError(
            "ffmpeg_failed", detail=_last_line(stderr, "ffmpeg burn failed")
        )
    if on_progress is not None and total is not None:
        on_progress(BurnProgress(done=total, total=total))
    return BurnOutcome(duration_s=duration, ffmpeg=str(exe))


def wav_duration(path: Path) -> float:
    """WAV duration in seconds, using the file header only."""
    try:
        with wave.open(str(path), "rb") as w:
            return round(w.getnframes() / float(w.getframerate()), 3)
    except (OSError, wave.Error) as e:
        raise OpenBBQError(
            "invalid_audio", path=str(path), fix="openbbq extract-audio"
        ) from e

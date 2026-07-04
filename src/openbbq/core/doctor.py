"""Environment probes for `openbbq doctor` (DESIGN §10.1).

Domain layer: runs read-only, idempotent checks and returns plain facts. No
typer, no Rich, no JSON — the command's Result shapes those. ASR-specific facts
(availability, accelerator, model cache) come from each backend, so doctor stays
backend-agnostic and a new backend reports itself.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .asr import ASRBackend, all_backends

_HOMEBREW_FFMPEG_FULL = (
    Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"),
    Path("/usr/local/opt/ffmpeg-full/bin/ffmpeg"),
)
_REQUIRED_SUBTITLE_FILTERS = frozenset({"ass", "subtitles"})


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str  # version, path, or why it's missing
    fix: str | None = None  # remediation hint when not ok


def _python() -> Check:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 12)
    return Check(
        "python",
        ok,
        f"{v.major}.{v.minor}.{v.micro}",
        None if ok else "OpenBBQ needs Python >= 3.12",
    )


def _ffmpeg_filter_names(executable: str | Path) -> set[str] | None:
    try:
        proc = subprocess.run(
            [str(executable), "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    names: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            names.add(parts[1])
    return names


def _ffmpeg_candidates() -> list[Path]:
    candidates: list[Path] = []
    path = shutil.which("ffmpeg")
    if path is not None:
        candidates.append(Path(path))
    candidates.extend(p for p in _HOMEBREW_FFMPEG_FULL if p.exists())
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            unique.append(candidate)
            seen.add(resolved)
    return unique


def _ffmpeg() -> Check:
    path = shutil.which("ffmpeg")
    if path is None:
        return Check("ffmpeg", False, "not on PATH", "brew install ffmpeg")
    return Check("ffmpeg", True, path)


def _ffmpeg_subtitle_filters() -> Check:
    candidates = _ffmpeg_candidates()
    if not candidates:
        return Check(
            "ffmpeg subtitle filters",
            False,
            "no ffmpeg candidate found",
            "install ffmpeg with libass support, e.g. Homebrew ffmpeg-full",
        )
    checked: list[str] = []
    for candidate in candidates:
        names = _ffmpeg_filter_names(candidate)
        if names is None:
            checked.append(f"{candidate}: filters unavailable")
            continue
        missing = sorted(_REQUIRED_SUBTITLE_FILTERS - names)
        if not missing:
            return Check(
                "ffmpeg subtitle filters",
                True,
                f"{candidate}  (ass, subtitles)",
            )
        checked.append(f"{candidate}: missing {', '.join(missing)}")
    return Check(
        "ffmpeg subtitle filters",
        False,
        "; ".join(checked),
        "install an ffmpeg build with libass, or pass --ffmpeg to openbbq burn",
    )


def _yt_dlp() -> Check:
    path = shutil.which("yt-dlp")
    if path is None:
        return Check(
            "yt-dlp",
            False,
            "not on PATH",
            "uv tool install yt-dlp  (or pip install yt-dlp)",
        )
    return Check("yt-dlp", True, path)


def _asr_backend(backend: ASRBackend) -> list[Check]:
    """ASR facts the backend reports about itself (install / accel / model cache)."""
    if not backend.is_available():
        return [Check(backend.name, False, "not installed", backend.install_hint)]
    cached = backend.cached_models()
    return [
        Check(backend.name, True, backend.version() or "installed"),
        Check(f"{backend.name} accel", True, backend.accelerator()),
        Check(
            "models",
            bool(cached),
            ", ".join(cached) or "none cached",
            None if cached else "openbbq models pull large-v3",
        ),
    ]


def run_checks() -> list[Check]:
    """Every probe, in display order. Add a new check by appending here."""
    checks = [_python(), _ffmpeg(), _ffmpeg_subtitle_filters(), _yt_dlp()]
    for backend in all_backends():
        checks.extend(_asr_backend(backend))
    return checks

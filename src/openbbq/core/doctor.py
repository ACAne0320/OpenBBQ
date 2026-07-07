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

from . import skill as skilllib
from .asr import ASRBackend, all_backends

_HOMEBREW_FFMPEG_FULL = (
    Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"),
    Path("/usr/local/opt/ffmpeg-full/bin/ffmpeg"),
)
_REQUIRED_SUBTITLE_FILTERS = frozenset({"ass", "subtitles"})


def _dependency_hint(dep: str, *, libass: bool = False) -> str:
    if dep == "ffmpeg":
        if sys.platform == "darwin":
            package = "ffmpeg-full" if libass else "ffmpeg"
            return f"brew install {package}"
        if sys.platform.startswith("linux"):
            hint = "sudo apt install ffmpeg (package name may differ by distro)"
            if libass:
                hint += "; ensure the build includes libass subtitle filters"
            return hint
        if sys.platform == "win32":
            hint = "winget install Gyan.FFmpeg  (or choco install ffmpeg)"
            if libass:
                hint += "; ensure the build includes libass subtitle filters"
            return hint
        return "install ffmpeg with your system package manager"
    if dep == "yt-dlp":
        if sys.platform == "darwin":
            return "brew install yt-dlp  (or uv tool install yt-dlp)"
        if sys.platform.startswith("linux"):
            return (
                "sudo apt install yt-dlp (package version may differ by distro), "
                "or uv tool install yt-dlp"
            )
        if sys.platform == "win32":
            return "winget install yt-dlp.yt-dlp  (or choco install yt-dlp)"
    return f"install {dep} with your system package manager"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str  # version, path, or why it's missing
    fix: str | None = None  # remediation hint when not ok
    required: bool = True  # false means guidance that should not fail doctor


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
        return Check("ffmpeg", False, "not on PATH", _dependency_hint("ffmpeg"))
    return Check("ffmpeg", True, path)


def _ffmpeg_subtitle_filters() -> Check:
    candidates = _ffmpeg_candidates()
    if not candidates:
        return Check(
            "ffmpeg subtitle filters",
            False,
            "no ffmpeg candidate found",
            _dependency_hint("ffmpeg", libass=True),
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
        f"{_dependency_hint('ffmpeg', libass=True)}, or pass --ffmpeg to openbbq burn",
    )


def _yt_dlp() -> Check:
    path = shutil.which("yt-dlp")
    if path is None:
        return Check(
            "yt-dlp",
            False,
            "not on PATH",
            _dependency_hint("yt-dlp"),
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


def _agent_skill_at(target: Path, *, fix: str = "openbbq skill install") -> Check:
    path = skilllib.installed_skill_path(target)
    try:
        installed = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Check(
            "agent skill",
            False,
            f"missing: {path}",
            fix,
            required=False,
        )
    except OSError:
        return Check(
            "agent skill",
            False,
            f"unreadable: {path}",
            f"{fix} --force",
            required=False,
        )
    if installed not in skilllib.packaged_skill_contents().values():
        return Check(
            "agent skill",
            False,
            f"outdated: {path}",
            f"{fix} --force",
            required=False,
        )
    return Check("agent skill", True, str(path), required=False)


def _agent_skill(target: Path | None = None) -> Check:
    if target is not None:
        return _agent_skill_at(target)

    current: list[str] = []
    outdated: list[str] = []
    unreadable: list[str] = []
    missing: list[str] = []
    packaged = set(skilllib.packaged_skill_contents().values())
    for agent in skilllib.SUPPORTED_AGENTS:
        path = skilllib.installed_skill_path(skilllib.target_for_agent(agent))
        label = f"{agent.value}: {path}"
        try:
            installed = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            missing.append(label)
        except OSError:
            unreadable.append(label)
        else:
            if installed in packaged:
                current.append(label)
            else:
                outdated.append(label)

    if unreadable:
        return Check(
            "agent skill",
            False,
            "unreadable: " + ", ".join(unreadable),
            "openbbq skill install --agent all --force",
            required=False,
        )
    if outdated:
        return Check(
            "agent skill",
            False,
            "outdated: " + ", ".join(outdated),
            "openbbq skill install --agent all --force",
            required=False,
        )
    if current:
        return Check("agent skill", True, "installed: " + ", ".join(current), required=False)
    return Check(
        "agent skill",
        False,
        "missing: " + ", ".join(missing),
        "openbbq skill install",
        required=False,
    )


def run_checks() -> list[Check]:
    """Every probe, in display order. Add a new check by appending here."""
    checks = [_python(), _ffmpeg(), _ffmpeg_subtitle_filters(), _yt_dlp()]
    checks.append(_agent_skill())
    for backend in all_backends():
        checks.extend(_asr_backend(backend))
    return checks

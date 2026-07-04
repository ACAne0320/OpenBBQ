from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from openbbq.core.auth import store as auth_store
from openbbq.core.auth.sites import policy_for_url, require_policy
from openbbq.errors import OpenBBQError
from openbbq.schemas import Manifest


@dataclass(frozen=True)
class FetchResult:
    artifact: str
    title: str | None = None
    author: str | None = None
    thumbnail: str | None = None
    auth: str | None = None


@dataclass(frozen=True)
class FetchMetadata:
    title: str | None = None
    author: str | None = None


@dataclass(frozen=True)
class FetchProgress:
    phase: str
    done: int = 0
    total: int | None = None
    status: str | None = None
    format_id: str | None = None
    ext: str | None = None
    vcodec: str | None = None
    acodec: str | None = None
    format_note: str | None = None
    postprocessor: str | None = None


ProgressCallback = Callable[[FetchProgress], None]
MetadataCallback = Callable[[FetchMetadata], None]
_PROGRESS_PREFIX = "openbbq-progress\t"
_OUTPUT_PREFIX = "openbbq-output\t"
_TITLE_PREFIX = "openbbq-title\t"
_ID_PREFIX = "openbbq-id\t"
_UPLOADER_PREFIX = "openbbq-uploader\t"
_CHANNEL_PREFIX = "openbbq-channel\t"
_CREATOR_PREFIX = "openbbq-creator\t"
_PRINT_PREFIXES = (
    _OUTPUT_PREFIX,
    _TITLE_PREFIX,
    _ID_PREFIX,
    _UPLOADER_PREFIX,
    _CHANNEL_PREFIX,
    _CREATOR_PREFIX,
)
_THUMBNAIL_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}


def _yt_dlp_command() -> list[str]:
    if path := shutil.which("yt-dlp"):
        return [path]
    return [sys.executable, "-m", "yt_dlp"]


def _parse_progress_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value == "NA":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _parse_progress_line(line: str) -> FetchProgress | None:
    if not line.startswith(_PROGRESS_PREFIX):
        return None
    fields = [
        _decode_print_value(value)
        for value in line[len(_PROGRESS_PREFIX) :].rstrip("\r\n").split("\t")
    ]
    if len(fields) < 2:
        return None
    phase = fields[0]
    if phase is None:
        return None
    done = _parse_progress_int(fields[2] if len(fields) > 2 else None) or 0
    total = _parse_progress_int(fields[3] if len(fields) > 3 else None)
    if total is None:
        total = _parse_progress_int(fields[4] if len(fields) > 4 else None)
    return FetchProgress(
        phase=phase,
        status=fields[1] if len(fields) > 1 else None,
        done=done,
        total=total,
        format_id=fields[6] if len(fields) > 6 else None,
        ext=fields[7] if len(fields) > 7 else None,
        vcodec=fields[8] if len(fields) > 8 else None,
        acodec=fields[9] if len(fields) > 9 else None,
        format_note=fields[10] if len(fields) > 10 else None,
        postprocessor=fields[11] if len(fields) > 11 else None,
    )


def _decode_print_value(raw: str) -> str | None:
    value = raw.strip()
    if not value or value == "NA":
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        decoded = value
    if decoded is None:
        return None
    return str(decoded)


def _extract_print_value(stdout: str, prefix: str) -> str | None:
    value: str | None = None
    for line in stdout.splitlines():
        if line.startswith(prefix):
            value = _decode_print_value(line[len(prefix) :])
    return value


def _extract_first_print_value(stdout: str, prefixes: tuple[str, ...]) -> str | None:
    for prefix in prefixes:
        value = _extract_print_value(stdout, prefix)
        if value is not None:
            return value
    return None


def _parse_metadata_line(line: str) -> FetchMetadata | None:
    if line.startswith(_TITLE_PREFIX):
        title = _decode_print_value(line[len(_TITLE_PREFIX) :])
        return FetchMetadata(title=title) if title is not None else None
    for prefix in (_UPLOADER_PREFIX, _CHANNEL_PREFIX, _CREATOR_PREFIX):
        if line.startswith(prefix):
            author = _decode_print_value(line[len(prefix) :])
            return FetchMetadata(author=author) if author is not None else None
    return None


def _run_yt_dlp(
    args: list[str],
    *,
    on_progress: ProgressCallback | None = None,
    on_metadata: MetadataCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.Popen(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output: list[str] = []
    if proc.stdout is not None:
        for line in proc.stdout:
            output.append(line)
            progress = _parse_progress_line(line)
            if progress is not None and on_progress is not None:
                on_progress(progress)
            metadata = _parse_metadata_line(line)
            if metadata is not None and on_metadata is not None:
                on_metadata(metadata)
    return subprocess.CompletedProcess(args, proc.wait(), stdout="".join(output))


def _relative_artifact(ws: Path, output_path: Path) -> str:
    try:
        return output_path.resolve().relative_to(ws.resolve()).as_posix()
    except ValueError:
        return str(output_path)


def _extract_output_path(stdout: str, ws: Path) -> Path | None:
    printed = _extract_print_value(stdout, _OUTPUT_PREFIX)
    if printed is not None:
        path = Path(printed)
        if not path.is_absolute():
            path = ws / path
        if path.exists():
            return path

    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if not candidate or candidate.startswith((_PROGRESS_PREFIX, *_PRINT_PREFIXES)):
            continue
        path = Path(candidate)
        if not path.is_absolute():
            path = ws / path
        if path.exists():
            return path
    return None


def _find_thumbnail(media_dir: Path, output_path: Path, video_id: str | None) -> Path | None:
    stems = [stem for stem in (video_id, output_path.stem) if stem]
    for stem in dict.fromkeys(stems):
        candidates = [
            path
            for path in media_dir.glob(f"{stem}.*")
            if path != output_path and path.suffix.lower() in _THUMBNAIL_EXTS
        ]
        if candidates:
            return max(candidates, key=lambda path: path.stat().st_mtime)
    return None


def auto_auth_site(url: str) -> str | None:
    policy = policy_for_url(url)
    if policy is None:
        return None
    return policy.key if auth_store.status(policy.key).configured else None


def fetch_media(
    ws: Path,
    manifest: Manifest,
    *,
    auth_site: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_metadata: MetadataCallback | None = None,
) -> FetchResult:
    if manifest.source.type != "url":
        raise OpenBBQError("fetch_not_needed", source_type=manifest.source.type)

    media_dir = ws / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    output_template = media_dir / "%(title)s.%(ext)s"
    base_cmd = _yt_dlp_command()
    cmd = [
        *base_cmd,
        "--no-playlist",
        "--no-simulate",
        "--continue",
        "--quiet",
        "--no-warnings",
        "--write-thumbnail",
        "--newline",
        "--progress",
        "--progress-template",
        f"download:{_PROGRESS_PREFIX}download\t%(progress.status|)j\t"
        "%(progress.downloaded_bytes|NA)s\t%(progress.total_bytes|NA)s\t"
        "%(progress.total_bytes_estimate|NA)s\t%(progress.ctx_id|)j\t"
        "%(info.format_id|)j\t%(info.ext|)j\t%(info.vcodec|)j\t"
        "%(info.acodec|)j\t%(info.format_note|)j\tNA",
        "--progress-template",
        f"postprocess:{_PROGRESS_PREFIX}postprocess\t%(progress.status|)j\t"
        "NA\tNA\tNA\tNA\tNA\tNA\tNA\tNA\tNA\t%(progress.postprocessor|)j",
        "--print",
        f"before_dl:{_TITLE_PREFIX}%(title)j",
        "--print",
        f"before_dl:{_UPLOADER_PREFIX}%(uploader)j",
        "--print",
        f"before_dl:{_CHANNEL_PREFIX}%(channel)j",
        "--print",
        f"before_dl:{_CREATOR_PREFIX}%(creator)j",
        "--print",
        f"after_move:{_OUTPUT_PREFIX}%(filepath)j",
        "--print",
        f"after_move:{_TITLE_PREFIX}%(title)j",
        "--print",
        f"after_move:{_ID_PREFIX}%(id)j",
        "-o",
        str(output_template),
        manifest.source.ref,
    ]

    cookie_path: Path | None = None
    if auth_site is not None:
        policy = require_policy(auth_site)
        cookie_path = auth_store.export_netscape_temp(policy.key)
        cmd = [*base_cmd, "--cookies", str(cookie_path), *cmd[len(base_cmd) :]]

    try:
        proc = _run_yt_dlp(cmd, on_progress=on_progress, on_metadata=on_metadata)
    finally:
        if cookie_path is not None:
            cookie_path.unlink(missing_ok=True)

    if proc.returncode != 0:
        output = proc.stdout.strip()
        if "Sign in to confirm" in output or "Use --cookies-from-browser" in output:
            raise OpenBBQError(
                "auth_required",
                site=auth_site or "youtube",
                fix="openbbq auth browser-login youtube",
            )
        if auth_site is not None and "HTTP Error 403" in output:
            raise OpenBBQError(
                "authenticated_download_forbidden",
                site=auth_site,
                fix="retry without --auth for public videos; PO-token provider support is out of phase 1",
            )
        raise OpenBBQError(
            "fetch_failed",
            detail=output[-1200:] if output else f"yt-dlp exited {proc.returncode}",
            fix="retry the URL with yt-dlp directly to inspect the upstream error",
        )

    output_path = _extract_output_path(proc.stdout, ws)
    if output_path is None:
        raise OpenBBQError(
            "fetch_no_output",
            fix="retry with yt-dlp directly; no output file was reported",
        )
    title = _extract_print_value(proc.stdout, _TITLE_PREFIX)
    author = _extract_first_print_value(
        proc.stdout, (_UPLOADER_PREFIX, _CHANNEL_PREFIX, _CREATOR_PREFIX)
    )
    video_id = _extract_print_value(proc.stdout, _ID_PREFIX)
    thumbnail_path = _find_thumbnail(media_dir, output_path, video_id)
    thumbnail = (
        _relative_artifact(ws, thumbnail_path) if thumbnail_path is not None else None
    )
    return FetchResult(
        artifact=_relative_artifact(ws, output_path),
        title=title,
        author=author,
        thumbnail=thumbnail,
        auth=auth_site,
    )

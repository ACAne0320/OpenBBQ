"""Generic model-cache plumbing shared by ASR backends: where cached model
files live, and a resumable HTTP download. Backend-specific catalogs, file
naming, and download sources live in the backend itself (see
``core/asr/whispercpp.py``) — this module knows nothing about whisper.cpp.
"""

from __future__ import annotations

import os
import urllib.request
from collections.abc import Callable
from pathlib import Path

_SIZE_TOLERANCE = 0.10
_CHUNK_SIZE = 1024 * 1024


class DownloadSizeMismatch(OSError):
    def __init__(self, *, actual_bytes: int, expected_size_mb: float) -> None:
        expected_bytes = int(expected_size_mb * 1024 * 1024)
        super().__init__(
            f"downloaded {actual_bytes} bytes; expected about "
            f"{expected_bytes} bytes ({expected_size_mb:.1f} MB)"
        )
        self.actual_bytes = actual_bytes
        self.expected_size_mb = expected_size_mb
        self.expected_bytes = expected_bytes


def cache_dir(provider: str) -> Path:
    """Per-provider model cache: ``$OPENBBQ_HOME/models/<provider>`` (default ~/.openbbq)."""
    home = Path(os.environ.get("OPENBBQ_HOME", "~/.openbbq")).expanduser()
    return home / "models" / provider


def _response_status(response: object) -> int:
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        return int(getcode())
    return 200


def _header(response: object, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    get = getattr(headers, "get", None)
    if not callable(get):
        return None
    value = get(name)
    return str(value) if value is not None else None


def _content_length(response: object) -> int | None:
    value = _header(response, "Content-Length")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _content_range_total(response: object) -> int | None:
    value = _header(response, "Content-Range")
    if value is None or "/" not in value:
        return None
    total = value.rsplit("/", 1)[1].strip()
    if not total or total == "*":
        return None
    try:
        return int(total)
    except ValueError:
        return None


def _total_bytes(response: object, resume_from: int) -> int:
    ranged_total = _content_range_total(response)
    if ranged_total is not None:
        return ranged_total
    length = _content_length(response)
    if length is None:
        return 0
    return resume_from + length if resume_from else length


def _request(url: str, resume_from: int) -> str | urllib.request.Request:
    if resume_from <= 0:
        return url
    return urllib.request.Request(url, headers={"Range": f"bytes={resume_from}-"})


def _validate_size(path: Path, expected_size_mb: float) -> None:
    actual = path.stat().st_size
    expected = expected_size_mb * 1024 * 1024
    lower = expected * (1 - _SIZE_TOLERANCE)
    upper = expected * (1 + _SIZE_TOLERANCE)
    if lower <= actual <= upper:
        return
    path.unlink(missing_ok=True)
    raise DownloadSizeMismatch(actual_bytes=actual, expected_size_mb=expected_size_mb)


def download(
    url: str,
    dst: Path,
    on_progress: Callable[[int, int], None] | None = None,
    *,
    expected_size_mb: float | None = None,
) -> None:
    """Stream ``url`` to ``dst`` atomically (tmp + os.replace), reporting bytes.

    A partial ``.tmp`` file is retained on I/O failure and resumed with HTTP
    Range on the next call. If the server ignores Range and returns 200, the tmp
    file is truncated and the download starts from byte 0.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    resume_from = tmp.stat().st_size if tmp.exists() else 0

    with urllib.request.urlopen(_request(url, resume_from), timeout=30) as response:
        if resume_from > 0 and _response_status(response) != 206:
            resume_from = 0
        total = _total_bytes(response, resume_from)
        done = resume_from
        mode = "ab" if resume_from > 0 else "wb"
        with tmp.open(mode) as f:
            if done and on_progress is not None:
                on_progress(done, total)
            while chunk := response.read(_CHUNK_SIZE):
                f.write(chunk)
                done += len(chunk)
                if on_progress is not None:
                    on_progress(done, total)

    try:
        if expected_size_mb is not None:
            _validate_size(tmp, expected_size_mb)
    except DownloadSizeMismatch:
        dst.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, dst)

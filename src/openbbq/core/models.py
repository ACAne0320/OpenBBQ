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


def cache_dir(provider: str) -> Path:
    """Per-provider model cache: ``$OPENBBQ_HOME/models/<provider>`` (default ~/.openbbq)."""
    home = Path(os.environ.get("OPENBBQ_HOME", "~/.openbbq")).expanduser()
    return home / "models" / provider


def download(
    url: str, dst: Path, on_progress: Callable[[int, int], None] | None = None
) -> None:
    """Stream ``url`` to ``dst`` atomically (tmp + os.replace), reporting (done, total) bytes.

    Raises ``OSError`` on failure (the caller maps it to a domain error) and
    leaves no partial file behind.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    try:
        with urllib.request.urlopen(url, timeout=30) as response, tmp.open("wb") as f:
            total = int(response.headers.get("Content-Length", 0))
            done = 0
            while chunk := response.read(1024 * 1024):
                f.write(chunk)
                done += len(chunk)
                if on_progress is not None:
                    on_progress(done, total)
        os.replace(tmp, dst)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise

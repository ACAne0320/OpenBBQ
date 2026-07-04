from __future__ import annotations

from openbbq.errors import OpenBBQError

from .base import ASRBackend, Capability, ModelInfo, TranscriptResult
from .whispercpp import WhisperCppBackend

__all__ = [
    "ASRBackend",
    "Capability",
    "ModelInfo",
    "TranscriptResult",
    "get_backend",
    "all_backends",
]


def get_backend(name: str = "auto") -> ASRBackend:
    if name in {"auto", "whisper.cpp", "whispercpp"}:
        return WhisperCppBackend()
    raise OpenBBQError("backend_unavailable", backend=name, fix="use --backend auto")


def all_backends() -> list[ASRBackend]:
    """Every registered backend — for catalog/health surfaces (models, doctor)
    that span backends rather than selecting one.
    """
    return [WhisperCppBackend()]

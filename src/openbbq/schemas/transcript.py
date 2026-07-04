from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from .common import OpenBBQModel, Seconds


class Word(OpenBBQModel):
    word: str
    start: Seconds
    end: Seconds
    prob: float | None = None  # not all backends emit per-word probability


class Segment(OpenBBQModel):
    id: int  # 0-based (whisper convention)
    start: Seconds
    end: Seconds
    text: str
    words: list[Word] | None = None  # None when backend has no word timestamps
    speaker: str | None = None  # present only when diarization ran


class ASRInfo(OpenBBQModel):
    backend: str
    model: str
    created_at: datetime


class Transcript(OpenBBQModel):
    schema_: Annotated[Literal["openbbq/transcript@1"], Field(alias="schema")] = (
        "openbbq/transcript@1"
    )
    language: str  # whisper language code, e.g. "en" / "zh"
    duration: Seconds
    asr: ASRInfo
    segments: list[Segment]

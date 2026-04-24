from __future__ import annotations

from pydantic import Field

from openbbq.domain.base import OpenBBQModel


class SegmentationParameters(OpenBBQModel):
    max_duration_seconds: float = 6.0
    min_duration_seconds: float = 0.8
    max_lines: int = Field(default=2, ge=1)
    max_chars_per_line: int = Field(default=40, ge=1)
    max_chars_per_second: float = Field(default=20.0, gt=0)
    pause_threshold_ms: int = Field(default=500, ge=0)
    prefer_sentence_boundaries: bool = True

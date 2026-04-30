from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from openbbq.domain.base import OpenBBQModel


class SegmentationParameters(OpenBBQModel):
    profile: str = "default"
    language: str | None = None
    max_duration_seconds: float = 6.0
    min_duration_seconds: float = 0.8
    max_lines: int = Field(default=2, ge=1)
    max_chars_per_line: int = Field(default=40, ge=1)
    max_chars_total: int | None = Field(default=None, ge=1)
    pause_threshold_ms: int = Field(default=500, ge=0)
    prefer_sentence_boundaries: bool = True
    prefer_clause_boundaries: bool = False
    merge_short_segments: bool = False
    protect_terms: bool = True
    glossary_rules: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("profile")
    @classmethod
    def nonempty_profile(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value.strip()

    @field_validator("language")
    @classmethod
    def nonempty_language(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value.strip()

    @model_validator(mode="after")
    def valid_duration_window(self) -> "SegmentationParameters":
        if self.max_duration_seconds <= 0:
            raise ValueError("max_duration_seconds must be greater than 0")
        if self.min_duration_seconds < 0:
            raise ValueError("min_duration_seconds must be greater than or equal to 0")
        if self.min_duration_seconds > self.max_duration_seconds:
            raise ValueError("min_duration_seconds cannot exceed max_duration_seconds")
        return self

from __future__ import annotations

from pydantic import field_validator

from openbbq.domain.base import OpenBBQModel


class TranslationParameters(OpenBBQModel):
    source_lang: str
    target_lang: str
    model: str | None = None
    temperature: float = 0
    max_segments_per_request: int = 20
    max_concurrency: int = 1
    completion_retry_rounds: int = 2

    @field_validator("source_lang", "target_lang")
    @classmethod
    def nonempty_language(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("language must be non-empty")
        return value

    @field_validator("max_segments_per_request", "max_concurrency")
    @classmethod
    def positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be positive")
        return value

    @field_validator("completion_retry_rounds")
    @classmethod
    def non_negative_int(cls, value: int) -> int:
        if value < 0:
            raise ValueError("value must be non-negative")
        return value

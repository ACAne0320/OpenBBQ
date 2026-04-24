from __future__ import annotations

from pydantic import field_validator

from openbbq.domain.base import OpenBBQModel


class TranslationParameters(OpenBBQModel):
    source_lang: str
    target_lang: str
    model: str | None = None
    temperature: float = 0

    @field_validator("source_lang", "target_lang")
    @classmethod
    def nonempty_language(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("language must be non-empty")
        return value

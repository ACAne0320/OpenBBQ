from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict


class OpenBBQModel(BaseModel):
    """Base for every schema model.

    - ``extra="forbid"``: unknown fields are a hard error (strict contract; we
      evolve via the schema version, not by silently accepting new keys).
    - ``populate_by_name`` + ``serialize_by_alias``: aliased fields (e.g.
      ``schema``) accept both name and alias on input, and always dump under the
      contract alias — so callers never have to remember ``by_alias=True``.
    """

    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, serialize_by_alias=True
    )


# Seconds, quantized to millisecond precision on write, then flow through unchanged.
Seconds = Annotated[float, AfterValidator(lambda x: round(x, 3))]


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Stage(StrEnum):
    """Single source of truth for which stages the pipeline has."""

    FETCH = "fetch"
    EXTRACT_AUDIO = "extract_audio"
    TRANSCRIBE = "transcribe"
    SEGMENT = "segment"
    TRANSLATE = "translate"
    REVIEW = "review"
    EXPORT = "export"
    BURN = "burn"

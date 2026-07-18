from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import OpenBBQModel, Seconds


class QaFrame(OpenBBQModel):
    path: str
    cue_id: int
    at: Seconds
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    reasons: list[str] = Field(default_factory=list)


class QaVisualIssueCode(StrEnum):
    CONTENT_ERROR = "content_error"
    SUBTITLE_OVERLAP = "subtitle_overlap"
    LOWER_THIRD_CONFLICT = "lower_third_conflict"
    UNSAFE_MARGIN = "unsafe_margin"
    TEXT_CLIPPED = "text_clipped"
    ILLEGIBLE_TEXT = "illegible_text"
    LINE_BREAK_ERROR = "line_break_error"
    OTHER = "other"


class QaVisualIssue(OpenBBQModel):
    code: QaVisualIssueCode
    cue_ids: list[int] = Field(default_factory=list)


class QaReport(OpenBBQModel):
    schema_: Annotated[Literal["openbbq/qa@1", "openbbq/qa@2"], Field(alias="schema")] = (
        "openbbq/qa@2"
    )
    artifact: str
    artifact_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    artifact_bytes: Annotated[int, Field(gt=0)]
    duration_s: Annotated[float, Field(gt=0)]
    frames: Annotated[list[QaFrame], Field(min_length=1)]
    created_at: datetime
    visual_status: Literal["not_performed", "pass", "fail"] = "not_performed"
    visual_reason: str | None = None
    visual_attested_at: datetime | None = None
    visual_issues: list[QaVisualIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_visual_attestation(self) -> QaReport:
        if self.visual_status == "not_performed":
            if (
                self.visual_reason is not None
                or self.visual_attested_at is not None
                or self.visual_issues
            ):
                raise ValueError(
                    "visual fields must be absent when inspection was not performed"
                )
            return self
        self.visual_reason = (self.visual_reason or "").strip()
        if not self.visual_reason or self.visual_attested_at is None:
            raise ValueError(
                "visual pass/fail requires a reason and attestation timestamp"
            )
        if self.visual_status == "pass" and self.visual_issues:
            raise ValueError("visual pass cannot contain failure issues")
        if (
            self.visual_status == "fail"
            and self.schema_ == "openbbq/qa@2"
            and not self.visual_issues
        ):
            raise ValueError("visual failure requires at least one structured issue")
        return self

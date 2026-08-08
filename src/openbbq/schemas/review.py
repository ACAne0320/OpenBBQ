from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import OpenBBQModel


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    FLAGGED = "flagged"


class Dismissal(OpenBBQModel):
    """A reviewer-dismissed issue kind on one cue.

    Persisted per cue so a deliberate "ignore" survives reloads; any content
    edit to the cue clears the list (the ignore was about the old content).
    """

    kind: str = Field(min_length=1)
    dismissed_at: datetime


class ReviewItem(OpenBBQModel):
    id: int = Field(gt=0)
    status: ReviewStatus = ReviewStatus.UNREVIEWED
    reviewed_content_hash: str | None = None
    note: str | None = None
    updated_at: datetime | None = None
    dismissals: list[Dismissal] = []

    @model_validator(mode="after")
    def validate_reviewed_hash(self) -> ReviewItem:
        if self.reviewed_content_hash is not None:
            prefix = "sha256:"
            digest = self.reviewed_content_hash.removeprefix(prefix)
            if not self.reviewed_content_hash.startswith(prefix) or len(digest) != 64:
                raise ValueError("reviewed_content_hash must be a sha256 digest")
            if any(character not in "0123456789abcdef" for character in digest):
                raise ValueError("reviewed_content_hash must be lowercase hexadecimal")
        if self.status is ReviewStatus.REVIEWED and self.reviewed_content_hash is None:
            raise ValueError("reviewed items require reviewed_content_hash")
        return self


class Review(OpenBBQModel):
    schema_: Annotated[Literal["openbbq/review@1"], Field(alias="schema")] = (
        "openbbq/review@1"
    )
    source_lang: str = Field(min_length=1)
    target_lang: str | None = None
    revision: int = Field(default=0, ge=0)
    next_cue_id: int = Field(gt=0)
    recent_op_ids: list[str] = Field(default_factory=list)
    items: list[ReviewItem]

    @model_validator(mode="after")
    def validate_identity_contract(self) -> Review:
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("review item ids must be unique")
        if ids and self.next_cue_id <= max(ids):
            raise ValueError("next_cue_id must be greater than every review item id")
        if self.target_lang is not None and not self.target_lang.strip():
            raise ValueError("target_lang cannot be blank")
        if any(not op_id.strip() for op_id in self.recent_op_ids):
            raise ValueError("recent_op_ids cannot contain blank values")
        if len(self.recent_op_ids) != len(set(self.recent_op_ids)):
            raise ValueError("recent_op_ids must be unique")
        return self

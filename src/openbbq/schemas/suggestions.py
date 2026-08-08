"""Agent-produced change suggestions attached to review cues.

One ``suggestions.<lang>.json`` document per review language, stored next to
``review.<lang>.json`` (``suggestions.source.json`` for the source review).
Suggestions are resolved by the human reviewer — accepting applies the patch
through the same code path as a manual edit; rejecting keeps it recoverable
via reopen.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import OpenBBQModel


class SuggestionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class SuggestionPatch(OpenBBQModel):
    """A partial cue patch. Only fields present in the input apply; at least
    one field is required so a suggestion always proposes a concrete change.
    """

    source: str | None = None
    target: str | None = None
    start: float | None = None
    end: float | None = None

    @model_validator(mode="after")
    def validate_non_empty(self) -> SuggestionPatch:
        if not self.model_fields_set:
            raise ValueError("suggestion patch requires at least one field")
        return self


class SuggestionDraft(OpenBBQModel):
    """The producer-side suggestion body: what an agent submits.  OpenBBQ
    assigns the id, content hash, pending status, and timestamps when the
    draft is archived into a suggestions document.
    """

    cue_id: int = Field(gt=0)
    kind: str = Field(default="agent_note", min_length=1)
    severity: Literal["warning", "info"] = "info"
    message: str
    patch: SuggestionPatch

    @model_validator(mode="after")
    def validate_message(self) -> SuggestionDraft:
        self.message = self.message.strip()
        if not self.message:
            raise ValueError("suggestion message must be non-blank")
        return self


class Suggestion(OpenBBQModel):
    id: str = Field(min_length=1)
    cue_id: int = Field(gt=0)
    kind: str = Field(min_length=1)  # e.g. "agent_note", "term", "timing"
    severity: Literal["warning", "info"] = "info"
    message: str
    patch: SuggestionPatch
    content_hash: str  # cue content hash at generation time (staleness hint only)
    status: SuggestionStatus = SuggestionStatus.PENDING
    created_at: datetime
    resolved_at: datetime | None = None

    @model_validator(mode="after")
    def validate_content_hash(self) -> Suggestion:
        prefix = "sha256:"
        digest = self.content_hash.removeprefix(prefix)
        if not self.content_hash.startswith(prefix) or len(digest) != 64:
            raise ValueError("content_hash must be a sha256 digest")
        if any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("content_hash must be lowercase hexadecimal")
        return self


class Suggestions(OpenBBQModel):
    schema_: Annotated[Literal["openbbq/suggestions@1"], Field(alias="schema")] = (
        "openbbq/suggestions@1"
    )
    source_lang: str = Field(min_length=1)
    target_lang: str | None = None
    suggestions: list[Suggestion] = []

    @model_validator(mode="after")
    def validate_identity_contract(self) -> Suggestions:
        ids = [suggestion.id for suggestion in self.suggestions]
        if len(ids) != len(set(ids)):
            raise ValueError("suggestion ids must be unique")
        if self.target_lang is not None and not self.target_lang.strip():
            raise ValueError("target_lang cannot be blank")
        return self

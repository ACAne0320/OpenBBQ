from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import OpenBBQModel


class AsrDecision(OpenBBQModel):
    action: Literal["accept", "replace", "drop", "keep_first"]
    reason: str
    find: str | None = None
    replacement: str | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> AsrDecision:
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("reason must not be blank")
        if self.action in {"accept", "drop", "keep_first"}:
            if self.find is not None or self.replacement is not None:
                raise ValueError(
                    f"{self.action} decisions cannot include find/replacement"
                )
            return self
        self.find = self.find.strip() if self.find is not None else None
        self.replacement = (self.replacement or "").strip()
        if not self.replacement:
            raise ValueError("replace decisions require a replacement")
        if self.find and self.find.casefold() == self.replacement.casefold():
            raise ValueError("replacement must differ from find")
        return self


class AsrReview(OpenBBQModel):
    schema_: Annotated[
        Literal["openbbq/asr-review@1", "openbbq/asr-review@2"],
        Field(alias="schema"),
    ] = (
        "openbbq/asr-review@2"
    )
    transcript_hash: str
    max_prob: float
    decisions: dict[str, AsrDecision] = Field(default_factory=dict)

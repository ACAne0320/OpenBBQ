from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import OpenBBQModel

TranslationAuditFlagCode = Literal["budget_rewrite", "shortened_translation"]


class TranslationAuditDecision(OpenBBQModel):
    action: Literal["accept", "revise"]
    reason: str
    target: str | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> TranslationAuditDecision:
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("reason must not be blank")
        if self.action == "accept":
            if self.target is not None:
                raise ValueError("accept decisions cannot include target")
            return self
        self.target = (self.target or "").strip()
        if not self.target:
            raise ValueError("revise decisions require a non-blank target")
        return self


class TranslationAuditRecord(OpenBBQModel):
    content_hash: str
    context_hash: str | None = None
    action: Literal["accept", "revise"]
    reason: str


class TranslationAuditFlag(OpenBBQModel):
    content_hash: str
    codes: list[TranslationAuditFlagCode]


class TranslationAudit(OpenBBQModel):
    schema_: Annotated[
        Literal[
            "openbbq/translation-audit@1",
            "openbbq/translation-audit@2",
        ],
        Field(alias="schema"),
    ] = "openbbq/translation-audit@2"
    target_lang: str
    coverage: Literal["risks", "all"] = "risks"
    reviews: dict[int, TranslationAuditRecord] = Field(default_factory=dict)
    flags: dict[int, TranslationAuditFlag] = Field(default_factory=dict)

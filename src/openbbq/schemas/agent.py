from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from .common import OpenBBQModel
from .glossary import Term

AgentSemanticAction = Literal[
    "select_glossary",
    "review_source",
    "translate",
    "review_risks",
    "finish",
]


class AgentGlossaryUpdate(OpenBBQModel):
    source: str
    target: str | None = None
    aliases: list[str] = Field(default_factory=list)
    note: str | None = None
    keep: bool = False
    reusable: bool
    evidence: str

    @model_validator(mode="after")
    def validate_update(self) -> AgentGlossaryUpdate:
        self.source = self.source.strip()
        self.evidence = self.evidence.strip()
        if not self.source or not self.evidence:
            raise ValueError("glossary updates require source and evidence")
        self.aliases = [alias.strip() for alias in self.aliases if alias.strip()]
        if self.target is not None:
            self.target = self.target.strip() or None
        if self.note is not None:
            self.note = self.note.strip() or None
        return self

    def term(self) -> Term:
        values: dict[str, object] = {
            "source": self.source,
            "aliases": self.aliases,
        }
        # Preserve patch semantics: an omitted optional field must not erase
        # guidance learned by an earlier batch.
        for field in ("target", "note", "keep"):
            if field in self.model_fields_set:
                values[field] = getattr(self, field)
        return Term.model_validate(values)


class AgentSourceFix(OpenBBQModel):
    segment_id: int
    find: str
    replacement: str
    evidence: str

    @model_validator(mode="after")
    def validate_fix(self) -> AgentSourceFix:
        self.find = self.find.strip()
        self.replacement = self.replacement.strip()
        self.evidence = self.evidence.strip()
        if not self.find or not self.replacement or not self.evidence:
            raise ValueError("source fixes require find, replacement, and evidence")
        if self.find == self.replacement:
            raise ValueError("source fix replacement must differ from find")
        return self


class AgentCueSourceFix(OpenBBQModel):
    cue_id: int
    find: str
    replacement: str
    occurrence: int = Field(default=1, ge=1)
    evidence: str

    @model_validator(mode="after")
    def validate_fix(self) -> AgentCueSourceFix:
        self.find = self.find.strip()
        self.replacement = self.replacement.strip()
        self.evidence = self.evidence.strip()
        if not self.find or not self.replacement or not self.evidence:
            raise ValueError("source fixes require find, replacement, and evidence")
        if self.find == self.replacement:
            raise ValueError("source fix replacement must differ from find")
        return self


class AgentLease(OpenBBQModel):
    action: AgentSemanticAction
    batch_id: str
    selected_ids: list[int] = Field(default_factory=list)
    issue_ids: list[str] = Field(default_factory=list)
    source_hash: str
    worksheet_hash: str | None = None
    policy_hash: str | None = None
    payload: dict[str, Any]


class SourceReviewEvidence(OpenBBQModel):
    segment_hash: str
    batch_id: str


class TranslationEvidence(OpenBBQModel):
    cue_hash: str
    source_hash: str
    target_hash: str
    glossary_hash: str
    policy_hash: str
    batch_id: str


class RiskReviewEvidence(OpenBBQModel):
    item_hash: str
    policy_hash: str
    batch_id: str


class AgentWarning(OpenBBQModel):
    code: str
    detail: str
    retry_argv: list[str] | None = None


class AgentFinished(OpenBBQModel):
    inputs_hash: str
    subtitle: str
    video: str
    preset: Literal["fansub", "mobile"]
    glossary_published: bool


class AgentSession(OpenBBQModel):
    schema_: Annotated[Literal["openbbq/agent-session@1"], Field(alias="schema")] = (
        "openbbq/agent-session@1"
    )
    target_lang: str
    mode: Literal["balanced", "thorough"] = "balanced"
    glossary_selected: bool = False
    glossary_name: str | None = None
    glossary_disabled: bool = False
    source_reviews: dict[int, SourceReviewEvidence] = Field(default_factory=dict)
    translation_evidence: dict[int, TranslationEvidence] = Field(default_factory=dict)
    risk_reviews: dict[int, RiskReviewEvidence] = Field(default_factory=dict)
    source_fixed_cue_ids: list[int] = Field(default_factory=list)
    active_lease: AgentLease | None = None
    finish_pid: int | None = None
    finished: AgentFinished | None = None
    warnings: list[AgentWarning] = Field(default_factory=list)


class GlossaryOverlayEntry(OpenBBQModel):
    term: Term
    evidence: list[str] = Field(default_factory=list)
    update_fields: list[Literal["target", "note", "keep"]] = Field(
        default_factory=list
    )


class GlossaryOverlay(OpenBBQModel):
    schema_: Annotated[
        Literal["openbbq/glossary-overlay@1"], Field(alias="schema")
    ] = "openbbq/glossary-overlay@1"
    base_name: str | None = None
    base_hash: str | None = None
    context: str | None = None
    entries: list[GlossaryOverlayEntry] = Field(default_factory=list)

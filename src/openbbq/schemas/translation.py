from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import OpenBBQModel
from .cues import Budget, SegmentParams


class GlossaryRef(OpenBBQModel):
    """A glossary term surfaced to the translating Agent (the deferred 3rd
    touchpoint): canonical ``source`` → ``target``, or ``keep`` = render source
    verbatim. Embedded in the worksheet so the draft is self-contained.
    """

    source: str
    target: str | None = None
    aliases: list[str] = []
    note: str | None = None
    keep: bool = False


class TranslationItem(OpenBBQModel):
    id: int  # matches a cues.json cue id
    source: str  # read-only copy (cues.json stays canonical; check verifies match)
    budget: Budget  # char/seconds allowance for THIS target language
    target: str | None = None  # the Agent fills this; None/blank = untranslated


class TranslationBrief(OpenBBQModel):
    """Reproducible translation policy embedded in ``translation@2``.

    Agent harnesses should not have to reconstruct translation rules from a
    Skill or prose documentation.  Keeping the brief in the worksheet makes
    every semantic batch self-contained and lets OpenBBQ hash the exact policy
    used to produce a translation.
    """

    source_lang: str
    target_lang: str
    ruleset: str
    generic_translation_rules: bool = False
    title: str | None = None
    author: str | None = None
    domain_context: str | None = None
    rules: list[str]


class Translation(OpenBBQModel):
    """Per-language translation worksheet — Agent-owned, joined with cues at
    export (DESIGN translate spec). ``params`` snapshots the target-side profile
    so budget (init) and one-line export share the same target-language caps.
    """

    schema_: Annotated[
        Literal["openbbq/translation@1", "openbbq/translation@2"],
        Field(alias="schema"),
    ] = "openbbq/translation@1"
    source_lang: str
    target_lang: str
    params: SegmentParams  # target-side snapshot for budget + one-line export
    glossary: list[GlossaryRef] = []  # includes pending note-only terms in @2
    brief: TranslationBrief | None = None
    items: list[TranslationItem]

    @model_validator(mode="after")
    def validate_versioned_brief(self) -> Translation:
        if self.schema_ == "openbbq/translation@2":
            if self.brief is None:
                raise ValueError("translation@2 requires a translation brief")
            if (
                self.brief.source_lang != self.source_lang
                or self.brief.target_lang != self.target_lang
            ):
                raise ValueError("translation brief languages must match the worksheet")
        return self

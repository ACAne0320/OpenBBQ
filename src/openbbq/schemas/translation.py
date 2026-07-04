from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .common import OpenBBQModel
from .cues import Budget, SegmentParams


class GlossaryRef(OpenBBQModel):
    """A glossary term surfaced to the translating Agent (the deferred 3rd
    touchpoint): canonical ``source`` → ``target``, or ``keep`` = render source
    verbatim. Embedded in the worksheet so the draft is self-contained.
    """

    source: str
    target: str | None = None
    note: str | None = None
    keep: bool = False


class TranslationItem(OpenBBQModel):
    id: int  # matches a cues.json cue id
    source: str  # read-only copy (cues.json stays canonical; check verifies match)
    budget: Budget  # char/seconds allowance for THIS target language
    target: str | None = None  # the Agent fills this; None/blank = untranslated


class Translation(OpenBBQModel):
    """Per-language translation worksheet — Agent-owned, joined with cues at
    export (DESIGN translate spec). ``params`` snapshots the target-side profile
    so budget (init) and one-line export share the same target-language caps.
    """

    schema_: Annotated[Literal["openbbq/translation@1"], Field(alias="schema")] = (
        "openbbq/translation@1"
    )
    source_lang: str
    target_lang: str
    params: SegmentParams  # target-side snapshot for budget + one-line export
    glossary: list[GlossaryRef] = []  # source→target map (terms with target or keep)
    items: list[TranslationItem]

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .common import OpenBBQModel


class Term(OpenBBQModel):
    """One named entity, feeding all three glossary touchpoints from one row.

    ``source`` (canonical spelling) drives ASR biasing, is the replacement target
    for correction, and is the key of the translation map. ``aliases`` are known
    mishearings corrected back to ``source``. ``target``/``keep`` express the
    three-way translation intent: a set ``target`` = canonical translation; no
    ``target`` and no ``keep`` = undecided (agent's call); ``keep`` = deliberately
    untranslated, render ``source`` verbatim (brand/proper noun).
    """

    source: str
    target: str | None = None
    aliases: list[str] = []
    note: str | None = None  # disambiguation context shown to the agent
    keep: bool = False  # do-not-translate: keep source form in the target


class Glossary(OpenBBQModel):
    schema_: Annotated[Literal["openbbq/glossary@1"], Field(alias="schema")] = (
        "openbbq/glossary@1"
    )
    name: str
    context: str | None = None  # series/topic background: agent judgement + ASR prompt + tone
    terms: list[Term] = []

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .common import OpenBBQModel, Seconds


class SegmentParams(OpenBBQModel):
    """Source-side cue-splitting constraints.

    Used both as ``cues.json``'s ``params`` and (via subclass) as the segment
    stage's manifest params.
    """

    max_cps: float
    max_chars_per_line: int  # per line, not per cue (cf. Budget.max_chars)
    max_lines: int
    min_dur: Seconds
    max_dur: Seconds
    min_gap: Seconds
    pause_threshold: Seconds = 0.3  # natural-pause split threshold


class Budget(OpenBBQModel):
    """Per-cue translation allowance. Lives on the translation worksheet (it's
    target-language-specific), not on cues — see ``schemas/translation.py``.
    """

    max_chars: int  # whole-cue budget = floor(min(cps * dur, per_line * lines))
    seconds: Seconds  # = end - start; redundant, kept self-contained for the agent


class Cue(OpenBBQModel):
    """Source-side subtitle cue. Usually the deterministic product of ``segment``;
    the agent facade may apply a validated cue-scoped ASR correction while
    synchronizing every worksheet source copy. Translation lives in a separate
    per-language worksheet joined at export, never here.
    """

    id: int  # 1-based (subtitle convention)
    start: Seconds
    end: Seconds
    source: str


class Cues(OpenBBQModel):
    schema_: Annotated[Literal["openbbq/cues@1"], Field(alias="schema")] = (
        "openbbq/cues@1"
    )
    source_lang: str
    params: SegmentParams
    cues: list[Cue]

from __future__ import annotations

from typing import Literal

from rich.console import RenderableType

from ..schemas import OpenBBQModel


class Result(OpenBBQModel):
    """Base for every command's stdout — the agent-facing output contract.

    A command produces a ``Result``; ``Output`` decides where it goes: machine
    mode emits ``payload()`` (compact JSON), human mode prints ``render()``.
    Subclasses add their own fields and implement ``render()``.
    """

    ok: Literal[True] = True
    next: str | None = None

    def payload(self) -> dict[str, object]:
        # mode="json": datetimes/enums become JSON-ready primitives; drop nulls
        # for compactness (an absent key reads as "none").
        return self.model_dump(mode="json", exclude_none=True)

    def render(self) -> RenderableType:  # str is a valid renderable; so is a Table
        raise NotImplementedError

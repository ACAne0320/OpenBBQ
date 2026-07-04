from __future__ import annotations


class OpenBBQError(Exception):
    """A structured, agent-fixable error.

    ``code`` is the machine tag; ``fix`` is a suggested remedy command; any
    extra keyword context (model, dep, ...) is surfaced in the JSON payload.
    New error kinds are new ``code`` strings, not new classes.

        raise OpenBBQError("model_missing", model="large-v3",
                           fix="openbbq models pull large-v3")
    """

    def __init__(self, code: str, *, fix: str | None = None, **context: object) -> None:
        super().__init__(code)
        self.code = code
        self.fix = fix
        self.context = context

    def payload(self) -> dict[str, object]:
        data: dict[str, object] = {"error": self.code, **self.context}
        if self.fix is not None:
            data["fix"] = self.fix
        return data

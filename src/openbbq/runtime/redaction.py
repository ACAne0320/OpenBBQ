from __future__ import annotations

from collections.abc import Iterable


def redact_values(message: str, values: Iterable[str]) -> str:
    redacted = message
    for value in values:
        if not value:
            continue
        redacted = redacted.replace(value, "[REDACTED]")
    return redacted

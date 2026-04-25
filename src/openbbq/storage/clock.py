from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

TimestampProvider = Callable[[], str]


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()

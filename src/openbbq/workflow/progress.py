from __future__ import annotations

from collections.abc import Callable
import math

from openbbq.storage.project_store import ProjectStore


class ProgressReporter:
    def __init__(
        self,
        store: ProjectStore,
        *,
        workflow_id: str,
        step_id: str,
        attempt: int,
        min_percent_delta: float = 1.0,
        redactor: Callable[[str], str] | None = None,
    ) -> None:
        self._store = store
        self._workflow_id = workflow_id
        self._step_id = step_id
        self._attempt = attempt
        self._min_percent_delta = min_percent_delta
        self._redactor = redactor
        self._last_percent: float | None = None
        self._last_phase: str | None = None
        self._last_label: str | None = None

    def report(
        self,
        *,
        phase: str,
        label: str,
        percent: float,
        current: float | None = None,
        total: float | None = None,
        unit: str | None = None,
    ) -> None:
        normalized = _clamp_percent(percent)
        redacted_phase = self._redact(phase)
        redacted_label = self._redact(label)
        if not self._should_emit(
            phase=redacted_phase,
            label=redacted_label,
            percent=normalized,
        ):
            return
        self._last_phase = redacted_phase
        self._last_label = redacted_label
        self._last_percent = normalized
        progress = {
            "phase": redacted_phase,
            "label": redacted_label,
            "percent": normalized,
        }
        if current is not None:
            progress["current"] = current
        if total is not None:
            progress["total"] = total
        if unit is not None:
            progress["unit"] = self._redact(unit)
        self._store.append_event(
            self._workflow_id,
            {
                "type": "step.progress",
                "step_id": self._step_id,
                "attempt": self._attempt,
                "message": f"{redacted_label} {normalized:.0f}%",
                "data": {"progress": progress},
            },
        )

    def _should_emit(self, *, phase: str, label: str, percent: float) -> bool:
        if self._last_percent is None:
            return True
        if percent in {0, 100} and percent != self._last_percent:
            return True
        if phase != self._last_phase or label != self._last_label:
            return True
        return abs(percent - self._last_percent) >= self._min_percent_delta

    def _redact(self, value: str) -> str:
        if self._redactor is None:
            return value
        return self._redactor(value)


def _clamp_percent(value: object) -> float:
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError):
        return 0
    if not math.isfinite(numeric):
        return 0
    return max(0, min(100, numeric))

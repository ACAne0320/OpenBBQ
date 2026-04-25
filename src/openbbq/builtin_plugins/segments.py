from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TimedWord:
    text: str
    start: float | None = None
    end: float | None = None
    confidence: float | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TimedWord:
        start = payload.get("start")
        end = payload.get("end")
        confidence = payload.get("confidence")
        return cls(
            text=str(payload.get("text", "")),
            start=float(start) if isinstance(start, (int, float)) else None,
            end=float(end) if isinstance(end, (int, float)) else None,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
        )


@dataclass(frozen=True)
class TimedSegment:
    start: float
    end: float
    text: str
    payload: dict[str, Any]
    source_text: str | None = None
    confidence: float | None = None
    words: tuple[TimedWord, ...] = ()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TimedSegment:
        confidence = payload.get("confidence")
        words = payload.get("words")
        source_text = payload.get("source_text")
        word_payloads = words if isinstance(words, list) else []
        return cls(
            start=float(payload["start"]),
            end=float(payload["end"]),
            text=str(payload.get("text", "")),
            payload=deepcopy(payload),
            source_text=str(source_text) if source_text is not None else None,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
            words=tuple(
                TimedWord.from_payload(word) for word in word_payloads if isinstance(word, dict)
            ),
        )

    def copy_payload(self) -> dict[str, Any]:
        return deepcopy(self.payload)


@dataclass(frozen=True)
class SegmentUnit:
    start: float
    end: float
    text: str
    source_segment_indexes: tuple[int, ...]


def timed_segments_from_request(
    request: dict[str, Any], *, input_name: str, error_prefix: str
) -> list[TimedSegment]:
    artifact = request.get("inputs", {}).get(input_name, {})
    if not isinstance(artifact, dict) or "content" not in artifact:
        raise ValueError(f"{error_prefix} requires {input_name} content.")
    content = artifact["content"]
    if not isinstance(content, list) or any(not isinstance(segment, dict) for segment in content):
        raise ValueError(f"{error_prefix} {input_name} content must be a list of objects.")
    for segment in content:
        if "start" not in segment or "end" not in segment:
            raise ValueError(f"{error_prefix} {input_name} segments must include start and end.")
    return [TimedSegment.from_payload(segment) for segment in content]


def timed_segments_from_any_input(
    request: dict[str, Any], *, input_names: tuple[str, ...], error_prefix: str
) -> list[TimedSegment]:
    for input_name in input_names:
        artifact = request.get("inputs", {}).get(input_name)
        if isinstance(artifact, dict) and "content" in artifact:
            return timed_segments_from_request(
                request, input_name=input_name, error_prefix=error_prefix
            )
    return timed_segments_from_request(
        request, input_name=input_names[0], error_prefix=error_prefix
    )

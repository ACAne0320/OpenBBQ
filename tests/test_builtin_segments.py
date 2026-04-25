from __future__ import annotations

import re

import pytest

from openbbq.builtin_plugins.llm import segment_chunks
from openbbq.builtin_plugins.segments import (
    SegmentUnit,
    TimedSegment,
    timed_segments_from_any_input,
    timed_segments_from_request,
)


def test_timed_segments_from_request_preserves_validation_messages() -> None:
    with pytest.raises(ValueError, match=re.escape("translation.qa requires translation content.")):
        timed_segments_from_request({}, input_name="translation", error_prefix="translation.qa")

    with pytest.raises(
        ValueError,
        match=re.escape("translation.qa translation content must be a list of objects."),
    ):
        timed_segments_from_request(
            {"inputs": {"translation": {"content": "bad"}}},
            input_name="translation",
            error_prefix="translation.qa",
        )

    with pytest.raises(
        ValueError,
        match=re.escape("translation.qa translation content must be a list of objects."),
    ):
        timed_segments_from_request(
            {"inputs": {"translation": {"content": [1]}}},
            input_name="translation",
            error_prefix="translation.qa",
        )

    with pytest.raises(
        ValueError,
        match=re.escape("translation.qa translation segments must include start and end."),
    ):
        timed_segments_from_request(
            {"inputs": {"translation": {"content": [{"start": 0.0, "text": "Hello"}]}}},
            input_name="translation",
            error_prefix="translation.qa",
        )


def test_timed_segment_normalizes_fields_and_preserves_payload_copy() -> None:
    payload = {
        "start": "0.5",
        "end": 1,
        "text": 123,
        "source_text": "source",
        "confidence": 0.75,
        "words": [
            {"start": 0.5, "end": 0.7, "text": "Hello", "confidence": 0.6},
            {"text": "loose"},
            "ignored",
        ],
    }

    segment = TimedSegment.from_payload(payload)
    payload["text"] = "mutated"
    payload["words"][0]["text"] = "changed"
    copied = segment.copy_payload()
    copied["text"] = "changed"
    copied["words"][0]["text"] = "copy-change"

    assert segment.start == 0.5
    assert segment.end == 1.0
    assert segment.text == "123"
    assert segment.source_text == "source"
    assert segment.confidence == 0.75
    assert [word.text for word in segment.words] == ["Hello", "loose"]
    assert segment.words[0].start == 0.5
    assert segment.words[0].end == 0.7
    assert segment.words[0].confidence == 0.6
    assert segment.words[1].start is None
    assert segment.copy_payload()["text"] == 123
    assert segment.copy_payload()["words"][0]["text"] == "Hello"


def test_timed_segments_from_any_input_prefers_first_present_input() -> None:
    request = {
        "inputs": {
            "transcript": {"content": [{"start": 0.0, "end": 1.0, "text": "Transcript"}]},
            "subtitle_segments": {"content": [{"start": 2.0, "end": 3.0, "text": "Subtitle"}]},
        }
    }

    segments = timed_segments_from_any_input(
        request,
        input_names=("subtitle_segments", "transcript"),
        error_prefix="translation.translate",
    )

    assert [segment.text for segment in segments] == ["Subtitle"]


def test_segment_unit_stores_source_indexes_as_tuple() -> None:
    unit = SegmentUnit(start=0.0, end=1.0, text="Hello", source_segment_indexes=(1, 2))

    assert unit.source_segment_indexes == (1, 2)


def test_segment_chunks_accepts_typed_sequences() -> None:
    segments = [
        TimedSegment.from_payload({"start": 0.0, "end": 1.0, "text": "a"}),
        TimedSegment.from_payload({"start": 1.0, "end": 2.0, "text": "b"}),
        TimedSegment.from_payload({"start": 2.0, "end": 3.0, "text": "c"}),
    ]

    chunks = segment_chunks(segments, 2, error_prefix="translation.translate")

    assert [[segment.text for segment in chunk] for chunk in chunks] == [["a", "b"], ["c"]]

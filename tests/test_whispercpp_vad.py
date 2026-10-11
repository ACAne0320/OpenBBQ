from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from openbbq.core.asr import whispercpp_vad
from openbbq.core.asr.whispercpp_vad import (
    SpeechRegion,
    _native_time_to_seconds,
    coalesce_regions,
)
from openbbq.errors import OpenBBQError


def test_native_vad_timestamps_are_centiseconds() -> None:
    assert _native_time_to_seconds(50.0) == 0.5


def test_detect_speech_uses_timestamp_safe_defaults(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class Library:
        @staticmethod
        def whisper_vad_default_context_params():
            return SimpleNamespace(use_gpu=True)

        @staticmethod
        def whisper_vad_init_from_file_with_params(_model, context_params):
            seen["use_gpu"] = context_params.use_gpu
            return object()

        @staticmethod
        def whisper_vad_default_params():
            return SimpleNamespace(
                threshold=0.0,
                min_speech_duration_ms=0,
                min_silence_duration_ms=0,
                speech_pad_ms=0,
            )

        @staticmethod
        def whisper_vad_segments_from_samples(_context, params, _pointer, _size):
            seen["params"] = params
            return object()

        @staticmethod
        def whisper_vad_segments_n_segments(_segments):
            return 1

        @staticmethod
        def whisper_vad_segments_get_segment_t0(_segments, _index):
            return 460.0

        @staticmethod
        def whisper_vad_segments_get_segment_t1(_segments, _index):
            return 660.0

        @staticmethod
        def whisper_vad_free_segments(_segments):
            return None

        @staticmethod
        def whisper_vad_free(_context):
            return None

    monkeypatch.setattr(whispercpp_vad, "_load_library", lambda: Library())

    assert whispercpp_vad.detect_speech([0.0] * 16_000, Path("vad.bin")) == [
        SpeechRegion(4.6, 6.6)
    ]
    params = cast(SimpleNamespace, seen["params"])
    assert params.threshold == 0.25
    assert params.min_speech_duration_ms == 100
    assert params.min_silence_duration_ms == 200
    assert params.speech_pad_ms == 250
    assert seen["use_gpu"] is False


def test_detect_speech_file_parses_isolated_process_result(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="[[0.5, 1.25]]\n", stderr="")

    monkeypatch.setattr(whispercpp_vad.subprocess, "run", fake_run)

    assert whispercpp_vad.detect_speech_file(Path("audio.wav"), Path("vad.bin")) == [
        SpeechRegion(0.5, 1.25)
    ]
    assert seen["command"] == [
        whispercpp_vad.sys.executable,
        "-m",
        "openbbq.core.asr.whispercpp_vad",
        "audio.wav",
        "vad.bin",
    ]


def test_detect_speech_file_surfaces_process_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        whispercpp_vad.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=7, stdout="", stderr="native VAD failed"
        ),
    )

    with pytest.raises(OpenBBQError) as raised:
        whispercpp_vad.detect_speech_file(Path("audio.wav"), Path("vad.bin"))

    assert raised.value.code == "vad_detect_failed"
    assert raised.value.context["detail"] == "native VAD failed"


def test_detect_speech_file_preserves_structured_child_error(monkeypatch) -> None:
    monkeypatch.setattr(
        whispercpp_vad.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=(
                '{"error":"vad_runtime_unsupported","detail":"missing symbols",'
                '"fix":"reinstall whispercpp"}\n'
            ),
        ),
    )

    with pytest.raises(OpenBBQError) as raised:
        whispercpp_vad.detect_speech_file(Path("audio.wav"), Path("vad.bin"))

    assert raised.value.payload() == {
        "error": "vad_runtime_unsupported",
        "detail": "missing symbols",
        "fix": "reinstall whispercpp",
    }


def test_coalesce_regions_clamps_and_merges_without_exceeding_chunk_limit() -> None:
    regions = [
        SpeechRegion(-0.5, 3.0),
        SpeechRegion(3.0, 7.0),
        SpeechRegion(7.4, 12.0),
        SpeechRegion(20.0, 22.0),
    ]

    assert coalesce_regions(regions, duration=21.0, max_chunk_s=10.0) == [
        SpeechRegion(0.0, 7.0),
        SpeechRegion(7.4, 12.0),
        SpeechRegion(20.0, 21.0),
    ]


def test_coalesce_regions_keeps_gaps_above_half_a_second() -> None:
    assert coalesce_regions(
        [SpeechRegion(2.4, 4.2), SpeechRegion(4.71, 11.59)],
        duration=15.0,
    ) == [SpeechRegion(2.4, 4.2), SpeechRegion(4.71, 11.59)]


def test_coalesce_regions_drops_empty_or_out_of_range_regions() -> None:
    regions = [
        SpeechRegion(4.0, 3.0),
        SpeechRegion(8.0, 9.0),
        SpeechRegion(11.0, 12.0),
    ]

    assert coalesce_regions(regions, duration=10.0, max_chunk_s=30.0) == [
        SpeechRegion(8.0, 9.0)
    ]

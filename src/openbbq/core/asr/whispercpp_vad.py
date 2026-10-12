from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from openbbq.errors import OpenBBQError

SAMPLE_RATE = 16_000
# Tuned against the 12-minute Tears of Steel test clip.  Keep native padding
# modest: padding is part of the returned timestamp, so using seconds of it as
# ASR context makes whisper spread the first words across preceding effects.
DEFAULT_THRESHOLD = 0.25
DEFAULT_MIN_SPEECH_DURATION_MS = 100
DEFAULT_MIN_SILENCE_DURATION_MS = 200
DEFAULT_SPEECH_PAD_MS = 250
DEFAULT_MAX_CHUNK_S = 28.0
DEFAULT_MAX_GAP_S = 0.5
_NATIVE_TIMESTAMP_SCALE = 100.0  # whisper.cpp VAD getters return centiseconds


@dataclass(frozen=True, slots=True)
class SpeechRegion:
    start: float
    end: float


class _VADContextParams(ctypes.Structure):
    _fields_ = [
        ("n_threads", ctypes.c_int),
        ("use_gpu", ctypes.c_bool),
        ("gpu_device", ctypes.c_int),
    ]


class _VADParams(ctypes.Structure):
    _fields_ = [
        ("threshold", ctypes.c_float),
        ("min_speech_duration_ms", ctypes.c_int),
        ("min_silence_duration_ms", ctypes.c_int),
        ("max_speech_duration_s", ctypes.c_float),
        ("speech_pad_ms", ctypes.c_int),
        ("samples_overlap", ctypes.c_float),
    ]


def detect_speech_file(audio: Path, model: Path) -> list[SpeechRegion]:
    """Run native VAD in an isolated process before a GPU ASR context exists."""

    command = [sys.executable, "-m", __name__, str(audio), str(model)]
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OpenBBQError("vad_detect_failed", detail=str(error)) from error
    if process.returncode != 0:
        detail = process.stderr.strip()
        try:
            payload = json.loads(detail)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("error"), str):
            context = dict(payload)
            code = str(context.pop("error"))
            fix_value = context.pop("fix", None)
            fix = str(fix_value) if fix_value is not None else None
            raise OpenBBQError(code, fix=fix, **context)
        detail = detail or f"VAD subprocess exited {process.returncode}"
        raise OpenBBQError("vad_detect_failed", detail=detail)
    try:
        values = json.loads(process.stdout)
        return [SpeechRegion(float(start), float(end)) for start, end in values]
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise OpenBBQError(
            "vad_detect_failed", detail="VAD subprocess returned invalid data"
        ) from error


def detect_speech(samples: Any, model: Path) -> list[SpeechRegion]:
    """Detect speech on the original audio timeline with whisper.cpp's VAD API.

    pywhispercpp's high-level ``vad=True`` path compresses non-speech before ASR.
    Its segment timestamps are mapped back, but its token timestamps are not.  Calling
    the standalone C API keeps detection separate so OpenBBQ can transcribe original
    audio slices and preserve the transcript's absolute word-timestamp contract.
    """

    try:
        numpy = __import__("numpy")
    except ImportError as error:
        raise OpenBBQError(
            "missing_dependency",
            dep="numpy",
            fix="pip install 'openbbq[whispercpp]'",
        ) from error

    audio = numpy.ascontiguousarray(samples, dtype=numpy.float32)
    if audio.ndim != 1:
        raise OpenBBQError("vad_audio_invalid", detail="expected mono PCM samples")
    if not audio.size:
        return []

    library = _load_library()
    context_params = library.whisper_vad_default_context_params()
    # The model is tiny and CPU avoids platform-specific VAD GPU initialization.
    context_params.use_gpu = False
    context = None
    segments = None
    with _silenced_native_stderr():
        context = library.whisper_vad_init_from_file_with_params(
            os.fsencode(model), context_params
        )
        if not context:
            raise OpenBBQError(
                "vad_model_load_failed",
                model=str(model),
                fix=f"retry download: openbbq models pull-vad {model.stem.removeprefix('ggml-')}",
            )
        try:
            params = library.whisper_vad_default_params()
            params.threshold = DEFAULT_THRESHOLD
            params.min_speech_duration_ms = DEFAULT_MIN_SPEECH_DURATION_MS
            params.min_silence_duration_ms = DEFAULT_MIN_SILENCE_DURATION_MS
            params.speech_pad_ms = DEFAULT_SPEECH_PAD_MS
            pointer = audio.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
            segments = library.whisper_vad_segments_from_samples(
                context, params, pointer, int(audio.size)
            )
            if not segments:
                raise OpenBBQError("vad_detect_failed", detail="no VAD result")
            count = library.whisper_vad_segments_n_segments(segments)
            return [
                SpeechRegion(
                    _native_time_to_seconds(
                        library.whisper_vad_segments_get_segment_t0(segments, index)
                    ),
                    _native_time_to_seconds(
                        library.whisper_vad_segments_get_segment_t1(segments, index)
                    ),
                )
                for index in range(count)
            ]
        finally:
            if segments:
                library.whisper_vad_free_segments(segments)
            library.whisper_vad_free(context)


def coalesce_regions(
    regions: Sequence[SpeechRegion],
    *,
    duration: float,
    max_chunk_s: float = DEFAULT_MAX_CHUNK_S,
    max_gap_s: float = DEFAULT_MAX_GAP_S,
) -> list[SpeechRegion]:
    """Clamp and join nearby VAD regions without creating oversized ASR chunks."""

    cleaned = [
        SpeechRegion(max(0.0, region.start), min(duration, region.end))
        for region in sorted(regions, key=lambda region: (region.start, region.end))
        if region.end > 0.0 and region.start < duration and region.end > region.start
    ]
    cleaned = [region for region in cleaned if region.end > region.start]
    merged: list[SpeechRegion] = []
    for region in cleaned:
        if not merged:
            merged.append(region)
            continue
        previous = merged[-1]
        gap = region.start - previous.end
        combined_end = max(previous.end, region.end)
        if gap <= max_gap_s and combined_end - previous.start <= max_chunk_s:
            merged[-1] = SpeechRegion(previous.start, combined_end)
        else:
            merged.append(region)
    return merged


def _native_time_to_seconds(value: float) -> float:
    return value / _NATIVE_TIMESTAMP_SCALE


@lru_cache(maxsize=1)
def _load_library() -> Any:
    spec = importlib.util.find_spec("_pywhispercpp")
    if spec is None or spec.origin is None:
        raise OpenBBQError(
            "missing_dependency",
            dep="pywhispercpp",
            fix="pip install 'openbbq[whispercpp]'",
        )

    root = Path(spec.origin).resolve().parent
    directories = (
        root,
        root / "pywhispercpp" / ".dylibs",
        root / "pywhispercpp" / ".libs",
        root / "pywhispercpp.libs",
    )
    patterns = ("libwhisper*.dylib", "libwhisper*.so*", "whisper*.dll")
    candidates: list[str] = []
    for directory in directories:
        for pattern in patterns:
            candidates.extend(
                str(path) for path in directory.glob(pattern) if path.is_file()
            )
    system_library = ctypes.util.find_library("whisper")
    if system_library:
        candidates.append(system_library)

    required = (
        "whisper_vad_default_context_params",
        "whisper_vad_default_params",
        "whisper_vad_init_from_file_with_params",
        "whisper_vad_segments_from_samples",
        "whisper_vad_segments_n_segments",
        "whisper_vad_segments_get_segment_t0",
        "whisper_vad_segments_get_segment_t1",
        "whisper_vad_free_segments",
        "whisper_vad_free",
    )
    errors: list[str] = []
    for candidate in dict.fromkeys(candidates):
        try:
            library = ctypes.CDLL(candidate)
        except OSError as error:
            errors.append(f"{candidate}: {error}")
            continue
        if not all(hasattr(library, symbol) for symbol in required):
            errors.append(f"{candidate}: standalone VAD symbols unavailable")
            continue
        _configure_library(library)
        return library
    detail = "; ".join(errors) if errors else "bundled libwhisper was not found"
    raise OpenBBQError(
        "vad_runtime_unsupported",
        detail=detail,
        fix="reinstall 'openbbq[whispercpp]' with a pywhispercpp wheel that includes VAD",
    )


def _configure_library(library: Any) -> None:
    library.whisper_vad_default_context_params.argtypes = []
    library.whisper_vad_default_context_params.restype = _VADContextParams
    library.whisper_vad_default_params.argtypes = []
    library.whisper_vad_default_params.restype = _VADParams
    library.whisper_vad_init_from_file_with_params.argtypes = [
        ctypes.c_char_p,
        _VADContextParams,
    ]
    library.whisper_vad_init_from_file_with_params.restype = ctypes.c_void_p
    library.whisper_vad_segments_from_samples.argtypes = [
        ctypes.c_void_p,
        _VADParams,
        ctypes.POINTER(ctypes.c_float),
        ctypes.c_int,
    ]
    library.whisper_vad_segments_from_samples.restype = ctypes.c_void_p
    library.whisper_vad_segments_n_segments.argtypes = [ctypes.c_void_p]
    library.whisper_vad_segments_n_segments.restype = ctypes.c_int
    library.whisper_vad_segments_get_segment_t0.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    library.whisper_vad_segments_get_segment_t0.restype = ctypes.c_float
    library.whisper_vad_segments_get_segment_t1.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    library.whisper_vad_segments_get_segment_t1.restype = ctypes.c_float
    library.whisper_vad_free_segments.argtypes = [ctypes.c_void_p]
    library.whisper_vad_free_segments.restype = None
    library.whisper_vad_free.argtypes = [ctypes.c_void_p]
    library.whisper_vad_free.restype = None


@contextlib.contextmanager
def _silenced_native_stderr() -> Iterator[None]:
    saved = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(devnull)


def _main() -> int:
    if len(sys.argv) != 3:
        return 2
    try:
        model_module = __import__("pywhispercpp.model", fromlist=["Model"])
        samples = model_module.Model._load_audio(sys.argv[1])
        regions = detect_speech(samples, Path(sys.argv[2]))
    except OpenBBQError as error:
        print(json.dumps(error.payload()), file=sys.stderr)
        return 1
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps([[region.start, region.end] for region in regions]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

from __future__ import annotations

import contextlib
import ctypes
import importlib
import importlib.metadata
import importlib.util
import math
import os
import re
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

from openbbq.core import media, models
from openbbq.errors import OpenBBQError
from openbbq.schemas import Segment, Word

from .base import Capability, ModelInfo, TranscriptResult
from . import whispercpp_vad

PROVIDER = "whisper.cpp"
VAD_PROVIDER = "whisper.cpp-vad"
DEFAULT_VAD_MODEL = "silero-v6.2.0"
VAD_MODEL_SIZE_MB = 885_098 / 1024 / 1024

DEFAULT_OPTS: dict[str, object] = {
    "token_timestamps": True,
    "split_on_word": True,
    "max_len": 0,
}

# A weak phrase can sit immediately before the next Silero region.  Search a
# small amount backwards only after a genuinely long gap; doing this across
# short effect gaps is what caused the opening words to be timestamped early.
VAD_RECALL_LOOKBACK_S = 1.5
VAD_RECALL_MIN_GAP_S = 3.0

# whisper.cpp ggml catalog (HF `ggerganov/whisper.cpp`, resolve/main/ggml-<name>.bin),
# sizes captured 2026-06-29; names mirror pywhispercpp.constants.AVAILABLE_MODELS.
_CATALOG: list[ModelInfo] = [
    ModelInfo("base", PROVIDER, 148.0),
    ModelInfo("base-q5_1", PROVIDER, 59.7),
    ModelInfo("base-q8_0", PROVIDER, 81.8),
    ModelInfo("base.en", PROVIDER, 148.0),
    ModelInfo("base.en-q5_1", PROVIDER, 59.7),
    ModelInfo("base.en-q8_0", PROVIDER, 81.8),
    ModelInfo("large-v1", PROVIDER, 3094.6),
    ModelInfo("large-v2", PROVIDER, 3094.6),
    ModelInfo("large-v2-q5_0", PROVIDER, 1080.7),
    ModelInfo("large-v2-q8_0", PROVIDER, 1656.1),
    ModelInfo("large-v3", PROVIDER, 3095.0),
    ModelInfo("large-v3-q5_0", PROVIDER, 1081.1),
    ModelInfo("large-v3-turbo", PROVIDER, 1624.6),
    ModelInfo("large-v3-turbo-q5_0", PROVIDER, 574.0),
    ModelInfo("large-v3-turbo-q8_0", PROVIDER, 874.2),
    ModelInfo("medium", PROVIDER, 1533.8),
    ModelInfo("medium-q5_0", PROVIDER, 539.2),
    ModelInfo("medium-q8_0", PROVIDER, 823.4),
    ModelInfo("medium.en", PROVIDER, 1533.8),
    ModelInfo("medium.en-q5_0", PROVIDER, 539.2),
    ModelInfo("medium.en-q8_0", PROVIDER, 823.4),
    ModelInfo("small", PROVIDER, 487.6),
    ModelInfo("small-q5_1", PROVIDER, 190.1),
    ModelInfo("small-q8_0", PROVIDER, 264.5),
    ModelInfo("small.en", PROVIDER, 487.6),
    ModelInfo("small.en-q5_1", PROVIDER, 190.1),
    ModelInfo("small.en-q8_0", PROVIDER, 264.5),
    ModelInfo("tiny", PROVIDER, 77.7),
    ModelInfo("tiny-q5_1", PROVIDER, 32.2),
    ModelInfo("tiny-q8_0", PROVIDER, 43.5),
    ModelInfo("tiny.en", PROVIDER, 77.7),
    ModelInfo("tiny.en-q5_1", PROVIDER, 32.2),
    ModelInfo("tiny.en-q8_0", PROVIDER, 43.6),
]

# Quality order for picking a default among several cached models (best first).
_QUALITY_ORDER = ["large-v3", "large-v2", "large-v1", "medium", "small", "base", "tiny"]


class WhisperCppBackend:
    name = PROVIDER
    install_hint = "pip install 'openbbq[whispercpp]'"
    capabilities = {
        Capability.WORD_TIMESTAMPS,
        Capability.PROGRESS,
        Capability.BIASING,
        Capability.VAD,
    }

    # --- availability / environment -------------------------------------------
    def is_available(self) -> bool:
        try:
            importlib.import_module("pywhispercpp.model")
        except ImportError:
            return False
        return True

    def version(self) -> str | None:
        try:
            return importlib.metadata.version("pywhispercpp")
        except importlib.metadata.PackageNotFoundError:
            return None

    def accelerator(self) -> str:
        try:
            model = importlib.import_module("pywhispercpp.model")
        except ImportError:
            return "unknown"
        with _silenced_native_stderr():  # device probes init the GPU backend, banner and all
            gpu = _gpu_device()
            info = str(model.Model.system_info()) if gpu is None else ""
        if gpu is not None:
            return gpu
        for marker, label in (("CUDA", "CUDA"), ("VULKAN", "Vulkan"), ("MTL", "Metal")):
            if marker in info:
                return label
        return "CPU"

    # --- models ---------------------------------------------------------------
    def available_models(self) -> list[ModelInfo]:
        return list(_CATALOG)

    def cached_models(self) -> list[str]:
        path = models.cache_dir(PROVIDER)
        if not path.is_dir():
            return []
        return sorted(
            p.name.removeprefix("ggml-").removesuffix(".bin")
            for p in path.glob("ggml-*.bin")
        )

    def default_model(self) -> str | None:
        names = self.cached_models()
        if len(names) <= 1:
            return names[0] if names else None
        return sorted(names, key=_quality_key)[0]

    def has_model(self, name: str) -> bool:
        return _ggml_path(name).is_file()

    def available_vad_models(self) -> list[ModelInfo]:
        return [ModelInfo(DEFAULT_VAD_MODEL, VAD_PROVIDER, VAD_MODEL_SIZE_MB)]

    def default_vad_model(self) -> str:
        return DEFAULT_VAD_MODEL

    def has_vad_model(self, name: str) -> bool:
        return _vad_path(name).is_file()

    def resolve_vad_model(self, name: str) -> Path:
        return _vad_path(name)

    def pull_vad_model(
        self, name: str, on_progress: Callable[[int, int], None] | None = None
    ) -> Path:
        info = _vad_info(name)
        if info is None:
            raise OpenBBQError(
                "vad_model_missing",
                model=name,
                fix=f"openbbq models pull-vad {DEFAULT_VAD_MODEL}",
            )
        path = _vad_path(name)
        if path.exists():
            return path
        endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
        url = f"{endpoint}/ggml-org/whisper-vad/resolve/main/ggml-{name}.bin"
        try:
            models.download(url, path, on_progress, expected_size_mb=info.size_mb)
        except models.DownloadSizeMismatch as e:
            raise OpenBBQError(
                "model_size_mismatch",
                model=name,
                expected_mb=round(e.expected_size_mb, 1),
                actual_mb=round(e.actual_bytes / 1024 / 1024, 1),
                fix=f"retry download: openbbq models pull-vad {name}",
            ) from e
        except OSError as e:
            raise OpenBBQError(
                "vad_model_download_failed", model=name, detail=str(e)
            ) from e
        return path

    def pull(
        self, name: str, on_progress: Callable[[int, int], None] | None = None
    ) -> Path:
        info = _info(name)
        if info is None:
            raise OpenBBQError("model_missing", model=name, fix="openbbq models list")
        path = _ggml_path(name)
        if path.exists():
            return path
        endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
        url = f"{endpoint}/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
        try:
            models.download(url, path, on_progress, expected_size_mb=info.size_mb)
        except models.DownloadSizeMismatch as e:
            raise OpenBBQError(
                "model_size_mismatch",
                model=name,
                expected_mb=round(e.expected_size_mb, 1),
                actual_mb=round(e.actual_bytes / 1024 / 1024, 1),
                fix=f"retry download: openbbq models pull {name}",
            ) from e
        except OSError as e:
            raise OpenBBQError("model_download_failed", model=name, detail=str(e)) from e
        return path

    # --- transcription --------------------------------------------------------
    def transcribe(
        self,
        audio: Path,
        *,
        model: str,
        language: str | None,
        on_progress: Callable[[int, int], None] | None = None,
        bias: Sequence[str] | None = None,
        **opts: object,
    ) -> TranscriptResult:
        path = _ggml_path(model)
        if not path.exists():
            raise OpenBBQError(
                "model_missing", model=model, fix=f"openbbq models pull {model}"
            )
        duration = media.wav_duration(audio)
        total = max(1, int(duration))
        raw_prompt = opts.pop("initial_prompt", None)
        use_gpu = opts.pop("use_gpu", None)
        vad = opts.pop("vad", False)
        vad_model = opts.pop("vad_model", None)
        opts.pop("vad_model_path", None)
        vad_path: Path | None = None
        if bool(vad):
            selected_vad_model = (
                str(vad_model) if vad_model is not None else self.default_vad_model()
            )
            vad_path = self.resolve_vad_model(selected_vad_model)
            if not vad_path.is_file():
                raise OpenBBQError(
                    "vad_model_missing",
                    model=selected_vad_model,
                    fix=f"openbbq models pull-vad {selected_vad_model}",
                )
        prompt = _initial_prompt(bias, raw_prompt if isinstance(raw_prompt, str) else None)
        model_kwargs: dict[str, object] = {
            "print_progress": False,
            "redirect_whispercpp_logs_to": None,
        }
        if isinstance(use_gpu, bool):
            model_kwargs["context_params"] = {"use_gpu": use_gpu}
        try:
            regions: list[whispercpp_vad.SpeechRegion] = []
            if vad_path is not None:
                # Some bundled libwhisper builds crash when CPU VAD and Metal/CUDA
                # ASR contexts share a process, so native detection is isolated.
                regions = whispercpp_vad.coalesce_regions(
                    whispercpp_vad.detect_speech_file(audio, vad_path),
                    duration=duration,
                )
            # Importing the native ASR module before spawning VAD makes Metal
            # initialization crash on macOS; load it only after VAD exits.
            Model, native = _pywhispercpp()
            model_obj = Model(str(path), **model_kwargs)
            lang = _language(model_obj, audio, language)
            call_kw = {
                "language": lang,
                "new_segment_callback": _progress_callback(on_progress, total),
                **DEFAULT_OPTS,
                **opts,
            }
            if prompt is not None:
                call_kw["initial_prompt"] = prompt
            if vad_path is None:
                raw = model_obj.transcribe(str(audio), **call_kw)
                words = _words_from_context(model_obj._ctx, native)
                segments = _to_segments(raw, words)
            else:
                samples = model_obj._load_audio(str(audio))
                segments = _transcribe_regions(
                    model_obj,
                    native,
                    samples,
                    regions,
                    total,
                    call_kw,
                    on_progress,
                )
            return TranscriptResult(segments=segments, language=lang)
        except OpenBBQError:
            raise
        except Exception as e:
            raise OpenBBQError("transcribe_failed", detail=str(e)) from e


# --- whisper.cpp model paths / catalog lookups (backend-private) --------------


def _ggml_path(name: str) -> Path:
    """Resolve a model to a file: a direct .bin path, else a cached ggml name."""
    path = Path(name).expanduser()
    if path.is_file() or path.parent != Path("."):
        return path.resolve()
    filename = (
        name if name.startswith("ggml-") and name.endswith(".bin") else f"ggml-{name}.bin"
    )
    return models.cache_dir(PROVIDER) / filename


def _vad_path(name: str) -> Path:
    """Resolve a VAD model without mixing it into the ASR model catalog/cache."""
    path = Path(name).expanduser()
    if path.is_file() or path.parent != Path("."):
        return path.resolve()
    filename = (
        name
        if name.startswith("ggml-") and name.endswith(".bin")
        else f"ggml-{name}.bin"
    )
    return models.cache_dir(VAD_PROVIDER) / filename


def _info(name: str) -> ModelInfo | None:
    return next((m for m in _CATALOG if m.name == name), None)


def _vad_info(name: str) -> ModelInfo | None:
    return next(
        (
            model
            for model in WhisperCppBackend().available_vad_models()
            if model.name == name
        ),
        None,
    )


def _quality_key(name: str) -> tuple[int, int, str]:
    for i, prefix in enumerate(_QUALITY_ORDER):
        if name == prefix or name.startswith(f"{prefix}.") or name.startswith(f"{prefix}-"):
            return (i, _catalog_index(name), name)
    return (len(_QUALITY_ORDER), _catalog_index(name), name)


def _catalog_index(name: str) -> int:
    return next((i for i, m in enumerate(_CATALOG) if m.name == name), len(_CATALOG))


# --- biasing ------------------------------------------------------------------


def _initial_prompt(bias: Sequence[str] | None, explicit: str | None) -> str | None:
    """Map backend-agnostic bias terms (+ an explicit raw prompt) to whisper's
    ``initial_prompt`` — whisper.cpp's native form of context biasing.
    """
    parts: list[str] = []
    if bias:
        parts.append("Terms: " + ", ".join(bias) + ".")
    if explicit:
        parts.append(explicit)
    return " ".join(parts) if parts else None


# --- native bindings + timestamp mapping --------------------------------------

# libggml holds the backend registry.  Wheel repair tools may rename it with a
# hash (auditwheel: libggml-c28dfeb1.so.0, delvewheel: ggml-<32 hex>.dll); the
# hex-only suffix keeps ggml-base / ggml-cpu / ggml-vulkan from matching.
_GGML_LIBRARY = re.compile(r"^(lib)?ggml(-[0-9a-f]{8,32})?(\.\d+)*\.(dll|dylib|so)(\.\d+)*$")
_GPU_DEVICE_TYPES = (1, 2)  # GGML_BACKEND_DEVICE_TYPE_GPU, _IGPU
_GPU_BACKENDS = (("MTL", "Metal"), ("Vulkan", "Vulkan"), ("CUDA", "CUDA"))


def _ggml_library() -> Any | None:
    spec = importlib.util.find_spec("_pywhispercpp")
    if spec is None or spec.origin is None:
        return None
    root = Path(spec.origin).resolve().parent
    # Prefer the copy _pywhispercpp itself links against.
    for directory in (root / "pywhispercpp" / ".dylibs", root / "pywhispercpp.libs", root):
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not _GGML_LIBRARY.match(path.name):
                continue
            try:
                library = ctypes.CDLL(str(path))
                library.ggml_backend_dev_count
            except (OSError, AttributeError):
                continue
            library.ggml_backend_dev_count.restype = ctypes.c_size_t
            library.ggml_backend_dev_get.argtypes = [ctypes.c_size_t]
            library.ggml_backend_dev_get.restype = ctypes.c_void_p
            for name in ("ggml_backend_dev_name", "ggml_backend_dev_description"):
                getattr(library, name).argtypes = [ctypes.c_void_p]
                getattr(library, name).restype = ctypes.c_char_p
            library.ggml_backend_dev_type.argtypes = [ctypes.c_void_p]
            library.ggml_backend_dev_type.restype = ctypes.c_int
            return library
    return None


def _gpu_device() -> str | None:
    """The first GPU ggml registered, e.g. "Vulkan (NVIDIA GeForce RTX 4070)".

    Vulkan does not advertise itself in whisper's system_info(), so ask the
    backend registry directly. None means no GPU device (or no probe-able ggml).
    """
    library = _ggml_library()
    if library is None:
        return None
    for index in range(library.ggml_backend_dev_count()):
        device = library.ggml_backend_dev_get(index)
        if library.ggml_backend_dev_type(device) not in _GPU_DEVICE_TYPES:
            continue
        name = (library.ggml_backend_dev_name(device) or b"").decode("utf-8", "replace")
        description = (library.ggml_backend_dev_description(device) or b"").decode("utf-8", "replace")
        label = next((label for prefix, label in _GPU_BACKENDS if name.startswith(prefix)), name)
        return f"{label} ({description})" if description else label
    return None


@contextlib.contextmanager
def _silenced_native_stderr() -> Iterator[None]:
    """Mute whisper.cpp/ggml's C-level stderr (the Metal init banner) around a probe.

    The noise is written directly to fd 2 by the native library, so a Python-level
    redirect won't catch it — we swap fd 2 for /dev/null and restore it.
    """
    saved = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(devnull)


def _pywhispercpp() -> tuple[Any, Any]:
    try:
        model_module = importlib.import_module("pywhispercpp.model")
        native = importlib.import_module("_pywhispercpp")
    except ImportError as e:
        raise OpenBBQError(
            "missing_dependency",
            dep="pywhispercpp",
            fix="pip install 'openbbq[whispercpp]'",
        ) from e
    return model_module.Model, native


def _language(model_obj: Any, audio: Path, language: str | None) -> str:
    if language:
        return language
    detected, _ = model_obj.auto_detect_language(str(audio))
    return str(detected[0])


def _progress_callback(
    on_progress: Callable[[int, int], None] | None,
    total: int,
    offset: float = 0.0,
) -> Callable[[Any], None] | None:
    if on_progress is None:
        return None

    def cb(segment: Any) -> None:
        on_progress(min(total, int(offset + _seconds(segment.t1))), total)

    return cb


def _transcribe_regions(
    model_obj: Any,
    native: Any,
    samples: Any,
    regions: Sequence[whispercpp_vad.SpeechRegion],
    total: int,
    call_kw: dict[str, object],
    on_progress: Callable[[int, int], None] | None,
) -> list[Segment]:
    segments: list[Segment] = []
    for index, region in enumerate(regions):
        previous = regions[index - 1] if index else None
        chunk_start = _vad_chunk_start(region, previous)
        start_sample = max(0, round(chunk_start * whispercpp_vad.SAMPLE_RATE))
        end_sample = min(len(samples), round(region.end * whispercpp_vad.SAMPLE_RATE))
        if end_sample <= start_sample:
            continue
        chunk_kw = {
            **call_kw,
            "new_segment_callback": _progress_callback(
                on_progress, total, offset=chunk_start
            ),
        }
        raw = model_obj.transcribe(samples[start_sample:end_sample], **chunk_kw)
        words = _words_from_context(model_obj._ctx, native)
        local = _to_segments(raw, words)
        segments.extend(
            _offset_segments(
                local, offset=chunk_start, limit=region.end, start_id=len(segments)
            )
        )
    if on_progress is not None:
        on_progress(total, total)
    return segments


def _vad_chunk_start(
    region: whispercpp_vad.SpeechRegion,
    previous: whispercpp_vad.SpeechRegion | None,
) -> float:
    if previous is None or region.start - previous.end < VAD_RECALL_MIN_GAP_S:
        return region.start
    return max(previous.end, region.start - VAD_RECALL_LOOKBACK_S)


def _offset_segments(
    segments: Sequence[Segment],
    *,
    offset: float,
    limit: float,
    start_id: int,
) -> list[Segment]:
    result: list[Segment] = []
    for segment in segments:
        start = min(limit, max(offset, offset + segment.start))
        end = min(limit, max(start, offset + segment.end))
        words = [
            Word(
                word=word.word,
                start=min(end, max(start, offset + word.start)),
                end=min(end, max(start, offset + word.end)),
                prob=word.prob,
            )
            for word in segment.words or []
        ]
        result.append(
            Segment(
                id=start_id + len(result),
                start=start,
                end=end,
                text=segment.text,
                words=words or None,
                speaker=segment.speaker,
            )
        )
    return result


def _to_segments(raw: list[Any], words: list[list[Word]]) -> list[Segment]:
    return [
        Segment(
            id=i,
            start=_seconds(seg.t0),
            end=_seconds(seg.t1),
            text=str(seg.text).strip(),
            words=words[i] or None,
        )
        for i, seg in enumerate(raw)
    ]


def _words_from_context(ctx: Any, native: Any) -> list[list[Word]]:
    return [
        _segment_words(ctx, native, i)
        for i in range(native.whisper_full_n_segments(ctx))
    ]


def _segment_words(ctx: Any, native: Any, segment: int) -> list[Word]:
    """Merge whisper's sub-word tokens into whole words.

    Tokens are BPE pieces: a leading space marks a word start; pieces without
    one — and trailing punctuation — continue the current word. Special tokens
    (``[_...]``) carry no usable text and are skipped.
    """
    words: list[Word] = []
    for i in range(native.whisper_full_n_tokens(ctx, segment)):
        raw = str(native.whisper_full_get_token_text(ctx, segment, i))
        text = raw.strip()
        if not text or text.startswith("[_"):
            continue
        data = native.whisper_full_get_token_data(ctx, segment, i)
        if raw.startswith(" ") or not words:
            words.append(
                Word(
                    word=text,
                    start=_seconds(data.t0),
                    end=_seconds(data.t1),
                    prob=_probability(data.p),
                )
            )
        else:  # continuation / trailing punctuation -> extend the current word
            head = words[-1]
            words[-1] = Word(
                word=head.word + text,
                start=head.start,
                end=_seconds(data.t1),
                prob=head.prob,
            )
    return words


def _seconds(cs: int) -> float:
    return cs / 100


def _probability(value: float) -> float | None:
    return None if math.isnan(value) else value

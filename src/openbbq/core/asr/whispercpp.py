from __future__ import annotations

import contextlib
import importlib
import importlib.metadata
import math
import os
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

from openbbq.core import media, models
from openbbq.errors import OpenBBQError
from openbbq.schemas import Segment, Word

from .base import Capability, ModelInfo, TranscriptResult

PROVIDER = "whisper.cpp"

DEFAULT_OPTS: dict[str, object] = {
    "token_timestamps": True,
    "split_on_word": True,
    "max_len": 0,
}

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
    capabilities = {Capability.WORD_TIMESTAMPS, Capability.PROGRESS, Capability.BIASING}

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
        with _silenced_native_stderr():  # system_info() inits the GPU backend, banner and all
            info = str(model.Model.system_info())
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

    def pull(
        self, name: str, on_progress: Callable[[int, int], None] | None = None
    ) -> Path:
        if _info(name) is None:
            raise OpenBBQError("model_missing", model=name, fix="openbbq models list")
        path = _ggml_path(name)
        if path.exists():
            return path
        endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
        url = f"{endpoint}/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
        try:
            models.download(url, path, on_progress)
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
        Model, native = _pywhispercpp()
        total = max(1, int(media.wav_duration(audio)))
        raw_prompt = opts.pop("initial_prompt", None)
        use_gpu = opts.pop("use_gpu", None)
        prompt = _initial_prompt(bias, raw_prompt if isinstance(raw_prompt, str) else None)
        model_kwargs: dict[str, object] = {
            "print_progress": False,
            "redirect_whispercpp_logs_to": None,
        }
        if isinstance(use_gpu, bool):
            model_kwargs["context_params"] = {"use_gpu": use_gpu}
        try:
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
            raw = model_obj.transcribe(str(audio), **call_kw)
            words = _words_from_context(model_obj._ctx, native)
            return TranscriptResult(segments=_to_segments(raw, words), language=lang)
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


def _info(name: str) -> ModelInfo | None:
    return next((m for m in _CATALOG if m.name == name), None)


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
    on_progress: Callable[[int, int], None] | None, total: int
) -> Callable[[Any], None] | None:
    if on_progress is None:
        return None

    def cb(segment: Any) -> None:
        on_progress(int(_seconds(segment.t1)), total)

    return cb


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

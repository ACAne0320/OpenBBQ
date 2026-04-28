from __future__ import annotations

from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import Path
from threading import Lock
from typing import Any

from openbbq.errors import ExecutionError, ValidationError
from openbbq.runtime.models import FasterWhisperSettings, ModelAssetStatus, RuntimeSettings

SUPPORTED_FASTER_WHISPER_MODELS: tuple[str, ...] = ("tiny", "base", "small", "medium", "large-v3")
REQUIRED_FAST_WHISPER_PAYLOAD_FILES: frozenset[str] = frozenset(
    {"model.bin", "config.json", "tokenizer.json"}
)
FASTER_WHISPER_DOWNLOAD_ALLOW_PATTERNS: tuple[str, ...] = (
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
)
ProgressCallback = Callable[..., None]


def faster_whisper_model_status(
    settings: RuntimeSettings,
    model: str | None = None,
) -> ModelAssetStatus:
    model_settings = (
        settings.models.faster_whisper
        if settings.models is not None
        else FasterWhisperSettings(
            cache_dir=settings.cache.root / "models" / "faster-whisper",
            default_model="base",
            default_device="cpu",
            default_compute_type="int8",
        )
    )
    cache_dir = model_settings.cache_dir
    model = model_settings.default_model if model is None else model
    candidate_paths = _faster_whisper_cache_candidates(cache_dir, model)
    candidate_sizes = tuple(
        size for path in candidate_paths if (size := _candidate_size(path)) is not None
    )
    return ModelAssetStatus(
        provider="faster-whisper",
        model=model,
        cache_dir=cache_dir,
        present=bool(candidate_sizes),
        size_bytes=sum(candidate_sizes),
    )


def faster_whisper_model_statuses(settings: RuntimeSettings) -> tuple[ModelAssetStatus, ...]:
    model_settings = (
        settings.models.faster_whisper
        if settings.models is not None
        else FasterWhisperSettings(
            cache_dir=settings.cache.root / "models" / "faster-whisper",
            default_model="base",
            default_device="cpu",
            default_compute_type="int8",
        )
    )
    return tuple(
        faster_whisper_model_status(settings, model=model)
        for model in _default_first_faster_whisper_models(model_settings.default_model)
    )


def require_supported_faster_whisper_model(model: str) -> None:
    if model in SUPPORTED_FASTER_WHISPER_MODELS:
        return
    allowed = ", ".join(SUPPORTED_FASTER_WHISPER_MODELS)
    raise ValidationError(
        f"Unsupported faster-whisper model '{model}'. Supported models: {allowed}."
    )


def download_faster_whisper_model(
    model: str,
    *,
    cache_dir: Path,
    device: str,
    compute_type: str,
    progress: ProgressCallback | None = None,
) -> None:
    require_supported_faster_whisper_model(model)
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import HfApi, snapshot_download
        from tqdm.auto import tqdm as base_tqdm
    except ImportError as exc:
        raise ExecutionError(
            "huggingface-hub is not installed. Install OpenBBQ with the media optional dependencies."
        ) from exc

    _ = (device, compute_type)
    repo_id = _faster_whisper_repo_id(model)
    total_bytes = _faster_whisper_repository_size(HfApi(), repo_id)
    if progress is not None:
        progress(percent=0, current_bytes=0, total_bytes=total_bytes)
    snapshot_download(
        repo_id,
        cache_dir=cache_dir,
        allow_patterns=list(FASTER_WHISPER_DOWNLOAD_ALLOW_PATTERNS),
        tqdm_class=_progress_tqdm_class(base_tqdm, progress, total_bytes),
    )
    if progress is not None:
        progress(percent=100, current_bytes=total_bytes, total_bytes=total_bytes)


def _default_first_faster_whisper_models(default_model: str) -> tuple[str, ...]:
    models = tuple(model for model in SUPPORTED_FASTER_WHISPER_MODELS if model != default_model)
    if default_model in SUPPORTED_FASTER_WHISPER_MODELS:
        return (default_model, *models)
    return SUPPORTED_FASTER_WHISPER_MODELS


def _faster_whisper_cache_candidates(cache_dir: Path, model: str) -> tuple[Path, ...]:
    return (
        cache_dir / model,
        cache_dir / f"faster-whisper-{model}",
        cache_dir / f"models--Systran--faster-whisper-{model}",
    )


def _faster_whisper_repo_id(model: str) -> str:
    return f"Systran/faster-whisper-{model}"


def _faster_whisper_repository_size(api: Any, repo_id: str) -> int | None:
    try:
        repo_info = api.model_info(repo_id, files_metadata=True)
    except Exception:
        return None

    total = 0
    matched = False
    for sibling in getattr(repo_info, "siblings", ()) or ():
        filename = getattr(sibling, "rfilename", "")
        if not _matches_faster_whisper_download(filename):
            continue
        size = getattr(sibling, "size", None)
        if isinstance(size, int):
            total += size
            matched = True
    if not matched:
        return None
    return total


def _matches_faster_whisper_download(filename: str) -> bool:
    return any(fnmatch(filename, pattern) for pattern in FASTER_WHISPER_DOWNLOAD_ALLOW_PATTERNS)


def _progress_tqdm_class(
    base_tqdm: Any,
    progress: ProgressCallback | None,
    expected_total_bytes: int | None,
) -> Any:
    lock = Lock()
    cumulative_bytes = 0
    cumulative_total_bytes = 0
    n_by_progress_bar: dict[int, int] = {}
    total_by_progress_bar: dict[int, int] = {}

    class ProgressTqdm(base_tqdm):
        def __init__(self, *args, **kwargs):
            self._openbbq_reports_bytes = kwargs.get("unit") == "B"
            self._openbbq_n = int(kwargs.get("initial", 0) or 0)
            kwargs.setdefault("disable", True)
            super().__init__(*args, **kwargs)
            self._openbbq_n = max(self._openbbq_n, int(getattr(self, "n", 0) or 0))
            self._openbbq_emit_progress()

        def refresh(self, *args, **kwargs):
            value = super().refresh(*args, **kwargs)
            self._openbbq_emit_progress()
            return value

        def update(self, n=1):
            previous_n = self._openbbq_current_n()
            value = super().update(n)
            next_n = int(getattr(self, "n", 0) or 0)
            if next_n <= previous_n and n is not None:
                next_n = previous_n + int(n)
            self._openbbq_n = max(previous_n, next_n)
            self._openbbq_emit_progress()
            return value

        def _openbbq_current_n(self) -> int:
            return max(self._openbbq_n, int(getattr(self, "n", 0) or 0))

        def _openbbq_emit_progress(self) -> None:
            nonlocal cumulative_bytes, cumulative_total_bytes

            if progress is None or not self._openbbq_reports_bytes:
                return

            progress_bar_id = id(self)
            n = self._openbbq_current_n()
            total = _positive_int(getattr(self, "total", None))
            with lock:
                previous_n = n_by_progress_bar.get(progress_bar_id, 0)
                n_by_progress_bar[progress_bar_id] = n
                cumulative_bytes += max(0, n - previous_n)

                if expected_total_bytes is None and total is not None:
                    previous_total = total_by_progress_bar.get(progress_bar_id, 0)
                    total_by_progress_bar[progress_bar_id] = total
                    cumulative_total_bytes += max(0, total - previous_total)

                current_bytes = cumulative_bytes
                total_bytes = expected_total_bytes or cumulative_total_bytes or None

            percent = 0 if not total_bytes else (current_bytes / total_bytes) * 100
            progress(
                percent=max(0, min(100, percent)),
                current_bytes=current_bytes,
                total_bytes=total_bytes,
            )

    return ProgressTqdm


def _positive_int(value: Any) -> int | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return int(value)


def _candidate_size(path: Path) -> int | None:
    if not path.is_dir():
        return None
    snapshot_size = _hugging_face_snapshot_size(path)
    if snapshot_size is not None:
        return snapshot_size
    if (path / "snapshots").is_dir():
        return None
    if not _contains_faster_whisper_payload(path):
        return None
    return _directory_size(path)


def _hugging_face_snapshot_size(path: Path) -> int | None:
    snapshots_dir = path / "snapshots"
    if not snapshots_dir.is_dir():
        return None

    ref_path = path / "refs" / "main"
    if ref_path.is_file():
        snapshot_name = ref_path.read_text(encoding="utf-8").strip()
        if not snapshot_name:
            return None
        return _snapshot_directory_size(snapshots_dir / snapshot_name)

    snapshot_sizes: list[int] = []
    for snapshot_dir in sorted(snapshots_dir.iterdir(), key=lambda child: child.name):
        if not snapshot_dir.is_dir():
            continue
        size = _snapshot_directory_size(snapshot_dir)
        if size is not None:
            snapshot_sizes.append(size)
    if not snapshot_sizes:
        return None
    return sum(snapshot_sizes)


def _snapshot_directory_size(path: Path) -> int | None:
    if not path.is_dir() or not _contains_faster_whisper_payload(path):
        return None
    return _directory_size(path)


def _contains_faster_whisper_payload(path: Path) -> bool:
    if not path.is_dir():
        return False
    filenames = {child.name for child in path.rglob("*") if child.is_file()}
    return REQUIRED_FAST_WHISPER_PAYLOAD_FILES.issubset(filenames)


def _directory_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    if not path.is_dir():
        return total
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total

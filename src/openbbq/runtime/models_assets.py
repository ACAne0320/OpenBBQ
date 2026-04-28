from __future__ import annotations

from pathlib import Path

from openbbq.errors import ExecutionError, ValidationError
from openbbq.runtime.models import FasterWhisperSettings, ModelAssetStatus, RuntimeSettings

SUPPORTED_FASTER_WHISPER_MODELS: tuple[str, ...] = ("tiny", "base", "small", "medium", "large-v3")
REQUIRED_FAST_WHISPER_PAYLOAD_FILES: frozenset[str] = frozenset(
    {"model.bin", "config.json", "tokenizer.json"}
)


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
) -> None:
    require_supported_faster_whisper_model(model)
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        from faster_whisper.utils import download_model
    except ImportError as exc:
        raise ExecutionError(
            "faster-whisper is not installed. Install OpenBBQ with the media optional dependencies."
        ) from exc

    _ = (device, compute_type)
    download_model(model, cache_dir=str(cache_dir))


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

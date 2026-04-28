from __future__ import annotations

from pathlib import Path

from openbbq.runtime.models import FasterWhisperSettings, ModelAssetStatus, RuntimeSettings


def faster_whisper_model_status(settings: RuntimeSettings) -> ModelAssetStatus:
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
    model = model_settings.default_model
    present = cache_dir.exists()
    return ModelAssetStatus(
        provider="faster-whisper",
        model=model,
        cache_dir=cache_dir,
        present=present,
        size_bytes=_directory_size(cache_dir) if present else 0,
    )


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

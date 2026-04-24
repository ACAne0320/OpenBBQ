from __future__ import annotations

from pathlib import Path

from openbbq.runtime.models import ModelAssetStatus, RuntimeSettings


def faster_whisper_model_status(settings: RuntimeSettings) -> ModelAssetStatus:
    if settings.models is None:
        cache_dir = settings.cache.root / "models" / "faster-whisper"
        model = "base"
    else:
        cache_dir = settings.models.faster_whisper.cache_dir
        model = settings.models.faster_whisper.default_model
    present = cache_dir.exists()
    return ModelAssetStatus(
        provider="faster_whisper",
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

from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_BEST_FORMAT = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"


class MissingDownloadDependencyError(RuntimeError):
    pass


def run(request: dict, downloader_factory=None) -> dict:
    if request.get("tool_name") != "download":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    parameters = request.get("parameters", {})
    url = _required_string(parameters, "url")
    output_format = parameters.get("format", "mp4")
    if output_format != "mp4":
        raise ValueError("remote_video.download currently supports mp4 output only.")
    quality = str(parameters.get("quality", "best"))
    work_dir = Path(request["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)
    output_path = work_dir / "video.mp4"
    options = {
        "outtmpl": str(work_dir / "video.%(ext)s"),
        "merge_output_format": "mp4",
        "format": _format_selector(quality),
    }
    if downloader_factory is None:
        downloader_factory = _default_downloader_factory
    try:
        with downloader_factory(options) as downloader:
            info = downloader.extract_info(url, download=True)
    except MissingDownloadDependencyError:
        raise
    except Exception as exc:
        raise RuntimeError(f"yt-dlp failed: {exc}") from exc
    if not output_path.is_file():
        raise RuntimeError("yt-dlp did not produce the expected video output.")
    metadata = {
        "url": url,
        "format": "mp4",
        "quality": quality,
    }
    if isinstance(info, dict):
        _copy_string_metadata(info, metadata, "title", "title")
        _copy_string_metadata(info, metadata, "id", "source_id")
        _copy_string_metadata(info, metadata, "extractor", "extractor")
    return {
        "outputs": {
            "video": {
                "type": "video",
                "file_path": str(output_path),
                "metadata": metadata,
            }
        }
    }


def _default_downloader_factory(options: dict[str, Any]):
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise MissingDownloadDependencyError(
            "yt-dlp is not installed. Install OpenBBQ with the download optional dependencies."
        ) from exc
    return YoutubeDL(options)


def _required_string(parameters: dict[str, Any], name: str) -> str:
    value = parameters.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"remote_video.download parameter '{name}' must be a non-empty string.")
    return value


def _format_selector(quality: str) -> str:
    if quality == "best":
        return DEFAULT_BEST_FORMAT
    return quality


def _copy_string_metadata(
    source: dict[str, Any], target: dict[str, Any], source_key: str, target_key: str
) -> None:
    value = source.get(source_key)
    if isinstance(value, str):
        target[target_key] = value

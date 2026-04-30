from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import urlparse


DEFAULT_BEST_FORMAT = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
DEFAULT_720P_FORMAT = "best[ext=mp4][height<=720]/best[height<=720]/best"
DEFAULT_AUTH_MODE = "auto"
CACHE_SCHEMA_VERSION = 1
DEFAULT_BROWSER_COOKIE_BROWSERS = (
    "chrome",
    "edge",
    "firefox",
    "brave",
    "chromium",
    "opera",
    "vivaldi",
    "whale",
    "safari",
)
COOKIE_FALLBACK_ERROR_MARKERS = (
    "sign in to confirm you're not a bot",
    "cookies",
    "cookie",
    "login",
    "authentication",
    "confirm your age",
    "age-restricted",
    "members-only",
)
YOUTUBE_HOST_SUFFIXES = (
    "youtube.com",
    "youtube-nocookie.com",
    "youtu.be",
)
SUPPORTED_JS_RUNTIMES = ("deno", "node", "quickjs", "bun")
YOUTUBE_REMOTE_COMPONENTS = ["ejs:github"]
FORMAT_PRESETS = (
    ("best", "Best available"),
    (DEFAULT_720P_FORMAT, "Best up to 720p"),
    ("best[ext=mp4][height<=1080]/best[height<=1080]/best", "Best up to 1080p"),
    ("best[ext=mp4][height<=480]/best[height<=480]/best", "Best up to 480p"),
)


class MissingDownloadDependencyError(RuntimeError):
    pass


def list_format_options(request: dict, downloader_factory=None) -> dict:
    parameters = request.get("parameters", {})
    url = _required_url(parameters, "url")
    auth_mode = _auth_mode(parameters)
    browser = _optional_string(parameters, "browser")
    browser_profile = _optional_string(parameters, "browser_profile")
    base_options = {"socket_timeout": 15}
    base_options.update(_recommended_download_options(url))
    if downloader_factory is None:
        downloader_factory = _default_downloader_factory
    attempts = _download_attempts(
        url=url,
        auth_mode=auth_mode,
        browser=browser,
        browser_profile=browser_profile,
    )
    info = None
    failure_messages: list[str] = []
    for index, attempt in enumerate(attempts):
        try:
            with downloader_factory(_options_for_attempt(base_options, attempt)) as downloader:
                info = downloader.extract_info(url, download=False)
            break
        except MissingDownloadDependencyError:
            raise
        except Exception as exc:
            failure_messages.append(_attempt_failure_message(attempt, exc))
            has_more_attempts = index + 1 < len(attempts)
            if not _should_try_next_attempt(
                url=url,
                auth_mode=auth_mode,
                error=exc,
                has_more_attempts=has_more_attempts,
            ):
                break
    if not isinstance(info, dict):
        message = "; ".join(failure_messages) if failure_messages else "unknown format failure"
        raise RuntimeError(f"yt-dlp format discovery failed: {message}")
    return {"formats": _format_options_from_info(info)}


def run(request: dict, downloader_factory=None, progress=None) -> dict:
    if request.get("tool_name") != "download":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    parameters = request.get("parameters", {})
    url = _required_url(parameters, "url")
    output_format = parameters.get("format", "mp4")
    if output_format != "mp4":
        raise ValueError("remote_video.download currently supports mp4 output only.")
    quality = str(parameters.get("quality", "best"))
    auth_mode = _auth_mode(parameters)
    browser = _optional_string(parameters, "browser")
    browser_profile = _optional_string(parameters, "browser_profile")
    work_dir = Path(request["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)
    output_path = work_dir / "video.mp4"
    cache_entry = _cache_entry(request, url=url, output_format=output_format, quality=quality)
    cached_path = _valid_cached_video(cache_entry)
    if cached_path is not None:
        _report(
            progress,
            phase="video_download",
            label="Download video",
            percent=100,
            unit="bytes",
        )
        return {
            "outputs": {
                "video": {
                    "type": "video",
                    "file_path": str(cached_path),
                    "metadata": _cached_metadata(cache_entry),
                }
            }
        }
    base_options = {
        "outtmpl": str(work_dir / "video.%(ext)s"),
        "merge_output_format": "mp4",
        "format": _format_selector(quality),
    }
    base_options.update(_recommended_download_options(url))
    if downloader_factory is None:
        downloader_factory = _default_downloader_factory
    attempts = _download_attempts(
        url=url,
        auth_mode=auth_mode,
        browser=browser,
        browser_profile=browser_profile,
    )
    _report(
        progress,
        phase="video_download",
        label="Download video",
        percent=0,
        unit="bytes",
    )
    info = None
    auth_source = None
    failure_messages: list[str] = []
    for index, attempt in enumerate(attempts):
        try:
            options = _options_for_attempt(base_options, attempt)
            if progress is not None:
                options["progress_hooks"] = [_yt_dlp_progress_hook(progress)]
            with downloader_factory(options) as downloader:
                info = downloader.extract_info(url, download=True)
            auth_source = attempt
            break
        except MissingDownloadDependencyError:
            raise
        except Exception as exc:
            failure_messages.append(_attempt_failure_message(attempt, exc))
            has_more_attempts = index + 1 < len(attempts)
            if not _should_try_next_attempt(
                url=url,
                auth_mode=auth_mode,
                error=exc,
                has_more_attempts=has_more_attempts,
            ):
                break
    if info is None or auth_source is None:
        message = "; ".join(failure_messages) if failure_messages else "unknown download failure"
        raise RuntimeError(f"yt-dlp failed: {message}")
    if not output_path.is_file():
        raise RuntimeError("yt-dlp did not produce the expected video output.")
    metadata = {
        "url": url,
        "format": "mp4",
        "quality": quality,
        "auth_strategy": auth_source["auth_strategy"],
    }
    if auth_source.get("browser") is not None:
        metadata["cookie_browser"] = auth_source["browser"]
    if auth_source.get("browser_profile") is not None:
        metadata["cookie_browser_profile"] = auth_source["browser_profile"]
    if isinstance(info, dict):
        _copy_string_metadata(info, metadata, "title", "title")
        _copy_string_metadata(info, metadata, "id", "source_id")
        _copy_string_metadata(info, metadata, "extractor", "extractor")
    if cache_entry is not None:
        cached_path = _write_cached_video(cache_entry, output_path, metadata)
        metadata = dict(metadata)
        metadata["cache_hit"] = False
        metadata["cache_key"] = cache_entry["key"]
        file_path = cached_path
    else:
        file_path = output_path
    return {
        "outputs": {
            "video": {
                "type": "video",
                "file_path": str(file_path),
                "metadata": metadata,
            }
        }
    }


def _report(
    progress,
    *,
    phase: str,
    label: str,
    percent: float,
    current=None,
    total=None,
    unit=None,
) -> None:
    if progress is None:
        return
    try:
        progress(
            phase=phase,
            label=label,
            percent=percent,
            current=current,
            total=total,
            unit=unit,
        )
    except Exception:
        return


def _yt_dlp_progress_hook(progress):
    def hook(payload: dict[str, Any]) -> None:
        status = payload.get("status")
        total = payload.get("total_bytes") or payload.get("total_bytes_estimate")
        current = payload.get("downloaded_bytes")
        if (
            status == "downloading"
            and isinstance(total, (int, float))
            and total > 0
            and isinstance(current, (int, float))
        ):
            _report(
                progress,
                phase="video_download",
                label="Download video",
                percent=min((current / total) * 100, 99),
                current=current,
                total=total,
                unit="bytes",
            )
        elif status == "finished":
            _report(
                progress,
                phase="video_download",
                label="Download video",
                percent=100,
                unit="bytes",
            )

    return hook


def _default_downloader_factory(options: dict[str, Any]):
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise MissingDownloadDependencyError(
            "yt-dlp is not installed. Install OpenBBQ with the download optional dependencies."
        ) from exc
    return YoutubeDL(options)


def _cache_entry(
    request: dict[str, Any],
    *,
    url: str,
    output_format: str,
    quality: str,
) -> dict[str, Any] | None:
    runtime = request.get("runtime")
    if not isinstance(runtime, dict):
        return None
    cache = runtime.get("cache")
    if not isinstance(cache, dict):
        return None
    cache_root_raw = cache.get("root")
    if not isinstance(cache_root_raw, str) or not cache_root_raw.strip():
        return None
    parameters = request.get("parameters", {})
    key_payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "url": url.strip(),
        "format": output_format,
        "quality": quality,
        "auth": str(parameters.get("auth", DEFAULT_AUTH_MODE)),
        "browser": parameters.get("browser"),
        "browser_profile": parameters.get("browser_profile"),
    }
    raw_key = json.dumps(key_payload, sort_keys=True, separators=(",", ":"))
    key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    root = Path(cache_root_raw).expanduser() / "remote-video" / "downloads" / key
    return {
        "key": key,
        "key_payload": key_payload,
        "root": root,
        "video": root / "video.mp4",
        "metadata": root / "metadata.json",
    }


def _valid_cached_video(cache_entry: dict[str, Any] | None) -> Path | None:
    if cache_entry is None:
        return None
    video_path = Path(cache_entry["video"])
    metadata_path = Path(cache_entry["metadata"])
    if not video_path.is_file() or not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    size = metadata.get("content_size")
    digest = metadata.get("content_hash")
    if not isinstance(size, int) or not isinstance(digest, str):
        return None
    try:
        if video_path.stat().st_size != size:
            return None
        if _hash_file(video_path) != digest:
            return None
    except OSError:
        return None
    return video_path


def _cached_metadata(cache_entry: dict[str, Any]) -> dict[str, Any]:
    metadata = json.loads(Path(cache_entry["metadata"]).read_text(encoding="utf-8"))
    source_metadata = metadata.get("source_metadata")
    if not isinstance(source_metadata, dict):
        source_metadata = {}
    return {
        **source_metadata,
        "cache_hit": True,
        "cache_key": cache_entry["key"],
    }


def _write_cached_video(
    cache_entry: dict[str, Any],
    output_path: Path,
    source_metadata: dict[str, Any],
) -> Path:
    root = Path(cache_entry["root"])
    root.mkdir(parents=True, exist_ok=True)
    video_path = Path(cache_entry["video"])
    metadata_path = Path(cache_entry["metadata"])
    size, digest = _copy_file_atomic(video_path, output_path)
    metadata = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "cache_key": cache_entry["key"],
        "key_payload": cache_entry["key_payload"],
        "content_size": size,
        "content_hash": digest,
        "source_metadata": dict(source_metadata),
    }
    _write_json_atomic(metadata_path, metadata)
    return video_path


def _copy_file_atomic(destination: Path, source: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with NamedTemporaryFile(
        "wb",
        dir=destination.parent,
        delete=False,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    ) as handle:
        with source.open("rb") as source_handle:
            for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
                handle.write(chunk)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    temp_path.replace(destination)
    _fsync_parent(destination.parent)
    return size, digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "wb",
        dir=path.parent,
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    temp_path.replace(path)
    _fsync_parent(path.parent)


def _fsync_parent(path: Path) -> None:
    if os.name == "nt":
        return
    directory_fd = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_string(parameters: dict[str, Any], name: str) -> str:
    value = parameters.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"remote_video.download parameter '{name}' must be a non-empty string.")
    return value


def _required_url(parameters: dict[str, Any], name: str) -> str:
    value = _required_string(parameters, name)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"remote_video.download parameter '{name}' must be an http or https URL.")
    return value


def _optional_string(parameters: dict[str, Any], name: str) -> str | None:
    value = parameters.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"remote_video.download parameter '{name}' must be a non-empty string.")
    return value


def _auth_mode(parameters: dict[str, Any]) -> str:
    value = str(parameters.get("auth", DEFAULT_AUTH_MODE))
    if value not in {"auto", "anonymous", "browser_cookies"}:
        raise ValueError(
            "remote_video.download parameter 'auth' must be one of: "
            "auto, anonymous, browser_cookies."
        )
    return value


def _download_attempts(
    *,
    url: str,
    auth_mode: str,
    browser: str | None,
    browser_profile: str | None,
) -> list[dict[str, Any]]:
    if auth_mode == "anonymous":
        return [{"auth_strategy": "anonymous", "browser": None, "browser_profile": None}]
    if browser is not None:
        cookie_attempts = [
            {
                "auth_strategy": "browser_cookies",
                "browser": browser,
                "browser_profile": browser_profile,
            }
        ]
    else:
        cookie_attempts = [
            {
                "auth_strategy": "browser_cookies",
                "browser": browser_name,
                "browser_profile": browser_profile,
            }
            for browser_name in _default_browser_order(url)
        ]
    if auth_mode == "browser_cookies":
        return cookie_attempts
    return [
        {"auth_strategy": "anonymous", "browser": None, "browser_profile": None},
        *cookie_attempts,
    ]


def _options_for_attempt(base_options: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any]:
    options = dict(base_options)
    if attempt["auth_strategy"] != "browser_cookies":
        return options
    cookie_spec: tuple[str, ...]
    if attempt["browser_profile"] is None:
        cookie_spec = (attempt["browser"],)
    else:
        cookie_spec = (attempt["browser"], attempt["browser_profile"])
    options["cookiesfrombrowser"] = cookie_spec
    return options


def _default_browser_order(url: str) -> tuple[str, ...]:
    if _is_youtube_url(url):
        return DEFAULT_BROWSER_COOKIE_BROWSERS
    return DEFAULT_BROWSER_COOKIE_BROWSERS


def _recommended_download_options(url: str) -> dict[str, Any]:
    if not _is_youtube_url(url):
        return {}
    runtime_config = _available_js_runtimes()
    if not runtime_config:
        return {}
    return {
        "js_runtimes": runtime_config,
        "remote_components": list(YOUTUBE_REMOTE_COMPONENTS),
    }


def _available_js_runtimes() -> dict[str, dict[str, str]]:
    runtimes: dict[str, dict[str, str]] = {}
    for runtime in SUPPORTED_JS_RUNTIMES:
        path = shutil.which(runtime)
        if path is not None:
            runtimes[runtime] = {"path": path}
    return runtimes


def _attempt_failure_message(attempt: dict[str, Any], error: Exception) -> str:
    if attempt["auth_strategy"] == "anonymous":
        return f"anonymous attempt failed: {error}"
    browser = attempt["browser"]
    if attempt["browser_profile"] is None:
        return f"browser cookies ({browser}) failed: {error}"
    return f"browser cookies ({browser}:{attempt['browser_profile']}) failed: {error}"


def _should_try_next_attempt(
    *,
    url: str,
    auth_mode: str,
    error: Exception,
    has_more_attempts: bool,
) -> bool:
    if not has_more_attempts or auth_mode == "anonymous":
        return False
    if _is_youtube_url(url):
        return True
    return any(marker in str(error).lower() for marker in COOKIE_FALLBACK_ERROR_MARKERS)


def _is_youtube_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    host = host.lower()
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in YOUTUBE_HOST_SUFFIXES)


def _format_selector(quality: str) -> str:
    if quality == "best":
        return DEFAULT_BEST_FORMAT
    return quality


def _format_options_from_info(info: dict[str, Any]) -> tuple[dict[str, str], ...]:
    options: list[dict[str, str]] = [
        {"value": value, "label": label} for value, label in FORMAT_PRESETS
    ]
    seen = {option["value"] for option in options}
    formats = info.get("formats")
    if not isinstance(formats, list):
        return tuple(options)
    for raw_format in formats:
        if not isinstance(raw_format, dict):
            continue
        option = _format_option(raw_format)
        if option is None or option["value"] in seen:
            continue
        options.append(option)
        seen.add(option["value"])
    return tuple(options)


def _format_option(raw_format: dict[str, Any]) -> dict[str, str] | None:
    format_id = raw_format.get("format_id")
    if not isinstance(format_id, str) or not format_id:
        return None
    ext = str(raw_format.get("ext") or "")
    vcodec = str(raw_format.get("vcodec") or "")
    acodec = str(raw_format.get("acodec") or "")
    if vcodec == "none":
        return None
    height = raw_format.get("height")
    fps = raw_format.get("fps")
    resolution = _resolution_label(raw_format)
    if acodec == "none":
        value = f"{format_id}+bestaudio[ext=m4a]/best[height<={height}]" if height else format_id
        audio_label = "video + best audio"
    else:
        value = format_id
        audio_label = "video + audio"
    details = [format_id, ext.upper() if ext else None, resolution, _fps_label(fps), audio_label]
    size = raw_format.get("filesize") or raw_format.get("filesize_approx")
    size_label = _size_label(size)
    if size_label is not None:
        details.append(size_label)
    return {
        "value": value,
        "label": " - ".join(item for item in details if item),
    }


def _resolution_label(raw_format: dict[str, Any]) -> str | None:
    width = raw_format.get("width")
    height = raw_format.get("height")
    if isinstance(width, int) and isinstance(height, int):
        return f"{width}x{height}"
    if isinstance(height, int):
        return f"{height}p"
    resolution = raw_format.get("resolution")
    return resolution if isinstance(resolution, str) and resolution else None


def _fps_label(value: Any) -> str | None:
    if isinstance(value, (int, float)) and value > 0:
        return f"{value:g}fps"
    return None


def _size_label(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    units = ("B", "KB", "MB", "GB")
    size = float(value)
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    return f"{size:.1f}{unit}"


def _copy_string_metadata(
    source: dict[str, Any], target: dict[str, Any], source_key: str, target_key: str
) -> None:
    value = source.get(source_key)
    if isinstance(value, str):
        target[target_key] = value

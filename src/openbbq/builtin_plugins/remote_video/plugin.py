from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_BEST_FORMAT = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
DEFAULT_AUTH_MODE = "auto"
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


class MissingDownloadDependencyError(RuntimeError):
    pass


def run(request: dict, downloader_factory=None, progress=None) -> dict:
    if request.get("tool_name") != "download":
        raise ValueError(f"Unsupported tool: {request.get('tool_name')}")
    parameters = request.get("parameters", {})
    url = _required_string(parameters, "url")
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
    return {
        "outputs": {
            "video": {
                "type": "video",
                "file_path": str(output_path),
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


def _required_string(parameters: dict[str, Any], name: str) -> str:
    value = parameters.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"remote_video.download parameter '{name}' must be a non-empty string.")
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


def _copy_string_metadata(
    source: dict[str, Any], target: dict[str, Any], source_key: str, target_key: str
) -> None:
    value = source.get(source_key)
    if isinstance(value, str):
        target[target_key] = value

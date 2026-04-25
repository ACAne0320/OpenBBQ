import pytest

from openbbq.builtin_plugins.remote_video import plugin as remote_video_plugin
from tests.builtin_plugin_fakes import (
    BrowserCookieAwareDownloaderFactory,
    CustomDownloaderFactory,
    FailingDownloader,
    NoOutputDownloader,
    RecordingDownloaderFactory,
    _mock_js_runtime,
)


def test_remote_video_download_uses_yt_dlp_factory_and_returns_file_output(tmp_path):
    factory = RecordingDownloaderFactory()

    response = remote_video_plugin.run(
        {
            "tool_name": "download",
            "work_dir": str(tmp_path / "work"),
            "parameters": {
                "url": "https://video.example/watch/123",
                "format": "mp4",
                "quality": "best",
            },
            "inputs": {},
        },
        downloader_factory=factory,
    )

    expected_output = tmp_path / "work/video.mp4"
    assert expected_output.read_bytes() == b"video"
    assert factory.calls == [
        {
            "outtmpl": str(tmp_path / "work/video.%(ext)s"),
            "merge_output_format": "mp4",
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        }
    ]
    assert factory.downloader.extract_calls == [
        {"url": "https://video.example/watch/123", "download": True}
    ]
    assert response == {
        "outputs": {
            "video": {
                "type": "video",
                "file_path": str(expected_output),
                "metadata": {
                    "url": "https://video.example/watch/123",
                    "format": "mp4",
                    "quality": "best",
                    "auth_strategy": "anonymous",
                    "title": "Remote Video",
                    "source_id": "source-123",
                    "extractor": "generic",
                },
            }
        }
    }


def test_remote_video_download_falls_back_to_browser_cookies_for_youtube(monkeypatch, tmp_path):
    _mock_js_runtime(monkeypatch)
    factory = BrowserCookieAwareDownloaderFactory(success_browser="chrome")

    response = remote_video_plugin.run(
        {
            "tool_name": "download",
            "work_dir": str(tmp_path / "work"),
            "parameters": {
                "url": "https://www.youtube.com/watch?v=test-video",
                "format": "mp4",
            },
            "inputs": {},
        },
        downloader_factory=factory,
    )

    expected_output = tmp_path / "work/video.mp4"
    assert expected_output.read_bytes() == b"video"
    assert factory.calls[0] == {
        "outtmpl": str(tmp_path / "work/video.%(ext)s"),
        "merge_output_format": "mp4",
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "js_runtimes": {"node": {"path": "/usr/bin/node"}},
        "remote_components": ["ejs:github"],
    }
    assert factory.calls[1] == {
        "outtmpl": str(tmp_path / "work/video.%(ext)s"),
        "merge_output_format": "mp4",
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "js_runtimes": {"node": {"path": "/usr/bin/node"}},
        "remote_components": ["ejs:github"],
        "cookiesfrombrowser": ("chrome",),
    }
    assert response["outputs"]["video"]["metadata"]["auth_strategy"] == "browser_cookies"
    assert response["outputs"]["video"]["metadata"]["cookie_browser"] == "chrome"
    assert response["outputs"]["video"]["metadata"]["extractor"] == "youtube"


def test_remote_video_download_can_start_with_explicit_browser_cookies(monkeypatch, tmp_path):
    _mock_js_runtime(monkeypatch)
    factory = BrowserCookieAwareDownloaderFactory(success_browser="firefox")

    response = remote_video_plugin.run(
        {
            "tool_name": "download",
            "work_dir": str(tmp_path / "work"),
            "parameters": {
                "url": "https://www.youtube.com/watch?v=test-video",
                "auth": "browser_cookies",
                "browser": "firefox",
                "browser_profile": "default",
            },
            "inputs": {},
        },
        downloader_factory=factory,
    )

    assert len(factory.calls) == 1
    assert factory.calls[0] == {
        "outtmpl": str(tmp_path / "work/video.%(ext)s"),
        "merge_output_format": "mp4",
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "js_runtimes": {"node": {"path": "/usr/bin/node"}},
        "remote_components": ["ejs:github"],
        "cookiesfrombrowser": ("firefox", "default"),
    }
    assert response["outputs"]["video"]["metadata"]["auth_strategy"] == "browser_cookies"
    assert response["outputs"]["video"]["metadata"]["cookie_browser"] == "firefox"
    assert response["outputs"]["video"]["metadata"]["cookie_browser_profile"] == "default"


def test_remote_video_download_requires_url(tmp_path):
    with pytest.raises(ValueError, match="url"):
        remote_video_plugin.run(
            {
                "tool_name": "download",
                "work_dir": str(tmp_path / "work"),
                "parameters": {"url": ""},
                "inputs": {},
            },
            downloader_factory=RecordingDownloaderFactory(),
        )


def test_remote_video_download_rejects_non_mp4_format(tmp_path):
    with pytest.raises(ValueError, match="mp4 output only"):
        remote_video_plugin.run(
            {
                "tool_name": "download",
                "work_dir": str(tmp_path / "work"),
                "parameters": {
                    "url": "https://video.example/watch/123",
                    "format": "webm",
                },
                "inputs": {},
            },
            downloader_factory=RecordingDownloaderFactory(),
        )


def test_remote_video_download_rejects_unknown_auth_mode(tmp_path):
    with pytest.raises(ValueError, match="parameter 'auth'"):
        remote_video_plugin.run(
            {
                "tool_name": "download",
                "work_dir": str(tmp_path / "work"),
                "parameters": {
                    "url": "https://video.example/watch/123",
                    "auth": "interactive_browser",
                },
                "inputs": {},
            },
            downloader_factory=RecordingDownloaderFactory(),
        )


def test_remote_video_download_wraps_downloader_failures(tmp_path):
    factory = CustomDownloaderFactory(FailingDownloader)

    with pytest.raises(
        RuntimeError, match="yt-dlp failed: anonymous attempt failed: download unavailable"
    ):
        remote_video_plugin.run(
            {
                "tool_name": "download",
                "work_dir": str(tmp_path / "work"),
                "parameters": {"url": "https://video.example/watch/123"},
                "inputs": {},
            },
            downloader_factory=factory,
        )
    assert len(factory.calls) == 1


def test_remote_video_download_requires_expected_output_file(tmp_path):
    with pytest.raises(RuntimeError, match="expected video output"):
        remote_video_plugin.run(
            {
                "tool_name": "download",
                "work_dir": str(tmp_path / "work"),
                "parameters": {"url": "https://video.example/watch/123"},
                "inputs": {},
            },
            downloader_factory=CustomDownloaderFactory(NoOutputDownloader),
        )


def test_remote_video_download_missing_dependency_message(monkeypatch, tmp_path):
    import builtins

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yt_dlp":
            raise ImportError("missing yt-dlp")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="download optional dependencies"):
        remote_video_plugin.run(
            {
                "tool_name": "download",
                "work_dir": str(tmp_path / "work"),
                "parameters": {"url": "https://video.example/watch/123"},
                "inputs": {},
            }
        )

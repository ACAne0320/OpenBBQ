import json
from pathlib import Path

import pytest

from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin
from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin
from openbbq.builtin_plugins.glossary import plugin as glossary_plugin
from openbbq.builtin_plugins.llm import plugin as llm_plugin
from openbbq.builtin_plugins.remote_video import plugin as remote_video_plugin
from openbbq.builtin_plugins.subtitle import plugin as subtitle_plugin
from openbbq.config.loader import load_project_config
from openbbq.plugins.registry import discover_plugins


def write_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "openbbq.yaml").write_text(
        """
version: 1
project:
  name: Builtins
workflows:
  demo:
    name: Demo
    steps:
      - id: extract_audio
        name: Extract Audio
        tool_ref: ffmpeg.extract_audio
        inputs:
          video: project.art_missing
        outputs:
          - name: audio
            type: audio
        parameters: {}
        on_error: abort
        max_retries: 0
""",
        encoding="utf-8",
    )
    return project


def test_builtin_plugin_path_is_discovered_by_default(tmp_path):
    config = load_project_config(write_project(tmp_path))

    registry = discover_plugins(config.plugin_paths)

    assert "ffmpeg.extract_audio" in registry.tools
    assert "faster_whisper.transcribe" in registry.tools
    assert "glossary.replace" in registry.tools
    assert "llm.translate" in registry.tools
    assert "remote_video.download" in registry.tools
    assert "subtitle.export" in registry.tools


def test_glossary_replace_updates_segment_text_and_preserves_other_fields():
    response = glossary_plugin.run(
        {
            "tool_name": "replace",
            "parameters": {
                "rules": [
                    {
                        "find": "Open BBQ",
                        "replace": "OpenBBQ",
                        "is_regex": False,
                        "case_sensitive": False,
                    },
                    {
                        "find": r"frieren",
                        "replace": "Frieren",
                        "is_regex": True,
                        "case_sensitive": False,
                    },
                ]
            },
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {
                            "start": 0.0,
                            "end": 1.5,
                            "text": "open bbq talks about frieren",
                            "confidence": -0.1,
                            "words": [{"start": 0.0, "end": 0.4, "text": "open"}],
                        },
                        {"start": 1.5, "end": 2.0, "text": "No match"},
                    ],
                }
            },
        }
    )

    assert response["outputs"]["transcript"]["type"] == "asr_transcript"
    assert response["outputs"]["transcript"]["content"] == [
        {
            "start": 0.0,
            "end": 1.5,
            "text": "OpenBBQ talks about Frieren",
            "confidence": -0.1,
            "words": [{"start": 0.0, "end": 0.4, "text": "open"}],
        },
        {"start": 1.5, "end": 2.0, "text": "No match"},
    ]
    assert response["outputs"]["transcript"]["metadata"] == {
        "segment_count": 2,
        "word_count": 6,
        "rule_count": 2,
    }


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class RecordingChatCompletions:
    def __init__(self, response_content):
        self.response_content = response_content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeCompletion(self.response_content)


class RecordingChat:
    def __init__(self, response_content):
        self.completions = RecordingChatCompletions(response_content)


class RecordingOpenAIClient:
    def __init__(self, response_content):
        self.chat = RecordingChat(response_content)


class RecordingOpenAIClientFactory:
    def __init__(self, response_content):
        self.response_content = response_content
        self.calls = []
        self.client = RecordingOpenAIClient(response_content)

    def __call__(self, *, api_key, base_url):
        self.calls.append({"api_key": api_key, "base_url": base_url})
        return self.client


class SequencedRecordingChatCompletions:
    def __init__(self, response_contents):
        self.response_contents = list(response_contents)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        return FakeCompletion(self.response_contents[index])


class SequencedRecordingChat:
    def __init__(self, response_contents):
        self.completions = SequencedRecordingChatCompletions(response_contents)


class SequencedRecordingOpenAIClient:
    def __init__(self, response_contents):
        self.chat = SequencedRecordingChat(response_contents)


class SequencedRecordingOpenAIClientFactory:
    def __init__(self, response_contents):
        self.calls = []
        self.client = SequencedRecordingOpenAIClient(response_contents)

    def __call__(self, *, api_key, base_url):
        self.calls.append({"api_key": api_key, "base_url": base_url})
        return self.client


class RecordingDownloader:
    def __init__(self, options, output_bytes=b"video"):
        self.options = options
        self.output_bytes = output_bytes
        self.extract_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def extract_info(self, url, download=True):
        self.extract_calls.append({"url": url, "download": download})
        output = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.output_bytes)
        return {
            "id": "source-123",
            "title": "Remote Video",
            "extractor": "generic",
        }


class RecordingDownloaderFactory:
    def __init__(self):
        self.calls = []
        self.downloader = None

    def __call__(self, options):
        self.calls.append(options)
        self.downloader = RecordingDownloader(options)
        return self.downloader


class NoOutputDownloader(RecordingDownloader):
    def extract_info(self, url, download=True):
        self.extract_calls.append({"url": url, "download": download})
        return {"id": "source-123"}


class FailingDownloader(RecordingDownloader):
    def extract_info(self, url, download=True):
        self.extract_calls.append({"url": url, "download": download})
        raise RuntimeError("download unavailable")


class CustomDownloaderFactory:
    def __init__(self, downloader_class):
        self.downloader_class = downloader_class
        self.calls = []
        self.downloader = None

    def __call__(self, options):
        self.calls.append(options)
        self.downloader = self.downloader_class(options)
        return self.downloader


class BrowserCookieAwareDownloader(RecordingDownloader):
    def __init__(self, options, *, success_browser, output_bytes=b"video"):
        super().__init__(options, output_bytes=output_bytes)
        self.success_browser = success_browser

    def extract_info(self, url, download=True):
        self.extract_calls.append({"url": url, "download": download})
        cookie_spec = self.options.get("cookiesfrombrowser")
        if cookie_spec is None:
            raise RuntimeError("Sign in to confirm you're not a bot")
        if cookie_spec[0] != self.success_browser:
            raise FileNotFoundError(f"browser cookies unavailable for {cookie_spec[0]}")
        output = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.output_bytes)
        return {
            "id": "source-123",
            "title": "Remote Video",
            "extractor": "youtube",
        }


class BrowserCookieAwareDownloaderFactory:
    def __init__(self, *, success_browser):
        self.success_browser = success_browser
        self.calls = []
        self.downloaders = []

    def __call__(self, options):
        self.calls.append(options)
        downloader = BrowserCookieAwareDownloader(options, success_browser=self.success_browser)
        self.downloaders.append(downloader)
        return downloader


def _mock_js_runtime(monkeypatch, *, node_path="/usr/bin/node"):
    monkeypatch.setattr(
        remote_video_plugin.shutil,
        "which",
        lambda name: node_path if name == "node" else None,
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


def test_llm_translate_uses_openai_client_and_returns_translation(monkeypatch):
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "test-key")
    monkeypatch.setenv("OPENBBQ_LLM_BASE_URL", "https://llm.example/v1")
    factory = RecordingOpenAIClientFactory(
        '[{"index": 0, "text": "你好"}, {"index": 1, "text": "OpenBBQ"}]'
    )

    response = llm_plugin.run(
        {
            "tool_name": "translate",
            "parameters": {
                "source_lang": "en",
                "target_lang": "zh-Hans",
                "model": "gpt-4o-mini",
                "temperature": 0,
            },
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {"start": 0.0, "end": 1.5, "text": "Hello"},
                        {"start": 1.5, "end": 3.0, "text": "OpenBBQ"},
                    ],
                }
            },
        },
        client_factory=factory,
    )

    assert factory.calls == [{"api_key": "test-key", "base_url": "https://llm.example/v1"}]
    call = factory.client.chat.completions.calls[0]
    assert call["model"] == "gpt-4o-mini"
    assert call["temperature"] == 0
    assert "response_format" not in call
    assert len(call["messages"]) == 2
    assert "Return JSON only" in call["messages"][0]["content"]
    assert '"target_lang":"zh-Hans"' in call["messages"][1]["content"]

    assert response == {
        "outputs": {
            "translation": {
                "type": "translation",
                "content": [
                    {"start": 0.0, "end": 1.5, "source_text": "Hello", "text": "你好"},
                    {"start": 1.5, "end": 3.0, "source_text": "OpenBBQ", "text": "OpenBBQ"},
                ],
                "metadata": {
                    "source_lang": "en",
                    "target_lang": "zh-Hans",
                    "model": "gpt-4o-mini",
                    "segment_count": 2,
                },
            }
        }
    }


def test_llm_translate_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENBBQ_LLM_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENBBQ_LLM_API_KEY"):
        llm_plugin.run(
            {
                "tool_name": "translate",
                "parameters": {
                    "source_lang": "en",
                    "target_lang": "zh-Hans",
                    "model": "gpt-4o-mini",
                },
                "inputs": {
                    "transcript": {
                        "type": "asr_transcript",
                        "content": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
                    }
                },
            },
            client_factory=RecordingOpenAIClientFactory("[]"),
        )


def test_llm_translate_rejects_malformed_model_json(monkeypatch):
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "test-key")
    factory = RecordingOpenAIClientFactory('[{"index": 1, "text": "错位"}]')

    with pytest.raises(ValueError, match="expected translated segment index 0"):
        llm_plugin.run(
            {
                "tool_name": "translate",
                "parameters": {
                    "source_lang": "en",
                    "target_lang": "zh-Hans",
                    "model": "gpt-4o-mini",
                },
                "inputs": {
                    "transcript": {
                        "type": "asr_transcript",
                        "content": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
                    }
                },
            },
            client_factory=factory,
        )


def test_subtitle_export_writes_srt_from_transcript_segments():
    response = subtitle_plugin.run(
        {
            "tool_name": "export",
            "parameters": {"format": "srt"},
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {"start": 0.0, "end": 1.5, "text": "Hello"},
                        {"start": 1.5, "end": 3.0, "text": "OpenBBQ"},
                    ],
                }
            },
        }
    )

    assert response == {
        "outputs": {
            "subtitle": {
                "type": "subtitle",
                "content": "1\n00:00:00,000 --> 00:00:01,500\nHello\n\n"
                "2\n00:00:01,500 --> 00:00:03,000\nOpenBBQ\n",
                "metadata": {"format": "srt", "segment_count": 2, "duration_seconds": 3.0},
            }
        }
    }


class RecordingRunner:
    def __init__(self):
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        output_path = command[-1]
        Path(output_path).write_bytes(b"wav")


def test_ffmpeg_extract_audio_builds_command_and_returns_file_output(tmp_path):
    runner = RecordingRunner()
    video = tmp_path / "input.mp4"
    video.write_bytes(b"video")
    work_dir = tmp_path / "work"

    response = ffmpeg_plugin.run(
        {
            "tool_name": "extract_audio",
            "work_dir": str(work_dir),
            "parameters": {"format": "wav", "sample_rate": 16000, "channels": 1},
            "inputs": {"video": {"type": "video", "file_path": str(video)}},
        },
        runner=runner,
    )

    assert runner.commands == [
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(work_dir / "audio.wav"),
        ]
    ]
    assert response["outputs"]["audio"]["type"] == "audio"
    assert response["outputs"]["audio"]["file_path"] == str(work_dir / "audio.wav")
    assert response["outputs"]["audio"]["metadata"] == {
        "format": "wav",
        "sample_rate": 16000,
        "channels": 1,
    }


class FakeWord:
    start = 0.0
    end = 0.5
    word = "Hello"
    probability = 0.9


class FakeSegment:
    start = 0.0
    end = 1.0
    text = "Hello"
    avg_logprob = -0.1
    words = [FakeWord()]


class FakeInfo:
    language = "en"
    duration = 1.0


class FakeWhisperModel:
    def __init__(self, model, device, compute_type):
        self.model = model
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, audio_path, language=None, word_timestamps=True, vad_filter=False):
        return [FakeSegment()], FakeInfo()


def test_faster_whisper_transcribe_uses_backend_and_returns_segments(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")

    response = whisper_plugin.run(
        {
            "tool_name": "transcribe",
            "parameters": {
                "model": "base",
                "device": "cpu",
                "compute_type": "int8",
                "word_timestamps": True,
            },
            "inputs": {"audio": {"type": "audio", "file_path": str(audio)}},
        },
        model_factory=FakeWhisperModel,
    )

    assert response["outputs"]["transcript"]["type"] == "asr_transcript"
    assert response["outputs"]["transcript"]["content"] == [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "Hello",
            "confidence": -0.1,
            "words": [{"start": 0.0, "end": 0.5, "text": "Hello", "confidence": 0.9}],
        }
    ]
    assert response["outputs"]["transcript"]["metadata"] == {
        "model": "base",
        "device": "cpu",
        "compute_type": "int8",
        "language": "en",
        "duration_seconds": 1.0,
    }

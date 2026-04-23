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

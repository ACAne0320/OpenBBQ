from pathlib import Path

from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin
from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin
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
    assert "subtitle.export" in registry.tools


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

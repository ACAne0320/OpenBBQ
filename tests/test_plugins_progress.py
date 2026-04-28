from pathlib import Path
from types import SimpleNamespace

from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin
from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin
from openbbq.builtin_plugins.remote_video import plugin as remote_video_plugin
from openbbq.builtin_plugins.translation import plugin as translation_plugin


def test_remote_video_reports_download_percentages(tmp_path: Path):
    calls = []

    class FakeDownloader:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def extract_info(self, url, download):
            hook = self.options["progress_hooks"][0]
            hook({"status": "downloading", "downloaded_bytes": 25, "total_bytes": 100})
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            (tmp_path / "video.mp4").write_bytes(b"video")
            hook({"status": "finished", "downloaded_bytes": 100, "total_bytes": 100})
            return {"title": "sample"}

    remote_video_plugin.run(
        {
            "tool_name": "download",
            "parameters": {"url": "https://example.com/video", "format": "mp4"},
            "work_dir": str(tmp_path),
        },
        downloader_factory=FakeDownloader,
        progress=lambda **payload: calls.append(payload),
    )

    assert [call["percent"] for call in calls] == [0, 25, 50, 100]
    assert calls[-1]["phase"] == "video_download"


def test_ffmpeg_reports_extract_audio_percentages(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    audio = tmp_path / "audio.wav"
    calls = []

    def fake_probe_duration(path):
        assert path == video
        return 10.0

    def fake_runner(command, on_progress):
        on_progress(2.5)
        on_progress(7.5)
        audio.write_bytes(b"audio")

    ffmpeg_plugin.run(
        {
            "tool_name": "extract_audio",
            "inputs": {"video": {"file_path": str(video)}},
            "parameters": {"format": "wav", "sample_rate": 16000},
            "work_dir": str(tmp_path),
        },
        runner=fake_runner,
        duration_probe=fake_probe_duration,
        progress=lambda **payload: calls.append(payload),
    )

    assert [call["percent"] for call in calls] == [0, 25, 75, 100]
    assert calls[-1]["phase"] == "extract_audio"


def test_faster_whisper_reports_asr_percentages(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    calls = []

    class FakeModel:
        def transcribe(self, audio_path, **kwargs):
            segments = [
                SimpleNamespace(start=0, end=2, text="hello", avg_logprob=None, words=[]),
                SimpleNamespace(start=2, end=5, text="world", avg_logprob=None, words=[]),
            ]
            return segments, SimpleNamespace(language="en", duration=5)

    whisper_plugin.run(
        {
            "tool_name": "transcribe",
            "inputs": {"audio": {"file_path": str(audio)}},
            "parameters": {"model": "base", "word_timestamps": False},
            "runtime": {},
            "work_dir": str(tmp_path),
        },
        model_factory=lambda *args, **kwargs: FakeModel(),
        progress=lambda **payload: calls.append(payload),
    )

    assert [call["percent"] for call in calls] == [0, 40, 100]
    assert calls[-1]["phase"] == "asr_parse"


def test_translation_reports_completed_segment_percentages():
    calls = []

    class FakeClient:
        def chat(self):
            raise AssertionError("not used")

    def fake_translate_chunk(**kwargs):
        return [{"index": item.index, "text": f"zh {item.text}"} for item in kwargs["chunk"]]

    original = translation_plugin._translate_chunk
    translation_plugin._translate_chunk = fake_translate_chunk
    try:
        translation_plugin.run_translation(
            {
                "tool_name": "translate",
                "parameters": {
                    "provider": "openai",
                    "source_lang": "en",
                    "target_lang": "zh",
                    "model": "gpt",
                },
                "inputs": {
                    "subtitle_segments": {
                        "type": "subtitle_segments",
                        "content": [
                            {"index": 0, "start": 0, "end": 1, "text": "a"},
                            {"index": 1, "start": 1, "end": 2, "text": "b"},
                        ],
                    }
                },
                "runtime": {
                    "providers": {
                        "openai": {
                            "type": "openai_compatible",
                            "api_key": "sk-test",
                            "base_url": None,
                        }
                    }
                },
            },
            client_factory=lambda **kwargs: FakeClient(),
            error_prefix="translation.translate",
            include_provider_metadata=True,
            input_names=("subtitle_segments",),
            progress=lambda **payload: calls.append(payload),
        )
    finally:
        translation_plugin._translate_chunk = original

    assert calls[0]["percent"] == 0
    assert calls[-1]["percent"] == 100
    assert calls[-1]["phase"] == "translate"

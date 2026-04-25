from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin
from tests.builtin_plugin_fakes import FakeInfo, FakeSegment, FakeWhisperModel


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
        "model_cache_dir": None,
        "language": "en",
        "duration_seconds": 1.0,
    }


def test_faster_whisper_transcribe_uses_runtime_cache_dir(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    calls = []

    class RuntimeCacheWhisperModel:
        def transcribe(self, audio_path, **kwargs):
            return [FakeSegment()], FakeInfo()

    def fake_model_factory(model_name, *, device, compute_type, download_root=None):
        calls.append(
            {
                "model_name": model_name,
                "device": device,
                "compute_type": compute_type,
                "download_root": download_root,
            }
        )
        return RuntimeCacheWhisperModel()

    whisper_plugin.run(
        {
            "tool_name": "transcribe",
            "parameters": {"model": "base", "device": "cpu", "compute_type": "int8"},
            "runtime": {"cache": {"faster_whisper": str(tmp_path / "models/fw")}},
            "inputs": {"audio": {"type": "audio", "file_path": str(audio)}},
        },
        model_factory=fake_model_factory,
    )

    assert calls == [
        {
            "model_name": "base",
            "device": "cpu",
            "compute_type": "int8",
            "download_root": str(tmp_path / "models/fw"),
        }
    ]


def test_faster_whisper_transcribe_forwards_optional_decoder_controls(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")

    captured = {}

    class RecordingWhisperModel(FakeWhisperModel):
        def transcribe(self, audio_path, **kwargs):
            captured["audio_path"] = audio_path
            captured["kwargs"] = kwargs
            return [FakeSegment()], FakeInfo()

    whisper_plugin.run(
        {
            "tool_name": "transcribe",
            "parameters": {
                "model": "base",
                "device": "cpu",
                "compute_type": "int8",
                "language": "en",
                "word_timestamps": True,
                "vad_filter": True,
                "initial_prompt": "OpenBBQ and Moonshot",
                "hotwords": ["OpenBBQ", "Moonshot"],
                "condition_on_previous_text": False,
                "chunk_length": 30,
                "hallucination_silence_threshold": 1.5,
                "vad_parameters": {"min_silence_duration_ms": 350},
            },
            "inputs": {"audio": {"type": "audio", "file_path": str(audio)}},
        },
        model_factory=RecordingWhisperModel,
    )

    assert captured == {
        "audio_path": str(audio),
        "kwargs": {
            "language": "en",
            "word_timestamps": True,
            "vad_filter": True,
            "initial_prompt": "OpenBBQ and Moonshot",
            "hotwords": "OpenBBQ, Moonshot",
            "condition_on_previous_text": False,
            "chunk_length": 30,
            "hallucination_silence_threshold": 1.5,
            "vad_parameters": {"min_silence_duration_ms": 350},
        },
    }

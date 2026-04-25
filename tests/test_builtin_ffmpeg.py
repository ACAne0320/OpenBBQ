from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin
from tests.builtin_plugin_fakes import RecordingRunner


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

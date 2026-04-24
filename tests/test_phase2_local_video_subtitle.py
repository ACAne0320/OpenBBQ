import json
from pathlib import Path

from openbbq.cli.app import main


def write_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path("tests/fixtures/projects/local-video-subtitle/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(source, encoding="utf-8")
    return project


def test_cli_imports_video_and_runs_local_video_subtitle_with_fake_media_plugins(
    tmp_path, monkeypatch, capsys
):
    from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin
    from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin

    def fake_runner(command):
        Path(command[-1]).write_bytes(b"audio")

    class FakeSegment:
        start = 0.0
        end = 1.0
        text = "Hello OpenBBQ"
        avg_logprob = -0.1
        words = []

    class FakeInfo:
        language = "en"
        duration = 1.0

    class FakeWhisperModel:
        def __init__(self, model, device, compute_type, download_root=None):
            pass

        def transcribe(self, audio_path, language=None, word_timestamps=True, vad_filter=False):
            return [FakeSegment()], FakeInfo()

    monkeypatch.setattr(ffmpeg_plugin, "_run_subprocess", fake_runner)
    monkeypatch.setattr(whisper_plugin, "_default_model_factory", FakeWhisperModel)

    project = write_project(tmp_path)
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"video")

    assert (
        main(
            [
                "--project",
                str(project),
                "--json",
                "artifact",
                "import",
                str(video),
                "--type",
                "video",
                "--name",
                "source.video",
            ]
        )
        == 0
    )
    imported = json.loads(capsys.readouterr().out)
    artifact_id = imported["artifact"]["id"]

    config_path = project / "openbbq.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "project.art_imported_video", f"project.{artifact_id}"
        ),
        encoding="utf-8",
    )

    assert main(["--project", str(project), "--json", "run", "local-video-subtitle"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"

    assert (
        main(
            [
                "--project",
                str(project),
                "--json",
                "artifact",
                "list",
                "--workflow",
                "local-video-subtitle",
            ]
        )
        == 0
    )
    artifacts = json.loads(capsys.readouterr().out)["artifacts"]
    assert [artifact["name"] for artifact in artifacts] == [
        "extract_audio.audio",
        "transcribe.transcript",
        "subtitle.subtitle",
    ]

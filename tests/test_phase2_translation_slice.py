import json
from pathlib import Path

from openbbq.cli.app import main


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeChatCompletions:
    def create(self, **kwargs):
        user_content = kwargs["messages"][1]["content"]
        request = json.loads(user_content)
        translated = [
            {"index": segment["index"], "text": f"[zh-Hans] {segment['text']}"}
            for segment in request["segments"]
        ]
        return FakeCompletion(json.dumps(translated, ensure_ascii=False))


class FakeChat:
    completions = FakeChatCompletions()


class FakeOpenAIClient:
    chat = FakeChat()


def write_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path("tests/fixtures/projects/local-video-translate-subtitle/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(source, encoding="utf-8")
    return project


def test_cli_runs_local_video_translate_subtitle_with_fake_plugins(tmp_path, monkeypatch, capsys):
    from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin
    from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin
    from openbbq.builtin_plugins.translation import plugin as translation_plugin

    user_config = tmp_path / "user-config.toml"
    user_config.write_text(
        """
version = 1
[providers.openai]
type = "openai_compatible"
base_url = "https://llm.example/v1"
api_key = "env:OPENBBQ_LLM_API_KEY"
default_chat_model = "gpt-4o-mini"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "test-key")

    def fake_runner(command):
        Path(command[-1]).write_bytes(b"audio")

    class FakeSegment:
        start = 0.0
        end = 1.0
        text = "Hello Open BBQ"
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

    def fake_client_factory(*, api_key, base_url):
        assert api_key == "test-key"
        assert base_url == "https://llm.example/v1"
        return FakeOpenAIClient()

    monkeypatch.setattr(ffmpeg_plugin, "_run_subprocess", fake_runner)
    monkeypatch.setattr(whisper_plugin, "_default_model_factory", FakeWhisperModel)
    monkeypatch.setattr(translation_plugin, "_default_client_factory", fake_client_factory)

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

    assert main(["--project", str(project), "--json", "run", "local-video-translate-subtitle"]) == 0
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
                "local-video-translate-subtitle",
            ]
        )
        == 0
    )
    artifacts = json.loads(capsys.readouterr().out)["artifacts"]
    assert [artifact["name"] for artifact in artifacts] == [
        "extract_audio.audio",
        "transcribe.transcript",
        "glossary.transcript",
        "segment.subtitle_segments",
        "translate.translation",
        "subtitle.subtitle",
    ]

    subtitle_id = artifacts[-1]["id"]
    assert main(["--project", str(project), "--json", "artifact", "show", subtitle_id]) == 0
    subtitle = json.loads(capsys.readouterr().out)
    assert "[zh-Hans] Hello OpenBBQ" in subtitle["current_version"]["content"]

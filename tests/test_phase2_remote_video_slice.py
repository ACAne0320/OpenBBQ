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
        request = json.loads(kwargs["messages"][1]["content"])
        translated = [
            {"index": segment["index"], "text": f"[zh-Hans] {segment['text']}"}
            for segment in request["segments"]
        ]
        return FakeCompletion(json.dumps(translated, ensure_ascii=False))


class FakeChat:
    completions = FakeChatCompletions()


class FakeOpenAIClient:
    chat = FakeChat()


class FakeDownloader:
    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def extract_info(self, url, download=True):
        output = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        return {"id": "remote-1", "title": "Remote Test", "extractor": "generic"}


def write_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path("tests/fixtures/projects/remote-video-translate-subtitle/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(source, encoding="utf-8")
    return project


def test_cli_runs_remote_video_translate_subtitle_with_fake_plugins(tmp_path, monkeypatch, capsys):
    from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin
    from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin
    from openbbq.builtin_plugins.llm import plugin as llm_plugin
    from openbbq.builtin_plugins.remote_video import plugin as remote_video_plugin

    def fake_downloader_factory(options):
        return FakeDownloader(options)

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
        return FakeOpenAIClient()

    monkeypatch.setattr(remote_video_plugin, "_default_downloader_factory", fake_downloader_factory)
    monkeypatch.setattr(ffmpeg_plugin, "_run_subprocess", fake_runner)
    monkeypatch.setattr(whisper_plugin, "_default_model_factory", FakeWhisperModel)
    monkeypatch.setattr(llm_plugin, "_default_client_factory", fake_client_factory)
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "test-key")
    monkeypatch.setenv("OPENBBQ_LLM_BASE_URL", "https://llm.example/v1")

    project = write_project(tmp_path)

    assert (
        main(
            [
                "--project",
                str(project),
                "--json",
                "run",
                "remote-video-translate-subtitle",
            ]
        )
        == 0
    )
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
                "remote-video-translate-subtitle",
            ]
        )
        == 0
    )
    artifacts = json.loads(capsys.readouterr().out)["artifacts"]
    assert [artifact["name"] for artifact in artifacts] == [
        "download.video",
        "extract_audio.audio",
        "transcribe.transcript",
        "glossary.transcript",
        "translate.translation",
        "subtitle.subtitle",
    ]

    subtitle_id = artifacts[-1]["id"]
    assert main(["--project", str(project), "--json", "artifact", "show", subtitle_id]) == 0
    subtitle = json.loads(capsys.readouterr().out)
    assert "[zh-Hans] Hello OpenBBQ" in subtitle["current_version"]["content"]

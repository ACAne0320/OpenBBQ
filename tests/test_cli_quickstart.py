import json
from importlib import resources
from pathlib import Path

from openbbq.cli.app import main
from openbbq.cli.quickstart import write_youtube_subtitle_workflow


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
        if "target_lang" in request:
            response = [
                {"index": segment["index"], "text": f"[zh] {segment['text']}"}
                for segment in request["segments"]
            ]
        else:
            response = [
                {"index": segment["index"], "text": segment["text"], "status": "unchanged"}
                for segment in request["segments"]
            ]
        return FakeCompletion(json.dumps(response, ensure_ascii=False))


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
        return {"id": "video-1", "title": "Test Video", "extractor": "youtube"}


def test_youtube_workflow_template_is_packaged_as_workflow_dsl():
    template = (
        resources.files("openbbq.workflow_templates.youtube_subtitle")
        .joinpath("openbbq.yaml")
        .read_text(encoding="utf-8")
    )

    assert "workflows:" in template
    assert "youtube-to-srt:" in template
    assert "tool_ref: remote_video.download" in template
    assert "tool_ref: translation.translate" in template


def test_youtube_workflow_generation_can_create_isolated_jobs(tmp_path):
    first = write_youtube_subtitle_workflow(
        workspace_root=tmp_path,
        url="https://www.youtube.com/watch?v=one",
        source_lang="en",
        target_lang="zh",
        provider="openai",
        model=None,
        asr_model="tiny",
        asr_device="cpu",
        asr_compute_type="int8",
        quality="best",
        auth="auto",
        browser=None,
        browser_profile=None,
        run_id="job-one",
    )
    second = write_youtube_subtitle_workflow(
        workspace_root=tmp_path,
        url="https://www.youtube.com/watch?v=two",
        source_lang="en",
        target_lang="ja",
        provider="openai",
        model=None,
        asr_model="tiny",
        asr_device="cpu",
        asr_compute_type="int8",
        quality="best",
        auth="auto",
        browser=None,
        browser_profile=None,
        run_id="job-two",
    )

    assert first.project_root != second.project_root
    assert first.config_path.is_file()
    assert second.config_path.is_file()
    assert "watch?v=one" in first.config_path.read_text(encoding="utf-8")
    assert "watch?v=two" in second.config_path.read_text(encoding="utf-8")


def test_auth_set_with_secret_reference_writes_provider_and_check_resolves_env(
    tmp_path, monkeypatch, capsys
):
    user_config = tmp_path / "config.toml"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-test")

    code = main(
        [
            "--json",
            "auth",
            "set",
            "openai",
            "--type",
            "openai_compatible",
            "--base-url",
            "https://api.openai.com/v1",
            "--api-key-ref",
            "env:OPENBBQ_LLM_API_KEY",
            "--default-chat-model",
            "gpt-4o-mini",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    rendered = user_config.read_text(encoding="utf-8")
    assert 'api_key = "env:OPENBBQ_LLM_API_KEY"' in rendered
    assert "sk-test" not in rendered

    code = main(["--json", "auth", "check", "openai"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["provider"]["name"] == "openai"
    assert payload["secret"]["resolved"] is True
    assert payload["secret"]["value_preview"] == "sk-...test"


def test_auth_set_json_requires_api_key_ref(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "config.toml"))

    code = main(["--json", "auth", "set", "openai", "--type", "openai_compatible"])

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "api-key-ref" in payload["error"]["message"]


def test_auth_set_without_secret_reference_prompts_and_uses_keyring_default(
    tmp_path, monkeypatch, capsys
):
    from openbbq.cli import app

    class FakeSecretResolver:
        calls = []

        def set_secret(self, reference, value):
            self.calls.append((reference, value))

    user_config = tmp_path / "config.toml"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))
    monkeypatch.setattr(app.getpass, "getpass", lambda prompt: "sk-prompt")
    monkeypatch.setattr(app, "SecretResolver", FakeSecretResolver)

    code = main(["auth", "set", "openai", "--default-chat-model", "gpt-4o-mini"])

    assert code == 0
    assert capsys.readouterr().out.strip() == "Configured provider 'openai'."
    assert FakeSecretResolver.calls == [("keyring:openbbq/providers/openai/api_key", "sk-prompt")]
    rendered = user_config.read_text(encoding="utf-8")
    assert 'api_key = "keyring:openbbq/providers/openai/api_key"' in rendered
    assert "sk-prompt" not in rendered


def test_subtitle_youtube_runs_generated_workflow_and_writes_output(tmp_path, monkeypatch, capsys):
    from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin
    from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin
    from openbbq.builtin_plugins.remote_video import plugin as remote_video_plugin
    from openbbq.builtin_plugins.transcript import plugin as transcript_plugin
    from openbbq.builtin_plugins.translation import plugin as translation_plugin

    user_config = tmp_path / "user-config.toml"
    model_cache_dir = tmp_path / "models/fw"
    user_config.write_text(
        f"""
version = 1
[providers.openai]
type = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key = "env:OPENBBQ_LLM_API_KEY"
default_chat_model = "gpt-4o-mini"
[models.faster_whisper]
cache_dir = "{model_cache_dir.as_posix()}"
default_model = "tiny"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-runtime")

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
            assert model == "tiny"
            assert download_root == str(model_cache_dir.resolve())

        def transcribe(self, audio_path, **kwargs):
            assert kwargs["language"] == "en"
            return [FakeSegment()], FakeInfo()

    def fake_client_factory(*, api_key, base_url):
        assert api_key == "sk-runtime"
        assert base_url == "https://api.openai.com/v1"
        return FakeOpenAIClient()

    monkeypatch.setattr(remote_video_plugin, "_default_downloader_factory", fake_downloader_factory)
    monkeypatch.setattr(ffmpeg_plugin, "_run_subprocess", fake_runner)
    monkeypatch.setattr(whisper_plugin, "_default_model_factory", FakeWhisperModel)
    monkeypatch.setattr(transcript_plugin, "_default_client_factory", fake_client_factory)
    monkeypatch.setattr(translation_plugin, "_default_client_factory", fake_client_factory)

    project = tmp_path / "workspace"
    output = tmp_path / "out" / "subtitle.srt"

    code = main(
        [
            "--project",
            str(project),
            "--json",
            "subtitle",
            "youtube",
            "--url",
            "https://www.youtube.com/watch?v=test",
            "--source",
            "en",
            "--target",
            "zh",
            "--output",
            str(output),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["workflow_id"] == "youtube-to-srt"
    assert payload["output_path"] == str(output.resolve())
    assert output.read_text(encoding="utf-8").splitlines()[2] == "[zh] Hello Open BBQ"
    generated_config = Path(payload["generated_config_path"])
    assert generated_config.is_file()
    assert "https://www.youtube.com/watch?v=test" in generated_config.read_text(encoding="utf-8")

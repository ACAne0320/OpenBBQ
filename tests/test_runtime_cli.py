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


def test_settings_show_json_uses_user_config(tmp_path, monkeypatch, capsys):
    user_config = tmp_path / "config.toml"
    user_config.write_text(
        """
version = 1
[providers.openai]
type = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key = "env:OPENBBQ_LLM_API_KEY"
default_chat_model = "gpt-4o-mini"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))

    code = main(["--json", "settings", "show"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["settings"]["providers"]["openai"]["api_key"] == "env:OPENBBQ_LLM_API_KEY"


def test_settings_set_provider_writes_user_config(tmp_path, monkeypatch, capsys):
    user_config = tmp_path / "config.toml"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))

    code = main(
        [
            "--json",
            "settings",
            "set-provider",
            "openai",
            "--type",
            "openai_compatible",
            "--base-url",
            "https://api.openai.com/v1",
            "--api-key",
            "env:OPENBBQ_LLM_API_KEY",
            "--default-chat-model",
            "gpt-4o-mini",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    rendered = user_config.read_text(encoding="utf-8")
    assert rendered.count("[providers.openai]") == 1
    assert "gpt-4o-mini" in rendered


def test_settings_set_provider_rejects_unknown_type(tmp_path, monkeypatch, capsys):
    user_config = tmp_path / "config.toml"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))

    code = main(
        [
            "--json",
            "settings",
            "set-provider",
            "openai",
            "--type",
            "custom",
        ]
    )

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "providers.openai.type" in payload["error"]["message"]
    assert not user_config.exists()


def test_settings_set_provider_rejects_literal_api_key(tmp_path, monkeypatch, capsys):
    user_config = tmp_path / "config.toml"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))

    code = main(
        [
            "--json",
            "settings",
            "set-provider",
            "openai",
            "--type",
            "openai_compatible",
            "--api-key",
            "sk-should-not-be-here",
        ]
    )

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "providers.openai.api_key" in payload["error"]["message"]
    assert not user_config.exists()


def test_secret_check_json_reports_unresolved_env(monkeypatch, capsys):
    monkeypatch.delenv("OPENBBQ_LLM_API_KEY", raising=False)

    code = main(["--json", "secret", "check", "env:OPENBBQ_LLM_API_KEY"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["secret"]["resolved"] is False
    assert "OPENBBQ_LLM_API_KEY" in payload["secret"]["error"]


def test_secret_set_rejects_json_mode(capsys):
    code = main(["--json", "secret", "set", "keyring:openbbq/providers/openai/api_key"])

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "interactive" in payload["error"]["message"].lower()


def test_models_list_json_reports_faster_whisper_cache(tmp_path, monkeypatch, capsys):
    user_config = tmp_path / "config.toml"
    cache_dir = tmp_path / "models/fw"
    user_config.write_text(
        f"""
version = 1
[models.faster_whisper]
cache_dir = "{cache_dir.as_posix()}"
default_model = "base"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))

    code = main(["--json", "models", "list"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["models"][0]["provider"] == "faster-whisper"
    assert payload["models"][0]["model"] == "base"


def test_doctor_json_reports_checks(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    project = tmp_path / "project"
    project.mkdir()
    source = Path("tests/fixtures/projects/text-basic/openbbq.yaml").read_text(encoding="utf-8")
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )

    code = main(["--project", str(project), "--json", "doctor", "--workflow", "text-demo"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert isinstance(payload["checks"], list)


def test_doctor_without_workflow_reports_settings_checks(tmp_path, monkeypatch, capsys):
    user_config = tmp_path / "user-config.toml"
    cache_dir = tmp_path / "cache"
    user_config.write_text(
        f"""
version = 1
[cache]
root = "{cache_dir.as_posix()}"
[providers.openai]
type = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key = "env:OPENBBQ_LLM_API_KEY"
default_chat_model = "gpt-4o-mini"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))
    monkeypatch.delenv("OPENBBQ_LLM_API_KEY", raising=False)

    code = main(["--json", "doctor"])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    check_ids = {check["id"] for check in payload["checks"]}
    assert "cache.root_writable" in check_ids
    assert "provider.openai.api_key" in check_ids


def test_doctor_returns_nonzero_when_required_checks_fail(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.delenv("OPENBBQ_LLM_API_KEY", raising=False)
    project = tmp_path / "project"
    project.mkdir()
    source = Path(
        "tests/fixtures/projects/local-video-corrected-translate-subtitle/openbbq.yaml"
    ).read_text(encoding="utf-8")
    source = source.replace("provider: openai_compatible", "provider: openai")
    (project / "openbbq.yaml").write_text(source, encoding="utf-8")

    code = main(
        [
            "--project",
            str(project),
            "--json",
            "doctor",
            "--workflow",
            "local-video-corrected-translate-subtitle",
        ]
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert any(check["id"] == "provider.openai.configured" for check in payload["checks"])


def test_cli_run_builds_runtime_context_from_user_settings(tmp_path, monkeypatch, capsys):
    from openbbq.builtin_plugins.faster_whisper import plugin as whisper_plugin
    from openbbq.builtin_plugins.ffmpeg import plugin as ffmpeg_plugin
    from openbbq.builtin_plugins.transcript import plugin as transcript_plugin
    from openbbq.builtin_plugins.translation import plugin as translation_plugin

    model_cache_dir = tmp_path / "models/fw"
    user_config = tmp_path / "user-config.toml"
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
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(user_config))
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-runtime")

    def fake_runner(command):
        Path(command[-1]).write_bytes(b"audio")

    class FakeSegment:
        start = 0.0
        end = 1.0
        text = "Hello"
        avg_logprob = -0.1
        words = []

    class FakeInfo:
        language = "en"
        duration = 1.0

    class FakeWhisperModel:
        def __init__(self, model, device, compute_type, download_root=None):
            assert download_root == str(model_cache_dir.resolve())

        def transcribe(self, audio_path, **kwargs):
            return [FakeSegment()], FakeInfo()

    def fake_client_factory(*, api_key, base_url):
        assert api_key == "sk-runtime"
        assert base_url == "https://api.openai.com/v1"
        return FakeOpenAIClient()

    monkeypatch.setattr(ffmpeg_plugin, "_run_subprocess", fake_runner)
    monkeypatch.setattr(whisper_plugin, "_default_model_factory", FakeWhisperModel)
    monkeypatch.setattr(transcript_plugin, "_default_client_factory", fake_client_factory)
    monkeypatch.setattr(translation_plugin, "_default_client_factory", fake_client_factory)

    project = tmp_path / "project"
    project.mkdir()
    source = Path(
        "tests/fixtures/projects/local-video-corrected-translate-subtitle/openbbq.yaml"
    ).read_text(encoding="utf-8")
    source = source.replace(
        "source_lang: en\n          model: gpt-4o-mini",
        "source_lang: en\n          provider: openai",
    )
    source = source.replace("provider: openai_compatible", "provider: openai")
    source = source.replace("\n          model: gpt-4o-mini", "")
    (project / "openbbq.yaml").write_text(source, encoding="utf-8")
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
    artifact_id = json.loads(capsys.readouterr().out)["artifact"]["id"]
    config_path = project / "openbbq.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "project.art_imported_video", f"project.{artifact_id}"
        ),
        encoding="utf-8",
    )

    code = main(
        ["--project", str(project), "--json", "run", "local-video-corrected-translate-subtitle"]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"

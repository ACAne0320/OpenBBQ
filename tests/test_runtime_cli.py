import json
from pathlib import Path

from openbbq.cli.app import main


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
    assert payload["models"][0]["provider"] == "faster_whisper"
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

from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from openbbq.api.app import ApiAppSettings, create_app


def write_project(tmp_path, fixture_name: str) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path(f"tests/fixtures/projects/{fixture_name}/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(Path.cwd() / "tests/fixtures/plugins")),
        encoding="utf-8",
    )
    return project


def authed_client(project):
    client = TestClient(
        create_app(ApiAppSettings(project_root=project, token="token", execute_runs_inline=True))
    )
    return client, {"Authorization": "Bearer token"}


def test_project_and_plugin_routes(tmp_path):
    project = write_project(tmp_path, "text-basic")
    client, headers = authed_client(project)

    project_response = client.get("/projects/current", headers=headers)
    plugins_response = client.get("/plugins", headers=headers)
    plugin_response = client.get("/plugins/mock_text", headers=headers)

    assert project_response.status_code == 200
    assert project_response.json()["data"]["name"] == "Text Basic"
    assert plugins_response.json()["data"]["plugins"][0]["name"] == "mock_text"
    assert plugin_response.json()["data"]["plugin"]["name"] == "mock_text"


def test_project_init_route_creates_project_config(tmp_path):
    project = tmp_path / "new-project"
    client = TestClient(create_app(ApiAppSettings(token="token")))
    headers = {"Authorization": "Bearer token"}

    response = client.post(
        "/projects/init",
        headers=headers,
        json={"project_root": str(project)},
    )

    assert response.status_code == 200
    assert response.json()["data"]["config_path"] == str(project / "openbbq.yaml")
    assert (project / "openbbq.yaml").is_file()


def test_runtime_routes(tmp_path, monkeypatch):
    project = write_project(tmp_path, "text-basic")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    client, headers = authed_client(project)

    settings_response = client.get("/runtime/settings", headers=headers)
    models_response = client.get("/runtime/models", headers=headers)
    doctor_response = client.get("/doctor", headers=headers)

    assert settings_response.status_code == 200
    assert "settings" in settings_response.json()["data"]
    assert models_response.json()["data"]["models"][0]["provider"] == "faster_whisper"
    assert isinstance(doctor_response.json()["data"]["checks"], list)


def test_runtime_auth_and_secret_routes(tmp_path, monkeypatch):
    project = write_project(tmp_path, "text-basic")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-test")
    client, headers = authed_client(project)

    provider = client.put(
        "/runtime/providers/openai/auth",
        headers=headers,
        json={
            "type": "openai_compatible",
            "api_key_ref": "env:OPENBBQ_LLM_API_KEY",
            "default_chat_model": "gpt-4o-mini",
        },
    )
    check = client.get("/runtime/providers/openai/check", headers=headers)
    secret = client.post(
        "/runtime/secrets/check",
        headers=headers,
        json={"reference": "env:OPENBBQ_LLM_API_KEY"},
    )

    assert provider.status_code == 200
    assert provider.json()["data"]["provider"]["name"] == "openai"
    assert check.json()["data"]["secret"]["resolved"] is True
    assert secret.json()["data"]["secret"]["value_preview"] == "sk-...test"


def test_runtime_auth_route_stores_user_secret_in_sqlite(tmp_path, monkeypatch):
    project = write_project(tmp_path, "text-basic")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    client, headers = authed_client(project)

    response = client.put(
        "/runtime/providers/openai/auth",
        headers=headers,
        json={
            "type": "openai_compatible",
            "secret_value": "sk-api",
            "default_chat_model": "gpt-4o-mini",
        },
    )
    check = client.get("/runtime/providers/openai/check", headers=headers)

    with sqlite3.connect(tmp_path / "openbbq.db") as connection:
        row = connection.execute(
            "select reference, value from credentials"
        ).fetchone()

    assert response.status_code == 200
    assert response.json()["data"]["provider"]["api_key"] == (
        "sqlite:openbbq/providers/openai/api_key"
    )
    assert check.json()["data"]["secret"]["resolved"] is True
    assert row == ("sqlite:openbbq/providers/openai/api_key", "sk-api")

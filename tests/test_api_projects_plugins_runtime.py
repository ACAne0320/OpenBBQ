from pathlib import Path

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
        create_app(
            ApiAppSettings(project_root=project, token="token", execute_runs_inline=True)
        )
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

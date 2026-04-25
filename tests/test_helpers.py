from pathlib import Path

from tests.helpers import authed_client, write_project_fixture


def test_write_project_fixture_copies_config_and_rewrites_plugin_path(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")

    config_text = (project / "openbbq.yaml").read_text(encoding="utf-8")

    assert project == tmp_path / "project"
    assert "../../plugins" not in config_text
    assert str((Path(__file__).parent / "fixtures" / "plugins").resolve()) in config_text


def test_authed_client_returns_standard_token_headers(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project)

    response = client.get("/projects/current", headers=headers)

    assert headers == {"Authorization": "Bearer token"}
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Text Basic"

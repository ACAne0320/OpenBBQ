from fastapi.testclient import TestClient

from openbbq.api.app import ApiAppSettings, create_app


def test_health_is_available_without_token(tmp_path):
    app = create_app(ApiAppSettings(project_root=tmp_path, token="secret-token"))
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["project_root"] == str(tmp_path)


def test_authorized_route_requires_bearer_token(tmp_path):
    app = create_app(ApiAppSettings(project_root=tmp_path, token="secret-token"))
    client = TestClient(app)

    response = client.get("/projects/current")

    assert response.status_code == 401
    assert response.json() == {
        "ok": False,
        "error": {
            "code": "unauthorized",
            "message": "Missing or invalid bearer token.",
            "details": {},
        },
    }


def test_authorized_route_accepts_bearer_token(tmp_path):
    app = create_app(ApiAppSettings(project_root=tmp_path, token="secret-token"))
    client = TestClient(app)
    (tmp_path / "openbbq.yaml").write_text(
        "version: 1\n\nproject:\n  name: Demo\n\nworkflows: {}\n",
        encoding="utf-8",
    )

    response = client.get(
        "/projects/current",
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code != 401

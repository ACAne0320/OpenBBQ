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


def test_workflow_run_and_artifact_routes(tmp_path):
    project = write_project(tmp_path, "text-basic")
    client = TestClient(
        create_app(ApiAppSettings(project_root=project, token="token", execute_runs_inline=True))
    )
    headers = {"Authorization": "Bearer token"}

    workflows = client.get("/workflows", headers=headers)
    validate = client.post("/workflows/text-demo/validate", headers=headers)
    run = client.post(
        "/workflows/text-demo/runs",
        headers=headers,
        json={"project_root": str(project), "workflow_id": "text-demo"},
    )

    assert workflows.status_code == 200
    assert workflows.json()["data"]["workflows"][0]["id"] == "text-demo"
    assert validate.json()["data"]["workflow_id"] == "text-demo"
    assert run.status_code == 200
    run_id = run.json()["data"]["id"]

    run_status = client.get(f"/runs/{run_id}", headers=headers)
    artifacts = client.get("/artifacts", headers=headers)

    assert run_status.json()["data"]["workflow_id"] == "text-demo"
    assert artifacts.status_code == 200


def test_run_route_uses_sidecar_project_and_lists_runs(tmp_path):
    project = write_project(tmp_path, "text-basic")
    client = TestClient(
        create_app(ApiAppSettings(project_root=project, token="token", execute_runs_inline=True))
    )
    headers = {"Authorization": "Bearer token"}

    run = client.post("/workflows/text-demo/runs", headers=headers, json={})
    runs = client.get("/runs", headers=headers)

    assert run.status_code == 200
    assert runs.status_code == 200
    assert [item["id"] for item in runs.json()["data"]["runs"]] == [run.json()["data"]["id"]]


def test_run_route_rejects_project_root_outside_sidecar_project(tmp_path):
    project = write_project(tmp_path, "text-basic")
    other_project = tmp_path / "other-project"
    other_project.mkdir()
    client = TestClient(
        create_app(ApiAppSettings(project_root=project, token="token", execute_runs_inline=True))
    )
    headers = {"Authorization": "Bearer token"}

    response = client.post(
        "/workflows/text-demo/runs",
        headers=headers,
        json={"project_root": str(other_project)},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_request_validation_errors_use_api_error_envelope(tmp_path):
    project = write_project(tmp_path, "text-basic")
    client = TestClient(
        create_app(ApiAppSettings(project_root=project, token="token", execute_runs_inline=True))
    )
    headers = {"Authorization": "Bearer token"}

    response = client.post(
        "/workflows/text-demo/runs",
        headers=headers,
        json={"force": True, "step_id": "uppercase"},
    )

    assert response.status_code == 422
    assert response.json()["ok"] is False
    assert response.json()["error"]["code"] == "validation_error"
    assert "force cannot be combined" in response.json()["error"]["message"]


def test_artifact_route_filters_and_serves_file_backed_versions(tmp_path):
    project = write_project(tmp_path, "text-basic")
    client = TestClient(
        create_app(ApiAppSettings(project_root=project, token="token", execute_runs_inline=True))
    )
    headers = {"Authorization": "Bearer token"}
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake-video")

    run = client.post("/workflows/text-demo/runs", headers=headers, json={})
    text_artifacts = client.get(
        "/artifacts?workflow_id=text-demo&artifact_type=text",
        headers=headers,
    )
    imported = client.post(
        "/artifacts/import",
        headers=headers,
        json={
            "path": str(video),
            "artifact_type": "video",
            "name": "source.video",
        },
    )
    version_id = imported.json()["data"]["version"]["id"]
    file_response = client.get(f"/artifact-versions/{version_id}/file", headers=headers)

    assert run.status_code == 200
    assert text_artifacts.status_code == 200
    assert [artifact["type"] for artifact in text_artifacts.json()["data"]["artifacts"]] == [
        "text",
        "text",
    ]
    assert imported.status_code == 200
    assert file_response.status_code == 200
    assert file_response.content == b"fake-video"

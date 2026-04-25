from tests.helpers import authed_client, write_project_fixture


def test_workflow_run_and_artifact_routes(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project)

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
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project)

    run = client.post("/workflows/text-demo/runs", headers=headers, json={})
    runs = client.get("/runs", headers=headers)

    assert run.status_code == 200
    assert runs.status_code == 200
    assert [item["id"] for item in runs.json()["data"]["runs"]] == [run.json()["data"]["id"]]


def test_run_route_rejects_project_root_outside_sidecar_project(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    other_project = tmp_path / "other-project"
    other_project.mkdir()
    client, headers = authed_client(project)

    response = client.post(
        "/workflows/text-demo/runs",
        headers=headers,
        json={"project_root": str(other_project)},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_missing_run_uses_api_not_found_envelope(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project, raise_server_exceptions=False)

    response = client.get("/runs/missing", headers=headers)

    assert response.status_code == 404
    assert response.json() == {
        "ok": False,
        "error": {
            "code": "run_not_found",
            "message": "run not found: missing",
            "details": {},
        },
    }


def test_missing_artifact_uses_artifact_not_found_envelope(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project, raise_server_exceptions=False)

    response = client.get("/artifacts/missing", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "artifact_not_found"
    assert response.json()["error"]["message"] == "artifact not found: missing"


def test_request_validation_errors_use_api_error_envelope(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project)

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
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project)
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


def test_artifact_version_preview_and_export_routes(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project)

    client.post("/workflows/text-demo/runs", headers=headers, json={})
    artifacts = client.get(
        "/artifacts?workflow_id=text-demo&artifact_type=text",
        headers=headers,
    )
    version_id = artifacts.json()["data"]["artifacts"][0]["current_version_id"]
    preview = client.get(
        f"/artifact-versions/{version_id}/preview?max_bytes=4",
        headers=headers,
    )
    output = tmp_path / "exported.txt"
    exported = client.post(
        f"/artifact-versions/{version_id}/export",
        headers=headers,
        json={"path": str(output)},
    )

    assert preview.status_code == 200
    assert preview.json()["data"]["version"]["id"] == version_id
    assert preview.json()["data"]["truncated"] is True
    assert exported.status_code == 200
    assert exported.json()["data"]["path"] == str(output)
    assert output.is_file()

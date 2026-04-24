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

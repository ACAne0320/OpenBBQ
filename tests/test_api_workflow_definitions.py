from tests.helpers import authed_client, write_project_fixture


def test_workflow_definition_routes_list_builtins_and_save_custom(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    custom_root = tmp_path / "workflow_custom"
    monkeypatch.setenv("OPENBBQ_WORKFLOW_CUSTOM_ROOT", str(custom_root))
    client, headers = authed_client(project)

    listed = client.get("/workflow-definitions", headers=headers)

    assert listed.status_code == 200
    workflows = listed.json()["data"]["workflows"]
    assert [workflow["id"] for workflow in workflows[:2]] == ["local-subtitle", "youtube-subtitle"]

    local = workflows[0]
    saved = client.put(
        "/workflow-definitions/local-subtitle-custom",
        headers=headers,
        json={
            "id": "local-subtitle-custom",
            "name": "Local video custom",
            "description": "Saved local workflow",
            "source_types": local["source_types"],
            "result_types": local["result_types"],
            "steps": local["steps"],
        },
    )

    assert saved.status_code == 200
    assert saved.json()["data"]["origin"] == "custom"
    assert (custom_root / "local-subtitle-custom.yaml").is_file()

    relisted = client.get("/workflow-definitions", headers=headers)
    ids = [workflow["id"] for workflow in relisted.json()["data"]["workflows"]]
    assert "local-subtitle-custom" in ids


def test_workflow_definition_route_rejects_builtin_id_conflict(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    monkeypatch.setenv("OPENBBQ_WORKFLOW_CUSTOM_ROOT", str(tmp_path / "workflow_custom"))
    client, headers = authed_client(project)
    local = client.get("/workflow-definitions", headers=headers).json()["data"]["workflows"][0]

    response = client.put(
        "/workflow-definitions/local-subtitle",
        headers=headers,
        json={
            "id": "local-subtitle",
            "name": "Conflicting workflow",
            "description": "Should fail",
            "source_types": local["source_types"],
            "result_types": local["result_types"],
            "steps": local["steps"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

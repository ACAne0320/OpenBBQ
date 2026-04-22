import json
from pathlib import Path

from openbbq.cli import main
from openbbq.storage import ProjectStore


def write_project(tmp_path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "openbbq.yaml").write_text(
        """
version: 1
project:
  name: Artifact Diff
workflows:
  demo:
    name: Demo
    steps:
      - id: seed
        name: Seed
        tool_ref: mock_text.echo
        inputs:
          text: hello
        outputs:
          - name: text
            type: text
""",
        encoding="utf-8",
    )
    return project


def write_version_pair(store: ProjectStore):
    artifact, first = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello\n",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "demo", "step_id": "seed"},
    )
    _, second = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello openbbq\n",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "demo", "step_id": "seed"},
        artifact_id=artifact.id,
    )
    return first, second


def test_cli_artifact_diff_outputs_unified_diff(tmp_path, capsys):
    project = write_project(tmp_path)
    store = ProjectStore(project / ".openbbq")
    first, second = write_version_pair(store)

    code = main(["--project", str(project), "artifact", "diff", first.id, second.id])

    assert code == 0
    output = capsys.readouterr().out
    assert f"--- {first.id}" in output
    assert f"+++ {second.id}" in output
    assert "-hello" in output
    assert "+hello openbbq" in output


def test_cli_artifact_diff_json_output(tmp_path, capsys):
    project = write_project(tmp_path)
    store = ProjectStore(project / ".openbbq")
    first, second = write_version_pair(store)

    code = main(["--project", str(project), "--json", "artifact", "diff", first.id, second.id])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["from"] == first.id
    assert payload["to"] == second.id
    assert payload["format"] == "unified"
    assert "+hello openbbq" in payload["diff"]


def test_cli_artifact_diff_rejects_binary_versions(tmp_path, capsys):
    project = write_project(tmp_path)
    store = ProjectStore(project / ".openbbq")
    _, first = store.write_artifact_version(
        artifact_type="text",
        name="binary.text",
        content=b"hello",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "demo", "step_id": "seed"},
    )

    code = main(["--project", str(project), "--json", "artifact", "diff", first.id, first.id])

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "validation_error"


def test_cli_artifact_list_filters_by_workflow(tmp_path, capsys):
    project = write_project(tmp_path)
    store = ProjectStore(project / ".openbbq")
    store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "demo", "step_id": "seed"},
    )
    store.write_artifact_version(
        artifact_type="text",
        name="other.text",
        content="other",
        metadata={},
        created_by_step_id="other",
        lineage={"workflow_id": "other", "step_id": "other"},
    )

    code = main(["--project", str(project), "--json", "artifact", "list", "--workflow", "demo"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [artifact["name"] for artifact in payload["artifacts"]] == ["seed.text"]

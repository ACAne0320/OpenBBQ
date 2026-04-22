import json
from pathlib import Path

from openbbq.cli.app import main
from openbbq.storage.project_store import ProjectStore


def write_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "openbbq.yaml").write_text(
        """
version: 1
project:
  name: Import Demo
workflows:
  demo:
    name: Demo
    steps:
      - id: noop
        name: Noop
        tool_ref: missing.noop
        inputs: {}
        outputs:
          - name: text
            type: text
        parameters: {}
        on_error: abort
        max_retries: 0
""",
        encoding="utf-8",
    )
    return project


def test_cli_artifact_import_creates_file_backed_project_artifact(tmp_path, capsys):
    project = write_project(tmp_path)
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"fake-video")

    code = main(
        [
            "--project",
            str(project),
            "--json",
            "artifact",
            "import",
            str(video),
            "--type",
            "video",
            "--name",
            "source.video",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["artifact"]["type"] == "video"
    assert payload["artifact"]["created_by_step_id"] is None
    assert payload["version"]["content_encoding"] == "file"
    assert payload["version"]["lineage"]["source"] == "cli_import"

    store = ProjectStore(project / ".openbbq")
    version = store.read_artifact_version(payload["version"]["id"])
    assert Path(version.content["file_path"]).read_bytes() == b"fake-video"


def test_cli_artifact_import_rejects_unknown_type(tmp_path, capsys):
    project = write_project(tmp_path)
    video = tmp_path / "sample.bin"
    video.write_bytes(b"fake")

    code = main(
        [
            "--project",
            str(project),
            "--json",
            "artifact",
            "import",
            str(video),
            "--type",
            "unknown",
            "--name",
            "source.unknown",
        ]
    )

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "validation_error"

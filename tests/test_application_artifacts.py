from openbbq.application.artifacts import (
    ArtifactImportRequest,
    ArtifactExportRequest,
    export_artifact_version,
    import_artifact,
    list_artifacts,
    preview_artifact_version,
)
from openbbq.config.loader import load_project_config
from openbbq.storage.project_store import ProjectStore


def test_artifact_application_service_imports_file_backed_artifact(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "openbbq.yaml").write_text(
        "version: 1\n\nproject:\n  name: Demo\n\nworkflows: {}\n",
        encoding="utf-8",
    )
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"media")

    imported = import_artifact(
        ArtifactImportRequest(
            project_root=project,
            path=source,
            artifact_type="video",
            name="source.video",
        )
    )
    artifacts = list_artifacts(project_root=project)

    assert imported.artifact.name == "source.video"
    assert [artifact.name for artifact in artifacts] == ["source.video"]


def test_preview_artifact_version_returns_bounded_text_content(tmp_path):
    project, version_id = write_text_artifact(tmp_path, "hello world")

    preview = preview_artifact_version(
        project_root=project,
        version_id=version_id,
        max_bytes=5,
    )

    assert preview.version.id == version_id
    assert preview.content == "hello"
    assert preview.truncated is True
    assert preview.content_encoding == "text"


def test_export_artifact_version_writes_text_content(tmp_path):
    project, version_id = write_text_artifact(tmp_path, "subtitle text")
    output = tmp_path / "exports" / "out.srt"

    result = export_artifact_version(
        ArtifactExportRequest(
            project_root=project,
            version_id=version_id,
            path=output,
        )
    )

    assert result.path == output
    assert result.bytes_written == len("subtitle text".encode("utf-8"))
    assert output.read_text(encoding="utf-8") == "subtitle text"


def write_text_artifact(tmp_path, content: str):
    project = tmp_path / "project"
    project.mkdir()
    (project / "openbbq.yaml").write_text(
        "version: 1\n\nproject:\n  name: Demo\n\nworkflows: {}\n",
        encoding="utf-8",
    )
    config = load_project_config(project)
    store = ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
    artifact, version = store.write_artifact_version(
        artifact_type="text",
        name="demo.text",
        content=content,
        metadata={},
        created_by_step_id=None,
        lineage={"workflow_id": "demo"},
    )
    return project, version.id

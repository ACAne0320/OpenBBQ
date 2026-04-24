from openbbq.application.artifacts import (
    ArtifactImportRequest,
    import_artifact,
    list_artifacts,
)


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

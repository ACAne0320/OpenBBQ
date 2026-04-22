from pathlib import Path

import pytest

from openbbq.storage.project_store import ProjectStore


def test_write_file_backed_artifact_version_copies_file_and_returns_descriptor(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"video-bytes")
    store = ProjectStore(tmp_path / ".openbbq")

    artifact, version = store.write_artifact_version(
        artifact_type="video",
        name="source.video",
        content=None,
        file_path=source,
        metadata={"format": "mp4"},
        created_by_step_id=None,
        lineage={"source": "cli_import", "original_path": str(source.resolve())},
    )

    assert artifact.record["created_by_step_id"] is None
    assert artifact.record["name"] == "source.video"
    assert version.record["content_encoding"] == "file"
    assert version.record["content_size"] == len(b"video-bytes")
    assert Path(version.record["content_path"]).read_bytes() == b"video-bytes"
    assert version.content == {
        "file_path": version.record["content_path"],
        "size": len(b"video-bytes"),
        "sha256": version.record["content_hash"],
    }

    reloaded = store.read_artifact_version(version.id)
    assert reloaded.content == version.content


def test_write_artifact_version_requires_exactly_one_payload(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"x")
    store = ProjectStore(tmp_path / ".openbbq")

    with pytest.raises(ValueError, match="exactly one"):
        store.write_artifact_version(
            artifact_type="video",
            name="bad.video",
            content=b"x",
            file_path=source,
            metadata={},
            created_by_step_id=None,
            lineage={},
        )

    with pytest.raises(ValueError, match="exactly one"):
        store.write_artifact_version(
            artifact_type="video",
            name="bad.video",
            content=None,
            file_path=None,
            metadata={},
            created_by_step_id=None,
            lineage={},
        )

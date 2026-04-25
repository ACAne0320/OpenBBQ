from openbbq.storage.artifact_content import ArtifactContentStore


def test_artifact_content_store_round_trips_json_text_bytes_and_files(tmp_path):
    store = ArtifactContentStore()
    source = tmp_path / "source.bin"
    source.write_bytes(b"file-body")

    json_content = store.write_content(tmp_path / "json" / "content", {"hello": "openbbq"})
    text_content = store.write_content(tmp_path / "text" / "content", "hello")
    bytes_content = store.write_content(tmp_path / "bytes" / "content", b"bytes")
    file_content = store.copy_file(tmp_path / "file" / "content", source)

    assert json_content.encoding == "json"
    assert store.read_content(json_content.path, json_content.encoding, json_content.size) == {
        "hello": "openbbq"
    }
    assert (
        store.read_content(text_content.path, text_content.encoding, text_content.size) == "hello"
    )
    assert (
        store.read_content(bytes_content.path, bytes_content.encoding, bytes_content.size)
        == b"bytes"
    )
    assert store.read_content(file_content.path, file_content.encoding, file_content.size) == {
        "file_path": file_content.path,
        "size": 9,
        "sha256": file_content.sha256,
    }

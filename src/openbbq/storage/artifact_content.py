from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from openbbq.storage.json_files import fsync_parent

ArtifactContentEncoding = Literal["text", "json", "bytes", "file"]


@dataclass(frozen=True)
class StoredContentInfo:
    path: Path
    encoding: ArtifactContentEncoding
    sha256: str
    size: int


class ArtifactContentStore:
    def write_content(self, path: Path, content: Any) -> StoredContentInfo:
        encoding, payload = self._encode_content(content)
        self._write_bytes(path, payload)
        return StoredContentInfo(
            path=path,
            encoding=encoding,
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )

    def copy_file(self, destination: Path, source: Path) -> StoredContentInfo:
        source = Path(source)
        if not source.is_file():
            raise ValueError(f"file-backed artifact source does not exist: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with NamedTemporaryFile(
            "wb",
            dir=destination.parent,
            delete=False,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        ) as handle:
            with source.open("rb") as source_handle:
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    size += len(chunk)
                    digest.update(chunk)
                    handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        temp_path.replace(destination)
        fsync_parent(destination.parent)
        return StoredContentInfo(
            path=destination,
            encoding="file",
            sha256=digest.hexdigest(),
            size=size,
        )

    def read_content(
        self,
        path: Path,
        encoding: ArtifactContentEncoding,
        size: int,
        sha256: str | None = None,
    ) -> Any:
        if encoding == "file":
            return {
                "file_path": path,
                "size": size,
                "sha256": sha256 or self._hash_file(path),
            }
        if encoding == "bytes":
            return path.read_bytes()
        raw = path.read_text(encoding="utf-8")
        if encoding == "json":
            return json.loads(raw)
        return raw

    def _encode_content(self, content: Any) -> tuple[ArtifactContentEncoding, bytes]:
        if isinstance(content, bytes):
            return "bytes", content
        if isinstance(content, (dict, list)):
            return (
                "json",
                json.dumps(
                    content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8"),
            )
        return "text", str(content).encode("utf-8")

    def _write_bytes(self, path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "wb",
            dir=path.parent,
            delete=False,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        temp_path.replace(path)
        fsync_parent(path.parent)

    def _hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

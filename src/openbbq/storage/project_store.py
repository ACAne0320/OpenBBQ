from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from openbbq.domain.base import ArtifactMetadata, JsonObject, LineagePayload
from openbbq.errors import ArtifactNotFoundError
from openbbq.storage.artifacts import (
    ArtifactIndex,
    read_artifact_index,
    write_artifact_index,
)
from openbbq.storage import events as event_storage
from openbbq.storage import workflows as workflow_storage
from openbbq.storage.json_files import (
    fsync_parent,
    read_json_object,
    write_json_atomic,
)
from openbbq.storage.models import (
    ArtifactRecord,
    ArtifactVersionRecord,
    StoredArtifact,
    StoredArtifactVersion,
    StepRunRecord,
    WorkflowEvent,
    WorkflowState,
)


class IdGenerator:
    def artifact_id(self) -> str:
        return f"art_{uuid4().hex}"

    def artifact_version_id(self) -> str:
        return f"av_{uuid4().hex}"

    def step_run_id(self) -> str:
        return f"sr_{uuid4().hex}"

    def workflow_event_id(self) -> str:
        return f"evt_{uuid4().hex}"


class ProjectStore:
    def __init__(
        self,
        root: Path,
        id_generator: IdGenerator | None = None,
        artifacts_root: Path | None = None,
        state_root: Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.id_generator = id_generator or IdGenerator()
        self.artifacts_root = (
            Path(artifacts_root) if artifacts_root is not None else self.root / "artifacts"
        )
        state_base = Path(state_root) if state_root is not None else self.root / "state"
        self.state_root = state_base / "workflows"
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.state_root.mkdir(parents=True, exist_ok=True)

    def write_json_atomic(self, path: Path, data: JsonObject) -> None:
        write_json_atomic(path, data)

    def append_event(self, workflow_id: str, event: JsonObject) -> WorkflowEvent:
        return event_storage.append_event(
            self.state_root,
            workflow_id,
            event,
            id_generator=self.id_generator,
            timestamp=self._timestamp(),
        )

    def write_workflow_state(
        self, workflow_id: str, state: JsonObject | WorkflowState
    ) -> WorkflowState:
        return workflow_storage.write_workflow_state(self.state_root, workflow_id, state)

    def read_workflow_state(self, workflow_id: str) -> WorkflowState:
        return workflow_storage.read_workflow_state(self.state_root, workflow_id)

    def write_step_run(
        self, workflow_id: str, step_run: JsonObject | StepRunRecord
    ) -> StepRunRecord:
        return workflow_storage.write_step_run(
            self.state_root,
            workflow_id,
            step_run,
            id_generator=self.id_generator,
        )

    def read_step_run(self, workflow_id: str, step_run_id: str) -> StepRunRecord:
        return workflow_storage.read_step_run(self.state_root, workflow_id, step_run_id)

    def list_artifacts(self) -> list[ArtifactRecord]:
        artifacts: list[ArtifactRecord] = []
        for artifact_dir in sorted(self.artifacts_root.iterdir(), key=lambda path: path.name):
            artifact_file = artifact_dir / "artifact.json"
            if artifact_file.exists():
                artifacts.append(ArtifactRecord.model_validate(read_json_object(artifact_file)))
        artifacts.sort(key=lambda record: (record.created_at, record.id))
        return artifacts

    def read_artifact(self, artifact_id: str) -> ArtifactRecord:
        artifact_file = self._artifact_dir(artifact_id) / "artifact.json"
        if not artifact_file.exists():
            raise ArtifactNotFoundError(f"artifact not found: {artifact_id}")
        return ArtifactRecord.model_validate(read_json_object(artifact_file))

    def read_artifact_version(self, version_id: str) -> StoredArtifactVersion:
        index = read_artifact_index(self.artifacts_root)
        indexed_path = index.version_paths.get(version_id)
        version_path = Path(indexed_path) if indexed_path is not None else None
        if version_path is not None and not (version_path / "version.json").exists():
            version_path = None
        if version_path is None:
            version_path = self._find_version_path(version_id)
        if version_path is None:
            raise ArtifactNotFoundError(f"artifact version not found: {version_id}")
        record = ArtifactVersionRecord.model_validate(
            read_json_object(version_path / "version.json")
        )
        content_path = record.content_path
        encoding = record.content_encoding
        if encoding == "file":
            content = {
                "file_path": content_path,
                "size": record.content_size,
                "sha256": record.content_hash,
            }
        elif encoding == "bytes":
            content = content_path.read_bytes()
        else:
            raw = content_path.read_text(encoding="utf-8")
            content = json.loads(raw) if encoding == "json" else raw
        return StoredArtifactVersion(record=record, content=content)

    def write_artifact_version(
        self,
        *,
        artifact_type: str,
        name: str,
        content: Any = None,
        file_path: Path | None = None,
        metadata: ArtifactMetadata,
        created_by_step_id: str | None,
        lineage: LineagePayload,
        artifact_id: str | None = None,
    ) -> tuple[StoredArtifact, StoredArtifactVersion]:
        has_content = content is not None
        has_file = file_path is not None
        if has_content == has_file:
            raise ValueError("Artifact versions require exactly one of content or file_path.")
        artifact = self._load_or_create_artifact(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            name=name,
            created_by_step_id=created_by_step_id,
        )
        timestamp = self._timestamp()
        version_id = self.id_generator.artifact_version_id()
        version_number = len(artifact["versions"]) + 1
        version_dir = (
            self._artifact_dir(artifact["id"]) / "versions" / f"{version_number}-{version_id}"
        )
        version_dir.mkdir(parents=True, exist_ok=True)
        content_path = version_dir / "content"
        if file_path is None:
            content_encoding, content_bytes = self._write_content_durably(content_path, content)
            content_hash = hashlib.sha256(content_bytes).hexdigest()
            content_size = len(content_bytes)
            stored_content = self._normalize_content(content, content_encoding)
        else:
            content_encoding, digest, content_size = self._copy_file_durably(
                content_path, file_path
            )
            content_hash = digest.hex()
            stored_content = {
                "file_path": content_path,
                "size": content_size,
                "sha256": content_hash,
            }
        version_record = {
            "id": version_id,
            "artifact_id": artifact["id"],
            "version_number": version_number,
            "content_path": str(content_path),
            "content_hash": content_hash,
            "content_encoding": content_encoding,
            "content_size": content_size,
            "metadata": dict(metadata),
            "lineage": dict(lineage),
            "created_at": timestamp,
        }
        self.write_json_atomic(version_dir / "version.json", version_record)
        artifact["versions"].append(version_id)
        artifact["current_version_id"] = version_id
        artifact["updated_at"] = timestamp
        self.write_json_atomic(self._artifact_dir(artifact["id"]) / "artifact.json", artifact)
        index = read_artifact_index(self.artifacts_root)
        index = index.model_copy(
            update={
                "artifact_paths": {
                    **index.artifact_paths,
                    artifact["id"]: str(self._artifact_dir(artifact["id"])),
                },
                "version_paths": {
                    **index.version_paths,
                    version_id: str(version_dir),
                },
            }
        )
        write_artifact_index(self.artifacts_root, index)
        return (
            StoredArtifact(record=ArtifactRecord.model_validate(artifact)),
            StoredArtifactVersion(
                record=ArtifactVersionRecord.model_validate(version_record),
                content=stored_content,
            ),
        )

    def rebuild_artifact_index(self) -> ArtifactIndex:
        artifact_paths: dict[str, str] = {}
        version_paths: dict[str, str] = {}
        for artifact_dir in sorted(self.artifacts_root.iterdir(), key=lambda path: path.name):
            artifact_file = artifact_dir / "artifact.json"
            if not artifact_file.exists():
                continue
            artifact = ArtifactRecord.model_validate(read_json_object(artifact_file))
            artifact_paths[artifact.id] = str(artifact_dir)
            versions_dir = artifact_dir / "versions"
            if not versions_dir.exists():
                continue
            for version_dir in sorted(versions_dir.iterdir(), key=lambda path: path.name):
                version_file = version_dir / "version.json"
                if not version_file.exists():
                    continue
                record = ArtifactVersionRecord.model_validate(read_json_object(version_file))
                version_paths[record.id] = str(version_dir)
        index = ArtifactIndex(artifact_paths=artifact_paths, version_paths=version_paths)
        write_artifact_index(self.artifacts_root, index)
        return index

    def _load_or_create_artifact(
        self,
        *,
        artifact_id: str | None,
        artifact_type: str,
        name: str,
        created_by_step_id: str | None,
    ) -> JsonObject:
        if artifact_id is not None:
            artifact = self.read_artifact(artifact_id).model_dump(mode="json")
            if artifact["type"] != artifact_type:
                raise ValueError(
                    f"artifact type mismatch for {artifact_id}: {artifact['type']} != {artifact_type}"
                )
            artifact.setdefault("created_by_step_id", created_by_step_id)
            return artifact
        artifact_id = self.id_generator.artifact_id()
        timestamp = self._timestamp()
        artifact = {
            "id": artifact_id,
            "type": artifact_type,
            "name": name,
            "versions": [],
            "current_version_id": None,
            "created_by_step_id": created_by_step_id,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        artifact_dir = self._artifact_dir(artifact_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        self.write_json_atomic(artifact_dir / "artifact.json", artifact)
        return artifact

    def _write_content_durably(self, path: Path, content: Any) -> tuple[str, bytes]:
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            payload = content
            encoding = "bytes"
        elif isinstance(content, (dict, list)):
            payload = json.dumps(
                content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            encoding = "json"
        else:
            payload = str(content).encode("utf-8")
            encoding = "text"
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
        self._fsync_parent(path.parent)
        return encoding, payload

    def _copy_file_durably(self, destination: Path, source: Path) -> tuple[str, bytes, int]:
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
        self._fsync_parent(destination.parent)
        return "file", digest.digest(), size

    def _normalize_content(self, content: Any, encoding: str) -> Any:
        if encoding == "bytes":
            return content
        if encoding == "json":
            return content
        if isinstance(content, str):
            return content
        return str(content)

    def _workflow_dir(self, workflow_id: str) -> Path:
        return workflow_storage.workflow_dir(self.state_root, workflow_id)

    def _artifact_dir(self, artifact_id: str) -> Path:
        return self.artifacts_root / artifact_id

    def _find_version_path(self, version_id: str) -> Path | None:
        for artifact_dir in self.artifacts_root.iterdir():
            versions_dir = artifact_dir / "versions"
            if not versions_dir.exists():
                continue
            for version_dir in versions_dir.iterdir():
                if version_dir.is_dir() and version_dir.name.endswith(f"-{version_id}"):
                    return version_dir
        return None

    def _next_event_sequence(self, events_path: Path) -> int:
        last_sequence = 0
        if not events_path.exists():
            return 1
        with events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    break
                sequence = record.get("sequence")
                if isinstance(sequence, int):
                    last_sequence = sequence
        return last_sequence + 1

    def _truncate_trailing_partial_jsonl_line(self, path: Path) -> None:
        if not path.exists():
            return
        data = path.read_bytes()
        if not data or data.endswith(b"\n"):
            return
        cutoff = data.rfind(b"\n")
        trailing_line = data if cutoff == -1 else data[cutoff + 1 :]
        try:
            json.loads(trailing_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            new_size = 0 if cutoff == -1 else cutoff + 1
        else:
            with path.open("ab") as handle:
                handle.write(b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._fsync_parent(path.parent)
            return
        with path.open("rb+") as handle:
            handle.truncate(new_size)
            handle.flush()
            os.fsync(handle.fileno())
        self._fsync_parent(path.parent)

    def _fsync_parent(self, path: Path) -> None:
        fsync_parent(path)

    def _timestamp(self) -> str:
        from datetime import UTC, datetime

        return datetime.now(UTC).isoformat()

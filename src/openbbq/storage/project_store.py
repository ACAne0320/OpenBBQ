from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping
from uuid import uuid4

from openbbq.errors import ArtifactNotFoundError


class IdGenerator:
    def artifact_id(self) -> str:
        return f"art_{uuid4().hex}"

    def artifact_version_id(self) -> str:
        return f"av_{uuid4().hex}"

    def step_run_id(self) -> str:
        return f"sr_{uuid4().hex}"

    def workflow_event_id(self) -> str:
        return f"evt_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    record: dict[str, Any]

    @property
    def id(self) -> str:
        return self.record["id"]


@dataclass(frozen=True, slots=True)
class StoredArtifactVersion:
    record: dict[str, Any]
    content: Any

    @property
    def id(self) -> str:
        return self.record["id"]

    @property
    def artifact_id(self) -> str:
        return self.record["artifact_id"]


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

    def write_json_atomic(self, path: Path, data: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
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

    def append_event(self, workflow_id: str, event: Mapping[str, Any]) -> dict[str, Any]:
        events_path = self._workflow_dir(workflow_id) / "events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        self._truncate_trailing_partial_jsonl_line(events_path)
        record = dict(event)
        record["workflow_id"] = workflow_id
        record["sequence"] = self._next_event_sequence(events_path)
        record.setdefault("id", self.id_generator.workflow_event_id())
        record.setdefault("created_at", self._timestamp())
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        self._fsync_parent(events_path.parent)
        return record

    def write_workflow_state(self, workflow_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
        state_path = self._workflow_dir(workflow_id) / "state.json"
        record = dict(state)
        record["id"] = workflow_id
        self.write_json_atomic(state_path, record)
        return record

    def read_workflow_state(self, workflow_id: str) -> dict[str, Any]:
        state_path = self._workflow_dir(workflow_id) / "state.json"
        if not state_path.exists():
            raise FileNotFoundError(state_path)
        return json.loads(state_path.read_text(encoding="utf-8"))

    def write_step_run(self, workflow_id: str, step_run: Mapping[str, Any]) -> dict[str, Any]:
        record = dict(step_run)
        record["workflow_id"] = workflow_id
        step_run_id = record.get("id")
        if not step_run_id:
            step_run_id = self.id_generator.step_run_id()
            record["id"] = step_run_id
        path = self._workflow_dir(workflow_id) / "step-runs" / f"{step_run_id}.json"
        self.write_json_atomic(path, record)
        return record

    def read_step_run(self, workflow_id: str, step_run_id: str) -> dict[str, Any]:
        path = self._workflow_dir(workflow_id) / "step-runs" / f"{step_run_id}.json"
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))

    def list_artifacts(self) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for artifact_dir in sorted(self.artifacts_root.iterdir(), key=lambda path: path.name):
            artifact_file = artifact_dir / "artifact.json"
            if artifact_file.exists():
                artifacts.append(json.loads(artifact_file.read_text(encoding="utf-8")))
        artifacts.sort(key=lambda record: (record.get("created_at", ""), record["id"]))
        return artifacts

    def read_artifact(self, artifact_id: str) -> dict[str, Any]:
        artifact_file = self._artifact_dir(artifact_id) / "artifact.json"
        if not artifact_file.exists():
            raise ArtifactNotFoundError(f"artifact not found: {artifact_id}")
        return json.loads(artifact_file.read_text(encoding="utf-8"))

    def read_artifact_version(self, version_id: str) -> StoredArtifactVersion:
        version_path = self._find_version_path(version_id)
        if version_path is None:
            raise ArtifactNotFoundError(f"artifact version not found: {version_id}")
        record = json.loads((version_path / "version.json").read_text(encoding="utf-8"))
        content_path = Path(record["content_path"])
        encoding = record.get("content_encoding", "text")
        if encoding == "bytes":
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
        content: Any,
        metadata: Mapping[str, Any],
        created_by_step_id: str,
        lineage: Mapping[str, Any],
        artifact_id: str | None = None,
    ) -> tuple[StoredArtifact, StoredArtifactVersion]:
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
        content_encoding, content_bytes = self._write_content_durably(content_path, content)
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        version_record = {
            "id": version_id,
            "artifact_id": artifact["id"],
            "version_number": version_number,
            "content_path": str(content_path),
            "content_hash": content_hash,
            "content_encoding": content_encoding,
            "metadata": dict(metadata),
            "lineage": dict(lineage),
            "created_at": timestamp,
        }
        self.write_json_atomic(version_dir / "version.json", version_record)
        artifact["versions"].append(version_id)
        artifact["current_version_id"] = version_id
        artifact["updated_at"] = timestamp
        self.write_json_atomic(self._artifact_dir(artifact["id"]) / "artifact.json", artifact)
        return StoredArtifact(record=artifact), StoredArtifactVersion(
            record=version_record,
            content=self._normalize_content(content, content_encoding),
        )

    def _load_or_create_artifact(
        self,
        *,
        artifact_id: str | None,
        artifact_type: str,
        name: str,
        created_by_step_id: str,
    ) -> dict[str, Any]:
        if artifact_id is not None:
            artifact = self.read_artifact(artifact_id)
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

    def _normalize_content(self, content: Any, encoding: str) -> Any:
        if encoding == "bytes":
            return content
        if encoding == "json":
            return content
        if isinstance(content, str):
            return content
        return str(content)

    def _workflow_dir(self, workflow_id: str) -> Path:
        return self.state_root / workflow_id

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
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _timestamp(self) -> str:
        from datetime import UTC, datetime

        return datetime.now(UTC).isoformat()

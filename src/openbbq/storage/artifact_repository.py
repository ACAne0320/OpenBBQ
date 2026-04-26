from __future__ import annotations

from pathlib import Path
from typing import Any

from openbbq.domain.base import ArtifactMetadata, LineagePayload
from openbbq.errors import ArtifactNotFoundError
from openbbq.storage.artifact_content import ArtifactContentStore
from openbbq.storage.clock import TimestampProvider, utc_timestamp
from openbbq.storage.database import ProjectDatabase
from openbbq.storage.id_generation import ArtifactIdGenerator
from openbbq.storage.models import (
    ArtifactRecord,
    ArtifactVersionRecord,
    StoredArtifact,
    StoredArtifactVersion,
)


class ArtifactRepository:
    def __init__(
        self,
        database: ProjectDatabase,
        *,
        artifacts_root: Path,
        id_generator: ArtifactIdGenerator,
        content_store: ArtifactContentStore | None = None,
        timestamp_provider: TimestampProvider = utc_timestamp,
    ) -> None:
        self.database = database
        self.artifacts_root = Path(artifacts_root)
        self.id_generator = id_generator
        self.content_store = content_store or ArtifactContentStore()
        self.timestamp_provider = timestamp_provider
        self.artifacts_root.mkdir(parents=True, exist_ok=True)

    def list_artifacts(self) -> list[ArtifactRecord]:
        return list(self.database.list_artifacts())

    def read_artifact(self, artifact_id: str) -> ArtifactRecord:
        artifact = self.database.read_artifact(artifact_id)
        if artifact is None:
            raise ArtifactNotFoundError(f"artifact not found: {artifact_id}")
        return artifact

    def read_artifact_version(self, version_id: str) -> StoredArtifactVersion:
        return self._stored_artifact_version_from_record(
            self.read_artifact_version_record(version_id)
        )

    def read_artifact_version_record(self, version_id: str) -> ArtifactVersionRecord:
        record = self.database.read_artifact_version(version_id)
        if record is None:
            raise ArtifactNotFoundError(f"artifact version not found: {version_id}")
        return record

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
        timestamp = self.timestamp_provider()
        version_id = self.id_generator.artifact_version_id()
        version_number = len(artifact.versions) + 1
        version_dir = (
            self._artifact_dir(artifact.id) / "versions" / f"{version_number}-{version_id}"
        )
        version_dir.mkdir(parents=True, exist_ok=True)
        content_path = version_dir / "content"
        if file_path is None:
            stored = self.content_store.write_content(content_path, content)
        else:
            stored = self.content_store.copy_file(content_path, file_path)
        stored_content = self.content_store.read_content(
            stored.path,
            stored.encoding,
            stored.size,
            stored.sha256,
        )

        version_record = ArtifactVersionRecord.model_validate(
            {
                "id": version_id,
                "artifact_id": artifact.id,
                "version_number": version_number,
                "content_path": str(stored.path),
                "content_hash": stored.sha256,
                "content_encoding": stored.encoding,
                "content_size": stored.size,
                "metadata": dict(metadata),
                "lineage": dict(lineage),
                "created_at": timestamp,
            }
        )
        updated_artifact = artifact.model_copy(
            update={
                "versions": (*artifact.versions, version_id),
                "current_version_id": version_id,
                "updated_at": timestamp,
            }
        )
        artifact_record = self.database.write_artifact(updated_artifact)
        typed_version = self.database.write_artifact_version(version_record)
        return (
            StoredArtifact(record=artifact_record),
            StoredArtifactVersion(record=typed_version, content=stored_content),
        )

    def _stored_artifact_version_from_record(
        self, record: ArtifactVersionRecord
    ) -> StoredArtifactVersion:
        content = self.content_store.read_content(
            record.content_path,
            record.content_encoding,
            record.content_size,
            record.content_hash,
        )
        return StoredArtifactVersion(record=record, content=content)

    def _load_or_create_artifact(
        self,
        *,
        artifact_id: str | None,
        artifact_type: str,
        name: str,
        created_by_step_id: str | None,
    ) -> ArtifactRecord:
        if artifact_id is not None:
            artifact = self.read_artifact(artifact_id)
            if artifact.type != artifact_type:
                raise ValueError(
                    f"artifact type mismatch for {artifact_id}: {artifact.type} != {artifact_type}"
                )
            if artifact.created_by_step_id is None and created_by_step_id is not None:
                artifact = artifact.model_copy(update={"created_by_step_id": created_by_step_id})
            return artifact

        artifact_id = self.id_generator.artifact_id()
        timestamp = self.timestamp_provider()
        artifact_dir = self._artifact_dir(artifact_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return ArtifactRecord(
            id=artifact_id,
            type=artifact_type,
            name=name,
            versions=(),
            current_version_id=None,
            created_by_step_id=created_by_step_id,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _artifact_dir(self, artifact_id: str) -> Path:
        return self.artifacts_root / artifact_id

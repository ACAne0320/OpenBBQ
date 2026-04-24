from __future__ import annotations

from pathlib import Path

from pydantic import Field

from openbbq.domain.base import OpenBBQModel
from openbbq.storage.json_files import read_json_object, write_json_atomic


class ArtifactIndex(OpenBBQModel):
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    version_paths: dict[str, str] = Field(default_factory=dict)


def index_path(artifacts_root: Path) -> Path:
    return artifacts_root / "index.json"


def read_artifact_index(artifacts_root: Path) -> ArtifactIndex:
    path = index_path(artifacts_root)
    if not path.exists():
        return ArtifactIndex()
    return ArtifactIndex.model_validate(read_json_object(path))


def write_artifact_index(artifacts_root: Path, index: ArtifactIndex) -> None:
    write_json_atomic(index_path(artifacts_root), index.model_dump(mode="json"))

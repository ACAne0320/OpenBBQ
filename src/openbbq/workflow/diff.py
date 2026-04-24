from __future__ import annotations

import difflib
import json

from openbbq.errors import ValidationError
from openbbq.storage.project_store import ProjectStore, StoredArtifactVersion


def diff_artifact_versions(
    store: ProjectStore, from_version_id: str, to_version_id: str
) -> dict[str, str]:
    from_version = store.read_artifact_version(from_version_id)
    to_version = store.read_artifact_version(to_version_id)
    from_text = _version_text(from_version)
    to_text = _version_text(to_version)
    diff = "".join(
        difflib.unified_diff(
            from_text.splitlines(keepends=True),
            to_text.splitlines(keepends=True),
            fromfile=from_version_id,
            tofile=to_version_id,
        )
    )
    return {
        "from": from_version_id,
        "to": to_version_id,
        "format": "unified",
        "diff": diff,
    }


def _version_text(version: StoredArtifactVersion) -> str:
    if version.record.content_encoding in {"bytes", "file"} or isinstance(version.content, bytes):
        raise ValidationError("Artifact diff supports text and JSON artifact versions only.")
    content = version.content
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return _ensure_trailing_newline(str(content))


def _ensure_trailing_newline(value: str) -> str:
    return value if value.endswith("\n") else value + "\n"

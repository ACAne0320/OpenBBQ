"""Workspace: source typing, slug, manifest I/O, resolution, and init — the
single place that knows the on-disk layout. Commands call in here; it never
imports cli/output — failures surface as OpenBBQError.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    AsrReview,
    Cues,
    Manifest,
    QaReport,
    Review,
    Source,
    SourceType,
    Stage,
    StageState,
    StageStatus,
    Transcript,
    Translation,
    TranslationAudit,
)

MANIFEST_NAME = "manifest.json"
_PROVENANCE_PATH = Path(".openbbq") / "artifacts.json"
_ASR_REVIEW_PATH = Path(".openbbq") / "asr-review.json"
_QA_PATH = Path(".openbbq") / "qa.json"
_REFERENCE_CAPTION_PATH = Path(".openbbq") / "reference-caption.vtt"
# BCP-47 subset: lang is interpolated into a filename, so guard against `../` etc.
_LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]+)*$")

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".ts"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".wma"}
_STAGE_ORDER = tuple(Stage)


# --- source typing + slug -----------------------------------------------------


def detect_source(ref: str) -> tuple[SourceType, str]:
    """Return (source_type, normalized_ref).

    url stays as-is; local files resolve to an absolute path and must exist.
    """
    if ref.startswith(("http://", "https://")):
        return "url", ref
    path = Path(ref).expanduser()
    if not path.exists():
        raise OpenBBQError(
            "source_not_found", ref=ref, fix="check the path and try again"
        )
    ext = path.suffix.lower()
    if ext in VIDEO_EXTS:
        return "local_video", str(path.resolve())
    if ext in AUDIO_EXTS:
        return "local_audio", str(path.resolve())
    raise OpenBBQError(
        "unsupported_source",
        ref=ref,
        ext=ext or "(none)",
        fix="use a video (.mp4/.mkv/.mov/.webm/…) or audio (.wav/.mp3/.m4a/…) file",
    )


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\-]+", "-", text.strip().lower())
    return re.sub(r"-+", "-", text).strip("-") or "project"


def derive_slug(source_type: SourceType, ref: str) -> str:
    if source_type == "url":
        parsed = urlparse(ref)
        v = parse_qs(parsed.query).get("v")
        seg = (
            (v[0] if v else "")
            or parsed.path.rstrip("/").rsplit("/", 1)[-1]
            or parsed.netloc
        )
        return _slugify(seg)
    return _slugify(Path(ref).stem)


# --- manifest I/O -------------------------------------------------------------


def write_text_atomic(path: Path, content: str) -> None:
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def write_manifest(ws: Path, manifest: Manifest) -> None:
    # indent + exclude_none for a compact, readable manifest.
    path = ws / MANIFEST_NAME
    write_text_atomic(path, manifest.model_dump_json(indent=2, exclude_none=True))


def read_manifest(ws: Path) -> Manifest:
    """Load + fully validate a workspace's manifest (the strict gate)."""
    path = ws / MANIFEST_NAME
    try:
        return Manifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise OpenBBQError(
            "invalid_manifest",
            path=str(path),
            fix="manifest is malformed or from an incompatible schema version",
        ) from e


def read_transcript(path: Path) -> Transcript:
    """Load + validate a transcript.json, mapping parse failures to a domain error.

    Same gate as read_manifest: a raw JSON/validation error here would escape the
    OpenBBQError contract, so corrupt or incompatible transcripts surface as a
    structured, agent-fixable error instead of a traceback.
    """
    try:
        return Transcript.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise OpenBBQError(
            "invalid_transcript",
            path=str(path),
            fix="transcript is malformed or incompatible; re-run openbbq transcribe",
        ) from e


def read_cues(path: Path) -> Cues:
    """Load + validate a cues.json, mapping parse failures to a domain error.

    Same gate as read_transcript: corrupt or incompatible cues surface as a
    structured error instead of a raw ValidationError escaping the contract.
    """
    try:
        return Cues.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise OpenBBQError(
            "invalid_cues",
            path=str(path),
            fix="cues is malformed or incompatible; re-run openbbq segment",
        ) from e


# --- translation worksheets (per target language) -----------------------------


def validate_lang(lang: str) -> str:
    """A target-language code safe to use as a filename component (no `../`)."""
    if not _LANG_RE.match(lang):
        raise OpenBBQError(
            "invalid_lang", lang=lang, fix="use a BCP-47 code like zh, en, or pt-BR"
        )
    return lang


def worksheet_path(ws: Path, lang: str) -> Path:
    """``<ws>/translation.<lang>.json`` (validates ``lang`` first)."""
    return ws / f"translation.{validate_lang(lang)}.json"


def find_worksheets(ws: Path) -> list[str]:
    """Target languages with a worksheet present (for check's single-ws inference)."""
    return sorted(
        p.name[len("translation.") : -len(".json")]
        for p in ws.glob("translation.*.json")
    )


def read_translation(path: Path) -> Translation:
    """Load + validate a translation worksheet, mapping failures to a domain error."""
    try:
        return Translation.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise OpenBBQError(
            "invalid_translation",
            path=str(path),
            fix="translation worksheet is malformed or from an incompatible schema",
        ) from e


def read_review(path: Path) -> Review:
    """Load + validate a review state document."""
    try:
        return Review.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise OpenBBQError(
            "invalid_review",
            path=str(path),
            fix="restore a review checkpoint or remove the malformed review file",
        ) from e


def asr_review_path(workspace: Path) -> Path:
    return workspace / _ASR_REVIEW_PATH


def read_asr_review_optional(workspace: Path) -> AsrReview | None:
    path = asr_review_path(workspace)
    if not path.is_file():
        return None
    try:
        return AsrReview.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise OpenBBQError(
            "invalid_asr_review",
            path=str(path),
            fix="remove .openbbq/asr-review.json and rerun openbbq asr check",
        ) from e


def write_asr_review(workspace: Path, review: AsrReview) -> Path:
    path = asr_review_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, review.model_dump_json(indent=2) + "\n")
    return path


def translation_audit_path(workspace: Path, lang: str) -> Path:
    return workspace / ".openbbq" / f"translation-audit.{validate_lang(lang)}.json"


def read_translation_audit_optional(
    workspace: Path, lang: str
) -> TranslationAudit | None:
    path = translation_audit_path(workspace, lang)
    if not path.is_file():
        return None
    try:
        audit = TranslationAudit.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise OpenBBQError(
            "invalid_translation_audit",
            path=str(path),
            fix=f"remove {path.name} and rerun openbbq translate audit {lang}",
        ) from e
    if audit.target_lang != lang:
        raise OpenBBQError(
            "invalid_translation_audit",
            path=str(path),
            target_lang=audit.target_lang,
            expected=lang,
        )
    return audit


def write_translation_audit(
    workspace: Path, lang: str, audit: TranslationAudit
) -> Path:
    path = translation_audit_path(workspace, lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, audit.model_dump_json(indent=2) + "\n")
    return path


def qa_path(workspace: Path) -> Path:
    return workspace / _QA_PATH


def read_qa_optional(workspace: Path) -> QaReport | None:
    path = qa_path(workspace)
    if not path.is_file():
        return None
    try:
        return QaReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise OpenBBQError(
            "invalid_qa_report",
            path=str(path),
            fix="remove .openbbq/qa.json and rerun openbbq qa render",
        ) from e


def write_qa(workspace: Path, report: QaReport) -> Path:
    path = qa_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, report.model_dump_json(indent=2) + "\n")
    return path


def reference_caption_path(workspace: Path) -> Path:
    return workspace / _REFERENCE_CAPTION_PATH


def read_reference_caption_optional(workspace: Path) -> str | None:
    path = reference_caption_path(workspace)
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise OpenBBQError(
            "invalid_reference_caption",
            path=str(path),
            fix="remove .openbbq/reference-caption.vtt or rerun openbbq fetch",
        ) from error


def write_reference_caption(workspace: Path, content: str) -> Path:
    path = reference_caption_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, content)
    return path


# --- artifact provenance -----------------------------------------------------


def _workspace_path_key(workspace: Path, path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return str(resolved.relative_to(workspace.resolve()))
    except ValueError:
        return str(resolved)


def _path_from_key(workspace: Path, key: str) -> Path:
    path = Path(key)
    return path if path.is_absolute() else workspace / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as e:
        raise OpenBBQError(
            "missing_input",
            artifact=str(path),
            fix="restore the artifact or rerun the producing stage",
        ) from e
    return digest.hexdigest()


def _read_provenance(workspace: Path) -> dict[str, Any]:
    path = workspace / _PROVENANCE_PATH
    if not path.is_file():
        return {"schema": "openbbq/artifacts@1", "artifacts": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise OpenBBQError(
            "invalid_provenance",
            path=str(path),
            fix="remove .openbbq/artifacts.json and rerun openbbq export",
        ) from e
    if (
        not isinstance(raw, dict)
        or raw.get("schema") != "openbbq/artifacts@1"
        or not isinstance(raw.get("artifacts"), dict)
    ):
        raise OpenBBQError(
            "invalid_provenance",
            path=str(path),
            fix="remove .openbbq/artifacts.json and rerun openbbq export",
        )
    return raw


def record_artifact_provenance(
    workspace: Path,
    artifact: Path,
    producer: Stage,
    *,
    inputs: list[Path],
) -> None:
    """Record exact content dependencies without changing manifest@1."""
    workspace = workspace.resolve()
    artifact_key = _workspace_path_key(workspace, artifact)
    raw = _read_provenance(workspace)
    records = cast(dict[str, Any], raw["artifacts"])
    records[artifact_key] = {
        "producer": producer.value,
        "sha256": _sha256(artifact),
        "inputs": {
            _workspace_path_key(workspace, input_path): _sha256(input_path)
            for input_path in inputs
        },
    }
    path = workspace / _PROVENANCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, json.dumps(raw, ensure_ascii=False, indent=2) + "\n")


def require_fresh_artifact(
    workspace: Path,
    artifact: Path,
    producer: Stage,
) -> Path:
    """Require an artifact and all recorded inputs to match their content hashes."""
    workspace = workspace.resolve()
    artifact_key = _workspace_path_key(workspace, artifact)
    raw = _read_provenance(workspace)
    records = cast(dict[str, Any], raw["artifacts"])
    record = records.get(artifact_key)
    if not isinstance(record, dict) or record.get("producer") != producer.value:
        raise OpenBBQError(
            "artifact_unverified",
            artifact=artifact_key,
            producer=producer.value,
            fix="rerun openbbq export, or pass --allow-stale for an intentional manual subtitle",
        )
    expected = record.get("sha256")
    if not isinstance(expected, str) or _sha256(artifact) != expected:
        raise OpenBBQError(
            "stale_artifact",
            artifact=artifact_key,
            fix="rerun openbbq export, or pass --allow-stale for an intentional manual subtitle",
        )
    inputs = record.get("inputs")
    if not isinstance(inputs, dict):
        raise OpenBBQError(
            "invalid_provenance",
            artifact=artifact_key,
            fix="rerun openbbq export",
        )
    for input_key, input_hash in inputs.items():
        if not isinstance(input_key, str) or not isinstance(input_hash, str):
            raise OpenBBQError(
                "invalid_provenance",
                artifact=artifact_key,
                fix="rerun openbbq export",
            )
        input_path = _path_from_key(workspace, input_key)
        if not input_path.is_file() or _sha256(input_path) != input_hash:
            raise OpenBBQError(
                "stale_artifact",
                artifact=artifact_key,
                input=input_key,
                fix="rerun openbbq export before burning subtitles",
            )
    return artifact


# --- workspace resolution (two forms, git-style) ------------------------------


def _is_openbbq_workspace(d: Path) -> bool:
    # Cheap marker check: a manifest.json whose top-level `schema` is ours?
    # Version-agnostic (matches @1/@2); full validation is read_manifest's job.
    path = d / MANIFEST_NAME
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and str(data.get("schema", "")).startswith(
        "openbbq/manifest@"
    )


def resolve_workspace(explicit: str | None) -> Path:
    """① --workspace DIR  →  ② cwd upward (git-style)  →  no_workspace.

    The chosen dir must hold an OpenBBQ manifest.json; a foreign manifest.json
    met while walking up is skipped, not grabbed.
    """
    if explicit:
        ws = Path(explicit).expanduser().resolve()
        if not _is_openbbq_workspace(ws):
            raise OpenBBQError(
                "no_workspace", workspace=str(ws), fix="openbbq init <source>"
            )
        return ws
    cwd = Path.cwd().resolve()
    for d in (cwd, *cwd.parents):
        if _is_openbbq_workspace(d):
            return d
    raise OpenBBQError(
        "no_workspace", fix="run inside a workspace, or pass --workspace"
    )


# --- init ---------------------------------------------------------------------


def init_workspace(
    source: str, *, workspace: str | None, glossary: str | None = None
) -> tuple[Path, Manifest]:
    source_type, ref = detect_source(source)
    if workspace:  # explicit dir; pass "." to use the current directory
        ws = Path(workspace).expanduser().resolve()
    else:  # default: a slug subdir under cwd, so we don't pollute it
        ws = (Path.cwd() / derive_slug(source_type, ref)).resolve()

    if (ws / MANIFEST_NAME).exists():
        raise OpenBBQError(
            "workspace_exists",
            workspace=str(ws),
            fix="choose another dir (--workspace) or remove the existing manifest",
        )
    ws.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    title = None if source_type == "url" else Path(ref).stem  # url title awaits fetch
    # stages start empty: the manifest is a log of work actually run, not a
    # prefilled pipeline. Each command records its own stage when it runs.
    manifest = Manifest(
        created_at=now,
        source=Source(type=source_type, ref=ref, title=title),
        glossary=glossary,
        stages={},
    )
    write_manifest(ws, manifest)
    return ws, manifest


# --- pipeline stage helpers (shared by extract-audio / transcribe / …) --------


def _manifest_for_merge(ws: Path, fallback: Manifest) -> Manifest:
    try:
        return read_manifest(ws)
    except OpenBBQError:
        return fallback


def _invalidate_later_stages(
    manifest: Manifest,
    stage: Stage,
    *,
    preserve: set[Stage] | None = None,
) -> None:
    index = _STAGE_ORDER.index(stage)
    for later in _STAGE_ORDER[index + 1 :]:
        if later in manifest.stages and (preserve is None or later not in preserve):
            manifest.stages[later] = StageState(status=StageStatus.PENDING)


def _sync_manifest_snapshot(target: Manifest, current: Manifest) -> None:
    target.source = current.source
    target.glossary = current.glossary
    target.stages = current.stages


def media_input(manifest: Manifest, workspace: Path | None = None) -> Path:
    """The media file to read: the fetched artifact, or a local source in place."""
    fetch = manifest.stages.get(Stage.FETCH)
    if fetch is not None and fetch.status is StageStatus.DONE and fetch.artifact:
        path = Path(fetch.artifact)
        if workspace is not None and not path.is_absolute():
            path = workspace / path
        return path
    if manifest.source.type in ("local_video", "local_audio"):
        return Path(manifest.source.ref)
    raise OpenBBQError("media_unavailable", fix="fetch the media first (url source)")


def record_stage(
    ws: Path,
    manifest: Manifest,
    stage: Stage,
    state: StageState,
    *,
    invalidate_later: bool = True,
    preserve_later: set[Stage] | None = None,
) -> None:
    """Merge one stage state into the latest on-disk manifest."""
    current = _manifest_for_merge(ws, manifest)
    current.stages[stage] = state
    if invalidate_later and state.status in {StageStatus.RUNNING, StageStatus.DONE}:
        _invalidate_later_stages(current, stage, preserve=preserve_later)
    write_manifest(ws, current)
    _sync_manifest_snapshot(manifest, current)


def record_source_metadata(
    ws: Path,
    manifest: Manifest,
    *,
    title: str | None = None,
    author: str | None = None,
    thumbnail: str | None = None,
    author_if_missing: bool = False,
) -> None:
    """Merge fetch-owned source metadata into the latest on-disk manifest."""
    current = _manifest_for_merge(ws, manifest)
    changed = False
    if title is not None and current.source.title != title:
        current.source.title = title
        changed = True
    if author is not None and (not author_if_missing or current.source.author is None):
        if current.source.author != author:
            current.source.author = author
            changed = True
    if thumbnail is not None and current.source.thumbnail != thumbnail:
        current.source.thumbnail = thumbnail
        changed = True
    if changed:
        write_manifest(ws, current)
    _sync_manifest_snapshot(manifest, current)


def record_glossary_binding(ws: Path, manifest: Manifest, glossary: str) -> None:
    """Merge a workspace glossary binding into the latest on-disk manifest."""
    current = _manifest_for_merge(ws, manifest)
    if current.glossary != glossary:
        current.glossary = glossary
        write_manifest(ws, current)
    _sync_manifest_snapshot(manifest, current)


def require_artifact(ws: Path, manifest: Manifest, stage: Stage, *, fix: str) -> Path:
    state = manifest.stages.get(stage)
    if state is None or state.status is not StageStatus.DONE or state.artifact is None:
        raise OpenBBQError("missing_input", stage=stage.value, fix=fix)
    path = Path(state.artifact)
    if not path.is_absolute():
        path = ws / path
    if not path.exists():
        raise OpenBBQError(
            "missing_input", stage=stage.value, artifact=state.artifact, fix=fix
        )
    return path

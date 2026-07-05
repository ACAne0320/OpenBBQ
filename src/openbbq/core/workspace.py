"""Workspace: source typing, slug, manifest I/O, resolution, and init — the
single place that knows the on-disk layout. Commands call in here; it never
imports cli/output — failures surface as OpenBBQError.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    Cues,
    Manifest,
    Source,
    SourceType,
    Stage,
    StageState,
    StageStatus,
    Transcript,
    Translation,
)

MANIFEST_NAME = "manifest.json"
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
        os.replace(tmp_path, path)
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


def _invalidate_later_stages(manifest: Manifest, stage: Stage) -> None:
    index = _STAGE_ORDER.index(stage)
    for later in _STAGE_ORDER[index + 1 :]:
        if later in manifest.stages:
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


def record_stage(ws: Path, manifest: Manifest, stage: Stage, state: StageState) -> None:
    """Merge one stage state into the latest on-disk manifest."""
    current = _manifest_for_merge(ws, manifest)
    current.stages[stage] = state
    if state.status in {StageStatus.RUNNING, StageStatus.DONE}:
        _invalidate_later_stages(current, stage)
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
    if author is not None and (
        not author_if_missing or current.source.author is None
    ):
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

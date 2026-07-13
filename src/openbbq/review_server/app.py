from __future__ import annotations

import math
import mimetypes
import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import wave
from array import array
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import Body, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from openbbq.core import review as reviewlib
from openbbq.core import translate as translatelib
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import ReviewStatus, Stage, StageStatus

_COOKIE = "openbbq_review"
_SAFE_HOSTS = {"127.0.0.1", "localhost", "testserver", "::1"}
_CSP = (
    "default-src 'self'; img-src 'self' data:; media-src 'self'; "
    "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
    "object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
)
_BROWSER_VIDEO_EXTENSIONS = {".mp4", ".webm", ".ogv"}


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthRequest(StrictRequest):
    secret: str


class MutationRequest(StrictRequest):
    base_revision: str
    op_id: str


class CuePatch(MutationRequest):
    source: str | None = None
    target: str | None = None
    start: float | None = None
    end: float | None = None


class StatusPatch(MutationRequest):
    status: ReviewStatus
    note: str | None = None


class SplitRequest(MutationRequest):
    at: float
    source_left: str
    source_right: str
    target_left: str | None = None
    target_right: str | None = None


class MergeRequest(MutationRequest):
    cue_ids: list[int]


class InsertRequest(MutationRequest):
    at: float


class SwitchTargetRequest(MutationRequest):
    target_lang: str | None = None


class ReviewManager:
    def __init__(self, path: Path, lang: str | None) -> None:
        self.path = path.resolve()
        self.lang = lang
        self.session_lock = threading.RLock()
        self.session = reviewlib.ReviewSession.open(self.path, lang)
        self._waveform: tuple[int, float, list[tuple[float, float]]] | None = None
        self._preview_status = "ready"
        self._preview_error: str | None = None
        self._preview_path: Path | None = None
        self._serving_preview = False
        manifest = ws.read_manifest(self.path)
        source = ws.media_input(manifest, self.path).resolve()
        if manifest.source.type != "local_audio":
            key = hashlib.sha256(
                f"{source}:{source.stat().st_size}:{source.stat().st_mtime_ns}".encode()
            ).hexdigest()
            self._preview_path = (
                self.path / ".openbbq" / "review" / "cache" / f"preview-{key}.mp4"
            )
            self._serving_preview = self._preview_path.is_file()
            if (
                not self._serving_preview
                and source.suffix.lower() not in _BROWSER_VIDEO_EXTENSIONS
            ):
                self._preview_status = "needed"

    def switch(self, lang: str | None, base_revision: str) -> None:
        if self.session.snapshot().revision != base_revision:
            raise OpenBBQError("review_conflict")
        self.lang = lang
        self.session = reviewlib.ReviewSession.open(self.path, lang)

    def media_path(self) -> Path:
        manifest = ws.read_manifest(self.path)
        source = ws.media_input(manifest, self.path).resolve()
        if self._preview_path is not None and self._serving_preview:
            return self._preview_path
        return source

    def preview_state(self) -> dict[str, object]:
        return {
            "status": self._preview_status,
            "error": self._preview_error,
        }

    def start_preview(self) -> dict[str, object]:
        if self._preview_path is None or self._serving_preview:
            return self.preview_state()
        if self._preview_status == "building":
            return self.preview_state()
        self._preview_status = "building"
        self._preview_error = None
        threading.Thread(target=self._build_preview, daemon=True).start()
        return self.preview_state()

    def _build_preview(self) -> None:
        assert self._preview_path is not None
        source = ws.media_input(ws.read_manifest(self.path), self.path).resolve()
        self._preview_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._preview_path.with_suffix(".building.mp4")
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            "scale=1280:-2:force_original_aspect_ratio=decrease",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            os.replace(temporary, self._preview_path)
            self._serving_preview = True
            self._preview_status = "ready"
        except (OSError, subprocess.CalledProcessError) as error:
            temporary.unlink(missing_ok=True)
            self._preview_error = (
                error.stderr.strip()
                if isinstance(error, subprocess.CalledProcessError) and error.stderr
                else str(error)
            )
            self._preview_status = "failed"

    def audio_path(self) -> Path:
        manifest = ws.read_manifest(self.path)
        state = manifest.stages.get(Stage.EXTRACT_AUDIO)
        if state is not None and state.status is StageStatus.DONE and state.artifact:
            path = Path(state.artifact)
            return (path if path.is_absolute() else self.path / path).resolve()
        media = self.media_path()
        if media.suffix.lower() == ".wav":
            return media
        raise OpenBBQError(
            "missing_input", stage="extract_audio", fix="openbbq extract-audio"
        )

    def duration(self) -> float:
        manifest = ws.read_manifest(self.path)
        state = manifest.stages.get(Stage.TRANSCRIBE)
        if state is not None and state.status is StageStatus.DONE and state.artifact:
            path = Path(state.artifact)
            path = path if path.is_absolute() else self.path / path
            return ws.read_transcript(path).duration
        audio = self.audio_path()
        with wave.open(str(audio), "rb") as handle:
            return handle.getnframes() / handle.getframerate()

    def waveform(self) -> tuple[int, float, list[tuple[float, float]]]:
        if self._waveform is not None:
            return self._waveform
        audio = self.audio_path()
        digest = hashlib.sha256()
        with audio.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        cache = (
            self.path
            / ".openbbq"
            / "review"
            / "cache"
            / f"waveform-{digest.hexdigest()}.json"
        )
        if cache.is_file():
            try:
                cached = json.loads(cache.read_text(encoding="utf-8"))
                self._waveform = (
                    int(cached["sample_rate"]),
                    float(cached["duration"]),
                    [(float(low), float(high)) for low, high in cached["peaks"]],
                )
                return self._waveform
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                cache.unlink(missing_ok=True)
        with wave.open(str(audio), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.getnframes()
            if channels != 1 or width != 2:
                raise OpenBBQError(
                    "invalid_audio",
                    path=str(audio),
                    fix="openbbq extract-audio",
                )
            values = array("h")
            values.frombytes(handle.readframes(frames))
            if sys.byteorder != "little":
                values.byteswap()
        per_peak = max(1, rate // 100)
        peaks: list[tuple[float, float]] = []
        scale = 32768.0
        for offset in range(0, len(values), per_peak):
            chunk = values[offset : offset + per_peak]
            peaks.append((min(chunk) / scale, max(chunk) / scale))
        self._waveform = (rate, frames / rate, peaks)
        cache.parent.mkdir(parents=True, exist_ok=True)
        ws.write_text_atomic(
            cache,
            json.dumps(
                {
                    "sample_rate": rate,
                    "duration": frames / rate,
                    "peaks": peaks,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        return self._waveform


def _target_map(snapshot: reviewlib.ReviewSnapshot) -> dict[int, Any]:
    if snapshot.translation is None:
        return {}
    return {item.id: item for item in snapshot.translation.items}


def _review_map(snapshot: reviewlib.ReviewSnapshot) -> dict[int, Any]:
    return {item.id: item for item in snapshot.review.items}


def _cue_payload(snapshot: reviewlib.ReviewSnapshot) -> list[dict[str, object]]:
    targets = _target_map(snapshot)
    reviews = _review_map(snapshot)
    term_warning_ids: set[int] = set()
    if snapshot.translation is not None:
        report = translatelib.check(
            snapshot.cues,
            snapshot.translation,
            snapshot.translation.target_lang,
        )
        term_warning_ids = {issue.id for issue in report.term_issues}
    result: list[dict[str, object]] = []
    for cue in snapshot.cues.cues:
        target = targets.get(cue.id)
        review = reviews.get(cue.id)
        duration = round(cue.end - cue.start, 3)
        source_profile, _ = translatelib.seg.resolve_profile(snapshot.cues.source_lang)
        source_cps = (
            round(
                translatelib.seg.count_chars(cue.source, source_profile) / duration, 1
            )
            if duration > 0
            else math.inf
        )
        over_budget = False
        if (
            target is not None
            and snapshot.translation is not None
            and translatelib.is_filled(target.target)
        ):
            target_profile, _ = translatelib.seg.resolve_profile(
                snapshot.translation.target_lang
            )
            over_budget = (
                translatelib.seg.count_chars(target.target or "", target_profile)
                > target.budget.max_chars
            )
        result.append(
            {
                "id": cue.id,
                "start": cue.start,
                "end": cue.end,
                "duration": duration,
                "source": cue.source,
                "source_cps": source_cps,
                "target": target.target if target is not None else None,
                "budget": target.budget.model_dump(mode="json")
                if target is not None
                else None,
                "over_budget": over_budget,
                "time_warning": (
                    source_cps > snapshot.cues.params.max_cps
                    or duration < snapshot.cues.params.min_dur
                    or duration > snapshot.cues.params.max_dur
                ),
                "term_warning": cue.id in term_warning_ids,
                "status": review.status.value if review is not None else "unreviewed",
                "note": review.note if review is not None else None,
            }
        )
    return result


def _snapshot_payload(snapshot: reviewlib.ReviewSnapshot) -> dict[str, object]:
    return {
        "revision": snapshot.revision,
        "changed": snapshot.changed,
        "progress": asdict(snapshot.progress),
        "cues": _cue_payload(snapshot),
    }


def _session_payload(manager: ReviewManager) -> dict[str, object]:
    snapshot = manager.session.snapshot()
    manifest = ws.read_manifest(manager.path)
    media = manager.media_path()
    preview = manager.preview_state()
    return {
        "workspace": str(manager.path),
        "title": manifest.source.title or manager.path.name,
        "source_type": manifest.source.type,
        "source_lang": snapshot.cues.source_lang,
        "target_lang": manager.lang,
        "languages": ws.find_worksheets(manager.path),
        "revision": snapshot.revision,
        "progress": asdict(snapshot.progress),
        "media": {
            "kind": "audio" if manifest.source.type == "local_audio" else "video",
            "url": "/api/media",
            "name": media.name,
            "duration": manager.duration(),
            "playable": preview["status"] == "ready",
            "preview_status": preview["status"],
            "preview_error": preview["error"],
        },
    }


def _domain_status(err: OpenBBQError) -> int:
    if err.code == "review_conflict":
        return 409
    if err.code == "unknown_cue":
        return 404
    if err.code in {
        "invalid_timeline",
        "invalid_split",
        "non_adjacent_merge",
        "review_blocked",
        "nothing_to_undo",
        "nothing_to_redo",
    }:
        return 422
    return 400


def _host_ok(value: str) -> bool:
    hostname = (
        value.rsplit(":", 1)[0].strip("[]")
        if value.count(":") <= 1
        else value.strip("[]")
    )
    return hostname in _SAFE_HOSTS


def _origin_ok(value: str | None, host: str) -> bool:
    if value is None:
        return True
    parsed = urlparse(value)
    return (
        parsed.scheme == "http"
        and (parsed.hostname or "") in _SAFE_HOSTS
        and parsed.netloc.lower() == host.lower()
    )


def _range_response(path: Path, range_header: str | None) -> Response:
    size = path.stat().st_size
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if range_header is None:
        return FileResponse(
            path, media_type=media_type, headers={"Accept-Ranges": "bytes"}
        )
    if not range_header.startswith("bytes=") or "," in range_header:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    raw_start, _, raw_end = range_header[6:].partition("-")
    try:
        if raw_start:
            start = int(raw_start)
            end = int(raw_end) if raw_end else size - 1
        else:
            suffix = int(raw_end)
            start = max(0, size - suffix)
            end = size - 1
    except ValueError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    if start < 0 or end < start or start >= size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    end = min(end, size - 1)
    length = end - start + 1

    def stream() -> Any:
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        stream(),
        status_code=206,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(length),
        },
    )


def create_app(path: Path, lang: str | None, *, secret: str | None = None) -> FastAPI:
    manager = ReviewManager(path, lang)
    session_secret = secret or secrets.token_urlsafe(32)
    app = FastAPI(title="OpenBBQ Review", docs_url=None, redoc_url=None)
    app.state.review_manager = manager
    app.state.review_secret = session_secret

    @app.exception_handler(OpenBBQError)
    async def domain_error(_request: Request, err: OpenBBQError) -> JSONResponse:
        return JSONResponse(err.payload(), status_code=_domain_status(err))

    @app.middleware("http")
    async def security(request: Request, call_next: Any) -> Response:
        host = request.headers.get("host", "")
        if not _host_ok(host) or not _origin_ok(request.headers.get("origin"), host):
            return JSONResponse({"error": "forbidden_origin"}, status_code=403)
        if (
            request.url.path.startswith("/api/")
            and request.url.path != "/api/auth/session"
        ):
            if not secrets.compare_digest(
                request.cookies.get(_COOKIE, ""), session_secret
            ):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.post("/api/auth/session", status_code=204)
    def authenticate(payload: AuthRequest) -> Response:
        if not secrets.compare_digest(payload.secret, session_secret):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        response = Response(status_code=204)
        response.set_cookie(
            _COOKIE,
            session_secret,
            httponly=True,
            samesite="strict",
            max_age=12 * 60 * 60,
        )
        return response

    @app.get("/api/session")
    def session_state() -> dict[str, object]:
        with manager.session_lock:
            return _session_payload(manager)

    @app.get("/api/cues")
    def cues_state() -> dict[str, object]:
        with manager.session_lock:
            return _snapshot_payload(manager.session.snapshot())

    @app.post("/api/session/target")
    def switch_target(payload: SwitchTargetRequest) -> dict[str, object]:
        with manager.session_lock:
            manager.switch(payload.target_lang, payload.base_revision)
            return {
                **_session_payload(manager),
                **_snapshot_payload(manager.session.snapshot()),
            }

    @app.patch("/api/cues/{cue_id}")
    def update_cue(cue_id: int, payload: CuePatch) -> dict[str, object]:
        with manager.session_lock:
            result = manager.session.update_cue(
                cue_id,
                source=payload.source,
                target=payload.target,
                start=payload.start,
                end=payload.end,
                base_revision=payload.base_revision,
                op_id=payload.op_id,
            )
            return _snapshot_payload(result)

    @app.patch("/api/review/{cue_id}")
    def set_status(cue_id: int, payload: StatusPatch) -> dict[str, object]:
        with manager.session_lock:
            return _snapshot_payload(
                manager.session.set_status(
                    cue_id,
                    payload.status,
                    note=payload.note,
                    base_revision=payload.base_revision,
                    op_id=payload.op_id,
                )
            )

    @app.post("/api/cues/{cue_id}/split")
    def split_cue(cue_id: int, payload: SplitRequest) -> dict[str, object]:
        with manager.session_lock:
            return _snapshot_payload(
                manager.session.split_cue(
                    cue_id,
                    at=payload.at,
                    source_left=payload.source_left,
                    source_right=payload.source_right,
                    target_left=payload.target_left,
                    target_right=payload.target_right,
                    base_revision=payload.base_revision,
                    op_id=payload.op_id,
                )
            )

    @app.post("/api/cues/merge")
    def merge_cues(payload: MergeRequest) -> dict[str, object]:
        with manager.session_lock:
            return _snapshot_payload(
                manager.session.merge_cues(
                    payload.cue_ids,
                    base_revision=payload.base_revision,
                    op_id=payload.op_id,
                )
            )

    @app.post("/api/cues")
    def insert_cue(payload: InsertRequest) -> dict[str, object]:
        with manager.session_lock:
            return _snapshot_payload(
                manager.session.insert_cue(
                    at=payload.at,
                    base_revision=payload.base_revision,
                    op_id=payload.op_id,
                )
            )

    @app.delete("/api/cues/{cue_id}")
    def delete_cue(
        cue_id: int, payload: Annotated[MutationRequest, Body()]
    ) -> dict[str, object]:
        with manager.session_lock:
            return _snapshot_payload(
                manager.session.delete_cue(
                    cue_id,
                    base_revision=payload.base_revision,
                    op_id=payload.op_id,
                )
            )

    @app.post("/api/undo")
    def undo(payload: MutationRequest) -> dict[str, object]:
        with manager.session_lock:
            return _snapshot_payload(
                manager.session.undo(
                    base_revision=payload.base_revision,
                    op_id=payload.op_id,
                )
            )

    @app.post("/api/redo")
    def redo(payload: MutationRequest) -> dict[str, object]:
        with manager.session_lock:
            return _snapshot_payload(
                manager.session.redo(
                    base_revision=payload.base_revision,
                    op_id=payload.op_id,
                )
            )

    @app.get("/api/media")
    def media(request: Request) -> Response:
        if manager.preview_state()["status"] != "ready":
            return JSONResponse(manager.preview_state(), status_code=425)
        return _range_response(manager.media_path(), request.headers.get("range"))

    @app.get("/api/media/preview-status")
    def preview_status() -> dict[str, object]:
        return manager.preview_state()

    @app.post("/api/media/preview", status_code=202)
    def start_preview() -> dict[str, object]:
        return manager.start_preview()

    @app.get("/api/waveform")
    def waveform_window(
        start: Annotated[float, Query(ge=0)] = 0,
        end: Annotated[float | None, Query(gt=0)] = None,
        pixels: Annotated[int, Query(ge=1, le=10_000)] = 1000,
    ) -> dict[str, object]:
        rate, duration, peaks = manager.waveform()
        end = min(duration, end if end is not None else duration)
        start = min(start, end)
        peak_rate = len(peaks) / duration if duration > 0 else 1
        left = max(0, math.floor(start * peak_rate))
        right = min(len(peaks), max(left + 1, math.ceil(end * peak_rate)))
        visible = peaks[left:right]
        if len(visible) > pixels:
            stride = len(visible) / pixels
            reduced: list[tuple[float, float]] = []
            for index in range(pixels):
                chunk = visible[
                    math.floor(index * stride) : math.ceil((index + 1) * stride)
                ]
                if chunk:
                    reduced.append(
                        (
                            min(value[0] for value in chunk),
                            max(value[1] for value in chunk),
                        )
                    )
            visible = reduced
        return {
            "sample_rate": rate,
            "duration": duration,
            "start": start,
            "end": end,
            "peaks": visible,
        }

    @app.get("/api/transcript/words")
    def transcript_words(
        start: Annotated[float, Query(ge=0)] = 0,
        end: Annotated[float | None, Query(gt=0)] = None,
    ) -> dict[str, object]:
        manifest = ws.read_manifest(manager.path)
        state = manifest.stages.get(Stage.TRANSCRIBE)
        if state is None or state.status is not StageStatus.DONE or not state.artifact:
            return {"words": []}
        path = Path(state.artifact)
        path = path if path.is_absolute() else manager.path / path
        transcript = ws.read_transcript(path)
        upper = transcript.duration if end is None else end
        words = [
            word.model_dump(mode="json")
            for segment in transcript.segments
            for word in (segment.words or [])
            if word.end >= start and word.start <= upper
        ]
        return {"words": words}

    static_root = Path(__file__).resolve().parent.parent / "review_ui" / "dist"
    assets = static_root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="review-assets")

    @app.get("/{path:path}")
    def spa(path: str) -> Response:
        candidate = (static_root / path).resolve()
        if path and candidate.is_file() and static_root.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(static_root / "index.html")

    return app

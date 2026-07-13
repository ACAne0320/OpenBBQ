"""Human subtitle review domain service.

The browser and HTTP layers are adapters.  This module owns cue mutations,
worksheet synchronization, review progress, optimistic revisions, checkpoints,
and cross-file recovery.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

from openbbq.core import segment as seg
from openbbq.core import translate as translatelib
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    Cue,
    Cues,
    Manifest,
    Progress,
    Review,
    ReviewItem,
    ReviewStatus,
    Stage,
    StageState,
    StageStatus,
    Translation,
    TranslationItem,
)

_STATE_DIR = ".openbbq/review"
_CHECKPOINTS = "checkpoints"
_JOURNAL = "journal.json"
_LOCK = "session.lock"
_CHECKPOINT_LIMIT = 20
_OP_RESULT_LIMIT = 100
_SAFE_OP_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class ReviewProgress:
    reviewed: int
    flagged: int
    unreviewed: int
    total: int


@dataclass(frozen=True)
class ReviewSnapshot:
    cues: Cues
    translation: Translation | None
    review: Review
    revision: str
    progress: ReviewProgress
    changed: list[int]


@dataclass
class _Documents:
    manifest: Manifest
    cues: Cues
    translations: dict[str, Translation]
    reviews: dict[str | None, Review]


def review_path(path: Path, lang: str | None) -> Path:
    return path / (
        "review.source.json"
        if lang is None
        else f"review.{ws.validate_lang(lang)}.json"
    )


def _lang_from_review_path(path: Path) -> str | None:
    if path.name == "review.source.json":
        return None
    return path.name[len("review.") : -len(".json")]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _content_hash(cue: Cue, target: str | None, *, include_target: bool) -> str:
    value: list[object] = [cue.id, cue.start, cue.end, cue.source]
    if include_target:
        value.append(target)
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _translation_item(
    translation: Translation | None, cue_id: int
) -> TranslationItem | None:
    if translation is None:
        return None
    return next((item for item in translation.items if item.id == cue_id), None)


def _review_hash(cue: Cue, translation: Translation | None) -> str:
    item = _translation_item(translation, cue.id)
    return _content_hash(
        cue,
        item.target if item is not None else None,
        include_target=translation is not None,
    )


def _progress(
    cues: Cues, translation: Translation | None, review: Review
) -> ReviewProgress:
    review_of = {item.id: item for item in review.items}
    reviewed = flagged = 0
    for cue in cues.cues:
        item = review_of.get(cue.id)
        if item is None:
            continue
        if item.status is ReviewStatus.FLAGGED:
            flagged += 1
        elif (
            item.status is ReviewStatus.REVIEWED
            and item.reviewed_content_hash == _review_hash(cue, translation)
        ):
            reviewed += 1
    total = len(cues.cues)
    return ReviewProgress(
        reviewed=reviewed,
        flagged=flagged,
        unreviewed=total - reviewed - flagged,
        total=total,
    )


def _revision(path: Path) -> str:
    digest = hashlib.sha256()
    names = [Path("cues.json")]
    names.extend(
        sorted((p.relative_to(path) for p in path.glob("translation.*.json")), key=str)
    )
    names.extend(
        sorted((p.relative_to(path) for p in path.glob("review.*.json")), key=str)
    )
    for rel in names:
        full = path / rel
        digest.update(str(rel).encode("utf-8"))
        digest.update(b"\0")
        if full.exists():
            digest.update(full.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _load_documents(path: Path) -> _Documents:
    manifest = ws.read_manifest(path)
    cues_path = ws.require_artifact(
        path, manifest, Stage.SEGMENT, fix="openbbq segment"
    )
    cues = ws.read_cues(cues_path)
    translations = {
        lang: ws.read_translation(ws.worksheet_path(path, lang))
        for lang in ws.find_worksheets(path)
    }
    reviews: dict[str | None, Review] = {}
    for review_file in sorted(path.glob("review.*.json")):
        reviews[_lang_from_review_path(review_file)] = ws.read_review(review_file)
    return _Documents(
        manifest=manifest,
        cues=cues,
        translations=translations,
        reviews=reviews,
    )


def _target_for(docs: _Documents, lang: str | None) -> Translation | None:
    if lang is None:
        return None
    try:
        return docs.translations[lang]
    except KeyError as e:
        raise OpenBBQError(
            "translation_not_found",
            lang=lang,
            fix=f"openbbq translate init {lang}",
        ) from e


def _max_next_id(docs: _Documents) -> int:
    from_cues = max((cue.id for cue in docs.cues.cues), default=0) + 1
    return max([from_cues, *(review.next_cue_id for review in docs.reviews.values())])


def _new_review(docs: _Documents, lang: str | None) -> Review:
    return Review(
        source_lang=docs.cues.source_lang,
        target_lang=lang,
        revision=0,
        next_cue_id=_max_next_id(docs),
        items=[ReviewItem(id=cue.id) for cue in docs.cues.cues],
    )


def _reconcile(docs: _Documents) -> bool:
    changed = False
    highwater = _max_next_id(docs)
    cue_ids = [cue.id for cue in docs.cues.cues]
    for lang, review in docs.reviews.items():
        if review.source_lang != docs.cues.source_lang or review.target_lang != lang:
            raise OpenBBQError(
                "invalid_review",
                lang=lang or "source",
                fix="restore a checkpoint or recreate the review file",
            )
        translation = _target_for(docs, lang)
        old = {item.id: item for item in review.items}
        new_items: list[ReviewItem] = []
        review_changed = review.next_cue_id != highwater or list(old) != cue_ids
        for cue in docs.cues.cues:
            item = old.get(cue.id, ReviewItem(id=cue.id))
            if (
                item.status is ReviewStatus.REVIEWED
                and item.reviewed_content_hash != _review_hash(cue, translation)
            ):
                item.status = ReviewStatus.UNREVIEWED
                item.reviewed_content_hash = None
                review_changed = True
            new_items.append(item)
        if review_changed:
            review.items = new_items
            review.next_cue_id = highwater
            review.revision += 1
            changed = True
    return changed


def _reorder(docs: _Documents) -> None:
    order = [cue.id for cue in docs.cues.cues]
    for translation in docs.translations.values():
        by_id = {item.id: item for item in translation.items}
        translation.items = [by_id[id_] for id_ in order]
    for review in docs.reviews.values():
        by_id = {item.id: item for item in review.items}
        review.items = [by_id[id_] for id_ in order]


def _validate_timeline(cues: Cues) -> None:
    seen: set[int] = set()
    previous: Cue | None = None
    for cue in cues.cues:
        if cue.id in seen:
            raise OpenBBQError("id_mismatch", detail="duplicate cue ids")
        seen.add(cue.id)
        if cue.start < 0 or cue.end <= cue.start:
            raise OpenBBQError(
                "invalid_timeline", id=cue.id, start=cue.start, end=cue.end
            )
        if previous is not None:
            gap = round(cue.start - previous.end, 3)
            if cue.start < previous.start or gap + 0.0005 < cues.params.min_gap:
                raise OpenBBQError(
                    "invalid_timeline",
                    ids=[previous.id, cue.id],
                    gap=gap,
                    min_gap=cues.params.min_gap,
                )
        previous = cue


def _reset_review_item(review: Review, cue_id: int) -> None:
    item = next((item for item in review.items if item.id == cue_id), None)
    if item is not None:
        item.status = ReviewStatus.UNREVIEWED
        item.reviewed_content_hash = None
        item.updated_at = _now()


def _touch_review(review: Review) -> None:
    review.revision += 1


def _update_manifest(docs: _Documents, lang: str | None) -> None:
    review = docs.reviews[lang]
    progress = _progress(docs.cues, _target_for(docs, lang), review)
    docs.manifest.stages[Stage.REVIEW] = StageState(
        status=(
            StageStatus.DONE
            if progress.reviewed == progress.total and progress.flagged == 0
            else StageStatus.RUNNING
        ),
        artifact=review_path(Path("."), lang).name,
        updated_at=_now(),
        progress=Progress(done=progress.reviewed, total=progress.total),
    )
    for stage in (Stage.EXPORT, Stage.BURN):
        if stage in docs.manifest.stages:
            docs.manifest.stages[stage] = StageState(status=StageStatus.PENDING)


def _serialized(path: Path, docs: _Documents) -> dict[Path, str]:
    values: dict[Path, str] = {
        path / ws.MANIFEST_NAME: docs.manifest.model_dump_json(
            indent=2, exclude_none=True
        ),
        path / "cues.json": docs.cues.model_dump_json(indent=2, exclude_none=True),
    }
    for lang, translation in docs.translations.items():
        values[ws.worksheet_path(path, lang)] = translation.model_dump_json(indent=2)
    for lang, review in docs.reviews.items():
        values[review_path(path, lang)] = review.model_dump_json(indent=2)
    return values


def _capture(path: Path) -> dict[str, bytes | None]:
    files = [path / ws.MANIFEST_NAME, path / "cues.json"]
    files.extend(sorted(path.glob("translation.*.json")))
    files.extend(sorted(path.glob("review.*.json")))
    return {
        str(file.relative_to(path)): file.read_bytes() if file.exists() else None
        for file in files
    }


def _state_dir(path: Path) -> Path:
    result = path / _STATE_DIR
    result.mkdir(parents=True, exist_ok=True)
    return result


def _checkpoint(path: Path, op_id: str, before: dict[str, bytes | None]) -> Path:
    root = _state_dir(path) / _CHECKPOINTS
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    safe = _SAFE_OP_RE.sub("-", op_id)[:64] or "operation"
    checkpoint = root / f"{stamp}-{safe}"
    files_dir = checkpoint / "files"
    files_dir.mkdir(parents=True)
    existed: dict[str, bool] = {}
    for rel, content in before.items():
        existed[rel] = content is not None
        if content is not None:
            dest = files_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
    (checkpoint / "metadata.json").write_text(
        json.dumps({"files": existed}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    checkpoints = sorted(p for p in root.iterdir() if p.is_dir())
    for old in checkpoints[:-_CHECKPOINT_LIMIT]:
        shutil.rmtree(old)
    return checkpoint


def _restore_capture(path: Path, capture: dict[str, bytes | None]) -> None:
    for rel, content in capture.items():
        target = path / rel
        if content is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            ws.write_text_atomic(target, content.decode("utf-8"))


def _recover_pending(path: Path) -> None:
    journal = path / _STATE_DIR / _JOURNAL
    if not journal.exists():
        return
    try:
        data = json.loads(journal.read_text(encoding="utf-8"))
        checkpoint = path / data["checkpoint"]
        metadata = json.loads(
            (checkpoint / "metadata.json").read_text(encoding="utf-8")
        )
        capture: dict[str, bytes | None] = {}
        for rel, existed in metadata["files"].items():
            capture[rel] = (
                (checkpoint / "files" / rel).read_bytes() if existed else None
            )
        _restore_capture(path, capture)
        journal.unlink(missing_ok=True)
    except (OSError, KeyError, json.JSONDecodeError) as e:
        raise OpenBBQError(
            "review_recovery_required",
            journal=str(journal),
            fix="inspect the review journal and checkpoint before retrying",
        ) from e


T = TypeVar("T")


class ReviewSession:
    """Stateful single-process review session with an in-memory undo stack."""

    def __init__(self, path: Path, lang: str | None) -> None:
        self.path = path
        self.lang = lang
        self._history: list[dict[str, bytes | None]] = []
        self._redo: list[dict[str, bytes | None]] = []
        self._op_results: dict[str, ReviewSnapshot] = {}

    @classmethod
    def open(cls, path: Path, lang: str | None) -> ReviewSession:
        path = path.resolve()
        _recover_pending(path)
        docs = _load_documents(path)
        _target_for(docs, lang)
        changed = False
        if lang not in docs.reviews:
            docs.reviews[lang] = _new_review(docs, lang)
            changed = True
        changed = _reconcile(docs) or changed
        if changed:
            _update_manifest(docs, lang)
            values = _serialized(path, docs)
            for file, content in values.items():
                ws.write_text_atomic(file, content)
        return cls(path, lang)

    def snapshot(self, *, changed: list[int] | None = None) -> ReviewSnapshot:
        docs = _load_documents(self.path)
        _target_for(docs, self.lang)
        review = docs.reviews.get(self.lang)
        if review is None:
            raise OpenBBQError("invalid_review", lang=self.lang or "source")
        translation = _target_for(docs, self.lang)
        return ReviewSnapshot(
            cues=docs.cues,
            translation=translation,
            review=review,
            revision=_revision(self.path),
            progress=_progress(docs.cues, translation, review),
            changed=changed or [],
        )

    def _commit(
        self,
        docs: _Documents,
        *,
        op_id: str,
        before: dict[str, bytes | None],
        record_history: bool = True,
    ) -> None:
        _validate_timeline(docs.cues)
        _reorder(docs)
        _update_manifest(docs, self.lang)
        checkpoint = _checkpoint(self.path, op_id, before)
        journal = _state_dir(self.path) / _JOURNAL
        ws.write_text_atomic(
            journal,
            json.dumps(
                {"op_id": op_id, "checkpoint": str(checkpoint.relative_to(self.path))},
                ensure_ascii=False,
            ),
        )
        try:
            for file, content in _serialized(self.path, docs).items():
                ws.write_text_atomic(file, content)
        except Exception:
            _restore_capture(self.path, before)
            raise
        else:
            journal.unlink(missing_ok=True)
        if record_history:
            self._append_history(self._history, before)
            self._redo.clear()

    def _mutate(
        self,
        *,
        base_revision: str,
        op_id: str,
        changed: list[int],
        mutate: Callable[[_Documents], None],
    ) -> ReviewSnapshot:
        previous = self._previous_result(op_id)
        if previous is not None:
            return previous
        current = _revision(self.path)
        if current != base_revision:
            raise OpenBBQError(
                "review_conflict",
                expected=base_revision,
                actual=current,
                fix="reload the review session or export a recovery patch",
            )
        before = _capture(self.path)
        docs = _load_documents(self.path)
        mutate(docs)
        current_review = docs.reviews[self.lang]
        current_review.recent_op_ids = [
            *[item for item in current_review.recent_op_ids if item != op_id][-99:],
            op_id,
        ]
        self._commit(docs, op_id=op_id, before=before)
        result = self.snapshot(changed=changed)
        self._remember_result(op_id, result)
        return result

    def _previous_result(self, op_id: str) -> ReviewSnapshot | None:
        cached = self._op_results.get(op_id)
        if cached is not None:
            return cached
        persisted = _load_documents(self.path).reviews.get(self.lang)
        if persisted is not None and op_id in persisted.recent_op_ids:
            return self.snapshot()
        return None

    def _remember_result(self, op_id: str, result: ReviewSnapshot) -> None:
        self._op_results[op_id] = result
        while len(self._op_results) > _OP_RESULT_LIMIT:
            self._op_results.pop(next(iter(self._op_results)))

    @staticmethod
    def _append_history(
        stack: list[dict[str, bytes | None]], capture: dict[str, bytes | None]
    ) -> None:
        stack.append(capture)
        del stack[:-_CHECKPOINT_LIMIT]

    def update_cue(
        self,
        cue_id: int,
        *,
        source: str | None = None,
        target: str | None = None,
        start: float | None = None,
        end: float | None = None,
        base_revision: str,
        op_id: str,
    ) -> ReviewSnapshot:
        def apply(docs: _Documents) -> None:
            cue = next((cue for cue in docs.cues.cues if cue.id == cue_id), None)
            if cue is None:
                raise OpenBBQError("unknown_cue", id=cue_id)
            source_changed = source is not None and source != cue.source
            time_changed = (start is not None and start != cue.start) or (
                end is not None and end != cue.end
            )
            target_changed = False
            if source is not None:
                cue.source = source
            if start is not None:
                cue.start = start
            if end is not None:
                cue.end = end
            for translation in docs.translations.values():
                item = _translation_item(translation, cue_id)
                if item is None:
                    raise OpenBBQError("id_mismatch", id=cue_id)
                if source_changed:
                    item.source = cue.source
                if time_changed:
                    item.budget = translatelib.budget_for_cue(
                        cue.start, cue.end, translation.params
                    )
            if target is not None:
                translation = _target_for(docs, self.lang)
                if translation is None:
                    raise OpenBBQError("translation_required", id=cue_id)
                item = _translation_item(translation, cue_id)
                if item is None:
                    raise OpenBBQError("id_mismatch", id=cue_id)
                target_changed = target != item.target
                item.target = target
            if source_changed or time_changed:
                for review in docs.reviews.values():
                    _reset_review_item(review, cue_id)
                    _touch_review(review)
            elif target_changed:
                review = docs.reviews[self.lang]
                _reset_review_item(review, cue_id)
                _touch_review(review)

        return self._mutate(
            base_revision=base_revision,
            op_id=op_id,
            changed=[cue_id],
            mutate=apply,
        )

    def set_status(
        self,
        cue_id: int,
        status: ReviewStatus,
        *,
        note: str | None = None,
        base_revision: str,
        op_id: str,
    ) -> ReviewSnapshot:
        def apply(docs: _Documents) -> None:
            cue = next((cue for cue in docs.cues.cues if cue.id == cue_id), None)
            if cue is None:
                raise OpenBBQError("unknown_cue", id=cue_id)
            translation = _target_for(docs, self.lang)
            target_item = _translation_item(translation, cue_id)
            if status is ReviewStatus.REVIEWED:
                if not cue.source.strip() or (
                    translation is not None
                    and (
                        target_item is None
                        or not translatelib.is_filled(target_item.target)
                    )
                ):
                    raise OpenBBQError("review_blocked", id=cue_id)
            review = docs.reviews[self.lang]
            item = next((item for item in review.items if item.id == cue_id), None)
            if item is None:
                raise OpenBBQError("id_mismatch", id=cue_id)
            item.status = status
            item.note = note
            item.updated_at = _now()
            item.reviewed_content_hash = (
                _review_hash(cue, translation)
                if status is ReviewStatus.REVIEWED
                else None
            )
            _touch_review(review)

        return self._mutate(
            base_revision=base_revision,
            op_id=op_id,
            changed=[cue_id],
            mutate=apply,
        )

    def split_cue(
        self,
        cue_id: int,
        *,
        at: float,
        source_left: str,
        source_right: str,
        target_left: str | None,
        target_right: str | None,
        base_revision: str,
        op_id: str,
    ) -> ReviewSnapshot:
        new_id_box: list[int] = []

        def apply(docs: _Documents) -> None:
            index = next(
                (i for i, cue in enumerate(docs.cues.cues) if cue.id == cue_id), -1
            )
            if index < 0:
                raise OpenBBQError("unknown_cue", id=cue_id)
            cue = docs.cues.cues[index]
            half_gap = docs.cues.params.min_gap / 2
            left_end = round(at - half_gap, 3)
            right_start = round(at + half_gap, 3)
            if left_end <= cue.start or right_start >= cue.end:
                raise OpenBBQError("invalid_split", id=cue_id, at=at)
            new_id = _max_next_id(docs)
            new_id_box.append(new_id)
            original_end = cue.end
            cue.end = left_end
            cue.source = source_left
            right = Cue(
                id=new_id, start=right_start, end=original_end, source=source_right
            )
            docs.cues.cues.insert(index + 1, right)

            for lang, translation in docs.translations.items():
                item_index = next(
                    (
                        i
                        for i, item in enumerate(translation.items)
                        if item.id == cue_id
                    ),
                    -1,
                )
                if item_index < 0:
                    raise OpenBBQError("id_mismatch", id=cue_id, lang=lang)
                item = translation.items[item_index]
                old_target = item.target
                item.source = source_left
                item.budget = translatelib.budget_for_cue(
                    cue.start, cue.end, translation.params
                )
                if lang == self.lang:
                    item.target = target_left
                    right_target = target_right
                else:
                    item.target = old_target
                    right_target = None
                translation.items.insert(
                    item_index + 1,
                    TranslationItem(
                        id=new_id,
                        source=source_right,
                        budget=translatelib.budget_for_cue(
                            right.start, right.end, translation.params
                        ),
                        target=right_target,
                    ),
                )
            for review in docs.reviews.values():
                item_index = next(
                    (i for i, item in enumerate(review.items) if item.id == cue_id), -1
                )
                if item_index < 0:
                    raise OpenBBQError("id_mismatch", id=cue_id)
                _reset_review_item(review, cue_id)
                review.items.insert(item_index + 1, ReviewItem(id=new_id))
                review.next_cue_id = new_id + 1
                _touch_review(review)

        result = self._mutate(
            base_revision=base_revision,
            op_id=op_id,
            changed=[cue_id],
            mutate=apply,
        )
        changed = [cue_id, new_id_box[0]] if new_id_box else result.changed
        result = ReviewSnapshot(
            cues=result.cues,
            translation=result.translation,
            review=result.review,
            revision=result.revision,
            progress=result.progress,
            changed=changed,
        )
        self._remember_result(op_id, result)
        return result

    def merge_cues(
        self,
        cue_ids: list[int],
        *,
        base_revision: str,
        op_id: str,
    ) -> ReviewSnapshot:
        if len(cue_ids) < 2:
            raise OpenBBQError("non_adjacent_merge", ids=cue_ids)

        def apply(docs: _Documents) -> None:
            indexes = [
                next((i for i, cue in enumerate(docs.cues.cues) if cue.id == id_), -1)
                for id_ in cue_ids
            ]
            if -1 in indexes or indexes != list(
                range(indexes[0], indexes[0] + len(indexes))
            ):
                raise OpenBBQError("non_adjacent_merge", ids=cue_ids)
            selected = [docs.cues.cues[i] for i in indexes]
            first = selected[0]
            first.source = _join_text(
                [cue.source for cue in selected], docs.cues.source_lang
            )
            first.end = selected[-1].end
            docs.cues.cues[indexes[0] : indexes[-1] + 1] = [first]
            removed = set(cue_ids[1:])
            for translation in docs.translations.values():
                items = [
                    next(item for item in translation.items if item.id == id_)
                    for id_ in cue_ids
                ]
                base = items[0]
                base.source = first.source
                targets = [
                    item.target for item in items if translatelib.is_filled(item.target)
                ]
                base.target = (
                    _join_text(
                        [target or "" for target in targets], translation.target_lang
                    )
                    if targets
                    else None
                )
                base.budget = translatelib.budget_for_cue(
                    first.start, first.end, translation.params
                )
                translation.items = [
                    item for item in translation.items if item.id not in removed
                ]
            for review in docs.reviews.values():
                review.items = [item for item in review.items if item.id not in removed]
                _reset_review_item(review, first.id)
                _touch_review(review)

        return self._mutate(
            base_revision=base_revision,
            op_id=op_id,
            changed=cue_ids,
            mutate=apply,
        )

    def insert_cue(
        self,
        *,
        at: float,
        base_revision: str,
        op_id: str,
    ) -> ReviewSnapshot:
        new_id_box: list[int] = []

        def apply(docs: _Documents) -> None:
            gap = docs.cues.params.min_gap
            index = next(
                (i for i, cue in enumerate(docs.cues.cues) if cue.start > at),
                len(docs.cues.cues),
            )
            previous = docs.cues.cues[index - 1] if index > 0 else None
            following = docs.cues.cues[index] if index < len(docs.cues.cues) else None
            start = max(0.0, at, (previous.end + gap) if previous else 0.0)
            upper = (following.start - gap) if following else start + 2.0
            end = min(start + 2.0, upper)
            if end <= start:
                raise OpenBBQError(
                    "invalid_timeline", at=at, detail="no room for a cue"
                )
            new_id = _max_next_id(docs)
            new_id_box.append(new_id)
            cue = Cue(id=new_id, start=start, end=end, source="")
            docs.cues.cues.insert(index, cue)
            for translation in docs.translations.values():
                translation.items.insert(
                    index,
                    TranslationItem(
                        id=new_id,
                        source="",
                        budget=translatelib.budget_for_cue(
                            start, end, translation.params
                        ),
                        target=None,
                    ),
                )
            for review in docs.reviews.values():
                review.items.insert(index, ReviewItem(id=new_id))
                review.next_cue_id = new_id + 1
                _touch_review(review)

        result = self._mutate(
            base_revision=base_revision,
            op_id=op_id,
            changed=[],
            mutate=apply,
        )
        changed = new_id_box[:]
        result = ReviewSnapshot(
            cues=result.cues,
            translation=result.translation,
            review=result.review,
            revision=result.revision,
            progress=result.progress,
            changed=changed,
        )
        self._remember_result(op_id, result)
        return result

    def delete_cue(
        self,
        cue_id: int,
        *,
        base_revision: str,
        op_id: str,
    ) -> ReviewSnapshot:
        def apply(docs: _Documents) -> None:
            if not any(cue.id == cue_id for cue in docs.cues.cues):
                raise OpenBBQError("unknown_cue", id=cue_id)
            docs.cues.cues = [cue for cue in docs.cues.cues if cue.id != cue_id]
            for translation in docs.translations.values():
                translation.items = [
                    item for item in translation.items if item.id != cue_id
                ]
            for review in docs.reviews.values():
                review.items = [item for item in review.items if item.id != cue_id]
                _touch_review(review)

        return self._mutate(
            base_revision=base_revision,
            op_id=op_id,
            changed=[cue_id],
            mutate=apply,
        )

    def undo(self, *, base_revision: str, op_id: str) -> ReviewSnapshot:
        previous_result = self._previous_result(op_id)
        if previous_result is not None:
            return previous_result
        if _revision(self.path) != base_revision:
            raise OpenBBQError(
                "review_conflict", expected=base_revision, actual=_revision(self.path)
            )
        if not self._history:
            raise OpenBBQError("nothing_to_undo")
        current = _capture(self.path)
        previous = self._history.pop()
        self._append_history(self._redo, current)
        _restore_capture(self.path, previous)
        docs = _load_documents(self.path)
        docs.reviews[self.lang].revision += 1
        docs.reviews[self.lang].recent_op_ids = [
            *docs.reviews[self.lang].recent_op_ids[-99:],
            op_id,
        ]
        _update_manifest(docs, self.lang)
        for file, content in _serialized(self.path, docs).items():
            ws.write_text_atomic(file, content)
        result = self.snapshot()
        self._remember_result(op_id, result)
        return result

    def redo(self, *, base_revision: str, op_id: str) -> ReviewSnapshot:
        previous_result = self._previous_result(op_id)
        if previous_result is not None:
            return previous_result
        if _revision(self.path) != base_revision:
            raise OpenBBQError(
                "review_conflict", expected=base_revision, actual=_revision(self.path)
            )
        if not self._redo:
            raise OpenBBQError("nothing_to_redo")
        current = _capture(self.path)
        following = self._redo.pop()
        self._append_history(self._history, current)
        _restore_capture(self.path, following)
        docs = _load_documents(self.path)
        docs.reviews[self.lang].revision += 1
        docs.reviews[self.lang].recent_op_ids = [
            *docs.reviews[self.lang].recent_op_ids[-99:],
            op_id,
        ]
        _update_manifest(docs, self.lang)
        for file, content in _serialized(self.path, docs).items():
            ws.write_text_atomic(file, content)
        result = self.snapshot()
        self._remember_result(op_id, result)
        return result


def _join_text(values: list[str], lang: str) -> str:
    profile, _ = seg.resolve_profile(lang)
    separator = "" if profile.cjk else " "
    return separator.join(value.strip() for value in values if value.strip())


def require_complete_review(
    path: Path,
    cues: Cues,
    translation: Translation | None,
    lang: str | None,
) -> None:
    """Enforce review only when a corresponding review file exists."""
    file = review_path(path, lang)
    if not file.exists():
        return
    review = ws.read_review(file)
    if review.source_lang != cues.source_lang or review.target_lang != lang:
        raise OpenBBQError(
            "invalid_review",
            lang=lang or "source",
            fix="reopen the review workspace or restore the matching review file",
        )
    review_of = {item.id: item for item in review.items}
    unreviewed: list[int] = []
    flagged: list[int] = []
    stale: list[int] = []
    for cue in cues.cues:
        item = review_of.get(cue.id)
        if item is None or item.status is ReviewStatus.UNREVIEWED:
            unreviewed.append(cue.id)
        elif item.status is ReviewStatus.FLAGGED:
            flagged.append(cue.id)
        elif item.reviewed_content_hash != _review_hash(cue, translation):
            stale.append(cue.id)
    extra = sorted(set(review_of) - {cue.id for cue in cues.cues})
    if unreviewed or flagged or stale or extra:
        raise OpenBBQError(
            "review_incomplete",
            lang=lang or "source",
            unreviewed=unreviewed[:20],
            flagged=flagged[:20],
            stale=stale[:20],
            extra=extra[:20],
            fix="finish review, or pass --allow-unreviewed",
        )


class ReviewLock:
    """Exclusive process lock used by the review server lifecycle."""

    def __init__(self, path: Path) -> None:
        self.path = _state_dir(path) / _LOCK
        self._held = False

    def acquire(self) -> None:
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as e:
            if self._remove_stale():
                return self.acquire()
            raise OpenBBQError(
                "review_locked",
                lock=str(self.path),
                fix="close the existing review session",
            ) from e
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"pid": os.getpid(), "created_at": _now().isoformat()})
            )
        self._held = True

    def _remove_stale(self) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            pid = int(data["pid"])
            os.kill(pid, 0)
        except ProcessLookupError:
            self.path.unlink(missing_ok=True)
            return True
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False
        return False

    def release(self) -> None:
        if self._held:
            self.path.unlink(missing_ok=True)
            self._held = False

    def __enter__(self) -> ReviewLock:
        self.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        self.release()

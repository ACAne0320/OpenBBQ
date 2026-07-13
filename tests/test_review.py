from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from openbbq.core import review
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    Budget,
    Cue,
    Cues,
    Manifest,
    Review,
    ReviewItem,
    ReviewStatus,
    SegmentParams,
    Source,
    Stage,
    StageState,
    StageStatus,
    Translation,
    TranslationItem,
)


EN_PARAMS = SegmentParams(
    max_cps=20,
    max_chars_per_line=80,
    max_lines=1,
    min_dur=0.5,
    max_dur=7,
    min_gap=0.1,
)
ZH_PARAMS = SegmentParams(
    max_cps=10,
    max_chars_per_line=30,
    max_lines=1,
    min_dur=0.5,
    max_dur=7,
    min_gap=0.1,
)
JA_PARAMS = SegmentParams(
    max_cps=5,
    max_chars_per_line=30,
    max_lines=1,
    min_dur=0.5,
    max_dur=7,
    min_gap=0.1,
)


def _translation(lang: str, params: SegmentParams) -> Translation:
    targets = {
        "zh": {1: "你好世界", 2: "第二句", 3: "第三句"},
        "ja": {1: "こんにちは世界", 2: "二つ目", 3: "三つ目"},
    }[lang]
    sources = {1: "Hello world", 2: "Second cue", 3: "Third cue"}
    return Translation(
        source_lang="en",
        target_lang=lang,
        params=params,
        items=[
            TranslationItem(
                id=id_,
                source=source,
                budget=Budget(max_chars=20, seconds=1.9),
                target=targets[id_],
            )
            for id_, source in sources.items()
        ],
    )


def _workspace(path: Path) -> Path:
    path.mkdir()
    source = path / "source.wav"
    source.write_bytes(b"fake-audio")
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_audio", ref=str(source), title="Review fixture"),
        stages={
            Stage.SEGMENT: StageState(status=StageStatus.DONE, artifact="cues.json"),
            Stage.TRANSLATE: StageState(
                status=StageStatus.DONE,
                artifact="translation.zh.json",
            ),
            Stage.EXPORT: StageState(
                status=StageStatus.DONE,
                artifact="out/zh.srt",
            ),
            Stage.BURN: StageState(
                status=StageStatus.DONE,
                artifact="out/zh-burned.mp4",
            ),
        },
    )
    ws.write_manifest(path, manifest)
    cues = Cues(
        source_lang="en",
        params=EN_PARAMS,
        cues=[
            Cue(id=1, start=0, end=1.9, source="Hello world"),
            Cue(id=2, start=3, end=4.9, source="Second cue"),
            Cue(id=3, start=6, end=7.9, source="Third cue"),
        ],
    )
    ws.write_text_atomic(path / "cues.json", cues.model_dump_json(indent=2))
    ws.write_text_atomic(
        path / "translation.zh.json",
        _translation("zh", ZH_PARAMS).model_dump_json(indent=2),
    )
    ws.write_text_atomic(
        path / "translation.ja.json",
        _translation("ja", JA_PARAMS).model_dump_json(indent=2),
    )
    return path


def test_open_initializes_review_and_marking_reviewed_persists(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")

    session = review.ReviewSession.open(path, "zh")
    initial = session.snapshot()

    assert initial.review.target_lang == "zh"
    assert initial.review.next_cue_id == 4
    assert [item.status for item in initial.review.items] == [
        ReviewStatus.UNREVIEWED,
        ReviewStatus.UNREVIEWED,
        ReviewStatus.UNREVIEWED,
    ]

    result = session.set_status(
        1,
        ReviewStatus.REVIEWED,
        base_revision=initial.revision,
        op_id="review-1",
    )

    assert result.progress.reviewed == 1
    stored = ws.read_review(path / "review.zh.json")
    assert stored.items[0].status is ReviewStatus.REVIEWED
    assert stored.items[0].reviewed_content_hash is not None
    manifest = ws.read_manifest(path)
    assert manifest.stages[Stage.REVIEW].status is StageStatus.RUNNING
    progress = manifest.stages[Stage.REVIEW].progress
    assert progress is not None
    assert progress.done == 1


def test_review_schema_round_trip_and_identity_validation() -> None:
    document = Review(
        source_lang="en",
        target_lang="zh",
        revision=2,
        next_cue_id=3,
        recent_op_ids=["op-1"],
        items=[
            ReviewItem(id=1),
            ReviewItem(
                id=2,
                status=ReviewStatus.REVIEWED,
                reviewed_content_hash="sha256:" + "a" * 64,
            ),
        ],
    )

    assert Review.model_validate_json(document.model_dump_json()) == document

    invalid_documents = [
        document.model_copy(update={"items": [ReviewItem(id=1), ReviewItem(id=1)]}),
        document.model_copy(update={"next_cue_id": 2}),
        document.model_copy(update={"target_lang": ""}),
        document.model_copy(update={"recent_op_ids": ["same", "same"]}),
    ]
    for invalid in invalid_documents:
        with pytest.raises(ValidationError):
            Review.model_validate(invalid.model_dump())

    with pytest.raises(ValidationError):
        ReviewItem(id=1, status=ReviewStatus.REVIEWED)
    with pytest.raises(ValidationError):
        ReviewItem(id=1, reviewed_content_hash="sha256:not-a-digest")
    with pytest.raises(ValidationError):
        Review.model_validate({**document.model_dump(), "unexpected": True})


def test_update_source_and_time_syncs_all_worksheets_and_invalidates_review(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path / "ws")
    zh = review.ReviewSession.open(path, "zh")
    marked = zh.set_status(
        1,
        ReviewStatus.REVIEWED,
        base_revision=zh.snapshot().revision,
        op_id="review-1",
    )
    review.ReviewSession.open(path, "ja")
    zh = review.ReviewSession.open(path, "zh")

    result = zh.update_cue(
        1,
        source="Hello brave world",
        start=0.2,
        end=2.2,
        base_revision=zh.snapshot().revision,
        op_id="update-1",
    )

    assert result.changed == [1]
    cues = ws.read_cues(path / "cues.json")
    assert cues.cues[0] == Cue(id=1, start=0.2, end=2.2, source="Hello brave world")
    for lang, expected_budget in (("zh", 20), ("ja", 10)):
        worksheet = ws.read_translation(path / f"translation.{lang}.json")
        assert worksheet.items[0].source == "Hello brave world"
        assert worksheet.items[0].budget.seconds == 2.0
        assert worksheet.items[0].budget.max_chars == expected_budget
        stored_review = ws.read_review(path / f"review.{lang}.json")
        assert stored_review.items[0].status is ReviewStatus.UNREVIEWED
    manifest = ws.read_manifest(path)
    assert manifest.stages[Stage.EXPORT].status is StageStatus.PENDING
    assert manifest.stages[Stage.BURN].status is StageStatus.PENDING
    assert result.revision != marked.revision


def test_split_preserves_current_language_parts_and_blanks_other_languages(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path / "ws")
    review.ReviewSession.open(path, "ja")
    session = review.ReviewSession.open(path, "zh")

    result = session.split_cue(
        1,
        at=1.0,
        source_left="Hello",
        source_right="world",
        target_left="你好",
        target_right="世界",
        base_revision=session.snapshot().revision,
        op_id="split-1",
    )

    assert result.changed == [1, 4]
    cues = ws.read_cues(path / "cues.json")
    assert [(cue.id, cue.source) for cue in cues.cues] == [
        (1, "Hello"),
        (4, "world"),
        (2, "Second cue"),
        (3, "Third cue"),
    ]
    assert cues.cues[0].end == 0.95
    assert cues.cues[1].start == 1.05

    zh = ws.read_translation(path / "translation.zh.json")
    assert [(item.id, item.target) for item in zh.items[:2]] == [
        (1, "你好"),
        (4, "世界"),
    ]
    ja = ws.read_translation(path / "translation.ja.json")
    assert [(item.id, item.target) for item in ja.items[:2]] == [
        (1, "こんにちは世界"),
        (4, None),
    ]
    for lang in ("zh", "ja"):
        doc = ws.read_review(path / f"review.{lang}.json")
        assert doc.next_cue_id == 5
        assert [item.id for item in doc.items] == [1, 4, 2, 3]


def test_merge_insert_delete_and_undo_keep_documents_aligned(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    session = review.ReviewSession.open(path, "zh")

    inserted = session.insert_cue(
        at=2.0,
        base_revision=session.snapshot().revision,
        op_id="insert-1",
    )
    new_id = inserted.changed[0]
    assert new_id == 4

    updated = session.update_cue(
        new_id,
        source="Inserted",
        target="插入",
        base_revision=inserted.revision,
        op_id="fill-inserted",
    )
    deleted = session.delete_cue(
        new_id,
        base_revision=updated.revision,
        op_id="delete-inserted",
    )
    assert deleted.changed == [new_id]

    undone = session.undo(base_revision=deleted.revision, op_id="undo-delete")
    assert any(
        cue.id == new_id and cue.source == "Inserted" for cue in undone.cues.cues
    )

    merged = session.merge_cues(
        [1, new_id],
        base_revision=undone.revision,
        op_id="merge-1",
    )
    assert merged.changed == [1, new_id]
    assert merged.cues.cues[0].source == "Hello world Inserted"
    for lang in ("zh", "ja"):
        worksheet = ws.read_translation(path / f"translation.{lang}.json")
        review_doc = ws.read_review(path / "review.zh.json")
        assert [item.id for item in worksheet.items] == [
            cue.id for cue in merged.cues.cues
        ]
        assert [item.id for item in review_doc.items] == [
            cue.id for cue in merged.cues.cues
        ]


def test_revision_conflict_and_repeated_operation_are_safe(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    session = review.ReviewSession.open(path, "zh")
    base = session.snapshot().revision

    first = session.split_cue(
        1,
        at=1.0,
        source_left="Hello",
        source_right="world",
        target_left="你好",
        target_right="世界",
        base_revision=base,
        op_id="same-op",
    )
    repeated = session.split_cue(
        1,
        at=1.0,
        source_left="Hello",
        source_right="world",
        target_left="你好",
        target_right="世界",
        base_revision=base,
        op_id="same-op",
    )

    assert repeated.revision == first.revision
    assert len(repeated.cues.cues) == 4

    restarted = review.ReviewSession.open(path, "zh")
    repeated_after_restart = restarted.split_cue(
        1,
        at=1.0,
        source_left="Hello",
        source_right="world",
        target_left="你好",
        target_right="世界",
        base_revision=base,
        op_id="same-op",
    )
    assert len(repeated_after_restart.cues.cues) == 4

    with pytest.raises(OpenBBQError) as raised:
        session.update_cue(
            2,
            source="stale edit",
            base_revision=base,
            op_id="stale-op",
        )
    assert raised.value.code == "review_conflict"


def test_active_session_rejects_external_file_changes(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    session = review.ReviewSession.open(path, "zh")
    base = session.snapshot().revision
    cues = ws.read_cues(path / "cues.json")
    cues.cues[0].source = "edited outside the review service"
    ws.write_text_atomic(path / "cues.json", cues.model_dump_json(indent=2))

    with pytest.raises(OpenBBQError) as raised:
        session.update_cue(
            2,
            source="must not overwrite the external edit",
            base_revision=base,
            op_id="after-external-change",
        )

    assert raised.value.code == "review_conflict"
    assert ws.read_cues(path / "cues.json").cues[0].source == cues.cues[0].source


def test_invalid_overlap_rolls_back_and_undo_redo_are_symmetric(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    session = review.ReviewSession.open(path, "zh")
    initial = session.snapshot()

    with pytest.raises(OpenBBQError) as raised:
        session.update_cue(
            2,
            start=1.8,
            base_revision=initial.revision,
            op_id="overlap",
        )
    assert raised.value.code == "invalid_timeline"
    assert ws.read_cues(path / "cues.json").cues[1].start == 3

    inserted = session.insert_cue(
        at=2.0,
        base_revision=session.snapshot().revision,
        op_id="insert-for-redo",
    )
    inserted_id = inserted.changed[0]
    undone = session.undo(base_revision=inserted.revision, op_id="undo-insert")
    assert all(cue.id != inserted_id for cue in undone.cues.cues)
    repeated_undo = session.undo(base_revision=inserted.revision, op_id="undo-insert")
    assert repeated_undo.revision == undone.revision
    redone = session.redo(base_revision=undone.revision, op_id="redo-insert")
    assert any(cue.id == inserted_id for cue in redone.cues.cues)
    repeated_redo = session.redo(base_revision=undone.revision, op_id="redo-insert")
    assert repeated_redo.revision == redone.revision


def test_source_only_review_uses_a_separate_document(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    session = review.ReviewSession.open(path, None)
    snapshot = session.snapshot()

    assert snapshot.translation is None
    assert snapshot.review.target_lang is None
    assert (path / "review.source.json").exists()
    result = session.set_status(
        1,
        ReviewStatus.REVIEWED,
        base_revision=snapshot.revision,
        op_id="review-source",
    )
    assert result.progress.reviewed == 1


def test_reviewed_content_gate_reports_incomplete_and_stale(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    session = review.ReviewSession.open(path, "zh")
    revision = session.snapshot().revision
    for cue_id in (1, 2, 3):
        result = session.set_status(
            cue_id,
            ReviewStatus.REVIEWED,
            base_revision=revision,
            op_id=f"review-{cue_id}",
        )
        revision = result.revision

    cues = ws.read_cues(path / "cues.json")
    translation = ws.read_translation(path / "translation.zh.json")
    review.require_complete_review(path, cues, translation, "zh")

    translation.items[1].target = "外部修改"
    ws.write_text_atomic(
        path / "translation.zh.json", translation.model_dump_json(indent=2)
    )

    with pytest.raises(OpenBBQError) as raised:
        review.require_complete_review(path, cues, translation, "zh")
    assert raised.value.code == "review_incomplete"
    assert raised.value.context["stale"] == [2]


def test_cross_file_failure_rolls_back_and_next_open_recovers_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _workspace(tmp_path / "ws")
    session = review.ReviewSession.open(path, "zh")
    canonical = {
        name: (path / name).read_bytes()
        for name in (
            "manifest.json",
            "cues.json",
            "translation.zh.json",
            "review.zh.json",
        )
    }
    original_write = review.ws.write_text_atomic
    failed = False

    def fail_once(file: Path, content: str) -> None:
        nonlocal failed
        if file.name == "translation.zh.json" and not failed:
            failed = True
            raise OSError("simulated disk failure")
        original_write(file, content)

    monkeypatch.setattr(review.ws, "write_text_atomic", fail_once)

    with pytest.raises(OSError, match="simulated disk failure"):
        session.update_cue(
            1,
            source="must roll back",
            base_revision=session.snapshot().revision,
            op_id="failing-transaction",
        )

    for name, expected in canonical.items():
        assert (path / name).read_bytes() == expected
    journal = path / ".openbbq" / "review" / "journal.json"
    assert journal.exists()

    monkeypatch.setattr(review.ws, "write_text_atomic", original_write)
    recovered = review.ReviewSession.open(path, "zh")

    assert recovered.snapshot().cues.cues[0].source == "Hello world"
    assert not journal.exists()


def test_review_lock_reclaims_stale_pid_and_rejects_live_second_session(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path / "ws")
    lock_path = path / ".openbbq" / "review" / "session.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text('{"pid":99999999}', encoding="utf-8")

    first = review.ReviewLock(path)
    first.acquire()
    assert lock_path.exists()

    with pytest.raises(OpenBBQError) as raised:
        review.ReviewLock(path).acquire()
    assert raised.value.code == "review_locked"

    first.release()
    assert not lock_path.exists()

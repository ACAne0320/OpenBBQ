from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from openbbq.core import glossary as glossarylib
from openbbq.core import glossary_overlay
from openbbq.core import review
from openbbq.core import review_issues
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    ASRInfo,
    Budget,
    Cue,
    Cues,
    Glossary,
    GlossaryOverlay,
    GlossaryOverlayEntry,
    GlossaryRef,
    Manifest,
    Review,
    ReviewItem,
    ReviewStatus,
    Segment,
    SegmentParams,
    Source,
    Stage,
    StageState,
    StageStatus,
    Suggestion,
    SuggestionPatch,
    Suggestions,
    SuggestionStatus,
    Term,
    Transcript,
    Translation,
    TranslationItem,
    Word,
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


def _translation(
    lang: str, params: SegmentParams, glossary: list[GlossaryRef] | None = None
) -> Translation:
    targets = {
        "zh": {1: "你好世界", 2: "第二句", 3: "第三句"},
        "ja": {1: "こんにちは世界", 2: "二つ目", 3: "三つ目"},
    }[lang]
    sources = {1: "Hello world", 2: "Second cue", 3: "Third cue"}
    return Translation(
        source_lang="en",
        target_lang=lang,
        params=params,
        glossary=glossary or [],
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


# --- P1: issues, dismissals, suggestions, batch, glossary ----------------------


def _transcript_doc(words: list[Word]) -> Transcript:
    return Transcript(
        language="en",
        duration=10,
        asr=ASRInfo(
            backend="fixture",
            model="fixture",
            created_at=datetime.now(timezone.utc),
        ),
        segments=[Segment(id=0, start=0, end=10, text="fixture", words=words)],
    )


def _suggestion(
    id_: str,
    cue_id: int,
    patch: SuggestionPatch,
    *,
    status: SuggestionStatus = SuggestionStatus.PENDING,
    content_hash: str = "sha256:" + "a" * 64,
) -> Suggestion:
    return Suggestion(
        id=id_,
        cue_id=cue_id,
        kind="agent_note",
        message=f"suggestion {id_}",
        patch=patch,
        content_hash=content_hash,
        status=status,
        created_at=datetime.now(timezone.utc),
    )


def _write_suggestions(path: Path, lang: str, items: list[Suggestion]) -> None:
    doc = Suggestions(source_lang="en", target_lang=lang, suggestions=items)
    ws.write_text_atomic(
        review.suggestions_path(path, lang), doc.model_dump_json(indent=2)
    )


def _snapshot_issues(
    snapshot: review.ReviewSnapshot,
) -> dict[int, list[review_issues.CueIssue]]:
    return review_issues.compute_issues(
        snapshot.cues,
        snapshot.translation,
        snapshot.review,
        snapshot.suggestions,
        None,
    )


def test_issue_computation_covers_every_rule_kind() -> None:
    cues = Cues(
        source_lang="en",
        params=EN_PARAMS,
        cues=[
            Cue(id=1, start=0, end=0.2, source="Hi"),
            Cue(id=2, start=1, end=2, source="x" * 30),
            Cue(id=3, start=2.5, end=4, source="Hello world"),
            Cue(id=4, start=5, end=6.5, source="Budget cue"),
        ],
    )
    translation = Translation(
        source_lang="en",
        target_lang="zh",
        params=ZH_PARAMS,
        glossary=[GlossaryRef(source="Hello", target="哈喽")],
        items=[
            TranslationItem(
                id=1, source="Hi", budget=Budget(max_chars=20, seconds=0.2),
                target="你好",
            ),
            TranslationItem(
                id=2, source="x" * 30, budget=Budget(max_chars=20, seconds=1),
                target="好",
            ),
            TranslationItem(
                id=3, source="Hello world", budget=Budget(max_chars=20, seconds=1.5),
                target="你好世界",
            ),
            TranslationItem(
                id=4, source="Budget cue", budget=Budget(max_chars=2, seconds=1.5),
                target="预算超了啊",
            ),
        ],
    )
    review_doc = Review(
        source_lang="en",
        target_lang="zh",
        next_cue_id=5,
        items=[ReviewItem(id=id_) for id_ in (1, 2, 3, 4)],
    )
    transcript = _transcript_doc(
        [
            Word(word="Hello", start=2.6, end=3.0, prob=0.3),
            Word(word="world", start=3.1, end=3.5),
            Word(word="fine", start=5.1, end=5.5, prob=0.9),
        ]
    )

    issues = review_issues.compute_issues(
        cues, translation, review_doc, None, transcript
    )

    assert [issue.kind for issue in issues[1]] == ["timing"]
    assert issues[1][0].severity == "warning"
    assert issues[1][0].detail == {
        "duration": 0.2,
        "min_duration": 0.5,
        "max_duration": 7,
    }
    assert [issue.kind for issue in issues[2]] == ["timing"]
    assert issues[2][0].detail == {"cps": 30.0, "max_cps": 20}
    assert [issue.kind for issue in issues[3]] == ["term", "asr_confidence"]
    term, asr = issues[3]
    assert term.severity == "warning"
    assert term.detail == {
        "term": "Hello",
        "expected": "哈喽",
        "occurrences": [[0, 5]],
    }
    assert term.source == "rule"
    assert term.dismissed is False
    assert asr.severity == "info"
    assert asr.detail == {
        "words": [{"word": "Hello", "prob": 0.3}],
        "threshold": review_issues.ASR_CONFIDENCE_THRESHOLD,
    }
    assert [issue.kind for issue in issues[4]] == ["budget"]
    assert issues[4][0].detail == {"used": 5, "limit": 2}


def test_asr_confidence_attributes_words_by_midpoint() -> None:
    # Mirrors the real report: word "Frieren." 13.110–13.630 touches cue 2
    # (start 13.63) with zero overlap but belongs to cue 1's text.
    cues = Cues(
        source_lang="en",
        params=EN_PARAMS,
        cues=[
            Cue(id=1, start=11.17, end=13.547, source="Welcome to Exploring Frieren."),
            Cue(id=2, start=13.63, end=16.99, source="My name is Pey, and today..."),
        ],
    )
    review_doc = Review(
        source_lang="en",
        target_lang=None,
        next_cue_id=3,
        items=[ReviewItem(id=1), ReviewItem(id=2)],
    )
    transcript = _transcript_doc(
        [
            Word(word="Frieren.", start=13.11, end=13.63, prob=0.38),
            Word(word="Pey", start=13.5, end=14.0, prob=0.4),
            Word(word="gap", start=13.55, end=13.6, prob=0.4),
        ]
    )

    issues = review_issues.compute_issues(cues, None, review_doc, None, transcript)

    assert [i.kind for i in issues[1]] == ["asr_confidence"]
    assert issues[1][0].detail["words"] == [{"word": "Frieren.", "prob": 0.38}]
    assert [i.kind for i in issues[2]] == ["asr_confidence"]
    assert issues[2][0].detail["words"] == [{"word": "Pey", "prob": 0.4}]
    # A word whose midpoint falls in the gap between cues belongs to neither.
    flagged = [w["word"] for cue_issues in issues.values() for i in cue_issues for w in i.detail.get("words", [])]
    assert "gap" not in flagged


def test_agent_issues_come_from_pending_suggestions(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    _write_suggestions(
        path,
        "zh",
        [
            _suggestion("s1", 1, SuggestionPatch(target="全新译文")),
            Suggestion(
                id="s2",
                cue_id=1,
                kind="agent_note",
                severity="warning",
                message="rejected one",
                patch=SuggestionPatch(target="另一个"),
                content_hash="sha256:" + "b" * 64,
                status=SuggestionStatus.REJECTED,
                created_at=datetime.now(timezone.utc),
                resolved_at=datetime.now(timezone.utc),
            ),
            _suggestion("s3", 99, SuggestionPatch(target="orphan")),
        ],
    )
    snapshot = review.ReviewSession.open(path, "zh").snapshot()

    issues = _snapshot_issues(snapshot)

    agent_notes = [issue for issue in issues[1] if issue.kind == "agent_note"]
    assert len(agent_notes) == 1
    note = agent_notes[0]
    assert note.source == "agent"
    assert note.severity == "info"
    assert note.message == "suggestion s1"
    assert note.suggestion_ids == ["s1"]
    assert note.detail["suggestion_kind"] == "agent_note"
    assert note.detail["content_hash"] == "sha256:" + "a" * 64


def test_suggestions_schema_round_trip_and_validation() -> None:
    doc = Suggestions(
        source_lang="en",
        target_lang="zh",
        suggestions=[_suggestion("s1", 1, SuggestionPatch(target="译文"))],
    )

    assert Suggestions.model_validate_json(doc.model_dump_json()) == doc

    with pytest.raises(ValidationError):
        SuggestionPatch()
    with pytest.raises(ValidationError):
        _suggestion("bad", 1, SuggestionPatch(target="x"), content_hash="sha256:nope")
    with pytest.raises(ValidationError):
        Suggestions(
            source_lang="en",
            target_lang="zh",
            suggestions=[
                _suggestion("same", 1, SuggestionPatch(target="甲")),
                _suggestion("same", 2, SuggestionPatch(target="乙")),
            ],
        )
    with pytest.raises(ValidationError):
        Suggestions.model_validate({**doc.model_dump(), "unexpected": True})


def test_dismissal_marks_issue_and_content_edit_invalidates_it(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path / "ws")
    ws.write_text_atomic(
        path / "translation.zh.json",
        _translation(
            "zh", ZH_PARAMS, glossary=[GlossaryRef(source="Hello", target="哈喽")]
        ).model_dump_json(indent=2),
    )
    session = review.ReviewSession.open(path, "zh")

    dismissed = session.dismiss_issue(
        1, "term", base_revision=session.snapshot().revision, op_id="dismiss-1"
    )
    stored = ws.read_review(path / "review.zh.json")
    assert [d.kind for d in stored.items[0].dismissals] == ["term"]
    term = next(i for i in _snapshot_issues(dismissed)[1] if i.kind == "term")
    assert term.dismissed is True

    # Repeating the same dismissal is a no-op: no revision bump, no write.
    repeated = session.dismiss_issue(
        1, "term", base_revision=dismissed.revision, op_id="dismiss-2"
    )
    assert repeated.changed == []
    assert repeated.revision == dismissed.revision

    # A target-only edit clears the dismissal in the current language ...
    edited = session.update_cue(
        1, target="哈喽世界", base_revision=repeated.revision, op_id="edit-1"
    )
    stored = ws.read_review(path / "review.zh.json")
    assert stored.items[0].dismissals == []
    assert edited.revision != repeated.revision


def test_dismissal_clearing_scope_matches_review_reset_scope(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    zh = review.ReviewSession.open(path, "zh")
    zh.dismiss_issue(1, "timing", base_revision=zh.snapshot().revision, op_id="d-zh")
    ja = review.ReviewSession.open(path, "ja")
    ja.dismiss_issue(1, "timing", base_revision=ja.snapshot().revision, op_id="d-ja")

    # Target-only edit: other languages keep their dismissals.
    zh = review.ReviewSession.open(path, "zh")
    zh.update_cue(
        1, target="新译文", base_revision=zh.snapshot().revision, op_id="edit-target"
    )
    assert ws.read_review(path / "review.zh.json").items[0].dismissals == []
    assert [
        d.kind for d in ws.read_review(path / "review.ja.json").items[0].dismissals
    ] == ["timing"]

    # Source/time edit: every language's dismissals are cleared.
    ja = review.ReviewSession.open(path, "ja")
    zh.update_cue(
        1, start=0.1, base_revision=zh.snapshot().revision, op_id="edit-time"
    )
    for lang in ("zh", "ja"):
        stored = ws.read_review(path / f"review.{lang}.json")
        assert stored.items[0].dismissals == []


def test_accept_suggestion_applies_patch_and_undo_restores_both(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path / "ws")
    _write_suggestions(path, "zh", [_suggestion("s1", 1, SuggestionPatch(target="全新译文"))])
    session = review.ReviewSession.open(path, "zh")
    marked = session.set_status(
        1,
        ReviewStatus.REVIEWED,
        base_revision=session.snapshot().revision,
        op_id="mark-1",
    )

    accepted = session.accept_suggestion(
        "s1", base_revision=marked.revision, op_id="accept-1"
    )

    assert accepted.changed == [1]
    assert accepted.suggestions is not None
    assert accepted.suggestions.suggestions[0].status is SuggestionStatus.ACCEPTED
    translation = ws.read_translation(path / "translation.zh.json")
    assert translation.items[0].target == "全新译文"
    # The accept went through the manual-edit path: review state was reset.
    stored_review = ws.read_review(path / "review.zh.json")
    assert stored_review.items[0].status is ReviewStatus.UNREVIEWED
    stored_suggestions = ws.read_suggestions(review.suggestions_path(path, "zh"))
    assert stored_suggestions.suggestions[0].resolved_at is not None

    undone = session.undo(base_revision=accepted.revision, op_id="undo-accept")
    assert undone.translation is not None
    assert undone.translation.items[0].target == "你好世界"
    restored = ws.read_suggestions(review.suggestions_path(path, "zh"))
    assert restored.suggestions[0].status is SuggestionStatus.PENDING
    assert restored.suggestions[0].resolved_at is None


def test_accept_suggestion_with_matching_content_only_changes_status(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path / "ws")
    # Patch target equals the current target: only the status may change.
    _write_suggestions(path, "zh", [_suggestion("s1", 1, SuggestionPatch(target="你好世界"))])
    session = review.ReviewSession.open(path, "zh")

    accepted = session.accept_suggestion(
        "s1", base_revision=session.snapshot().revision, op_id="accept-same"
    )

    translation = ws.read_translation(path / "translation.zh.json")
    assert translation.items[0].target == "你好世界"
    stored = ws.read_suggestions(review.suggestions_path(path, "zh"))
    assert stored.suggestions[0].status is SuggestionStatus.ACCEPTED
    # The suggestions-file write was not swallowed by the no-op guard: the
    # status change is a real mutation with its own undo entry.
    undone = session.undo(base_revision=accepted.revision, op_id="undo-accept-same")
    assert undone.suggestions is not None
    assert undone.suggestions.suggestions[0].status is SuggestionStatus.PENDING


def test_accept_suggestion_never_blocks_on_stale_content_hash(
    tmp_path: Path,
) -> None:
    path = _workspace(tmp_path / "ws")
    _write_suggestions(
        path,
        "zh",
        [
            _suggestion(
                "s1",
                1,
                SuggestionPatch(target="漂移后的译文"),
                content_hash="sha256:" + "0" * 64,
            )
        ],
    )
    session = review.ReviewSession.open(path, "zh")

    accepted = session.accept_suggestion(
        "s1", base_revision=session.snapshot().revision, op_id="accept-stale"
    )

    translation = ws.read_translation(path / "translation.zh.json")
    assert translation.items[0].target == "漂移后的译文"
    assert accepted.suggestions is not None
    assert accepted.suggestions.suggestions[0].status is SuggestionStatus.ACCEPTED


def test_suggestion_lifecycle_errors_and_reopen(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    _write_suggestions(
        path,
        "zh",
        [
            _suggestion("s1", 1, SuggestionPatch(target="甲")),
            _suggestion("s2", 2, SuggestionPatch(target="乙")),
        ],
    )
    session = review.ReviewSession.open(path, "zh")

    with pytest.raises(OpenBBQError) as raised:
        session.accept_suggestion(
            "missing", base_revision=session.snapshot().revision, op_id="a-missing"
        )
    assert raised.value.code == "unknown_suggestion"

    accepted = session.accept_suggestion(
        "s1", base_revision=session.snapshot().revision, op_id="a-1"
    )
    with pytest.raises(OpenBBQError) as raised:
        session.accept_suggestion("s1", base_revision=accepted.revision, op_id="a-2")
    assert raised.value.code == "suggestion_not_pending"
    with pytest.raises(OpenBBQError) as raised:
        session.reject_suggestion("s1", base_revision=accepted.revision, op_id="r-1")
    assert raised.value.code == "suggestion_not_pending"

    rejected = session.reject_suggestion(
        "s2", base_revision=accepted.revision, op_id="r-2"
    )
    assert rejected.suggestions is not None
    statuses = {s.id: s.status for s in rejected.suggestions.suggestions}
    assert statuses == {"s1": SuggestionStatus.ACCEPTED, "s2": SuggestionStatus.REJECTED}
    with pytest.raises(OpenBBQError) as raised:
        session.reject_suggestion("s2", base_revision=rejected.revision, op_id="r-3")
    assert raised.value.code == "suggestion_not_pending"

    reopened = session.reopen_suggestion(
        "s2", base_revision=rejected.revision, op_id="reopen-1"
    )
    assert reopened.suggestions is not None
    suggestion = reopened.suggestions.suggestions[1]
    assert suggestion.status is SuggestionStatus.PENDING
    assert suggestion.resolved_at is None
    with pytest.raises(OpenBBQError) as raised:
        session.reopen_suggestion(
            "s2", base_revision=reopened.revision, op_id="reopen-2"
        )
    assert raised.value.code == "suggestion_not_rejected"


def test_noop_mutation_skips_write_undo_history_and_revision(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    session = review.ReviewSession.open(path, "zh")
    base = session.snapshot()

    unchanged = session.update_cue(
        1, source="Hello world", base_revision=base.revision, op_id="noop-1"
    )
    assert unchanged.changed == []
    assert unchanged.revision == base.revision

    redundant_status = session.set_status(
        1, ReviewStatus.UNREVIEWED, base_revision=base.revision, op_id="noop-2"
    )
    assert redundant_status.changed == []
    assert redundant_status.revision == base.revision

    with pytest.raises(OpenBBQError) as raised:
        session.undo(base_revision=base.revision, op_id="undo-noop")
    assert raised.value.code == "nothing_to_undo"


def test_batch_replace_dry_run_previews_without_mutating(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    session = review.ReviewSession.open(path, "zh")
    base = session.snapshot()

    matches = cast(
        list[review.BatchMatch],
        session.batch_replace(
            "cue",
            "line",
            fields=["source"],
            dry_run=True,
            base_revision=base.revision,
            op_id="dry-1",
        ),
    )

    assert [(m.cue_id, m.field, m.spans) for m in matches] == [        (2, "source", [(7, 10)]),
        (3, "source", [(6, 9)]),
    ]
    assert matches[0].text == "Second cue"
    assert session.snapshot().revision == base.revision
    with pytest.raises(OpenBBQError) as raised:
        session.undo(base_revision=base.revision, op_id="undo-dry")
    assert raised.value.code == "nothing_to_undo"


def test_batch_replace_executes_as_one_undoable_mutation(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    review.ReviewSession.open(path, "ja")
    session = review.ReviewSession.open(path, "zh")
    session.set_status(
        2,
        ReviewStatus.REVIEWED,
        base_revision=session.snapshot().revision,
        op_id="mark-2",
    )

    result = session.batch_replace(
        "cue",
        "line",
        fields=["source"],
        base_revision=session.snapshot().revision,
        op_id="batch-1",
    )

    assert isinstance(result, review.ReviewSnapshot)
    assert result.changed == [2, 3]
    assert [cue.source for cue in result.cues.cues] == [
        "Hello world",
        "Second line",
        "Third line",
    ]
    for lang in ("zh", "ja"):
        worksheet = ws.read_translation(path / f"translation.{lang}.json")
        assert [item.source for item in worksheet.items] == [
            "Hello world",
            "Second line",
            "Third line",
        ]
        stored_review = ws.read_review(path / f"review.{lang}.json")
        assert [
            item.status for item in stored_review.items
        ] == [ReviewStatus.UNREVIEWED] * 3

    undone = session.undo(base_revision=result.revision, op_id="undo-batch")
    assert [cue.source for cue in undone.cues.cues] == [
        "Hello world",
        "Second cue",
        "Third cue",
    ]
    # One undo entry covered the whole batch, including the review-item reset.
    status_of = {item.id: item.status for item in undone.review.items}
    assert status_of[2] is ReviewStatus.REVIEWED

    # Target edits only touch the current language.
    replaced = session.batch_replace(
        "第二",
        "第2",
        fields=["target"],
        base_revision=undone.revision,
        op_id="batch-target",
    )
    assert isinstance(replaced, review.ReviewSnapshot)
    zh = ws.read_translation(path / "translation.zh.json")
    ja = ws.read_translation(path / "translation.ja.json")
    assert zh.items[1].target == "第2句"
    assert ja.items[1].target == "二つ目"


def test_batch_replace_validates_input(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    session = review.ReviewSession.open(path, "zh")
    base = session.snapshot().revision

    with pytest.raises(OpenBBQError) as raised:
        session.batch_replace(
            "", "x", fields=["source"], base_revision=base, op_id="bad-1"
        )
    assert raised.value.code == "invalid_batch"
    with pytest.raises(OpenBBQError) as raised:
        session.batch_replace(
            "[", "x", fields=["source"], regex=True, base_revision=base, op_id="bad-2"
        )
    assert raised.value.code == "invalid_regex"
    with pytest.raises(OpenBBQError) as raised:
        session.batch_replace(
            "cue", "x", fields=["source"], cue_ids=[99],
            base_revision=base, op_id="bad-3",
        )
    assert raised.value.code == "unknown_cue"
    assert session.snapshot().revision == base

    # Case sensitivity and regex mode both reach the matcher.
    sensitive = cast(
        list[review.BatchMatch],
        session.batch_replace(
            "CUE",
            "x",
            fields=["source"],
            case_sensitive=True,
            dry_run=True,
            base_revision=base,
            op_id="case-1",
        ),
    )
    assert sensitive == []
    regexed = cast(
        list[review.BatchMatch],
        session.batch_replace(
            "c.e",
            "x",
            fields=["source"],
            regex=True,
            dry_run=True,
            base_revision=base,
            op_id="regex-1",
        ),
    )
    assert [m.cue_id for m in regexed] == [2, 3]

    # An execution with zero matches is a no-op, not a write.
    untouched = session.batch_replace(
        "no-such-text",
        "x",
        fields=["source"],
        base_revision=base,
        op_id="zero-match",
    )
    assert isinstance(untouched, review.ReviewSnapshot)
    assert untouched.changed == []
    assert untouched.revision == base


def test_batch_status_validates_every_cue_before_writing(tmp_path: Path) -> None:
    path = _workspace(tmp_path / "ws")
    session = review.ReviewSession.open(path, "zh")

    reviewed = session.batch_status(
        [1, 2],
        ReviewStatus.REVIEWED,
        note="checked",
        base_revision=session.snapshot().revision,
        op_id="bs-1",
    )
    assert reviewed.progress.reviewed == 2
    stored = ws.read_review(path / "review.zh.json")
    assert [item.note for item in stored.items[:2]] == ["checked", "checked"]

    inserted = session.insert_cue(
        at=2.0, base_revision=reviewed.revision, op_id="insert-blank"
    )
    blank_id = inserted.changed[0]
    with pytest.raises(OpenBBQError) as raised:
        session.batch_status(
            [3, blank_id],
            ReviewStatus.REVIEWED,
            base_revision=inserted.revision,
            op_id="bs-blocked",
        )
    assert raised.value.code == "review_blocked"
    assert raised.value.context["ids"] == [blank_id]
    # All-or-nothing: cue 3 was not written.
    stored = ws.read_review(path / "review.zh.json")
    status_of = {item.id: item.status for item in stored.items}
    assert status_of[3] is ReviewStatus.UNREVIEWED
    assert status_of[blank_id] is ReviewStatus.UNREVIEWED
    assert session.snapshot().revision == inserted.revision

    with pytest.raises(OpenBBQError) as raised:
        session.batch_status(
            [3, 99],
            ReviewStatus.FLAGGED,
            base_revision=inserted.revision,
            op_id="bs-unknown",
        )
    assert raised.value.code == "unknown_cue"


def test_add_glossary_term_clears_related_term_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / "home"))
    path = _workspace(tmp_path / "ws")
    glossarylib.save(Glossary(name="series", terms=[Term(source="Hello", target="哈喽")]))
    manifest = ws.read_manifest(path)
    manifest.glossary = "series"
    ws.write_manifest(path, manifest)
    ws.write_text_atomic(
        path / "translation.zh.json",
        _translation(
            "zh", ZH_PARAMS, glossary=[GlossaryRef(source="Hello", target="哈喽")]
        ).model_dump_json(indent=2),
    )
    session = review.ReviewSession.open(path, "zh")
    before = session.snapshot()
    assert any(i.kind == "term" for i in _snapshot_issues(before)[1])

    result = session.add_glossary_term(
        "Hello", "你好世界", base_revision=before.revision, op_id="term-1"
    )

    assert result.glossary == "series"
    assert result.report.updated == ("Hello",)
    stored = glossarylib.load("series")
    term = next(t for t in stored.terms if t.source == "Hello")
    assert term.target == "你好世界"
    # The frozen refs of every loaded worksheet were refreshed from the merged
    # glossary, so the rule issue cleared everywhere.
    assert not any(i.kind == "term" for i in _snapshot_issues(result.snapshot)[1])
    ja = ws.read_translation(path / "translation.ja.json")
    assert [ref.source for ref in ja.glossary] == ["Hello"]


def test_add_glossary_term_scaffolds_and_binds_when_unbound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / "home"))
    path = _workspace(tmp_path / "ws")
    session = review.ReviewSession.open(path, "zh")

    result = session.add_glossary_term(
        "World",
        "世界",
        note="proper noun",
        base_revision=session.snapshot().revision,
        op_id="term-1",
    )

    assert result.glossary == "ws"
    assert result.report.added == ("World",)
    manifest = ws.read_manifest(path)
    assert manifest.glossary == "ws"
    stored = glossarylib.load("ws")
    assert [(t.source, t.target, t.note) for t in stored.terms] == [
        ("World", "世界", "proper noun")
    ]
    zh = ws.read_translation(path / "translation.zh.json")
    assert [ref.source for ref in zh.glossary] == ["World"]


def test_add_glossary_term_merges_unbound_overlay_onto_new_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / "home"))
    path = _workspace(tmp_path / "ws")
    # An agent workflow may have learned task-local terms without ever
    # selecting a global glossary: overlay exists, nothing is bound.
    glossary_overlay.write(
        path,
        GlossaryOverlay(
            base_name=None,
            entries=[
                GlossaryOverlayEntry(
                    term=Term(source="Second", target="第二"),
                    update_fields=["target"],
                )
            ],
        ),
    )
    session = review.ReviewSession.open(path, "zh")

    result = session.add_glossary_term(
        "Hello", "你好", base_revision=session.snapshot().revision, op_id="t-1"
    )

    assert result.glossary == "ws"
    zh = ws.read_translation(path / "translation.zh.json")
    # Refs carry both the new library term and the overlay's task-local entry.
    assert sorted(ref.source for ref in zh.glossary) == ["Hello", "Second"]

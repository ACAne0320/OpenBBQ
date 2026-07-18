from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer

from openbbq.cli.commands.asr import apply as apply_cmd
from openbbq.cli.commands.asr import amend as amend_cmd
from openbbq.cli.commands.asr import batch as batch_cmd
from openbbq.cli.commands.asr import check as check_cmd
from openbbq.cli.commands.segment import segment as segment_cmd
from openbbq.cli.output import Output
from openbbq.core import asr_review
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    ASRInfo,
    AsrDecision,
    Manifest,
    Segment,
    Source,
    Stage,
    StageState,
    StageStatus,
    Transcript,
    Word,
)


def _ctx() -> typer.Context:
    return cast(typer.Context, SimpleNamespace(obj=Output(json_mode=True)))


def _transcript(*segments: Segment) -> Transcript:
    return Transcript(
        language="en",
        duration=max((segment.end for segment in segments), default=0.0),
        asr=ASRInfo(
            backend="test",
            model="test",
            created_at=datetime.now(timezone.utc),
        ),
        segments=list(segments),
    )


def _segment(
    segment_id: int,
    text: str,
    words: list[tuple[str, float]],
) -> Segment:
    cursor = float(segment_id)
    timed: list[Word] = []
    for word, probability in words:
        timed.append(Word(word=word, start=cursor, end=cursor + 0.25, prob=probability))
        cursor += 0.25
    return Segment(
        id=segment_id,
        start=float(segment_id),
        end=cursor,
        text=text,
        words=timed,
    )


def _timed_segment(
    segment_id: int,
    start: float,
    end: float,
    text: str,
    words: Sequence[str],
) -> Segment:
    step = (end - start) / max(len(words), 1)
    return Segment(
        id=segment_id,
        start=start,
        end=end,
        text=text,
        words=[
            Word(
                word=word,
                start=start + index * step,
                end=start + (index + 1) * step,
                prob=0.99,
            )
            for index, word in enumerate(words)
        ],
    )


def _workspace(tmp_path: Path, transcript: Transcript) -> Path:
    path = tmp_path / "ws"
    path.mkdir()
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    (path / "transcript.json").write_text(
        transcript.model_dump_json(indent=2), encoding="utf-8"
    )
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_audio", ref=str(source)),
        stages={
            Stage.TRANSCRIBE: StageState(
                status=StageStatus.DONE,
                artifact="transcript.json",
            )
        },
    )
    ws.write_manifest(path, manifest)
    return path


def _payload(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    output = capsys.readouterr().out
    assert output.endswith("\n")
    return cast(dict[str, object], json.loads(output))


def test_extracts_every_low_probability_occurrence_with_stable_context() -> None:
    transcript = _transcript(
        _segment(
            7,
            "Thank you to Sean Hongxiu.",
            [
                ("Thank", 0.99),
                ("you", 0.99),
                ("to", 0.99),
                ("Sean", 0.38),
                ("Hongxiu.", 0.86),
            ],
        )
    )

    issues = asr_review.extract_issues(transcript)

    assert [issue.id for issue in issues] == ["s7:w3"]
    issue = issues[0]
    assert issue.word == "Sean"
    assert issue.segment_text == "Thank you to Sean Hongxiu."
    assert issue.start == 7.75 and issue.end == 8.0
    assert [(word.index, word.word, word.prob) for word in issue.context] == [
        (1, "you", 0.99),
        (2, "to", 0.99),
        (3, "Sean", 0.38),
        (4, "Hongxiu.", 0.86),
    ]


def test_transcript_without_word_probabilities_has_no_gate() -> None:
    transcript = _transcript(Segment(id=0, start=0, end=1, text="hello", words=None))

    report = asr_review.check(transcript, None)

    assert report.issues == []
    assert report.ready is True
    assert report.stale is False


def test_repeated_long_segment_run_is_one_severe_anomaly_and_can_be_dropped() -> None:
    text = "So you know I am going to use many things with the code."
    words = text.split()
    transcript = _transcript(
        *[
            _timed_segment(index, float(index), float(index + 1), text, words)
            for index in range(10, 16)
        ]
    )

    anomalies = asr_review.extract_anomalies(transcript)

    assert len(anomalies) == 1
    issue = anomalies[0]
    assert issue.code == "repeated_segment_run"
    assert issue.severity == "severe"
    assert issue.segment_ids == (10, 11, 12, 13, 14, 15)
    assert issue.id == "a:repeat:10-15"

    review = asr_review.merge_decisions(
        transcript,
        None,
        {
            issue.id: AsrDecision(
                action="drop",
                reason="The six identical dense segments are a Whisper hallucination during a demo.",
            )
        },
    )

    assert asr_review.check(transcript, review).ready is True
    assert asr_review.apply_segment_decisions(transcript, review).segments == []


def test_keep_first_removes_only_duplicate_segments_from_a_repeat_run() -> None:
    repeated = "Thank you all for coming to the conference today."
    repeated_words = repeated.split()
    following = _timed_segment(
        5,
        8.0,
        10.0,
        "Now let us move to the next topic.",
        "Now let us move to the next topic.".split(),
    )
    transcript = _transcript(
        *[
            _timed_segment(
                index, float(index * 2), float(index * 2 + 2), repeated, repeated_words
            )
            for index in range(1, 5)
        ],
        following,
    )
    issue = asr_review.extract_anomalies(transcript)[0]
    review = asr_review.merge_decisions(
        transcript,
        None,
        {
            issue.id: AsrDecision(
                action="keep_first",
                reason="The first sentence is audible; the following copies are decoder repetition.",
            )
        },
    )

    corrected = asr_review.apply_segment_decisions(transcript, review)

    assert [segment.id for segment in corrected.segments] == [1, 5]


def test_implausible_word_rate_is_a_severe_segment_anomaly() -> None:
    text = "one two three four five six seven eight nine ten"
    transcript = _transcript(_timed_segment(3, 4.0, 5.0, text, text.split()))

    anomalies = asr_review.extract_anomalies(transcript)

    assert len(anomalies) == 1
    assert anomalies[0].code == "implausible_word_rate"
    assert anomalies[0].words_per_second == 10.0
    assert anomalies[0].segment_ids == (3,)


def test_metadata_entity_conflict_catches_high_confidence_name_misspelling() -> None:
    transcript = _transcript(
        _timed_segment(
            4,
            10,
            15,
            "Today I am talking with Jeffrey Litt about software.",
            [
                "Today",
                "I",
                "am",
                "talking",
                "with",
                "Jeffrey",
                "Litt",
                "about",
                "software",
            ],
        )
    )

    anomalies = asr_review.extract_anomalies(
        transcript,
        reference_texts=["A conversation with Geoffrey Litt"],
    )

    assert len(anomalies) == 1
    assert anomalies[0].code == "metadata_entity_conflict"
    assert anomalies[0].find == "Jeffrey Litt"
    assert anomalies[0].replacement == "Geoffrey Litt"
    assert anomalies[0].reference_text == "A conversation with Geoffrey Litt"


def test_metadata_entity_replacement_corrects_text_without_collapsing_segment() -> None:
    transcript = _transcript(
        _timed_segment(
            4,
            10,
            15,
            "Today I am talking with Jeffrey Litt about software.",
            [
                "Today",
                "I",
                "am",
                "talking",
                "with",
                "Jeffrey",
                "Litt",
                "about",
                "software",
            ],
        )
    )
    references = ["A conversation with Geoffrey Litt"]
    issue = asr_review.extract_anomalies(transcript, reference_texts=references)[0]
    review = asr_review.merge_decisions(
        transcript,
        None,
        {
            issue.id: AsrDecision(
                action="replace",
                reason="The video title confirms the guest's spelling.",
                find="Jeffrey Litt",
                replacement="Geoffrey Litt",
            )
        },
        reference_texts=references,
    )

    reviewed = asr_review.apply_segment_decisions(
        transcript,
        review,
        reference_texts=references,
    )

    assert len(reviewed.segments) == 1
    assert reviewed.segments[0].start == 10
    assert asr_review.corrector(review)(reviewed.segments[0].text) == (
        "Today I am talking with Geoffrey Litt about software."
    )


def test_reference_caption_parser_returns_only_overlapping_caption_text() -> None:
    captions = asr_review.parse_reference_captions(
        """WEBVTT

00:00:00.000 --> 00:00:02.000
Opening line

00:00:02.000 --> 00:00:05.000
Geoffrey Litt joins us
"""
    )

    assert asr_review.reference_caption_text(captions, start=2.5, end=4.0) == (
        "Geoffrey Litt joins us"
    )


def test_reference_caption_evidence_unescapes_and_compacts_rolling_text() -> None:
    captions = asr_review.parse_reference_captions(
        """WEBVTT

00:00:01.000 --> 00:00:03.000
&gt;&gt; Thanks for coming to

00:00:02.000 --> 00:00:05.000
&gt;&gt; Thanks for coming to the design engineering track at AI.
"""
    )

    assert asr_review.reference_caption_text(captions, start=2.0, end=3.0) == (
        ">> Thanks for coming to the design engineering track at AI."
    )


def test_accept_decision_resolves_current_issue() -> None:
    transcript = _transcript(_segment(0, "Heva!", [("Heva!", 0.36)]))
    review = asr_review.merge_decisions(
        transcript,
        None,
        {
            "s0:w0": AsrDecision(
                action="accept",
                reason="Confirmed creator sign-off from the visible end card.",
            )
        },
    )

    report = asr_review.check(transcript, review)

    assert report.ready is True
    assert report.resolved_ids == ["s0:w0"]
    assert report.unresolved_ids == []


def test_replace_decision_corrects_full_phrase_boundary_safely() -> None:
    transcript = _transcript(
        _segment(
            206,
            "Thank you to Sean Hongxiu.",
            [
                ("Thank", 0.99),
                ("you", 0.99),
                ("to", 0.99),
                ("Sean", 0.38),
                ("Hongxiu.", 0.86),
            ],
        )
    )
    review = asr_review.merge_decisions(
        transcript,
        None,
        {
            "s206:w3": AsrDecision(
                action="replace",
                find="Sean Hongxiu",
                replacement="Xiaohongshu",
                reason="The video is thanking the platform, not a person.",
            )
        },
    )

    fix = asr_review.corrector(review)

    assert fix("Thank you to Sean Hongxiu.") == "Thank you to Xiaohongshu."
    assert fix("Sean HongxiuExtra") == "Sean HongxiuExtra"


def test_contextual_amendment_corrects_high_confidence_error_without_issue_id() -> None:
    transcript = _transcript(
        _segment(
            12,
            "That is my hot tick about agents.",
            [
                ("That", 0.99),
                ("is", 0.99),
                ("my", 0.99),
                ("hot", 0.98),
                ("tick", 0.97),
                ("about", 0.99),
                ("agents.", 0.99),
            ],
        )
    )
    assert asr_review.check(transcript, None).ready is True

    parsed = asr_review.parse_amendments(
        json.dumps(
            {
                "amendments": [
                    {
                        "segment_id": 12,
                        "find": "hot tick",
                        "replacement": "hot take",
                        "reason": "The surrounding sentence uses the idiom hot take.",
                    }
                ]
            }
        )
    )
    review, ids = asr_review.merge_amendments(transcript, None, parsed)

    assert ids[0].startswith("m:s12:")
    assert asr_review.check(transcript, review).ready is True
    assert asr_review.corrector(review)(transcript.segments[0].text) == (
        "That is my hot take about agents."
    )
    assert asr_review.resolved_transcript(transcript, review).segments[0].text == (
        "That is my hot take about agents."
    )


def test_contextual_amendment_requires_exact_phrase_in_declared_segment() -> None:
    transcript = _transcript(
        _segment(2, "Agents can edit the interface.", [("Agents", 0.99)])
    )
    amendment = asr_review.parse_amendments(
        json.dumps(
            {
                "amendments": [
                    {
                        "segment_id": 2,
                        "find": "Asians",
                        "replacement": "Agents",
                        "reason": "Context refers to software agents.",
                    }
                ]
            }
        )
    )

    with pytest.raises(OpenBBQError) as raised:
        asr_review.merge_amendments(transcript, None, amendment)

    assert raised.value.code == "asr_amendment_find_missing"


def test_contextual_amendment_can_be_revised_without_leaving_conflicting_rules() -> (
    None
):
    transcript = _transcript(_segment(3, "She mentioned Annie.", [("Annie.", 0.99)]))
    first = asr_review.parse_amendments(
        json.dumps(
            {
                "amendments": [
                    {
                        "segment_id": 3,
                        "find": "Annie",
                        "replacement": "Andy",
                        "reason": "Initial contextual reading.",
                    }
                ]
            }
        )
    )
    review, first_ids = asr_review.merge_amendments(transcript, None, first)
    revised = asr_review.parse_amendments(
        json.dumps(
            {
                "amendments": [
                    {
                        "segment_id": 3,
                        "find": "Annie",
                        "replacement": "Annie Murphy",
                        "reason": "Later context gives the full confirmed name.",
                    }
                ]
            }
        )
    )

    review, revised_ids = asr_review.merge_amendments(transcript, review, revised)

    assert revised_ids == first_ids
    assert len(review.decisions) == 1
    assert asr_review.corrector(review)(transcript.segments[0].text) == (
        "She mentioned Annie Murphy."
    )


def test_replace_must_cover_uncertain_word_and_exist_in_segment() -> None:
    transcript = _transcript(
        _segment(
            0, "Mew inspired me.", [("Mew", 0.4), ("inspired", 0.99), ("me.", 0.99)]
        )
    )

    with pytest.raises(OpenBBQError) as raised:
        asr_review.merge_decisions(
            transcript,
            None,
            {
                "s0:w0": AsrDecision(
                    action="replace",
                    find="inspired me",
                    replacement="helped me",
                    reason="This does not cover the uncertain word.",
                )
            },
        )

    assert raised.value.code == "asr_decision_invalid"


def test_conflicting_replacements_for_same_phrase_are_rejected() -> None:
    transcript = _transcript(
        _segment(0, "Hi, Komono!", [("Hi,", 0.99), ("Komono!", 0.3)]),
        _segment(1, "Hi, Komono!", [("Hi,", 0.99), ("Komono!", 0.2)]),
    )

    with pytest.raises(OpenBBQError) as raised:
        asr_review.merge_decisions(
            transcript,
            None,
            {
                "s0:w1": AsrDecision(
                    action="replace",
                    find="Komono",
                    replacement="Kemono",
                    reason="First interpretation.",
                ),
                "s1:w1": AsrDecision(
                    action="replace",
                    find="Komono",
                    replacement="Komano",
                    reason="Conflicting interpretation.",
                ),
            },
        )

    assert raised.value.code == "asr_decision_conflict"


def test_asr_apply_rejects_unbounded_bulk_decisions() -> None:
    transcript = _transcript(
        *[
            _segment(index, f"word{index}", [(f"word{index}", 0.2)])
            for index in range(21)
        ]
    )
    decisions = {
        f"s{index}:w0": AsrDecision(
            action="accept",
            reason=f"Cue {index} was checked against its audio context.",
        )
        for index in range(21)
    }

    with pytest.raises(OpenBBQError) as raised:
        asr_review.merge_decisions(transcript, None, decisions)

    assert raised.value.code == "asr_decisions_too_large"


def test_review_is_stale_when_transcript_changes() -> None:
    original = _transcript(_segment(0, "Mew.", [("Mew.", 0.4)]))
    review = asr_review.merge_decisions(
        original,
        None,
        {"s0:w0": AsrDecision(action="accept", reason="Confirmed name.")},
    )
    changed = _transcript(_segment(0, "Miyu.", [("Miyu.", 0.4)]))

    report = asr_review.check(changed, review)

    assert report.ready is False
    assert report.stale is True
    assert report.resolved_ids == []
    assert report.unresolved_ids == ["s0:w0"]


def test_check_command_is_read_only_and_reports_next_action(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _workspace(tmp_path, _transcript(_segment(0, "Heva!", [("Heva!", 0.36)])))
    manifest_before = (path / "manifest.json").read_bytes()

    check_cmd(_ctx(), workspace=str(path), max_prob=0.5)

    payload = _payload(capsys)
    assert payload["ready"] is False
    assert payload["unresolved"] == 1
    assert payload["next"] == f"openbbq asr batch --workspace {path} --limit 20"
    assert (path / "manifest.json").read_bytes() == manifest_before
    assert not ws.asr_review_path(path).exists()


def test_batch_is_bounded_and_apply_unblocks_segment_with_correction(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transcript = _transcript(
        _segment(
            0,
            "Thank you to Sean Hongxiu.",
            [
                ("Thank", 0.99),
                ("you", 0.99),
                ("to", 0.99),
                ("Sean", 0.38),
                ("Hongxiu.", 0.86),
            ],
        ),
        _segment(1, "Heva!", [("Heva!", 0.36)]),
    )
    path = _workspace(tmp_path, transcript)

    with pytest.raises(OpenBBQError) as blocked:
        segment_cmd(_ctx(), workspace=str(path))
    assert blocked.value.code == "asr_review_incomplete"

    batch_cmd(_ctx(), workspace=str(path), offset=0, limit=1, only_unresolved=True)
    payload = _payload(capsys)
    assert payload["selected_ids"] == ["s0:w3"]
    assert payload["remaining"] == 1

    decisions = tmp_path / "asr-decisions.json"
    decisions.write_text(
        json.dumps(
            {
                "s0:w3": {
                    "action": "replace",
                    "find": "Sean Hongxiu",
                    "replacement": "Xiaohongshu",
                    "reason": "Platform name confirmed from the video context.",
                },
                "s1:w0": {
                    "action": "accept",
                    "reason": "Creator sign-off confirmed from the end card.",
                },
            }
        ),
        encoding="utf-8",
    )
    apply_cmd(
        _ctx(),
        decisions=str(decisions),
        workspace=str(path),
        max_prob=0.5,
    )
    payload = _payload(capsys)
    assert payload["ready"] is True
    assert payload["applied"] == 2

    segment_cmd(_ctx(), workspace=str(path))
    _payload(capsys)
    cues = ws.read_cues(path / "cues.json")
    assert cues.cues[0].source == "Thank you to Xiaohongshu. Heva!"

    apply_cmd(
        _ctx(),
        decisions=str(decisions),
        workspace=str(path),
        max_prob=0.5,
    )
    _payload(capsys)
    assert ws.read_manifest(path).stages[Stage.SEGMENT].status is StageStatus.PENDING


def test_amend_command_persists_agent_found_high_confidence_correction(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transcript = _transcript(
        _segment(
            0,
            "Here is my hot tick.",
            [
                ("Here", 0.99),
                ("is", 0.99),
                ("my", 0.99),
                ("hot", 0.99),
                ("tick.", 0.99),
            ],
        )
    )
    path = _workspace(tmp_path, transcript)
    amendments = tmp_path / "amendments.json"
    amendments.write_text(
        json.dumps(
            {
                "amendments": [
                    {
                        "segment_id": 0,
                        "find": "hot tick",
                        "replacement": "hot take",
                        "reason": "The idiom is clear from the surrounding discussion.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    amend_cmd(_ctx(), amendments=str(amendments), workspace=str(path))

    payload = _payload(capsys)
    assert payload["applied"] == 1
    assert payload["ready"] is True
    segment_cmd(_ctx(), workspace=str(path))
    _payload(capsys)
    assert ws.read_cues(path / "cues.json").cues[0].source == "Here is my hot take."

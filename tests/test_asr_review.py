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


def test_exact_reference_text_repairs_only_large_local_timing_drift() -> None:
    surfaces = "Now this scene hits so hard in context.".split()
    transcript = _transcript(
        _timed_segment(
            7,
            462.5,
            470.7,
            "Now this scene hits so hard in context.",
            surfaces,
        )
    )
    reference = [
        Word(
            word=word,
            start=468.1 + index * 0.35,
            end=468.1 + (index + 1) * 0.35,
            prob=1.0,
        )
        for index, word in enumerate(surfaces)
    ]

    aligned = asr_review.align_exact_reference_timing(transcript, reference)
    segment = aligned.segments[0]

    assert segment.text == transcript.segments[0].text
    assert segment.start == reference[0].start
    assert segment.end == reference[-1].end
    assert segment.words is not None
    assert [word.word for word in segment.words] == surfaces
    assert [word.prob for word in segment.words] == [0.99] * len(surfaces)


def test_exact_reference_timing_repair_cannot_cross_adjacent_segment_boundary() -> None:
    first = _timed_segment(
        1, 10.0, 12.0, "But put it this way.", ["But", "put", "it", "this", "way."]
    )
    following = _timed_segment(
        2, 12.0, 14.0, "The next thought.", ["The", "next", "thought."]
    )
    reference = [
        Word(word=word, start=11.5 + index * 0.3, end=11.8 + index * 0.3, prob=1.0)
        for index, word in enumerate("But put it this way.".split())
    ]

    aligned = asr_review.align_exact_reference_timing(
        _transcript(first, following), reference
    )

    assert aligned.segments[0] == first
    assert aligned.segments[1] == following


def test_reference_word_parser_accepts_youtube_spacer_after_timing() -> None:
    words = asr_review.parse_reference_words(
        """WEBVTT

00:07:47.759 --> 00:07:51.270

Now,<00:07:48.160><c> this</c><00:07:48.319><c> scene.</c>
"""
    )

    assert [(word.word, word.start) for word in words] == [
        ("Now,", 467.759),
        ("this", 468.16),
        ("scene.", 468.319),
    ]


def test_reference_caption_hold_does_not_create_a_false_timing_repair() -> None:
    transcript = _transcript(
        _timed_segment(1, 10.0, 11.0, "This happens.", ["This", "happens."])
    )
    reference = [
        Word(word="This", start=10.1, end=10.5, prob=1.0),
        Word(word="happens.", start=10.5, end=18.0, prob=1.0),
    ]

    aligned = asr_review.align_exact_reference_timing(transcript, reference)

    assert aligned == transcript


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


def test_reference_disagreement_evidence_keeps_only_local_substitutions() -> None:
    source = (
        "improving your combo, improving your accuracy, improving your miscount, "
        "adding mods to your scores"
    )
    reference_text = source.replace("miscount", "miss count")
    reference = [
        Word(
            word=word,
            start=index * 0.25,
            end=(index + 1) * 0.25,
            prob=1.0,
        )
        for index, word in enumerate(reference_text.split())
    ]

    evidence = asr_review.reference_disagreement_evidence(
        source,
        start=0.0,
        end=len(reference) * 0.25,
        reference_words=reference,
    )

    assert evidence is not None
    assert [(item.source, item.reference) for item in evidence.differences] == [
        ("miscount", "miss count")
    ]
    assert "miss count" in evidence.reference_text


def test_reference_disagreement_evidence_ignores_boundary_drift() -> None:
    reference = [
        Word(word=word, start=index, end=index + 1, prob=1.0)
        for index, word in enumerate(
            "music this source is otherwise exactly aligned".split()
        )
    ]

    evidence = asr_review.reference_disagreement_evidence(
        "this source is otherwise exactly aligned",
        start=0.0,
        end=7.0,
        reference_words=reference,
    )

    assert evidence is None


def test_reference_word_parser_preserves_inline_youtube_timestamps() -> None:
    words = asr_review.parse_reference_words(
        """WEBVTT

00:00:00.000 --> 00:00:04.000
Hello<00:00:01.000><c> world</c><00:00:02.000><c> again.</c>
"""
    )

    assert [(word.word, word.start, word.end) for word in words] == [
        ("Hello", 0.0, 1.0),
        ("world", 1.0, 2.0),
        ("again.", 2.0, 4.0),
    ]


def test_reference_word_parser_discards_rolling_prefix_already_emitted() -> None:
    words = asr_review.parse_reference_words(
        """WEBVTT

00:00:00.000 --> 00:00:02.000
Hello<00:00:01.000><c> world</c>

00:00:02.000 --> 00:00:04.000
Hello world<00:00:03.000><c> again</c><00:00:03.500><c> now.</c>
"""
    )

    assert [word.word for word in words] == ["Hello", "world", "again", "now."]


def test_reference_word_parser_keeps_novel_plain_line_in_word_timed_vtt() -> None:
    words = asr_review.parse_reference_words(
        """WEBVTT

00:00:00.000 --> 00:00:02.000
This<00:00:01.000><c> is</c><00:00:01.500><c> a</c><00:00:01.800><c> natural</c>

00:00:02.000 --> 00:00:03.000
This is a natural
outcome.
"""
    )

    assert [word.word for word in words] == ["This", "is", "a", "natural", "outcome."]


def test_collapsed_timeline_uses_semantic_reference_beyond_local_drift_window() -> None:
    source = "That most people dream of if you seriously enjoy this game"
    segment = _timed_segment(7, 10.0, 12.0, source, source.split())
    assert segment.words is not None
    for word in segment.words:
        word.start = segment.end
        word.end = segment.end
    reference = [
        Word(word=word, start=22.0 + index * 0.3, end=22.3 + index * 0.3, prob=1.0)
        for index, word in enumerate(source.split())
    ]

    anomalies = asr_review.extract_anomalies(
        _transcript(segment), reference_words=reference
    )

    assert len(anomalies) == 1
    assert anomalies[0].replacement == source
    assert anomalies[0].reference_words[0].start == 22.0


def test_structural_reference_replacement_trims_future_neighbor_overlap() -> None:
    source = "Alpha bridge then next stable phrase"
    collapsed = _timed_segment(0, 0.0, 2.0, source, source.split())
    assert collapsed.words is not None
    for word in collapsed.words:
        word.start = collapsed.end
        word.end = collapsed.end
    transcript = _transcript(
        collapsed,
        _timed_segment(
            1, 2.0, 4.0, "temporary damaged bridge", ["temporary", "damaged", "bridge"]
        ),
        _timed_segment(
            2,
            4.0,
            6.0,
            "next stable phrase continues",
            ["next", "stable", "phrase", "continues"],
        ),
    )
    reference = [
        Word(word=word, start=10.0 + index, end=11.0 + index, prob=1.0)
        for index, word in enumerate(source.split())
    ]

    anomaly = asr_review.extract_anomalies(transcript, reference_words=reference)[0]

    assert anomaly.replacement == "Alpha bridge then"
    assert anomaly.reference_words[-1].word == "then"


def test_collapsed_timestamps_and_following_drift_require_timed_replacement() -> None:
    reference = """WEBVTT

00:00:00.000 --> 00:00:04.000
Hello<00:00:01.000><c> world</c><00:00:02.000><c> again</c><00:00:03.000><c> now.</c>

00:00:04.000 --> 00:00:08.000
This<00:00:05.000><c> timing</c><00:00:06.000><c> is</c><00:00:07.000><c> correct.</c>

00:00:08.000 --> 00:00:12.000
We<00:00:09.000><c> have</c><00:00:10.000><c> recovered</c><00:00:11.000><c> now.</c>
"""
    reference_words = asr_review.parse_reference_words(reference)
    transcript = _transcript(
        Segment(
            id=0,
            start=0,
            end=4,
            text="Hello bad timestamps pile up",
            words=[
                Word(word="Hello", start=0, end=1, prob=0.99),
                Word(word="bad", start=4, end=4, prob=0.99),
                Word(word="timestamps", start=4, end=4, prob=0.99),
                Word(word="pile", start=4, end=4, prob=0.99),
                Word(word="up", start=4, end=4, prob=0.99),
            ],
        ),
        _timed_segment(
            1,
            4,
            8,
            "Unrelated decoder text here",
            ["Unrelated", "decoder", "text", "here"],
        ),
        _timed_segment(
            2, 8, 12, "We have recovered now.", ["We", "have", "recovered", "now."]
        ),
    )

    anomalies = asr_review.extract_anomalies(
        transcript,
        reference_words=reference_words,
    )

    assert [issue.code for issue in anomalies] == [
        "collapsed_word_timestamps",
        "reference_timeline_mismatch",
    ]
    review = asr_review.merge_decisions(
        transcript,
        None,
        {
            issue.id: AsrDecision(
                action="replace",
                replacement=issue.replacement,
                reason="The timed reference caption restores this corrupted window.",
            )
            for issue in anomalies
        },
        reference_words=reference_words,
    )
    resolved = asr_review.resolved_transcript(
        transcript,
        review,
        reference_words=reference_words,
    )

    assert [segment.text for segment in resolved.segments] == [
        "Hello world again now.",
        "This timing is correct.",
        "We have recovered now.",
    ]
    assert all(
        word.end > word.start
        for segment in resolved.segments[:2]
        for word in segment.words or []
    )


def test_adjacent_timed_reference_replacements_deduplicate_shared_boundary_word() -> (
    None
):
    reference = """WEBVTT

00:00:00.000 --> 00:00:04.500
Start<00:00:01.000><c> by</c><00:00:03.500><c> controlling</c>

00:00:03.500 --> 00:00:08.000
controlling<00:00:04.500><c> the</c><00:00:05.500><c> worker</c><00:00:06.500><c> now.</c>
"""
    reference_words = asr_review.parse_reference_words(reference)
    transcript = _transcript(
        Segment(
            id=0,
            start=0,
            end=4,
            text="bad decoder output here",
            words=[
                Word(word=word, start=4, end=4, prob=0.99)
                for word in ("bad", "decoder", "output", "here")
            ],
        ),
        Segment(
            id=1,
            start=4,
            end=8,
            text="more broken output here",
            words=[
                Word(word=word, start=8, end=8, prob=0.99)
                for word in ("more", "broken", "output", "here")
            ],
        ),
    )
    anomalies = asr_review.extract_anomalies(
        transcript,
        reference_words=reference_words,
    )
    review = asr_review.merge_decisions(
        transcript,
        None,
        {
            issue.id: AsrDecision(
                action="replace",
                replacement=issue.replacement,
                reason="Use the timed reference to repair the collapsed window.",
            )
            for issue in anomalies
        },
        reference_words=reference_words,
    )

    resolved = asr_review.resolved_transcript(
        transcript,
        review,
        reference_words=reference_words,
    )

    assert [segment.text for segment in resolved.segments] == [
        "Start by controlling",
        "the worker now.",
    ]
    assert resolved.segments[1].start == 4.5


def test_collapsed_timestamp_anomaly_cannot_be_accepted() -> None:
    transcript = _transcript(
        Segment(
            id=0,
            start=0,
            end=2,
            text="bad timing here now",
            words=[
                Word(word=word, start=2, end=2, prob=0.99)
                for word in ("bad", "timing", "here", "now")
            ],
        )
    )
    issue = asr_review.extract_anomalies(transcript)[0]

    with pytest.raises(OpenBBQError) as error:
        asr_review.merge_decisions(
            transcript,
            None,
            {
                issue.id: AsrDecision(
                    action="accept",
                    reason="Text alone looks plausible.",
                )
            },
        )

    assert error.value.code == "asr_decision_invalid"


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

    fix = asr_review.corrector(review, segment_id=206)

    assert fix("Thank you to Sean Hongxiu.") == "Thank you to Xiaohongshu."
    assert fix("Sean HongxiuExtra") == "Sean HongxiuExtra"


def test_replace_decision_is_scoped_to_its_issue_segment() -> None:
    transcript = _transcript(
        _segment(9, "It works on Mac.", [("It", 0.99), ("works", 0.99), ("on", 0.3)]),
        _segment(10, "Turn it on again.", [("Turn", 0.99), ("it", 0.99), ("on", 0.99)]),
    )
    review = asr_review.merge_decisions(
        transcript,
        None,
        {
            "s9:w2": AsrDecision(
                action="replace",
                find="on",
                replacement="and",
                reason="The detector issue is limited to this occurrence.",
            )
        },
    )

    resolved = asr_review.resolved_transcript(transcript, review)

    assert [segment.text for segment in resolved.segments] == [
        "It works and Mac.",
        "Turn it on again.",
    ]


def test_replace_decision_is_scoped_to_the_declared_word_occurrence() -> None:
    transcript = _transcript(
        _segment(
            9,
            "on and on",
            [("on", 0.3), ("and", 0.99), ("on", 0.99)],
        )
    )
    review = asr_review.merge_decisions(
        transcript,
        None,
        {
            "s9:w0": AsrDecision(
                action="replace",
                find="on",
                replacement="and",
                reason="Only the first low-confidence occurrence is wrong.",
            )
        },
    )

    resolved = asr_review.resolved_transcript(transcript, review)

    assert resolved.segments[0].text == "and and on"


def test_contextual_amendment_rejects_an_ambiguous_repeated_phrase() -> None:
    transcript = _transcript(
        _segment(
            9,
            "hot tick and hot tick",
            [
                ("hot", 0.99),
                ("tick", 0.99),
                ("and", 0.99),
                ("hot", 0.99),
                ("tick", 0.99),
            ],
        )
    )
    amendment = asr_review.parse_amendments(
        json.dumps(
            {
                "amendments": [
                    {
                        "segment_id": 9,
                        "find": "hot tick",
                        "replacement": "hot take",
                        "reason": "Only one contextual occurrence is intended.",
                    }
                ]
            }
        )
    )

    with pytest.raises(OpenBBQError) as error:
        asr_review.merge_amendments(transcript, None, amendment)

    assert error.value.code == "asr_amendment_ambiguous_occurrence"


def test_case_only_asr_canonicalization_is_valid() -> None:
    decision = AsrDecision(
        action="replace",
        find="codex",
        replacement="Codex",
        reason="Use the product's canonical capitalization.",
    )
    amendment = asr_review.parse_amendments(
        json.dumps(
            {
                "amendments": [
                    {
                        "segment_id": 1,
                        "find": "Claude code",
                        "replacement": "Claude Code",
                        "reason": "Use the product's canonical capitalization.",
                    }
                ]
            }
        )
    )[0]

    assert decision.replacement == "Codex"
    assert amendment.replacement == "Claude Code"


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
    assert asr_review.corrector(review, segment_id=12)(transcript.segments[0].text) == (
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
    assert asr_review.corrector(review, segment_id=3)(transcript.segments[0].text) == (
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
        _segment(
            0,
            "Komono met Komono.",
            [("Komono", 0.3), ("met", 0.99), ("Komono.", 0.2)],
        ),
    )

    with pytest.raises(OpenBBQError) as raised:
        asr_review.merge_decisions(
            transcript,
            None,
            {
                "s0:w0": AsrDecision(
                    action="replace",
                    find="Komono",
                    replacement="Kemono",
                    reason="First interpretation.",
                ),
                "s0:w2": AsrDecision(
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


def test_low_confidence_review_is_optional_and_explicit_correction_still_applies(
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

    segment_cmd(_ctx(), workspace=str(path))
    initial = _payload(capsys)
    assert initial["asr_advisory_ids"] == ["s0:w3", "s1:w0"]
    cues = ws.read_cues(path / "cues.json")
    assert cues.cues[0].source == "Thank you to Sean Hongxiu. Heva!"

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
    assert ws.read_manifest(path).stages[Stage.SEGMENT].status is StageStatus.PENDING

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

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import typer

from openbbq.cli.commands.segment import segment
from openbbq.cli.output import Output
from openbbq.core import segment as seg
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    ASRInfo,
    Manifest,
    Segment,
    Source,
    Stage,
    StageState,
    StageStatus,
    Transcript,
    Word,
)

EN = seg.LANGUAGE_PROFILES["en"]


def W(word: str, start: float, end: float) -> Word:
    return Word(word=word, start=start, end=end, prob=0.9)


def _tight(**over: float | int) -> seg.LanguageProfile:
    """A profile narrow enough to force splits in unit tests."""
    base = seg.apply_overrides(
        EN, max_chars_per_line=10, max_lines=1, max_dur=100.0, pause_threshold=10.0
    )
    return seg.apply_overrides(base, **over)


# --- profiles + counting ------------------------------------------------------


def test_count_chars_latin_counts_spaces() -> None:
    assert seg.count_chars("Hello, world", EN) == 12


def test_count_chars_cjk_drops_whitespace() -> None:
    zh = seg.LANGUAGE_PROFILES["zh"]
    assert seg.count_chars("你 好 世 界", zh) == 4


def test_resolve_profile_hit_and_base_subtag() -> None:
    assert seg.resolve_profile("en") == (EN, False)
    assert seg.resolve_profile("zh-Hans") == (seg.LANGUAGE_PROFILES["zh"], False)


def test_resolve_profile_unknown_falls_back_to_generic() -> None:
    profile, generic = seg.resolve_profile("fr")
    assert generic is True
    assert profile is seg.DEFAULT_PROFILE


def test_apply_overrides_only_touches_given_fields() -> None:
    out = seg.apply_overrides(EN, max_cps=9, min_dur=None)
    assert out.max_cps == 9
    assert out.max_chars_per_line == EN.max_chars_per_line


# --- wrapping -----------------------------------------------------------------


def test_wrap_feasible_rejects_word_longer_than_line() -> None:
    # total chars under per_line*lines, but one word can't fit a line
    assert (
        seg.wrap_feasible([W("x" * (EN.max_chars_per_line + 1), 0, 1)], EN)
        is False
    )


def test_wrap_feasible_packs_short_words() -> None:
    assert seg.wrap_feasible([W("Hi", 0, 1), W("there", 1, 2)], EN) is True


# --- group_sentences ----------------------------------------------------------


def test_group_sentences_splits_on_terminal_punctuation() -> None:
    words = [W("Hello", 0, 0.5), W("world.", 0.5, 1.0), W("Bye", 1.0, 1.5)]
    groups = seg.group_sentences(words)
    assert [[w.word for w in g] for g in groups] == [["Hello", "world."], ["Bye"]]


# --- split_long ---------------------------------------------------------------


def test_split_long_prefers_secondary_punctuation() -> None:
    words = [W("alpha,", 0, 1), W("beta", 1, 2), W("gamma", 2, 3)]
    pieces = seg.split_long(words, _tight())
    assert [[w.word for w in p] for p in pieces] == [["alpha,"], ["beta", "gamma"]]


def test_split_long_ignores_leading_comma_in_long_sentence() -> None:
    words = [
        W("Well,", 0, 0.2),
        W("this", 0.2, 0.5),
        W("sentence", 0.5, 0.8),
        W("should", 0.8, 1.1),
        W("stay", 1.1, 1.4),
        W("connected", 1.4, 1.7),
        W("before", 1.7, 2.0),
        W("splitting.", 2.0, 2.3),
    ]
    pieces = seg.split_long(words, _tight(max_chars_per_line=24))
    assert [w.word for w in pieces[0]] != ["Well,"]


def test_split_long_uses_largest_pause_when_no_punctuation() -> None:
    # gap 0.5s > pause_threshold 0.3 splits between the two words
    words = [W("hello", 0, 1.0), W("world", 1.5, 2.5)]
    pieces = seg.split_long(words, _tight(pause_threshold=0.3))
    assert [[w.word for w in p] for p in pieces] == [["hello"], ["world"]]


def test_split_long_greedy_picks_split_near_midpoint() -> None:
    # cap 10: feasible prefixes are "aaaa"(4) and "aaaa bbbb"(9); 9 is nearer the
    # 14-char midpoint, so the fuller balanced split wins.
    words = [W("aaaa", 0, 1), W("bbbb", 1, 2), W("cccc", 2, 3)]
    pieces = seg.split_long(words, _tight())
    assert [[w.word for w in p] for p in pieces] == [["aaaa", "bbbb"], ["cccc"]]


def test_split_long_greedy_balances_to_avoid_widow() -> None:
    # cap 10: greedy-longest would take "aaaa bbbb"(9) and strand the widow "c";
    # the balanced split keeps "c" with "bbbb" instead.
    words = [W("aaaa", 0, 1), W("bbbb", 1, 2), W("c", 2, 3)]
    pieces = seg.split_long(words, _tight())
    assert [[w.word for w in p] for p in pieces] == [["aaaa"], ["bbbb", "c"]]


def test_split_long_emits_unsplittable_word_as_is() -> None:
    pieces = seg.split_long([W("x" * 20, 0, 1)], _tight())
    assert len(pieces) == 1 and len(pieces[0]) == 1


def test_split_long_keeps_short_text_despite_bogus_long_duration() -> None:
    # ASR swallowed trailing silence: 2 short words span 30s. Single-line text
    # must NOT be duration-split into "Thank"/"you." widows.
    words = [W("Thank", 0.0, 13.5), W("you.", 13.5, 30.0)]
    assert len(seg.split_long(words, EN)) == 1


# --- merge_short --------------------------------------------------------------


def test_merge_short_folds_tiny_cue_into_neighbor() -> None:
    pieces = [[W("Hi.", 0, 0.2)], [W("There", 0.3, 1.0), W("go.", 1.0, 2.0)]]
    merged = seg.merge_short(pieces, EN)
    assert len(merged) == 1


def test_merge_short_refuses_when_merge_overflows() -> None:
    profile = _tight(max_chars_per_line=5)
    pieces = [[W("Hi.", 0, 0.2)], [W("There", 0.3, 1.0)]]
    merged = seg.merge_short(pieces, profile)
    assert len(merged) == 2  # "Hi. There" exceeds the line cap, so no merge


def test_merge_short_keeps_sentence_prefix_with_following_clause() -> None:
    pieces = [
        [W("Previous", 0, 0.8), W("sentence.", 0.8, 1.6)],
        [W("No,", 1.62, 1.8)],
        [W("that", 1.88, 2.3), W("works.", 2.3, 3.0)],
    ]
    merged = seg.merge_short(pieces, EN)
    assert [[w.word for w in p] for p in merged] == [
        ["Previous", "sentence."],
        ["No,", "that", "works."],
    ]


# --- finalize + build_cues ----------------------------------------------------


def _transcript(*segments: Segment, language: str = "en") -> Transcript:
    return Transcript(
        language=language,
        duration=10.0,
        asr=ASRInfo(
            backend="test", model="t", created_at=datetime.now(timezone.utc)
        ),
        segments=list(segments),
    )


def test_finalize_assigns_1_based_ids_and_source() -> None:
    outcome = seg.build_cues(
        _transcript(Segment(id=0, start=0, end=2, text="x", words=[
            W("Hello", 0, 0.6), W("there.", 0.6, 1.6)
        ])),
        EN,
    )
    assert [c.id for c in outcome.cues] == [1]
    assert outcome.cues[0].source == "Hello there."


def test_build_cues_keeps_screen_fit_sentence_whole() -> None:
    words = [
        W("Frieren", 0.19, 0.43),
        W("isn't", 0.43, 0.74),
        W("the", 0.74, 0.93),
        W("most", 0.93, 1.18),
        W("interesting", 1.18, 1.88),
        W("member", 1.88, 2.26),
        W("of", 2.26, 2.36),
        W("her", 2.39, 2.56),
        W("party.", 2.58, 3.07),
    ]
    outcome = seg.build_cues(
        _transcript(Segment(id=0, start=0, end=3.1, text="x", words=words)),
        EN,
    )
    assert [c.source for c in outcome.cues] == [
        "Frieren isn't the most interesting member of her party."
    ]


def test_finalize_enforces_min_gap_by_trimming_previous_end() -> None:
    words = [W("Hi", 0, 0.4), W("there.", 0.4, 1.0),
             W("Bye", 1.0, 1.4), W("now.", 1.4, 2.0)]
    outcome = seg.build_cues(
        _transcript(Segment(id=0, start=0, end=2, text="x", words=words)), EN
    )
    assert len(outcome.cues) == 2
    # gap was 0; previous end trimmed to next.start - min_gap (0.083)
    assert outcome.cues[0].end == 0.917
    assert outcome.cues[1].start == 1.0


def test_finalize_clamps_preexisting_asr_word_overlap() -> None:
    words = [
        W("Alpha", 1.0, 1.1),
        W("bravo.", 1.1, 2.0),
        W("Charlie", 1.05, 1.25),
        W("delta.", 1.25, 1.8),
    ]
    outcome = seg.build_cues(
        _transcript(Segment(id=0, start=1.0, end=2.0, text="x", words=words)),
        _tight(max_chars_per_line=16),
    )

    assert [cue.source for cue in outcome.cues] == ["Alpha bravo.", "Charlie delta."]
    assert all(cue.start <= cue.end for cue in outcome.cues)
    assert all(
        left.end <= right.start
        for left, right in zip(outcome.cues, outcome.cues[1:])
    )


def test_finalize_counts_over_cps() -> None:
    # 29 chars in a sub-second cue, extended to min_dur 1.0 -> 29 cps > 21 (en)
    words = [
        W("hello", 0, 0.1), W("there", 0.1, 0.2),
        W("wonderful", 0.2, 0.3), W("people.", 0.3, 0.5),
    ]
    outcome = seg.build_cues(
        _transcript(Segment(id=0, start=0, end=0.5, text="x", words=words)), EN
    )
    assert outcome.over_cps == 1


def test_build_cues_counts_over_cap_for_unsplittable_word() -> None:
    outcome = seg.build_cues(
        _transcript(Segment(id=0, start=0, end=1, text="x", words=[
            W("supercalifragilisticexpialidocious" * 3, 0, 1)
        ])),
        EN,
    )
    assert outcome.over_cap == 1


def test_build_cues_clamps_bogus_long_word_instead_of_splitting() -> None:
    words = [W("Thank", 500.0, 513.5), W("you.", 513.5, 530.0)]
    outcome = seg.build_cues(
        _transcript(Segment(id=0, start=500, end=530, text="Thank you.", words=words)),
        EN,
    )
    assert len(outcome.cues) == 1
    assert outcome.cues[0].source == "Thank you."
    assert outcome.cues[0].end - outcome.cues[0].start <= EN.max_dur + 1e-6


def test_build_cues_raises_on_missing_word_timestamps() -> None:
    try:
        seg.build_cues(
            _transcript(Segment(id=0, start=0, end=1, text="x", words=None)), EN
        )
    except OpenBBQError as err:
        assert err.code == "missing_word_timestamps"
    else:
        raise AssertionError("expected OpenBBQError")


# --- command shell ------------------------------------------------------------


def _ctx() -> typer.Context:
    return cast(typer.Context, SimpleNamespace(obj=Output(json_mode=True)))


def _workspace(tmp_path: Path) -> tuple[Path, Manifest]:
    path = tmp_path / "ws"
    path.mkdir()
    source = tmp_path / "source.wav"
    source.write_bytes(b"")
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_audio", ref=str(source)),
        stages={},
    )
    ws.write_manifest(path, manifest)
    return path, manifest


def _with_transcript(path: Path, manifest: Manifest, transcript: Transcript) -> None:
    (path / "transcript.json").write_text(transcript.model_dump_json())
    manifest.stages[Stage.TRANSCRIBE] = StageState(
        status=StageStatus.DONE,
        artifact="transcript.json",
        updated_at=datetime.now(timezone.utc),
    )
    ws.write_manifest(path, manifest)


def test_segment_missing_input_errors(tmp_path) -> None:
    path, _ = _workspace(tmp_path)
    try:
        segment(_ctx(), workspace=str(path))
    except OpenBBQError as err:
        assert err.code == "missing_input"
    else:
        raise AssertionError("expected OpenBBQError")


def test_segment_invalid_transcript_errors(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    (path / "transcript.json").write_text("{not valid json")
    manifest.stages[Stage.TRANSCRIBE] = StageState(
        status=StageStatus.DONE,
        artifact="transcript.json",
        updated_at=datetime.now(timezone.utc),
    )
    ws.write_manifest(path, manifest)
    try:
        segment(_ctx(), workspace=str(path))
    except OpenBBQError as err:
        assert err.code == "invalid_transcript"
    else:
        raise AssertionError("expected OpenBBQError")


def test_segment_writes_cues_and_records_stage(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    transcript = _transcript(
        Segment(id=0, start=0, end=1.6, text="Hello there.", words=[
            W("Hello", 0, 0.6), W("there.", 0.6, 1.6)
        ])
    )
    _with_transcript(path, manifest, transcript)

    segment(_ctx(), workspace=str(path))

    cues_path = path / "cues.json"
    assert cues_path.exists()
    from openbbq.schemas import Cues

    doc = Cues.model_validate_json(cues_path.read_text())
    assert doc.source_lang == "en"
    assert [c.id for c in doc.cues] == [1]
    assert ws.read_manifest(path).stages[Stage.SEGMENT].status is StageStatus.DONE

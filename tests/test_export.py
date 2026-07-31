from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import typer

from openbbq.cli.commands.export import export
from openbbq.cli.output import Output
from openbbq.core import export as exp
from openbbq.core import review as reviewlib
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    Budget,
    Cue,
    Cues,
    Manifest,
    Progress,
    SegmentParams,
    ReviewStatus,
    Source,
    Stage,
    StageState,
    StageStatus,
    Translation,
    TranslationItem,
)

EN_PARAMS = SegmentParams(
    max_cps=17,
    max_chars_per_line=42,
    max_lines=1,
    min_dur=0.83,
    max_dur=7.0,
    min_gap=0.083,
)
ZH_PARAMS = SegmentParams(
    max_cps=9,
    max_chars_per_line=18,
    max_lines=1,
    min_dur=0.83,
    max_dur=7.0,
    min_gap=0.083,
)


def _cues(
    *cues: Cue, source_lang: str = "en", params: SegmentParams = EN_PARAMS
) -> Cues:
    return Cues(source_lang=source_lang, params=params, cues=list(cues))


def _item(id: int, source: str, target: str | None = None) -> TranslationItem:
    return TranslationItem(
        id=id, source=source, budget=Budget(max_chars=20, seconds=1.0), target=target
    )


def _translation(
    *items: TranslationItem,
    source_lang: str = "en",
    target_lang: str = "zh",
    params: SegmentParams = ZH_PARAMS,
) -> Translation:
    return Translation(
        source_lang=source_lang,
        target_lang=target_lang,
        params=params,
        items=list(items),
    )


# --- timestamps ---------------------------------------------------------------


def test_timestamp_formats_hms_millis() -> None:
    assert exp._timestamp(0.0) == "00:00:00,000"
    assert exp._timestamp(1.6) == "00:00:01,600"
    assert exp._timestamp(3661.083) == "01:01:01,083"


def test_timestamp_clamps_negative_to_zero() -> None:
    assert exp._timestamp(-1.0) == "00:00:00,000"


def test_ass_timestamp_formats_centiseconds() -> None:
    assert exp._ass_timestamp(0.06) == "0:00:00.06"
    assert exp._ass_timestamp(3661.087) == "1:01:01.09"


# --- mode resolution ----------------------------------------------------------


def test_default_mode_by_to_flag() -> None:
    assert exp.default_mode(None) is exp.ExportMode.SOURCE
    assert exp.default_mode("zh") is exp.ExportMode.TARGET


def test_output_lang_picks_side() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="hi"))
    tr = _translation(_item(1, "hi", "你好"))
    assert exp.output_lang(cues, None, exp.ExportMode.SOURCE) == "en"
    assert exp.output_lang(cues, tr, exp.ExportMode.TARGET) == "zh"


# --- render_srt ---------------------------------------------------------------


def test_render_srt_source_blocks() -> None:
    cues = _cues(
        Cue(id=1, start=0.0, end=1.6, source="Hello there."),
        Cue(id=2, start=1.6, end=3.0, source="Bye now."),
    )
    out = exp.render_srt(cues, exp.ExportMode.SOURCE)
    assert out == (
        "1\n00:00:00,000 --> 00:00:01,600\nHello there.\n"
        "\n"
        "2\n00:00:01,600 --> 00:00:03,000\nBye now.\n"
    )


def test_render_srt_keeps_source_on_one_line() -> None:
    params = SegmentParams(
        max_cps=17,
        max_chars_per_line=10,
        max_lines=1,
        min_dur=0.83,
        max_dur=7.0,
        min_gap=0.083,
    )
    cues = _cues(Cue(id=1, start=0, end=4, source="one two three four"), params=params)
    out = exp.render_srt(cues, exp.ExportMode.SOURCE)
    assert "one two three four" in out


def test_render_srt_target_keeps_cjk_on_one_line() -> None:
    cues = _cues(Cue(id=1, start=0, end=4, source="hello"))
    params = SegmentParams(
        max_cps=9,
        max_chars_per_line=3,
        max_lines=1,
        min_dur=0.83,
        max_dur=7.0,
        min_gap=0.083,
    )
    tr = _translation(_item(1, "hello", "你好世界吗"), params=params)
    out = exp.render_srt(cues, exp.ExportMode.TARGET, translation=tr)
    assert "你好世界吗" in out


def test_render_srt_target_collapses_explicit_newlines() -> None:
    cues = _cues(Cue(id=1, start=0, end=4, source="hello"))
    tr = _translation(_item(1, "hello", "我是 Pey\n今天聊胆小鬼"))
    out = exp.render_srt(cues, exp.ExportMode.TARGET, translation=tr)
    assert "我是 Pey 今天聊胆小鬼" in out


def test_render_srt_target_preserves_latin_spaces_in_cjk() -> None:
    cues = _cues(Cue(id=1, start=0, end=4, source="hello"))
    tr = _translation(_item(1, "hello", "Gabe Newell 说的是游戏"))
    out = exp.render_srt(cues, exp.ExportMode.TARGET, translation=tr)
    assert "Gabe Newell 说的是游戏" in out


def test_render_srt_target_normalizes_zh_subtitle_punctuation() -> None:
    cues = _cues(Cue(id=1, start=0, end=4, source="inside this box"))
    tr = _translation(
        _item(1, "inside this box", "这个箱子里，有一台科视 CP2230 放映机。")
    )
    out = exp.render_srt(cues, exp.ExportMode.TARGET, translation=tr)
    assert "这个箱子里 有一台科视 CP2230 放映机\n" in out


def test_render_srt_target_turns_inner_zh_period_into_space() -> None:
    cues = _cues(Cue(id=1, start=0, end=4, source="sure"))
    tr = _translation(_item(1, "sure", "当然可以。你觉得呢？"))
    out = exp.render_srt(cues, exp.ExportMode.TARGET, translation=tr)
    assert "当然可以 你觉得呢？\n" in out


def test_render_srt_source_keeps_english_punctuation() -> None:
    cues = _cues(Cue(id=1, start=0, end=4, source="Well, this is fine."))
    out = exp.render_srt(cues, exp.ExportMode.SOURCE)
    assert "Well, this is fine.\n" in out


def test_render_srt_source_strips_terminal_english_comma() -> None:
    cues = _cues(Cue(id=1, start=0, end=4, source="Hello, everyone,"))
    out = exp.render_srt(cues, exp.ExportMode.SOURCE)
    assert "Hello, everyone\n" in out


def test_render_srt_target_missing_raises() -> None:
    cues = _cues(
        Cue(id=1, start=0, end=1, source="hi"),
        Cue(id=2, start=1, end=2, source="bye"),
    )
    tr = _translation(_item(1, "hi", "你好"), _item(2, "bye", None))
    try:
        exp.render_srt(cues, exp.ExportMode.TARGET, translation=tr)
    except OpenBBQError as err:
        assert err.code == "incomplete_translation"
        assert err.context["missing"] == [2]
    else:
        raise AssertionError("expected OpenBBQError")


def test_render_srt_blank_target_counts_as_missing() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="hi"))
    tr = _translation(_item(1, "hi", "   "))  # whitespace-only = untranslated
    try:
        exp.render_srt(cues, exp.ExportMode.TARGET, translation=tr)
    except OpenBBQError as err:
        assert err.code == "incomplete_translation" and err.context["missing"] == [1]
    else:
        raise AssertionError("expected OpenBBQError")


def test_render_srt_allow_missing_falls_back_to_source() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="bye"))
    tr = _translation(_item(1, "bye", None))
    out = exp.render_srt(
        cues, exp.ExportMode.TARGET, translation=tr, allow_missing=True
    )
    assert "bye" in out


def test_render_srt_bilingual_puts_target_above_source() -> None:
    cues = _cues(Cue(id=1, start=0, end=1.6, source="Hello."))
    tr = _translation(_item(1, "Hello.", "你好。"))
    out = exp.render_srt(cues, exp.ExportMode.BILINGUAL, translation=tr)
    assert "你好\nHello." in out


# --- render_ass ---------------------------------------------------------------


def test_render_ass_has_styles_and_dialogues() -> None:
    cues = _cues(Cue(id=1, start=0.06, end=4.947, source="Hello, everyone,"))
    tr = _translation(_item(1, "Hello, everyone,", "大家好。"))
    out = exp.render_ass(cues, exp.ExportMode.BILINGUAL, translation=tr)
    assert "[Script Info]" in out
    assert (
        "Style: ZH_TOP,Hiragino Sans GB,68,&H00FFFFFF,&H000000FF,&H00000000,"
        "&H80000000,0,0,0,0,100,100,0,0,1,3,0,2,80,80,62,1"
    ) in out
    assert (
        "Style: EN,Arial,44,&H00FFFFFF,&H000000FF,&H00000000,"
        "&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,80,80,12,1"
    ) in out
    assert "Dialogue: 1,0:00:00.06,0:00:04.95,ZH_TOP,,0,0,0,,大家好\n" in out
    assert "Dialogue: 0,0:00:00.06,0:00:04.95,EN,,0,0,0,,Hello, everyone\n" in out


def test_render_ass_mobile_preset_uses_vertical_canvas_and_safe_margins() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="Hello."))
    tr = _translation(_item(1, "Hello.", "你好。"))
    out = exp.render_ass(
        cues,
        exp.ExportMode.BILINGUAL,
        translation=tr,
        preset=exp.AssPreset.MOBILE,
    )

    assert "PlayResX: 1080\nPlayResY: 1920" in out
    assert (
        "Style: ZH_TOP,Hiragino Sans GB,52,&H00FFFFFF,&H000000FF,&H00000000,"
        "&H80000000,0,0,0,0,100,100,0,0,1,4,0,2,72,72,320,1"
    ) in out
    assert (
        "Style: EN,Arial,31,&H00FFFFFF,&H000000FF,&H00000000,"
        "&H80000000,0,0,0,0,100,100,0,0,1,3,0,2,72,72,218,1"
    ) in out


def test_render_ass_fansub_preset_uses_emphasized_target_style() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="Hello."))
    tr = _translation(_item(1, "Hello.", "你好。"))
    out = exp.render_ass(
        cues,
        exp.ExportMode.BILINGUAL,
        translation=tr,
        preset=exp.AssPreset.FANSUB,
    )

    assert "PlayResX: 1920\nPlayResY: 1080" in out
    assert (
        "Style: ZH_TOP,Hiragino Sans GB,68,&H00FFF7F2,&H000000FF,&H00FF901E,"
        "&H80000000,0,0,0,0,100,100,0,0,1,3,0,2,80,80,62,1"
    ) in out


def test_render_ass_fansub_compact_reduces_stack_and_moves_it_above_lower_thirds() -> (
    None
):
    cues = _cues(Cue(id=1, start=0, end=1, source="Hello."))
    tr = _translation(_item(1, "Hello.", "你好。"))
    out = exp.render_ass(
        cues,
        exp.ExportMode.BILINGUAL,
        translation=tr,
        preset=exp.AssPreset.FANSUB_COMPACT,
    )

    assert "Style: ZH_TOP,Hiragino Sans GB,56" in out
    assert ",2,120,120,150,1" in out
    assert "Style: EN,Arial,36" in out
    assert ",2,120,120,92,1" in out


def test_render_ass_escapes_override_braces() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="literal {tag}"))
    out = exp.render_ass(cues, exp.ExportMode.SOURCE)
    assert r"literal \\{tag\\}" not in out
    assert r"literal \{tag\}" in out


def test_render_ass_reflows_two_target_lines_without_losing_text() -> None:
    cues = _cues(Cue(id=1, start=0, end=4, source="The idea made me love the craft."))
    params = SegmentParams(
        max_cps=11,
        max_chars_per_line=8,
        max_lines=2,
        min_dur=1,
        max_dur=7,
        min_gap=0.083,
    )
    translation = _translation(
        _item(1, "The idea made me love the craft.", "这个想法让我爱上这门技艺"),
        params=params,
    )

    out = exp.render_ass(
        cues,
        exp.ExportMode.BILINGUAL,
        translation=translation,
    )

    assert "这个想法让我爱上\\N这门技艺" in out
    assert "Dialogue: 0,0:00:00.00,0:00:04.00,EN" in out
    assert exp.is_bilingual_ass(out, cues, translation) is True


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


def _with_cues(path: Path, manifest: Manifest, doc: Cues) -> None:
    (path / "cues.json").write_text(doc.model_dump_json())
    manifest.stages[Stage.SEGMENT] = StageState(
        status=StageStatus.DONE,
        artifact="cues.json",
        updated_at=datetime.now(timezone.utc),
    )
    ws.write_manifest(path, manifest)


def _with_worksheet(path: Path, doc: Translation, lang: str = "zh") -> None:
    ws.worksheet_path(path, lang).write_text(doc.model_dump_json())


def _with_complete_review(path: Path, lang: str = "zh") -> None:
    session = reviewlib.ReviewSession.open(path, lang)
    for item in session.snapshot().review.items:
        snapshot = session.snapshot()
        session.set_status(
            item.id,
            ReviewStatus.REVIEWED,
            base_revision=snapshot.revision,
            op_id=f"review-{item.id}",
        )


def test_export_missing_input_errors(tmp_path) -> None:
    path, _ = _workspace(tmp_path)
    try:
        export(_ctx(), workspace=str(path))
    except OpenBBQError as err:
        assert err.code == "missing_input"
    else:
        raise AssertionError("expected OpenBBQError")


def test_export_invalid_cues_errors(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    (path / "cues.json").write_text("{not valid json")
    manifest.stages[Stage.SEGMENT] = StageState(
        status=StageStatus.DONE,
        artifact="cues.json",
        updated_at=datetime.now(timezone.utc),
    )
    ws.write_manifest(path, manifest)
    try:
        export(_ctx(), workspace=str(path))
    except OpenBBQError as err:
        assert err.code == "invalid_cues"
    else:
        raise AssertionError("expected OpenBBQError")


def test_export_unsupported_format_errors(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_cues(path, manifest, _cues(Cue(id=1, start=0, end=1, source="hi")))
    try:
        export(_ctx(), workspace=str(path), fmt="vtt")
    except OpenBBQError as err:
        assert err.code == "unsupported_format"
    else:
        raise AssertionError("expected OpenBBQError")


def test_export_writes_ass_with_default_extension(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_cues(path, manifest, _cues(Cue(id=1, start=0, end=1.6, source="Hello.")))

    export(_ctx(), workspace=str(path), fmt="ass")

    ass = path / "out" / "en.ass"
    assert ass.exists()
    assert "[V4+ Styles]" in ass.read_text()
    assert ws.read_manifest(path).stages[Stage.EXPORT].artifact == "out/en.ass"


def test_export_writes_ass_with_preset(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_cues(path, manifest, _cues(Cue(id=1, start=0, end=1.6, source="Hello.")))

    export(_ctx(), workspace=str(path), fmt="ass", ass_preset=exp.AssPreset.MOBILE)

    ass = path / "out" / "en.ass"
    text = ass.read_text()
    assert "PlayResX: 1080\nPlayResY: 1920" in text
    assert ws.read_manifest(path).stages[Stage.EXPORT].artifact == "out/en.ass"


def test_export_rejects_ass_preset_for_srt(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_cues(path, manifest, _cues(Cue(id=1, start=0, end=1, source="hi")))

    try:
        export(_ctx(), workspace=str(path), ass_preset=exp.AssPreset.MOBILE)
    except OpenBBQError as err:
        assert err.code == "ass_preset_requires_ass"
        assert err.fix == "use --format ass, or remove --ass-preset"
    else:
        raise AssertionError("expected OpenBBQError")


def test_export_writes_source_srt_and_records_stage(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_cues(
        path,
        manifest,
        _cues(
            Cue(id=1, start=0.0, end=1.6, source="Hello there."),
            Cue(id=2, start=1.6, end=3.0, source="Bye now."),
        ),
    )

    export(_ctx(), workspace=str(path))  # no --to → source, locks out/en.srt

    srt = path / "out" / "en.srt"
    assert srt.exists()
    text = srt.read_text()
    assert text.startswith("1\n00:00:00,000 --> 00:00:01,600\nHello there.\n")
    assert "Bye now." in text
    final = ws.read_manifest(path).stages[Stage.EXPORT]
    assert final.status is StageStatus.DONE and final.artifact == "out/en.srt"


def test_export_to_joins_worksheet(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    cues = _cues(Cue(id=1, start=0, end=1.6, source="Hello."))
    translation = _translation(_item(1, "Hello.", "你好。"))
    _with_cues(path, manifest, cues)
    _with_worksheet(path, translation)
    _with_complete_review(path)

    export(_ctx(), workspace=str(path), to="zh")

    srt = path / "out" / "zh.srt"
    assert srt.exists() and "你好\n" in srt.read_text()
    final_manifest = ws.read_manifest(path)
    assert final_manifest.stages[Stage.EXPORT].artifact == "out/zh.srt"
    assert final_manifest.stages[Stage.TRANSLATE].status is StageStatus.DONE
    assert final_manifest.stages[Stage.TRANSLATE].progress == Progress(done=1, total=1)
    ws.require_fresh_artifact(path, srt, Stage.EXPORT)


def test_export_requires_human_or_agent_evidence(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_cues(path, manifest, _cues(Cue(id=1, start=0, end=2, source="Hello there")))
    _with_worksheet(path, _translation(_item(1, "Hello there", "你好")))

    try:
        export(_ctx(), workspace=str(path), to="zh")
    except OpenBBQError as err:
        assert err.code == "translation_evidence_missing"
    else:
        raise AssertionError("expected OpenBBQError")


def test_export_provenance_detects_changed_translation(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    cues = _cues(Cue(id=1, start=0, end=2, source="Hello there"))
    translation = _translation(_item(1, "Hello there", "你好"))
    _with_cues(path, manifest, cues)
    _with_worksheet(path, translation)
    _with_complete_review(path)
    export(_ctx(), workspace=str(path), to="zh", fmt="ass")
    artifact = path / "out" / "zh.ass"

    doc = ws.read_translation(path / "translation.zh.json")
    doc.items[0].target = "您好"
    ws.write_text_atomic(path / "translation.zh.json", doc.model_dump_json())

    try:
        ws.require_fresh_artifact(path, artifact, Stage.EXPORT)
    except OpenBBQError as err:
        assert err.code == "stale_artifact"
        assert err.context["input"] == "translation.zh.json"
    else:
        raise AssertionError("expected OpenBBQError")


def test_export_target_rejects_id_mismatch(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_cues(
        path,
        manifest,
        _cues(
            Cue(id=1, start=0, end=1, source="hi"),
            Cue(id=2, start=1, end=2, source="bye"),
        ),
    )
    _with_worksheet(path, _translation(_item(1, "hi", "你好")))

    try:
        export(_ctx(), workspace=str(path), to="zh")
    except OpenBBQError as err:
        assert err.code == "id_mismatch"
    else:
        raise AssertionError("expected OpenBBQError")


def test_export_bilingual_rejects_id_mismatch(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_cues(
        path,
        manifest,
        _cues(
            Cue(id=1, start=0, end=1, source="hi"),
            Cue(id=2, start=1, end=2, source="bye"),
        ),
    )
    _with_worksheet(path, _translation(_item(1, "hi", "你好")))

    try:
        export(_ctx(), workspace=str(path), to="zh", mode=exp.ExportMode.BILINGUAL)
    except OpenBBQError as err:
        assert err.code == "id_mismatch"
    else:
        raise AssertionError("expected OpenBBQError")


def test_export_rejects_source_drift(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_cues(path, manifest, _cues(Cue(id=1, start=0, end=1, source="hi")))
    _with_worksheet(path, _translation(_item(1, "HELLO", "你好")))

    try:
        export(_ctx(), workspace=str(path), to="zh")
    except OpenBBQError as err:
        assert err.code == "source_drift"
    else:
        raise AssertionError("expected OpenBBQError")


def test_export_source_mode_does_not_require_worksheet(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_cues(path, manifest, _cues(Cue(id=1, start=0, end=1, source="hi")))

    export(_ctx(), workspace=str(path), to="zh", mode=exp.ExportMode.SOURCE)

    srt = path / "out" / "en.srt"
    assert srt.exists() and "hi\n" in srt.read_text()


def test_export_to_missing_worksheet_errors(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_cues(path, manifest, _cues(Cue(id=1, start=0, end=1, source="hi")))
    try:
        export(_ctx(), workspace=str(path), to="zh")
    except OpenBBQError as err:
        assert err.code == "translation_not_found"
    else:
        raise AssertionError("expected OpenBBQError")


def test_export_target_mode_without_to_errors(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_cues(path, manifest, _cues(Cue(id=1, start=0, end=1, source="hi")))
    try:
        export(_ctx(), workspace=str(path), mode=exp.ExportMode.TARGET)
    except OpenBBQError as err:
        assert err.code == "translation_required"
    else:
        raise AssertionError("expected OpenBBQError")


def test_export_output_override(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    _with_cues(path, manifest, _cues(Cue(id=1, start=0, end=1, source="hi")))

    export(_ctx(), workspace=str(path), output="subs/custom.srt")

    assert (path / "subs" / "custom.srt").exists()
    assert ws.read_manifest(path).stages[Stage.EXPORT].artifact == "subs/custom.srt"


def test_export_blocks_incomplete_review_when_review_exists(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    cues = _cues(Cue(id=1, start=0, end=1.6, source="Hello."))
    translation = _translation(_item(1, "Hello.", "你好。"))
    _with_cues(path, manifest, cues)
    _with_worksheet(path, translation)
    reviewlib.ReviewSession.open(path, "zh")

    try:
        export(_ctx(), workspace=str(path), to="zh")
    except OpenBBQError as err:
        assert err.code == "review_incomplete"
        assert err.context["unreviewed"] == [1]
    else:
        raise AssertionError("expected OpenBBQError")


def test_export_allow_unreviewed_explicitly_bypasses_review_gate(tmp_path) -> None:
    path, manifest = _workspace(tmp_path)
    cues = _cues(Cue(id=1, start=0, end=1.6, source="Hello."))
    translation = _translation(_item(1, "Hello.", "你好。"))
    _with_cues(path, manifest, cues)
    _with_worksheet(path, translation)
    reviewlib.ReviewSession.open(path, "zh")

    export(_ctx(), workspace=str(path), to="zh", allow_unreviewed=True)

    assert (path / "out" / "zh.srt").exists()


def test_export_finalizes_translation_without_invalidating_current_review(
    tmp_path: Path,
) -> None:
    path, manifest = _workspace(tmp_path)
    cues = _cues(Cue(id=1, start=0, end=1.6, source="Hello."))
    translation = _translation(_item(1, "Hello.", "你好。"))
    _with_cues(path, manifest, cues)
    _with_worksheet(path, translation)
    session = reviewlib.ReviewSession.open(path, "zh")
    snapshot = session.snapshot()
    session.set_status(
        1,
        ReviewStatus.REVIEWED,
        base_revision=snapshot.revision,
        op_id="review-1",
    )
    manifest = ws.read_manifest(path)
    manifest.stages[Stage.EXPORT] = StageState(
        status=StageStatus.DONE,
        artifact="out/old.ass",
    )
    manifest.stages[Stage.BURN] = StageState(
        status=StageStatus.DONE,
        artifact="out/old.mp4",
    )
    ws.write_manifest(path, manifest)

    export(_ctx(), workspace=str(path), to="zh")

    final = ws.read_manifest(path)
    assert final.stages[Stage.TRANSLATE].status is StageStatus.DONE
    assert final.stages[Stage.REVIEW].status is StageStatus.DONE
    assert final.stages[Stage.EXPORT].status is StageStatus.DONE
    assert final.stages[Stage.BURN].status is StageStatus.PENDING

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer
from pydantic import ValidationError

from openbbq.cli.commands.translate import apply as apply_cmd
from openbbq.cli.commands.translate import batch as batch_cmd
from openbbq.cli.commands.translate import check as check_cmd
from openbbq.cli.commands.translate import init as init_cmd
from openbbq.cli.output import Output
from openbbq.core import segment as seg
from openbbq.core import translate as tr
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    Budget,
    Cue,
    Cues,
    Glossary,
    GlossaryRef,
    Manifest,
    Progress,
    SegmentParams,
    Source,
    Stage,
    StageState,
    StageStatus,
    Term,
    Translation,
    TranslationItem,
)

EN_PARAMS = SegmentParams(
    max_cps=21,
    max_chars_per_line=50,
    max_lines=1,
    min_dur=1.0,
    max_dur=7.0,
    min_gap=0.083,
)


def _ctx() -> typer.Context:
    return cast(typer.Context, SimpleNamespace(obj=Output(json_mode=True)))


def _payload(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    stdout = capsys.readouterr().out
    assert stdout.endswith("\n")
    lines = stdout.removesuffix("\n").splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert isinstance(data, dict)
    return data


def _cues(*cues: Cue, source_lang: str = "en") -> Cues:
    return Cues(source_lang=source_lang, params=EN_PARAMS, cues=list(cues))


def _item(id: int, source: str, target: str | None = None) -> TranslationItem:
    return TranslationItem(
        id=id, source=source, budget=Budget(max_chars=20, seconds=1.0), target=target
    )


# --- schema -------------------------------------------------------------------


def test_translation_roundtrip_with_params() -> None:
    doc = Translation(
        source_lang="en",
        target_lang="zh",
        params=EN_PARAMS,
        items=[_item(1, "hi", "你好")],
    )
    dumped = doc.model_dump_json()
    assert '"schema":"openbbq/translation@1"' in dumped.replace(" ", "")
    assert Translation.model_validate_json(dumped) == doc


def test_cues_forbids_dropped_target_field() -> None:
    with pytest.raises(ValidationError):  # target/budget no longer on Cue
        Cue.model_validate(
            {"id": 1, "start": 0, "end": 1, "source": "hi", "target": "x"}
        )


# --- build_worksheet ----------------------------------------------------------


def test_build_worksheet_budget_and_snapshot() -> None:
    cues = _cues(Cue(id=1, start=0.0, end=2.0, source="hello world"))
    doc, generic = tr.build_worksheet(cues, None, "zh")
    assert generic is False
    zh = seg.LANGUAGE_PROFILES["zh"]
    assert doc.params.max_cps == zh.max_cps  # snapshot of the target profile
    expected = math.floor(min(zh.max_cps * 2.0, zh.max_chars_per_line * zh.max_lines))
    assert doc.items[0].budget.max_chars == expected
    assert doc.items[0].budget.seconds == 2.0
    assert doc.items[0].target is None and doc.items[0].source == "hello world"


def test_build_worksheet_target_line_override_increases_visual_capacity() -> None:
    cues = _cues(Cue(id=1, start=0.0, end=4.0, source="hello world"))

    default, _ = tr.build_worksheet(cues, None, "zh")
    two_lines, _ = tr.build_worksheet(cues, None, "zh", max_lines=2)

    assert default.items[0].budget.max_chars == 32
    assert two_lines.params.max_lines == 2
    assert two_lines.items[0].budget.max_chars == 44


def test_wrap_target_lines_preserves_mixed_cjk_and_latin_text() -> None:
    doc, _ = tr.build_worksheet(
        _cues(Cue(id=1, start=0, end=4, source="thanks")),
        None,
        "zh",
        max_chars_per_line=9,
        max_lines=2,
    )

    lines = tr.wrap_target_lines(doc, "感谢Sean Hongxiu支持")

    assert lines == ["感谢Sean", "Hongxiu支持"]
    assert "".join(lines).replace(" ", "") == "感谢SeanHongxiu支持"


def test_build_worksheet_unknown_lang_is_generic() -> None:
    _, generic = tr.build_worksheet(
        _cues(Cue(id=1, start=0, end=1, source="x")), None, "xx"
    )
    assert generic is True


def test_build_worksheet_glossary_refs_only_guided_terms() -> None:
    g = Glossary(
        name="g",
        terms=[
            Term(source="Frieren", target="芙莉莲"),
            Term(source="bare"),  # no target, no keep → skipped
            Term(source="Pey", keep=True),
        ],
    )
    doc, _ = tr.build_worksheet(_cues(Cue(id=1, start=0, end=1, source="x")), g, "zh")
    assert [r.source for r in doc.glossary] == ["Frieren", "Pey"]


# --- parse_targets / apply_targets ----------------------------------------------


def test_parse_targets_valid_map() -> None:
    assert tr.parse_targets('{"1": "你好", "2": "再见"}') == {1: "你好", 2: "再见"}


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '["1", "你好"]',  # top level must be an object
        "{}",  # empty batch is a mistake, not progress
        '{"x": "你好"}',  # key must be a cue id
        '{"1": "  "}',  # blank target
        '{"1": 2}',  # non-string target
        '{"1": "你好", "01": "重复"}',  # two keys, same id
    ],
)
def test_parse_targets_invalid(text: str) -> None:
    with pytest.raises(OpenBBQError) as exc:
        tr.parse_targets(text)
    assert exc.value.code == "targets_invalid"


def test_apply_targets_partial_batch() -> None:
    doc = _ws_doc(_item(1, "hi"), _item(2, "bye"), _item(3, "ok", "好的"))
    report = tr.apply_targets(doc, {1: "你好"})
    assert report.applied == 1 and report.overwritten == 0
    assert report.filled == 2 and report.total == 3  # id 3 was already filled
    assert doc.items[0].target == "你好" and doc.items[1].target is None


def test_apply_targets_overwrite_counted() -> None:
    doc = _ws_doc(_item(1, "hi", "旧译"))
    report = tr.apply_targets(doc, {1: "新译"})
    assert report.applied == 1 and report.overwritten == 1
    assert doc.items[0].target == "新译"


def test_apply_targets_unknown_id_fails_before_mutation() -> None:
    doc = _ws_doc(_item(1, "hi"))
    with pytest.raises(OpenBBQError) as exc:
        tr.apply_targets(doc, {1: "你好", 9: "多余"})
    assert exc.value.code == "unknown_ids" and exc.value.context["ids"] == [9]
    assert doc.items[0].target is None  # nothing half-applied


# --- check: integrity ---------------------------------------------------------


def _ws_doc(*items: TranslationItem, source_lang="en", target_lang="zh") -> Translation:
    return Translation(
        source_lang=source_lang,
        target_lang=target_lang,
        params=EN_PARAMS,
        items=list(items),
    )


def test_check_complete() -> None:
    cues = _cues(
        Cue(id=1, start=0, end=1, source="hi"), Cue(id=2, start=1, end=2, source="bye")
    )
    doc = _ws_doc(_item(1, "hi", "你好"), _item(2, "bye", "再见"))
    report = tr.check(cues, doc, "zh")
    assert report.filled == 2 and report.total == 2 and report.missing == []
    assert report.ready is True


def test_check_source_copy_is_quality_issue() -> None:
    cues = _cues(Cue(id=1, start=0, end=2, source="Hello there"))
    doc = _ws_doc(_item(1, "Hello there", "Hello there"))

    report = tr.check(cues, doc, "zh")

    assert report.ready is False
    assert report.quality_warnings == 1
    assert report.quality_issues == [
        tr.QualityIssue(id=1, code="source_copy", detail="target matches source")
    ]


def test_check_kept_glossary_only_source_is_not_source_copy() -> None:
    cues = _cues(Cue(id=1, start=0, end=2, source="OpenAI"))
    doc = Translation(
        source_lang="en",
        target_lang="zh",
        params=EN_PARAMS,
        glossary=[GlossaryRef(source="OpenAI", keep=True)],
        items=[_item(1, "OpenAI", "OpenAI")],
    )

    assert tr.check(cues, doc, "zh").quality_issues == []


def test_check_target_script_mismatch_is_quality_issue() -> None:
    cues = _cues(Cue(id=1, start=0, end=2, source="Hello from Vienna"))
    doc = _ws_doc(_item(1, "Hello from Vienna", "Hello from Austria"))

    report = tr.check(cues, doc, "zh")

    assert [issue.code for issue in report.quality_issues] == ["target_script"]


def test_check_repeated_target_for_distinct_sources_is_quality_issue() -> None:
    cues = _cues(
        Cue(id=1, start=0, end=1, source="First source"),
        Cue(id=2, start=1, end=2, source="Second source"),
        Cue(id=3, start=2, end=3, source="Third source"),
    )
    repeated = "我们客户不够。对。"
    doc = _ws_doc(
        _item(1, "First source", repeated),
        _item(2, "Second source", repeated),
        _item(3, "Third source", repeated),
    )

    report = tr.check(cues, doc, "zh")

    assert report.ready is False
    assert [(issue.id, issue.code) for issue in report.quality_issues] == [
        (1, "repeated_target"),
        (2, "repeated_target"),
        (3, "repeated_target"),
    ]


def test_check_zero_budget_is_explicit_blocker() -> None:
    cues = _cues(Cue(id=1, start=0, end=0.02, source="A full sentence"))
    doc = _ws_doc(
        TranslationItem(
            id=1,
            source="A full sentence",
            budget=Budget(max_chars=0, seconds=0.02),
            target=None,
        )
    )

    report = tr.check(cues, doc, "zh")

    assert report.zero_budget == [1]
    assert report.ready is False


def test_check_blank_counts_missing() -> None:
    cues = _cues(
        Cue(id=1, start=0, end=1, source="hi"), Cue(id=2, start=1, end=2, source="bye")
    )
    doc = _ws_doc(_item(1, "hi", "  "), _item(2, "bye", None))
    report = tr.check(cues, doc, "zh")
    assert report.filled == 0 and report.missing == [1, 2]
    assert report.over_budget == []


def test_check_over_budget_uses_target_language_counting() -> None:
    cues = _cues(
        Cue(id=1, start=0, end=1, source="long"),
        Cue(id=2, start=1, end=2, source="ok"),
        Cue(id=3, start=2, end=3, source="empty"),
    )
    doc = _ws_doc(
        TranslationItem(
            id=1,
            source="long",
            budget=Budget(max_chars=2, seconds=1.0),
            target="你 好 吗",
        ),
        TranslationItem(
            id=2,
            source="ok",
            budget=Budget(max_chars=2, seconds=1.0),
            target="你 好",
        ),
        TranslationItem(
            id=3,
            source="empty",
            budget=Budget(max_chars=0, seconds=1.0),
            target=None,
        ),
    )

    report = tr.check(cues, doc, "zh")

    assert report.over_budget == [1]


def test_check_duplicate_id_is_id_mismatch() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="hi"))
    doc = _ws_doc(_item(1, "hi", "你好"), _item(1, "hi", "你好"))
    with pytest.raises(OpenBBQError) as exc:
        tr.check(cues, doc, "zh")
    assert exc.value.code == "id_mismatch"


def test_check_id_set_mismatch() -> None:
    cues = _cues(
        Cue(id=1, start=0, end=1, source="hi"), Cue(id=2, start=1, end=2, source="bye")
    )
    doc = _ws_doc(_item(1, "hi", "你好"))  # missing id 2
    with pytest.raises(OpenBBQError) as exc:
        tr.check(cues, doc, "zh")
    assert exc.value.code == "id_mismatch"


def test_check_source_drift() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="hi"))
    doc = _ws_doc(_item(1, "HELLO", "你好"))  # source edited
    with pytest.raises(OpenBBQError) as exc:
        tr.check(cues, doc, "zh")
    assert exc.value.code == "source_drift"


def test_check_lang_mismatch_filename() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="hi"))
    doc = _ws_doc(_item(1, "hi", "你好"), target_lang="ja")
    with pytest.raises(OpenBBQError) as exc:
        tr.check(cues, doc, "zh")  # filename lang zh ≠ worksheet target_lang ja
    assert exc.value.code == "lang_mismatch"


def test_check_lang_mismatch_source() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="hi"), source_lang="en")
    doc = _ws_doc(_item(1, "hi", "你好"), source_lang="fr")
    with pytest.raises(OpenBBQError) as exc:
        tr.check(cues, doc, "zh")
    assert exc.value.code == "lang_mismatch"


# --- term_warnings ------------------------------------------------------------


def test_check_term_warnings_target_and_keep() -> None:
    cues = _cues(
        Cue(id=1, start=0, end=1, source="Frieren smiled"),
        Cue(id=2, start=1, end=2, source="Pey explains"),
    )
    doc = Translation(
        source_lang="en",
        target_lang="zh",
        params=EN_PARAMS,
        glossary=[
            GlossaryRef(source="Frieren", target="芙莉莲"),
            GlossaryRef(source="Pey", keep=True),
        ],
        items=[
            _item(1, "Frieren smiled", "微笑了"),  # dropped 芙莉莲 → warn
            _item(2, "Pey explains", "佩解释道"),  # dropped verbatim Pey → warn
        ],
    )
    report = tr.check(cues, doc, "zh")
    assert report.term_warnings == 2
    assert report.term_issues == [
        tr.TermIssue(id=1, term="Frieren", expected="芙莉莲"),
        tr.TermIssue(id=2, term="Pey", expected="Pey"),
    ]


def test_check_term_warning_satisfied() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="Frieren smiled"))
    doc = Translation(
        source_lang="en",
        target_lang="zh",
        params=EN_PARAMS,
        glossary=[GlossaryRef(source="Frieren", target="芙莉莲")],
        items=[_item(1, "Frieren smiled", "芙莉莲微笑了")],
    )
    assert tr.check(cues, doc, "zh").term_warnings == 0


def test_check_term_keep_is_case_insensitive_in_target() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="OpenAI shipped"))
    doc = Translation(
        source_lang="en",
        target_lang="zh",
        params=EN_PARAMS,
        glossary=[GlossaryRef(source="OpenAI", keep=True)],
        items=[_item(1, "OpenAI shipped", "openai 发布了")],
    )
    report = tr.check(cues, doc, "zh")
    assert report.term_warnings == 0
    assert report.term_issues == []


# --- lang validation ----------------------------------------------------------


@pytest.mark.parametrize("lang", ["zh", "en", "pt-BR", "zh-Hans"])
def test_validate_lang_accepts(lang: str) -> None:
    assert ws.validate_lang(lang) == lang


@pytest.mark.parametrize("lang", ["../zh", "zh CN", "", "z", "zh/.."])
def test_validate_lang_rejects(lang: str) -> None:
    with pytest.raises(OpenBBQError) as exc:
        ws.validate_lang(lang)
    assert exc.value.code == "invalid_lang"


# --- commands -----------------------------------------------------------------


def _workspace(tmp_path: Path, *cues: Cue, with_segment: bool = True) -> Path:
    path = tmp_path / "ws"
    path.mkdir()
    src = tmp_path / "a.wav"
    src.write_bytes(b"")
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_audio", ref=str(src)),
        stages={},
    )
    ws.write_manifest(path, manifest)
    if with_segment:
        (path / "cues.json").write_text(_cues(*cues).model_dump_json())
        manifest.stages[Stage.SEGMENT] = StageState(
            status=StageStatus.DONE,
            artifact="cues.json",
            updated_at=datetime.now(timezone.utc),
        )
        ws.write_manifest(path, manifest)
    return path


def test_init_writes_worksheet_and_records_running_progress(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1.6, source="Hello."))
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    wpath = path / "translation.zh.json"
    assert wpath.is_file()
    doc = ws.read_translation(wpath)
    assert (
        doc.target_lang == "zh" and len(doc.items) == 1 and doc.items[0].target is None
    )
    stage = ws.read_manifest(path).stages[Stage.TRANSLATE]
    assert stage.status is StageStatus.RUNNING
    assert stage.artifact == "translation.zh.json"
    assert stage.progress == Progress(done=0, total=1)


def test_init_accepts_target_line_budget_overrides(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=4, source="Hello."))

    init_cmd(
        _ctx(),
        lang="zh",
        workspace=str(path),
        max_chars_per_line=20,
        max_lines=2,
    )

    payload = _payload(capsys)
    doc = ws.read_translation(path / "translation.zh.json")
    assert payload["max_chars_per_line"] == 20
    assert payload["max_lines"] == 2
    assert doc.params.max_chars_per_line == 20
    assert doc.params.max_lines == 2
    assert doc.items[0].budget.max_chars == 40


def test_init_refuses_overwrite_without_force(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1, source="hi"))
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    with pytest.raises(OpenBBQError) as exc:
        init_cmd(_ctx(), lang="zh", workspace=str(path))
    assert exc.value.code == "translation_exists"
    init_cmd(_ctx(), lang="zh", workspace=str(path), force=True)  # --force ok


def test_init_missing_cues_errors(tmp_path) -> None:
    path = _workspace(tmp_path, with_segment=False)
    with pytest.raises(OpenBBQError) as exc:
        init_cmd(_ctx(), lang="zh", workspace=str(path))
    assert exc.value.code == "missing_input"


def test_init_invalid_lang(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1, source="hi"))
    with pytest.raises(OpenBBQError) as exc:
        init_cmd(_ctx(), lang="../x", workspace=str(path))
    assert exc.value.code == "invalid_lang"


def test_apply_command_merges_batches(tmp_path) -> None:
    path = _workspace(
        tmp_path,
        Cue(id=1, start=0, end=1, source="hi"),
        Cue(id=2, start=1, end=2, source="bye"),
    )
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    batch1 = tmp_path / "targets.1.json"
    batch1.write_text('{"1": "你好"}', encoding="utf-8")
    apply_cmd(_ctx(), lang="zh", targets=str(batch1), workspace=str(path))
    doc = ws.read_translation(path / "translation.zh.json")
    assert doc.items[0].target == "你好" and doc.items[1].target is None
    stage = ws.read_manifest(path).stages[Stage.TRANSLATE]
    assert stage.status is StageStatus.RUNNING
    assert stage.progress == Progress(done=1, total=2)
    batch2 = tmp_path / "targets.2.json"
    batch2.write_text('{"2": "再见"}', encoding="utf-8")
    apply_cmd(_ctx(), lang="zh", targets=str(batch2), workspace=str(path))
    stage = ws.read_manifest(path).stages[Stage.TRANSLATE]
    # Applying all targets is not the same as passing the quality gate.
    assert stage.status is StageStatus.RUNNING
    assert stage.progress == Progress(done=2, total=2)
    check_cmd(_ctx(), lang="zh", workspace=str(path))
    assert ws.read_manifest(path).stages[Stage.TRANSLATE].status is StageStatus.RUNNING


def test_apply_command_records_budget_driven_shortening_for_audit(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1, source="hello there"))
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    long_batch = tmp_path / "targets.long.json"
    long_batch.write_text(
        json.dumps({"1": "这是一条明显超过字幕预算的冗长翻译文本"}),
        encoding="utf-8",
    )
    apply_cmd(_ctx(), lang="zh", targets=str(long_batch), workspace=str(path))
    short_batch = tmp_path / "targets.short.json"
    short_batch.write_text(json.dumps({"1": "简短译文"}), encoding="utf-8")

    apply_cmd(_ctx(), lang="zh", targets=str(short_batch), workspace=str(path))

    audit = ws.read_translation_audit_optional(path, "zh")
    assert audit is not None
    assert "budget_rewrite" in audit.flags[1].codes
    assert "shortened_translation" in audit.flags[1].codes


def test_apply_command_requires_worksheet(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1, source="hi"))
    batch = tmp_path / "targets.json"
    batch.write_text('{"1": "你好"}', encoding="utf-8")
    with pytest.raises(OpenBBQError) as exc:
        apply_cmd(_ctx(), lang="zh", targets=str(batch), workspace=str(path))
    assert exc.value.code == "translation_not_found"


def test_apply_command_missing_targets_file(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1, source="hi"))
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    with pytest.raises(OpenBBQError) as exc:
        apply_cmd(
            _ctx(), lang="zh", targets=str(tmp_path / "nope.json"), workspace=str(path)
        )
    assert exc.value.code == "targets_not_found"


def test_check_command_progress(tmp_path) -> None:
    path = _workspace(
        tmp_path,
        Cue(id=1, start=0, end=1, source="hi"),
        Cue(id=2, start=1, end=2, source="bye"),
    )
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    # fill one target by editing the worksheet
    wpath = path / "translation.zh.json"
    doc = ws.read_translation(wpath)
    doc.items[0].target = "你好"
    ws.write_text_atomic(wpath, doc.model_dump_json())
    before = (path / "manifest.json").read_bytes()
    check_cmd(_ctx(), lang="zh", workspace=str(path))  # smoke: no raise, reports 1/2
    assert (path / "manifest.json").read_bytes() == before
    stage = ws.read_manifest(path).stages[Stage.TRANSLATE]
    assert stage.status is StageStatus.RUNNING
    assert stage.progress == Progress(done=0, total=2)


def test_translate_command_payload_next_hints(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _workspace(
        tmp_path,
        Cue(id=1, start=0, end=1, source="hi"),
        Cue(id=2, start=1, end=2, source="bye"),
    )
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    assert _payload(capsys)["next"] == "openbbq translate apply zh <targets.json>"

    batch1 = tmp_path / "targets.1.json"
    batch1.write_text('{"1": "你好"}', encoding="utf-8")
    apply_cmd(_ctx(), lang="zh", targets=str(batch1), workspace=str(path))
    assert _payload(capsys)["next"] == "openbbq translate apply zh <targets.json>"

    check_cmd(_ctx(), lang="zh", workspace=str(path))
    assert _payload(capsys)["next"] == "openbbq translate batch zh --limit 20"

    batch2 = tmp_path / "targets.2.json"
    batch2.write_text('{"2": "再见"}', encoding="utf-8")
    apply_cmd(_ctx(), lang="zh", targets=str(batch2), workspace=str(path))
    assert _payload(capsys)["next"] == "openbbq translate check zh"

    check_cmd(_ctx(), lang="zh", workspace=str(path))
    assert (
        _payload(capsys)["next"]
        == "openbbq translate audit zh --limit 20"
    )


def test_translate_check_payload_warns_over_budget(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _workspace(
        tmp_path,
        Cue(id=1, start=0, end=1, source="long"),
        Cue(id=2, start=1, end=2, source="empty"),
    )
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    _payload(capsys)
    wpath = path / "translation.zh.json"
    doc = ws.read_translation(wpath)
    doc.items[0].budget.max_chars = 2
    doc.items[0].target = "你 好 吗"
    doc.items[1].budget.max_chars = 0
    ws.write_text_atomic(wpath, doc.model_dump_json())

    check_cmd(_ctx(), lang="zh", workspace=str(path))

    payload = _payload(capsys)
    assert payload["over_budget"] == 1
    assert payload["over_budget_ids"] == [1]
    assert payload["missing"] == [2]
    assert payload["ready"] is False


def test_translate_check_payload_term_issues(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1, source="OpenAI shipped"))
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    _payload(capsys)
    wpath = path / "translation.zh.json"
    doc = ws.read_translation(wpath)
    doc.glossary = [GlossaryRef(source="OpenAI", keep=True)]
    doc.items[0].target = "发布了"
    ws.write_text_atomic(wpath, doc.model_dump_json())

    check_cmd(_ctx(), lang="zh", workspace=str(path))

    payload = _payload(capsys)
    assert payload["term_warnings"] == 1
    assert payload["term_issues"] == [{"id": 1, "term": "OpenAI", "expected": "OpenAI"}]
    assert payload["ready"] is False


def test_translate_check_quality_issue_keeps_stage_running(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=2, source="Hello there"))
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    _payload(capsys)
    wpath = path / "translation.zh.json"
    doc = ws.read_translation(wpath)
    doc.items[0].target = "Hello there"
    ws.write_text_atomic(wpath, doc.model_dump_json())

    check_cmd(_ctx(), lang="zh", workspace=str(path))

    payload = _payload(capsys)
    assert payload["ready"] is False
    assert payload["quality_warnings"] == 1
    quality_issues = cast(list[dict[str, object]], payload["quality_issues"])
    assert quality_issues[0]["code"] == "source_copy"
    assert ws.read_manifest(path).stages[Stage.TRANSLATE].status is StageStatus.RUNNING


def test_translate_check_reports_target_line_capacity() -> None:
    params = SegmentParams(
        max_cps=100,
        max_chars_per_line=4,
        max_lines=2,
        min_dur=1,
        max_dur=7,
        min_gap=0.083,
    )
    cues = _cues(Cue(id=1, start=0, end=2, source="hello"))
    worksheet = Translation(
        source_lang="en",
        target_lang="zh",
        params=params,
        items=[
            TranslationItem(
                id=1,
                source="hello",
                target="一二三四五六七八九",
                budget=Budget(max_chars=20, seconds=2),
            )
        ],
    )

    report = tr.check(cues, worksheet, "zh")

    assert report.over_budget == []
    assert [(issue.id, issue.code) for issue in report.quality_issues] == [
        (1, "line_capacity")
    ]


def test_translate_batch_returns_bounded_items_context_and_next_cursor(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _workspace(
        tmp_path,
        *(Cue(id=i, start=i - 1, end=i, source=f"source {i}") for i in range(1, 7)),
    )
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    _payload(capsys)
    wpath = path / "translation.zh.json"
    doc = ws.read_translation(wpath)
    doc.items[1].target = "已有译文"
    ws.write_text_atomic(wpath, doc.model_dump_json())

    batch_cmd(
        _ctx(),
        lang="zh",
        workspace=str(path),
        start=2,
        limit=2,
        only_missing=True,
        context=1,
    )

    payload = _payload(capsys)
    assert payload["selected_ids"] == [3, 4]
    items = cast(list[dict[str, object]], payload["items"])
    assert [item["id"] for item in items] == [2, 3, 4, 5]
    assert [item["selected"] for item in items] == [False, True, True, False]
    assert payload["next_from"] == 5
    assert payload["remaining"] == 2


def test_check_command_is_read_only_after_full_worksheet(tmp_path) -> None:
    path = _workspace(
        tmp_path,
        Cue(id=1, start=0, end=1, source="hi"),
        Cue(id=2, start=1, end=2, source="bye"),
    )
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    wpath = path / "translation.zh.json"
    doc = ws.read_translation(wpath)
    doc.items[0].target = "你好"
    doc.items[1].target = "再见"
    ws.write_text_atomic(wpath, doc.model_dump_json())

    manifest = ws.read_manifest(path)
    manifest.stages[Stage.EXPORT] = StageState(
        status=StageStatus.DONE,
        artifact="out/zh.ass",
    )
    manifest.stages[Stage.BURN] = StageState(
        status=StageStatus.DONE,
        artifact="out/zh-burned.mp4",
    )
    ws.write_manifest(path, manifest)
    before = (path / "manifest.json").read_bytes()

    check_cmd(_ctx(), lang="zh", workspace=str(path))

    assert (path / "manifest.json").read_bytes() == before
    after = ws.read_manifest(path)
    assert after.stages[Stage.TRANSLATE].status is StageStatus.RUNNING
    assert after.stages[Stage.EXPORT].status is StageStatus.DONE
    assert after.stages[Stage.BURN].status is StageStatus.DONE


def test_check_infers_single_worksheet(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1, source="hi"))
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    check_cmd(_ctx(), lang=None, workspace=str(path))  # infers zh


def test_check_no_worksheet_not_found(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1, source="hi"))
    with pytest.raises(OpenBBQError) as exc:
        check_cmd(_ctx(), lang=None, workspace=str(path))
    assert exc.value.code == "translation_not_found"

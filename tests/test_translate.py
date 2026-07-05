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
    max_cps=21, max_chars_per_line=50, max_lines=1, min_dur=1.0, max_dur=7.0, min_gap=0.083
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
        source_lang="en", target_lang="zh", params=EN_PARAMS, items=[_item(1, "hi", "你好")]
    )
    dumped = doc.model_dump_json()
    assert '"schema":"openbbq/translation@1"' in dumped.replace(" ", "")
    assert Translation.model_validate_json(dumped) == doc


def test_cues_forbids_dropped_target_field() -> None:
    with pytest.raises(ValidationError):  # target/budget no longer on Cue
        Cue.model_validate({"id": 1, "start": 0, "end": 1, "source": "hi", "target": "x"})


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


def test_build_worksheet_unknown_lang_is_generic() -> None:
    _, generic = tr.build_worksheet(_cues(Cue(id=1, start=0, end=1, source="x")), None, "xx")
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
        source_lang=source_lang, target_lang=target_lang, params=EN_PARAMS, items=list(items)
    )


def test_check_complete() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="hi"), Cue(id=2, start=1, end=2, source="bye"))
    doc = _ws_doc(_item(1, "hi", "你好"), _item(2, "bye", "再见"))
    report = tr.check(cues, doc, "zh")
    assert report.filled == 2 and report.total == 2 and report.missing == []


def test_check_blank_counts_missing() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="hi"), Cue(id=2, start=1, end=2, source="bye"))
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
    cues = _cues(Cue(id=1, start=0, end=1, source="hi"), Cue(id=2, start=1, end=2, source="bye"))
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
        source_lang="en", target_lang="zh", params=EN_PARAMS,
        glossary=[
            GlossaryRef(source="Frieren", target="芙莉莲"),
            GlossaryRef(source="Pey", keep=True),
        ],
        items=[
            _item(1, "Frieren smiled", "微笑了"),   # dropped 芙莉莲 → warn
            _item(2, "Pey explains", "佩解释道"),    # dropped verbatim Pey → warn
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
        source_lang="en", target_lang="zh", params=EN_PARAMS,
        glossary=[GlossaryRef(source="Frieren", target="芙莉莲")],
        items=[_item(1, "Frieren smiled", "芙莉莲微笑了")],
    )
    assert tr.check(cues, doc, "zh").term_warnings == 0


def test_check_term_keep_is_case_insensitive_in_target() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="OpenAI shipped"))
    doc = Translation(
        source_lang="en", target_lang="zh", params=EN_PARAMS,
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
            status=StageStatus.DONE, artifact="cues.json", updated_at=datetime.now(timezone.utc)
        )
        ws.write_manifest(path, manifest)
    return path


def test_init_writes_worksheet_and_records_running_progress(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1.6, source="Hello."))
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    wpath = path / "translation.zh.json"
    assert wpath.is_file()
    doc = ws.read_translation(wpath)
    assert doc.target_lang == "zh" and len(doc.items) == 1 and doc.items[0].target is None
    stage = ws.read_manifest(path).stages[Stage.TRANSLATE]
    assert stage.status is StageStatus.RUNNING
    assert stage.artifact == "translation.zh.json"
    assert stage.progress == Progress(done=0, total=1)


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
        tmp_path, Cue(id=1, start=0, end=1, source="hi"), Cue(id=2, start=1, end=2, source="bye")
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
    assert stage.status is StageStatus.DONE
    assert stage.progress == Progress(done=2, total=2)
    check_cmd(_ctx(), lang="zh", workspace=str(path))  # complete: no raise


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
        apply_cmd(_ctx(), lang="zh", targets=str(tmp_path / "nope.json"), workspace=str(path))
    assert exc.value.code == "targets_not_found"


def test_check_command_progress(tmp_path) -> None:
    path = _workspace(
        tmp_path, Cue(id=1, start=0, end=1, source="hi"), Cue(id=2, start=1, end=2, source="bye")
    )
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    # fill one target by editing the worksheet
    wpath = path / "translation.zh.json"
    doc = ws.read_translation(wpath)
    doc.items[0].target = "你好"
    ws.write_text_atomic(wpath, doc.model_dump_json())
    check_cmd(_ctx(), lang="zh", workspace=str(path))  # smoke: no raise, reports 1/2
    stage = ws.read_manifest(path).stages[Stage.TRANSLATE]
    assert stage.status is StageStatus.RUNNING
    assert stage.progress == Progress(done=1, total=2)


def test_translate_command_payload_next_hints(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _workspace(
        tmp_path, Cue(id=1, start=0, end=1, source="hi"), Cue(id=2, start=1, end=2, source="bye")
    )
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    assert _payload(capsys)["next"] == "openbbq translate apply zh <targets.json>"

    batch1 = tmp_path / "targets.1.json"
    batch1.write_text('{"1": "你好"}', encoding="utf-8")
    apply_cmd(_ctx(), lang="zh", targets=str(batch1), workspace=str(path))
    assert _payload(capsys)["next"] == "openbbq translate apply zh <targets.json>"

    check_cmd(_ctx(), lang="zh", workspace=str(path))
    assert _payload(capsys)["next"] == "openbbq translate apply zh <targets.json>"

    batch2 = tmp_path / "targets.2.json"
    batch2.write_text('{"2": "再见"}', encoding="utf-8")
    apply_cmd(_ctx(), lang="zh", targets=str(batch2), workspace=str(path))
    assert _payload(capsys)["next"] == "openbbq translate check zh"

    check_cmd(_ctx(), lang="zh", workspace=str(path))
    assert (
        _payload(capsys)["next"]
        == "openbbq export --to zh --mode bilingual --format ass"
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
    assert payload["term_issues"] == [
        {"id": 1, "term": "OpenAI", "expected": "OpenAI"}
    ]


def test_check_command_syncs_full_worksheet_to_done(tmp_path) -> None:
    path = _workspace(
        tmp_path, Cue(id=1, start=0, end=1, source="hi"), Cue(id=2, start=1, end=2, source="bye")
    )
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    wpath = path / "translation.zh.json"
    doc = ws.read_translation(wpath)
    doc.items[0].target = "你好"
    doc.items[1].target = "再见"
    ws.write_text_atomic(wpath, doc.model_dump_json())

    check_cmd(_ctx(), lang="zh", workspace=str(path))

    stage = ws.read_manifest(path).stages[Stage.TRANSLATE]
    assert stage.status is StageStatus.DONE
    assert stage.progress == Progress(done=2, total=2)


def test_check_infers_single_worksheet(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1, source="hi"))
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    check_cmd(_ctx(), lang=None, workspace=str(path))  # infers zh


def test_check_no_worksheet_not_found(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1, source="hi"))
    with pytest.raises(OpenBBQError) as exc:
        check_cmd(_ctx(), lang=None, workspace=str(path))
    assert exc.value.code == "translation_not_found"

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer
from pydantic import ValidationError

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


def test_check_term_warning_satisfied() -> None:
    cues = _cues(Cue(id=1, start=0, end=1, source="Frieren smiled"))
    doc = Translation(
        source_lang="en", target_lang="zh", params=EN_PARAMS,
        glossary=[GlossaryRef(source="Frieren", target="芙莉莲")],
        items=[_item(1, "Frieren smiled", "芙莉莲微笑了")],
    )
    assert tr.check(cues, doc, "zh").term_warnings == 0


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


def test_init_writes_worksheet_and_records_done(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1.6, source="Hello."))
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    wpath = path / "translation.zh.json"
    assert wpath.is_file()
    doc = ws.read_translation(wpath)
    assert doc.target_lang == "zh" and len(doc.items) == 1 and doc.items[0].target is None
    assert ws.read_manifest(path).stages[Stage.TRANSLATE].status is StageStatus.DONE


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


def test_check_command_progress(tmp_path) -> None:
    path = _workspace(
        tmp_path, Cue(id=1, start=0, end=1, source="hi"), Cue(id=2, start=1, end=2, source="bye")
    )
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    # fill one target by editing the worksheet
    wpath = path / "translation.zh.json"
    doc = ws.read_translation(wpath)
    doc.items[0].target = "你好"
    wpath.write_text(doc.model_dump_json())
    check_cmd(_ctx(), lang="zh", workspace=str(path))  # smoke: no raise, reports 1/2


def test_check_infers_single_worksheet(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1, source="hi"))
    init_cmd(_ctx(), lang="zh", workspace=str(path))
    check_cmd(_ctx(), lang=None, workspace=str(path))  # infers zh


def test_check_no_worksheet_not_found(tmp_path) -> None:
    path = _workspace(tmp_path, Cue(id=1, start=0, end=1, source="hi"))
    with pytest.raises(OpenBBQError) as exc:
        check_cmd(_ctx(), lang=None, workspace=str(path))
    assert exc.value.code == "translation_not_found"

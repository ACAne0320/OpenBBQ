from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer
from pydantic import ValidationError

from openbbq.cli.commands.glossary import use
from openbbq.cli.commands.init import init
from openbbq.cli.output import Output
from openbbq.core import glossary as gl
from openbbq.core import segment as seg
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    ASRInfo,
    Glossary,
    Segment,
    Term,
    Transcript,
    Word,
)

EN = seg.LANGUAGE_PROFILES["en"]


def _ctx() -> typer.Context:
    return cast(typer.Context, SimpleNamespace(obj=Output(json_mode=True)))


def W(word: str, start: float, end: float, prob: float = 0.9) -> Word:
    return Word(word=word, start=start, end=end, prob=prob)


def _transcript(*segments: Segment, language: str = "en") -> Transcript:
    return Transcript(
        language=language,
        duration=10.0,
        asr=ASRInfo(backend="test", model="t", created_at=datetime.now(timezone.utc)),
        segments=list(segments),
    )


def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path))


# --- schema -------------------------------------------------------------------


def test_term_defaults() -> None:
    t = Term(source="Frieren")
    assert t.target is None and t.aliases == [] and t.keep is False and t.note is None


def test_glossary_roundtrip_serializes_schema_alias() -> None:
    g = Glossary(name="frieren", context="bg", terms=[Term(source="Frieren", target="芙莉莲")])
    dumped = g.model_dump_json()
    assert '"schema":"openbbq/glossary@1"' in dumped.replace(" ", "")
    assert Glossary.model_validate_json(dumped) == g


def test_glossary_forbids_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        Glossary.model_validate({"schema": "openbbq/glossary@1", "name": "x", "bogus": 1})


# --- library ------------------------------------------------------------------


def test_scaffold_then_load_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _home(tmp_path, monkeypatch)
    path = gl.scaffold("frieren", context="奇幻动画")
    assert path.is_file() and path.name == "frieren.json"
    g = gl.load("frieren")
    assert g.name == "frieren" and g.context == "奇幻动画" and g.terms == []


def test_load_missing_is_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _home(tmp_path, monkeypatch)
    with pytest.raises(OpenBBQError) as exc:
        gl.load("nope")
    assert exc.value.code == "glossary_not_found"


def test_scaffold_existing_is_exists_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _home(tmp_path, monkeypatch)
    gl.scaffold("frieren")
    with pytest.raises(OpenBBQError) as exc:
        gl.scaffold("frieren")
    assert exc.value.code == "glossary_exists"


def test_load_malformed_is_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _home(tmp_path, monkeypatch)
    p = gl.glossary_path("broken")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"schema":"openbbq/glossary@1"}')  # missing required `name`
    with pytest.raises(OpenBBQError) as exc:
        gl.load("broken")
    assert exc.value.code == "invalid_glossary"


def test_list_names_empty_then_sorted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _home(tmp_path, monkeypatch)
    assert gl.list_names() == []
    gl.scaffold("zeta")
    gl.scaffold("alpha")
    assert gl.list_names() == ["alpha", "zeta"]


def test_load_optional_none_passes_through() -> None:
    assert gl.load_optional(None) is None


# --- touchpoint 1: bias -------------------------------------------------------


def test_bias_terms_dedupes_orders_and_strips() -> None:
    g = Glossary(
        name="g",
        terms=[Term(source="Frieren"), Term(source="  "), Term(source="Himmel"), Term(source="Frieren")],
    )
    assert gl.bias_terms(g) == ["Frieren", "Himmel"]


# --- touchpoint 2: correction -------------------------------------------------


def test_corrector_identity_without_glossary() -> None:
    fix = gl.corrector(None)
    assert fix("Freerun smiled") == "Freerun smiled"


def test_corrector_replaces_alias_case_insensitively() -> None:
    fix = gl.corrector(Glossary(name="g", terms=[Term(source="Frieren", aliases=["Freerun"])]))
    assert fix("and freerun smiled") == "and Frieren smiled"


def test_corrector_respects_word_boundary() -> None:
    fix = gl.corrector(Glossary(name="g", terms=[Term(source="ran", aliases=["run"])]))
    # "run" inside "Freerun"/"running" must not be touched; standalone is fixed
    assert fix("Freerun running, run!") == "Freerun running, ran!"


def test_corrector_multiword_alias_wins_over_shorter() -> None:
    g = Glossary(
        name="g",
        terms=[Term(source="Frieren", aliases=["Free run", "run"])],
    )
    fix = gl.corrector(g)
    assert fix("the Free run") == "the Frieren"


def test_correction_applies_in_build_cues() -> None:
    g = Glossary(name="g", terms=[Term(source="Frieren", aliases=["Freerun"])])
    t = _transcript(
        Segment(id=0, start=0, end=2, text="x", words=[W("And", 0, 0.3), W("Freerun.", 0.3, 1.2)])
    )
    outcome = seg.build_cues(t, EN, gl.corrector(g))
    assert outcome.cues[0].source == "And Frieren."


# --- touchpoint 3 helper: suggest ---------------------------------------------


def _proper_noun_transcript() -> Transcript:
    segs = [
        Segment(
            id=i, start=i, end=i + 1, text="And Freerun smiled at the village.",
            words=[
                W("And", i, i + 0.2, 0.99),
                W("Freerun", i + 0.2, i + 0.6, 0.41),
                W("smiled", i + 0.6, i + 0.8, 0.97),
                W("at", i + 0.8, i + 0.85, 0.99),
                W("the", i + 0.85, i + 0.9, 0.99),
                W("village.", i + 0.9, i + 1.0, 0.95),
            ],
        )
        for i in range(3)
    ]
    return _transcript(*segs)


def test_suggest_surfaces_low_prob_recurring_proper_noun() -> None:
    cands = gl.suggest_candidates(_proper_noun_transcript())
    surfaces = [c.surface for c in cands]
    assert "Freerun" in surfaces
    assert "the" not in surfaces  # high prob, not proper
    top = next(c for c in cands if c.surface == "Freerun")
    assert top.count == 3 and top.avg_prob is not None and top.avg_prob < 0.6


def test_suggest_excludes_known_terms() -> None:
    cands = gl.suggest_candidates(_proper_noun_transcript(), known={"freerun"})
    assert all(c.surface != "Freerun" for c in cands)


def test_suggest_no_words_fallback_uses_casing_and_frequency() -> None:
    t = _transcript(
        Segment(id=0, start=0, end=2, text="Stark trained hard.", words=None),
        Segment(id=1, start=2, end=4, text="Then Stark won.", words=None),
    )
    cands = gl.suggest_candidates(t)
    surfaces = [c.surface for c in cands]
    assert "Stark" in surfaces
    assert next(c for c in cands if c.surface == "Stark").avg_prob is None
    assert "trained" not in surfaces  # lowercase, not proper


# --- binding ------------------------------------------------------------------


def _local_video(tmp_path: Path) -> str:
    v = tmp_path / "clip.mp4"
    v.write_bytes(b"x")
    return str(v)


def test_init_binds_existing_glossary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _home(tmp_path, monkeypatch)
    gl.scaffold("frieren")
    wsdir = tmp_path / "ws"
    init(_ctx(), source=_local_video(tmp_path), workspace=str(wsdir), glossary="frieren")
    assert ws.read_manifest(wsdir).glossary == "frieren"


def test_init_rejects_missing_glossary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _home(tmp_path, monkeypatch)
    with pytest.raises(OpenBBQError) as exc:
        init(
            _ctx(),
            source=_local_video(tmp_path),
            workspace=str(tmp_path / "ws"),
            glossary="missing",
        )
    assert exc.value.code == "glossary_not_found"


def test_glossary_use_rebinds_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _home(tmp_path, monkeypatch)
    gl.scaffold("frieren")
    wsdir = tmp_path / "ws"
    init(_ctx(), source=_local_video(tmp_path), workspace=str(wsdir), glossary=None)
    use(_ctx(), name="frieren", workspace=str(wsdir))
    assert ws.read_manifest(wsdir).glossary == "frieren"

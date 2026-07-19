from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import typer

from openbbq.cli.commands.agent import finish as finish_command
from openbbq.cli.commands.export import export as export_command
from openbbq.cli.commands.segment import segment as segment_command
from openbbq.cli.delivery import assess_delivery
from openbbq.cli.output import Output
from openbbq.core import agent_workflow
from openbbq.core import export as exportlib
from openbbq.core import glossary as glossarylib
from openbbq.core import glossary_overlay
from openbbq.core import translate as translatelib
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    ASRInfo,
    AgentSession,
    Cue,
    Cues,
    Glossary,
    Segment,
    SegmentParams,
    Stage,
    StageState,
    StageStatus,
    Term,
    Transcript,
    Word,
)


def _workspace(tmp_path: Path, sources: list[str]) -> tuple[Path, AgentSession]:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    path, manifest = ws.init_workspace(
        str(video), workspace=str(tmp_path / "work")
    )
    session = agent_workflow.create_session(
        path,
        "zh",
        glossary_selected=True,
    )
    audio = path / "media" / "audio.16k.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")
    ws.record_stage(
        path,
        manifest,
        Stage.EXTRACT_AUDIO,
        StageState(status=StageStatus.DONE, artifact="media/audio.16k.wav"),
    )
    segments = []
    for index, source in enumerate(sources):
        start = index * 2.0
        tokens = source.split()
        step = 1.5 / max(len(tokens), 1)
        segments.append(
            Segment(
                id=index,
                start=start,
                end=start + 1.5,
                text=source,
                words=[
                    Word(
                        word=token,
                        start=start + word_index * step,
                        end=start + (word_index + 1) * step,
                        prob=0.99,
                    )
                    for word_index, token in enumerate(tokens)
                ],
            )
        )
    transcript = Transcript(
        language="en",
        duration=max(len(sources) * 2.0, 1.0),
        asr=ASRInfo(
            backend="test",
            model="test",
            created_at=datetime.now(timezone.utc),
        ),
        segments=segments,
    )
    transcript_path = path / "transcript.json"
    ws.write_text_atomic(transcript_path, transcript.model_dump_json(indent=2))
    ws.record_stage(
        path,
        manifest,
        Stage.TRANSCRIBE,
        StageState(status=StageStatus.DONE, artifact="transcript.json"),
    )
    return path, session


def _ctx() -> typer.Context:
    return cast(typer.Context, SimpleNamespace(obj=Output(json_mode=True)))


def _next(path: Path) -> dict[str, Any]:
    session = ws.read_agent_session_optional(path, "zh")
    assert session is not None
    return agent_workflow.next_action(path, ws.read_manifest(path), session)


def _apply(path: Path, response: dict[str, Any]) -> dict[str, Any]:
    session = ws.read_agent_session_optional(path, "zh")
    assert session is not None
    return agent_workflow.apply_response(
        path,
        ws.read_manifest(path),
        session,
        json.dumps(response),
    )


def _review_all_sources(path: Path) -> None:
    while True:
        action = _next(path)
        if action["action"] != "review_source":
            return
        _apply(
            path,
            {
                "batch_id": action["batch_id"],
                "reviewed_segment_ids": action["selected_segment_ids"],
                "issue_decisions": {
                    item["id"]: {
                        "action": "accept",
                        "reason": "context confirms the transcription",
                    }
                    for item in action["detector_issues"]
                },
                "source_fixes": [],
                "glossary_updates": [],
            },
        )


def _install_cues_and_worksheet(path: Path, sources: list[str], *, v1: bool = False):
    manifest = ws.read_manifest(path)
    params = SegmentParams(
        max_cps=21,
        max_chars_per_line=50,
        max_lines=1,
        min_dur=1,
        max_dur=7,
        min_gap=0.083,
    )
    cues = Cues(
        source_lang="en",
        params=params,
        cues=[
            Cue(id=index + 1, start=index * 2, end=index * 2 + 1.5, source=source)
            for index, source in enumerate(sources)
        ],
    )
    cues_path = path / "cues.json"
    ws.write_text_atomic(cues_path, cues.model_dump_json(indent=2))
    provenance_inputs = [path / "transcript.json"]
    if ws.asr_review_path(path).is_file():
        provenance_inputs.append(ws.asr_review_path(path))
    ws.record_artifact_provenance(
        path,
        cues_path,
        Stage.SEGMENT,
        inputs=provenance_inputs,
    )
    ws.record_stage(
        path,
        manifest,
        Stage.SEGMENT,
        StageState(status=StageStatus.DONE, artifact="cues.json"),
    )
    worksheet, _ = translatelib.build_worksheet(
        cues,
        glossary_overlay.merged(path, manifest.glossary),
        "zh",
        title=manifest.source.title,
        author=manifest.source.author,
    )
    if v1:
        worksheet.schema_ = "openbbq/translation@1"
        worksheet.brief = None
    ws.write_text_atomic(
        ws.worksheet_path(path, "zh"),
        worksheet.model_dump_json(indent=2),
    )
    return cues, worksheet


def test_source_review_lease_is_idempotent_and_covers_at_most_20_segments(
    tmp_path: Path,
) -> None:
    sources = [f"ordinary source {index}" for index in range(21)]
    path, _ = _workspace(tmp_path, sources)

    first = _next(path)
    repeated = _next(path)

    assert first == repeated
    assert first["action"] == "review_source"
    assert first["selected_segment_ids"] == list(range(20))
    assert first["source_metadata"]["title"] == "source"
    assert first["segments"][0]["word_count"] == 3
    assert first["segments"][0]["words"] == []
    assert first["segments"][0]["words_omitted"] == 3
    assert first["segments"][0]["raw_source"] is None
    assert first["segments"][0]["after_glossary"] is None
    _apply(
        path,
        {
            "batch_id": first["batch_id"],
            "reviewed_segment_ids": first["selected_segment_ids"],
            "issue_decisions": {},
            "source_fixes": [],
            "glossary_updates": [],
        },
    )
    second = _next(path)
    assert second["selected_segment_ids"] == [20]


def test_source_review_accepts_the_exact_id_set_in_any_order(tmp_path: Path) -> None:
    path, _ = _workspace(tmp_path, ["first segment", "second segment"])
    action = _next(path)

    result = _apply(
        path,
        {
            "batch_id": action["batch_id"],
            "reviewed_segment_ids": list(reversed(action["selected_segment_ids"])),
            "issue_decisions": {},
            "source_fixes": [],
            "glossary_updates": [],
        },
    )

    assert result["reviewed_segments"] == 2


def test_new_session_selects_glossary_then_returns_exact_mechanical_argv(
    tmp_path: Path,
) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    path, manifest = ws.init_workspace(
        str(video), workspace=str(tmp_path / "work")
    )
    session = agent_workflow.create_session(path, "zh")
    selection = agent_workflow.next_action(path, manifest, session)
    assert selection["action"] == "select_glossary"
    agent_workflow.apply_response(
        path,
        manifest,
        session,
        json.dumps({"batch_id": selection["batch_id"], "choice": "none"}),
    )

    command = _next(path)

    assert command == {
        "action": "run_command",
        "argv": [
            "openbbq",
            "--json",
            "extract-audio",
            "--workspace",
            str(path),
        ],
        "reason": "normalize source audio",
    }


def test_source_review_rejects_partial_segment_or_issue_sets(tmp_path: Path) -> None:
    path, _ = _workspace(tmp_path, ["uncertain token"])
    transcript = ws.read_transcript(path / "transcript.json")
    words = transcript.segments[0].words
    assert words is not None
    words[0].prob = 0.1
    ws.write_text_atomic(path / "transcript.json", transcript.model_dump_json(indent=2))
    action = _next(path)

    with pytest.raises(OpenBBQError) as segment_error:
        _apply(
            path,
            {
                "batch_id": action["batch_id"],
                "reviewed_segment_ids": [],
                "issue_decisions": {},
                "source_fixes": [],
                "glossary_updates": [],
            },
        )
    assert segment_error.value.code == "agent_id_set_mismatch"

    with pytest.raises(OpenBBQError) as issue_error:
        _apply(
            path,
            {
                "batch_id": action["batch_id"],
                "reviewed_segment_ids": [0],
                "issue_decisions": {},
                "source_fixes": [],
                "glossary_updates": [],
            },
        )
    assert issue_error.value.code == "agent_issue_set_mismatch"


def test_segment_is_blocked_until_agent_source_review_covers_every_segment(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, _ = _workspace(tmp_path, ["first segment", "second segment"])

    kwargs = {
        "workspace": str(path),
        "lang": None,
        "glossary": None,
        "max_cps": None,
        "max_chars_per_line": None,
        "max_lines": None,
        "min_dur": None,
        "max_dur": None,
        "min_gap": None,
        "pause_threshold": None,
    }
    with pytest.raises(OpenBBQError) as error:
        segment_command(_ctx(), **kwargs)
    assert error.value.code == "agent_source_review_incomplete"

    _review_all_sources(path)
    segment_command(_ctx(), **kwargs)
    capsys.readouterr()
    assert ws.read_manifest(path).stages[Stage.SEGMENT].status is StageStatus.DONE


def test_translation_v1_migrates_in_place_and_preserves_targets(tmp_path: Path) -> None:
    path, _ = _workspace(tmp_path, ["hello"])
    _review_all_sources(path)
    _, worksheet = _install_cues_and_worksheet(path, ["hello"], v1=True)
    worksheet.items[0].target = "已有译文"
    ws.write_text_atomic(
        ws.worksheet_path(path, "zh"), worksheet.model_dump_json(indent=2)
    )

    action = _next(path)
    migrated = ws.read_translation(ws.worksheet_path(path, "zh"))

    assert action["action"] == "translate"
    assert migrated.schema_ == "openbbq/translation@2"
    assert migrated.brief is not None
    assert migrated.items[0].target == "已有译文"


def test_translate_requires_exact_ids_policy_and_syncs_cue_scoped_source_fix(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["codex is useful"])
    _review_all_sources(path)
    _install_cues_and_worksheet(path, ["codex is useful"])
    action = _next(path)
    assert action["action"] == "translate"
    assert len(action["selected_ids"]) <= 20
    glossary_update_schema = action["response_schema"]["glossary_updates"][0]
    assert glossary_update_schema["reusable"] is True
    assert glossary_update_schema["aliases"] == ["reusable ASR mishearing"]

    with pytest.raises(OpenBBQError) as policy_error:
        _apply(
            path,
            {
                "batch_id": action["batch_id"],
                "policy_hash": "wrong",
                "translations": {"1": "Codex 很有用"},
                "source_fixes": [],
                "glossary_updates": [],
            },
        )
    assert policy_error.value.code == "agent_policy_hash_mismatch"

    _apply(
        path,
        {
            "batch_id": action["batch_id"],
            "policy_hash": action["policy_hash"],
            "translations": {"1": "Codex 很有用"},
            "source_fixes": [
                {
                    "cue_id": 1,
                    "find": "codex",
                    "replacement": "Codex",
                    "evidence": "official product casing",
                }
            ],
            "glossary_updates": [
                {
                    "source": "Codex",
                    "aliases": ["codex"],
                    "keep": True,
                    "reusable": True,
                    "evidence": "official product name recurs in related videos",
                }
            ],
        },
    )
    cues = ws.read_cues(path / "cues.json")
    worksheet = ws.read_translation(ws.worksheet_path(path, "zh"))
    assert cues.cues[0].source == "Codex is useful"
    assert worksheet.items[0].source == "Codex is useful"
    assert worksheet.items[0].target == "Codex 很有用"

    risk = _next(path)
    assert risk["action"] == "review_risks"
    assert "source_changed" in risk["items"][0]["risk_codes"]
    _apply(
        path,
        {
            "batch_id": risk["batch_id"],
            "policy_hash": risk["policy_hash"],
            "decisions": {"1": {"action": "accept"}},
        },
    )
    finish = _next(path)
    assert finish["action"] == "finish"
    assert _next(path) == finish


def test_balanced_risks_do_not_repeat_accepted_low_confidence_source_review(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["hello"])
    transcript = ws.read_transcript(path / "transcript.json")
    assert transcript.segments[0].words is not None
    transcript.segments[0].words[0].prob = 0.3
    ws.write_text_atomic(
        path / "transcript.json", transcript.model_dump_json(indent=2)
    )
    _review_all_sources(path)
    _install_cues_and_worksheet(path, ["hello"])
    action = _next(path)
    _apply(
        path,
        {
            "batch_id": action["batch_id"],
            "policy_hash": action["policy_hash"],
            "translations": {"1": "你好"},
            "source_fixes": [],
            "glossary_updates": [],
        },
    )

    assert _next(path)["action"] == "finish"


def test_risk_review_can_fix_source_and_learn_reusable_glossary_alias(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["code x works?"])
    _review_all_sources(path)
    _install_cues_and_worksheet(path, ["code x works?"])
    translate = _next(path)
    _apply(
        path,
        {
            "batch_id": translate["batch_id"],
            "policy_hash": translate["policy_hash"],
            "translations": {"1": "这可以工作。"},
            "source_fixes": [],
            "glossary_updates": [],
        },
    )
    risk = _next(path)
    assert risk["action"] == "review_risks"
    assert risk["response_schema"]["source_fixes"]
    result = _apply(
        path,
        {
            "batch_id": risk["batch_id"],
            "policy_hash": risk["policy_hash"],
            "decisions": {
                "1": {
                    "action": "revise",
                    "target": "Codex 可以工作吗？",
                    "reason": "Restore the question after correcting the product name.",
                }
            },
            "source_fixes": [
                {
                    "cue_id": 1,
                    "find": "code x",
                    "replacement": "Codex",
                    "evidence": "The surrounding discussion names the product Codex.",
                }
            ],
            "glossary_updates": [
                {
                    "source": "Codex",
                    "aliases": ["code x"],
                    "keep": True,
                    "reusable": True,
                    "evidence": "A recurring phonetic ASR spelling of the product name.",
                }
            ],
        },
    )

    assert result["source_fixes"] == 1
    assert ws.read_cues(path / "cues.json").cues[0].source == "Codex works?"
    assert ws.read_translation(ws.worksheet_path(path, "zh")).items[0].source == (
        "Codex works?"
    )
    assert ws.read_translation(ws.worksheet_path(path, "zh")).items[0].target == (
        "Codex 可以工作吗？"
    )
    effective = glossary_overlay.merged(path)
    assert effective is not None
    assert effective.terms[0].aliases == ["code x"]
    assert _next(path)["action"] == "finish"


def test_translation_discovered_alias_requires_a_current_cue_source_fix(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["code x works"])
    _review_all_sources(path)
    _install_cues_and_worksheet(path, ["code x works"])
    action = _next(path)

    with pytest.raises(OpenBBQError) as error:
        _apply(
            path,
            {
                "batch_id": action["batch_id"],
                "policy_hash": action["policy_hash"],
                "translations": {"1": "Codex 可以工作"},
                "source_fixes": [],
                "glossary_updates": [
                    {
                        "source": "Codex",
                        "aliases": ["code x"],
                        "keep": True,
                        "reusable": True,
                        "evidence": "confirmed recurring ASR spelling",
                    }
                ],
            },
        )

    assert error.value.code == "source_fix_requires_review"


def test_agent_translation_batches_are_cli_enforced_to_20(tmp_path: Path) -> None:
    sources = [f"ordinary source {index}" for index in range(21)]
    path, _ = _workspace(tmp_path, sources)
    _review_all_sources(path)
    _install_cues_and_worksheet(path, sources)

    first = _next(path)
    assert first["action"] == "translate"
    assert first["selected_ids"] == list(range(1, 21))
    _apply(
        path,
        {
            "batch_id": first["batch_id"],
            "policy_hash": first["policy_hash"],
            "translations": {
                str(item_id): f"第{item_id}条内容"
                for item_id in first["selected_ids"]
            },
            "source_fixes": [],
            "glossary_updates": [],
        },
    )

    second = _next(path)
    assert second["action"] == "translate"
    assert second["selected_ids"] == [21]


def test_translation_lease_becomes_stale_after_external_worksheet_change(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["hello"])
    _review_all_sources(path)
    _install_cues_and_worksheet(path, ["hello"])
    action = _next(path)
    worksheet_path = ws.worksheet_path(path, "zh")
    worksheet = ws.read_translation(worksheet_path)
    worksheet.items[0].source = "externally changed"
    ws.write_text_atomic(worksheet_path, worksheet.model_dump_json(indent=2))

    with pytest.raises(OpenBBQError) as error:
        _apply(
            path,
            {
                "batch_id": action["batch_id"],
                "policy_hash": action["policy_hash"],
                "translations": {"1": "你好"},
                "source_fixes": [],
                "glossary_updates": [],
            },
        )
    assert error.value.code == "agent_lease_stale"
    session = ws.read_agent_session_optional(path, "zh")
    assert session is not None
    assert session.active_lease is None


def test_upstream_transcript_change_invalidates_translation_lease_and_reopens_source_review(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["hello"])
    _review_all_sources(path)
    _install_cues_and_worksheet(path, ["hello"])
    translate = _next(path)
    transcript = ws.read_transcript(path / "transcript.json")
    transcript.segments[0].text = "hello again"
    ws.write_text_atomic(path / "transcript.json", transcript.model_dump_json(indent=2))

    reopened = _next(path)

    assert translate["batch_id"] != reopened["batch_id"]
    assert reopened["action"] == "review_source"
    assert reopened["selected_segment_ids"] == [0]


def test_cue_scoped_source_fix_rolls_back_cues_when_worksheet_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, _ = _workspace(tmp_path, ["codex works"])
    _review_all_sources(path)
    _install_cues_and_worksheet(path, ["codex works"])
    action = _next(path)
    cues_path = path / "cues.json"
    worksheet_path = ws.worksheet_path(path, "zh")
    original_cues = cues_path.read_text(encoding="utf-8")
    original_worksheet = worksheet_path.read_text(encoding="utf-8")
    overlay_path = glossary_overlay.path(path)
    original_overlay = overlay_path.read_text(encoding="utf-8")
    real_write = ws.write_text_atomic
    failed = False

    def fail_worksheet_once(target: Path, content: str) -> None:
        nonlocal failed
        if target == worksheet_path and not failed:
            failed = True
            raise OSError("simulated worksheet failure")
        real_write(target, content)

    monkeypatch.setattr(ws, "write_text_atomic", fail_worksheet_once)

    with pytest.raises(OSError):
        _apply(
            path,
            {
                "batch_id": action["batch_id"],
                "policy_hash": action["policy_hash"],
                "translations": {"1": "Codex 可以工作"},
                "source_fixes": [
                    {
                        "cue_id": 1,
                        "find": "codex",
                        "replacement": "Codex",
                        "evidence": "official casing",
                    }
                ],
                "glossary_updates": [
                    {
                        "source": "Codex",
                        "aliases": ["codex"],
                        "keep": True,
                        "reusable": True,
                        "evidence": "official product casing",
                    }
                ],
            },
        )

    assert cues_path.read_text(encoding="utf-8") == original_cues
    assert worksheet_path.read_text(encoding="utf-8") == original_worksheet
    assert overlay_path.read_text(encoding="utf-8") == original_overlay


def test_workspace_lock_prevents_concurrent_next_from_creating_two_batches(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["hello"])

    def call_next() -> str:
        with ws.agent_workspace_lock(path):
            session = ws.read_agent_session_optional(path, "zh")
            assert session is not None
            action = agent_workflow.next_action(
                path, ws.read_manifest(path), session
            )
            return str(action["batch_id"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        batch_ids = list(pool.map(lambda _value: call_next(), range(2)))

    assert batch_ids[0] == batch_ids[1]


def test_glossary_overlay_is_immediate_and_publishes_without_midtask_global_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("OPENBBQ_HOME", str(home))
    base = Glossary(
        name="series",
        context="AI tooling",
        terms=[Term(source="OpenAI", keep=True)],
    )
    glossarylib.save(base)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    glossary_overlay.initialize(workspace, base_name="series")

    glossary_overlay.apply_updates(
        workspace,
        [
            agent_workflow.AgentGlossaryUpdate(
                source="Codex",
                aliases=["Code X"],
                keep=True,
                reusable=True,
                evidence="recurring official product name",
            )
        ],
    )

    assert [term.source for term in glossarylib.load("series").terms] == ["OpenAI"]
    effective = glossary_overlay.merged(workspace, "series")
    assert effective is not None
    assert [term.source for term in effective.terms] == [
        "OpenAI",
        "Codex",
    ]
    report = glossary_overlay.publish(workspace)
    assert report.published is True
    assert [term.source for term in glossarylib.load("series").terms] == [
        "OpenAI",
        "Codex",
    ]
    assert glossary_overlay.publish(workspace).published is True


def test_later_overlay_alias_patch_does_not_erase_an_existing_target(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    glossary_overlay.initialize(workspace, base_name=None)
    glossary_overlay.apply_updates(
        workspace,
        [
            agent_workflow.AgentGlossaryUpdate(
                source="Codex",
                target="Codex",
                keep=True,
                reusable=True,
                evidence="official name",
            )
        ],
    )
    glossary_overlay.apply_updates(
        workspace,
        [
            agent_workflow.AgentGlossaryUpdate(
                source="Codex",
                aliases=["codex"],
                reusable=True,
                evidence="case-only ASR form",
            )
        ],
    )

    effective = glossary_overlay.merged(workspace)
    assert effective is not None
    term = effective.terms[0]
    assert term.target == "Codex"
    assert term.keep is True
    assert term.aliases == ["codex"]


def test_overlay_alias_patch_does_not_erase_base_glossary_translation_after_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / "home"))
    glossarylib.save(
        Glossary(
            name="products",
            terms=[Term(source="Codex", target="Codex", keep=True)],
        )
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    glossary_overlay.initialize(workspace, base_name="products")
    glossary_overlay.apply_updates(
        workspace,
        [
            agent_workflow.AgentGlossaryUpdate(
                source="Codex",
                aliases=["codex"],
                reusable=True,
                evidence="case-only ASR variant",
            )
        ],
    )

    effective = glossary_overlay.merged(workspace, "products")
    assert effective is not None
    assert effective.terms[0].target == "Codex"
    assert effective.terms[0].keep is True
    assert effective.terms[0].aliases == ["codex"]


def test_glossary_publish_conflict_does_not_overwrite_global_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / "home"))
    glossarylib.save(
        Glossary(name="series", terms=[Term(source="Agent", target="智能体")])
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    glossary_overlay.initialize(workspace, base_name="series")
    glossary_overlay.apply_updates(
        workspace,
        [
            agent_workflow.AgentGlossaryUpdate(
                source="Agent",
                target="代理",
                reusable=True,
                evidence="video usage",
            )
        ],
    )

    report = glossary_overlay.publish(workspace)

    assert report.published is False
    assert report.warnings[0].code == "glossary_publish_conflict"
    assert glossarylib.load("series").terms[0].target == "智能体"


def test_glossary_publish_merges_safe_alias_while_preserving_existing_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / "home"))
    glossarylib.save(
        Glossary(
            name="series",
            terms=[Term(source="tmux", keep=True, note="Existing translation rule")],
        )
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    glossary_overlay.initialize(workspace, base_name="series")
    glossary_overlay.apply_updates(
        workspace,
        [
            agent_workflow.AgentGlossaryUpdate(
                source="tmux",
                aliases=["Tmux"],
                note="New observation from this video",
                reusable=True,
                evidence="ASR produced a case-only variant",
            )
        ],
    )

    report = glossary_overlay.publish(workspace)

    assert report.published is True
    term = glossarylib.load("series").terms[0]
    assert term.aliases == ["Tmux"]
    assert term.note == "Existing translation rule"


def test_glossary_publish_permission_failure_is_non_blocking_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / "home"))
    glossarylib.save(Glossary(name="series"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    glossary_overlay.initialize(workspace, base_name="series")
    glossary_overlay.apply_updates(
        workspace,
        [
            agent_workflow.AgentGlossaryUpdate(
                source="Codex",
                keep=True,
                reusable=True,
                evidence="official recurring product name",
            )
        ],
    )
    monkeypatch.setattr(
        glossarylib,
        "save",
        lambda _glossary: (_ for _ in ()).throw(PermissionError("read only")),
    )

    report = glossary_overlay.publish(workspace)

    assert report.published is False
    assert report.warnings[0].code == "glossary_publish_failed"
    assert report.warnings[0].retry_argv == [
        "openbbq",
        "agent",
        "finish",
        "--workspace",
        str(workspace),
    ]


def test_finish_is_media_idempotent_and_never_uses_compact_preset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, _ = _workspace(tmp_path, ["hello"])
    _review_all_sources(path)
    _install_cues_and_worksheet(path, ["hello"])
    translate = _next(path)
    _apply(
        path,
        {
            "batch_id": translate["batch_id"],
            "policy_hash": translate["policy_hash"],
            "translations": {"1": "你好"},
            "source_fixes": [],
            "glossary_updates": [],
        },
    )
    assert _next(path)["action"] == "finish"
    calls = {"export": 0, "burn": 0}
    presets: list[str] = []

    def fake_export(_ctx, **kwargs) -> None:
        calls["export"] += 1
        presets.append(kwargs["ass_preset"].value)
        # finish claims under the lock but must release it before media work.
        with ws.agent_workspace_lock(path):
            pass
        subtitle = path / "out" / "zh.ass"
        subtitle.parent.mkdir(parents=True, exist_ok=True)
        subtitle.write_text("bilingual ass", encoding="utf-8")
        ws.record_artifact_provenance(
            path,
            subtitle,
            Stage.EXPORT,
            inputs=[path / "cues.json", path / "translation.zh.json"],
        )
        ws.record_stage(
            path,
            ws.read_manifest(path),
            Stage.EXPORT,
            StageState(status=StageStatus.DONE, artifact="out/zh.ass"),
        )

    def fake_burn(_ctx, **_kwargs) -> None:
        calls["burn"] += 1
        video = path / "out" / "zh-burned.mp4"
        video.write_bytes(b"burned")
        ws.record_artifact_provenance(
            path,
            video,
            Stage.BURN,
            inputs=[
                Path(ws.read_manifest(path).source.ref),
                path / "out" / "zh.ass",
            ],
        )
        ws.record_stage(
            path,
            ws.read_manifest(path),
            Stage.BURN,
            StageState(status=StageStatus.DONE, artifact="out/zh-burned.mp4"),
        )

    monkeypatch.setattr("openbbq.cli.commands.agent.export_command", fake_export)
    monkeypatch.setattr("openbbq.cli.commands.agent.burn_command", fake_burn)
    monkeypatch.setattr(
        "openbbq.cli.commands.agent.assess_delivery",
        lambda *_args, **_kwargs: SimpleNamespace(ready=True, issues=[], next=None),
    )

    finish_command(_ctx(), workspace=str(path), to="zh")
    first = json.loads(capsys.readouterr().out)
    finish_command(_ctx(), workspace=str(path), to="zh")
    second = json.loads(capsys.readouterr().out)

    assert first["delivery_ready"] is True
    assert second["delivery_ready"] is True
    assert calls == {"export": 1, "burn": 1}
    assert presets == ["fansub"]


def test_balanced_delivery_accepts_agent_evidence_and_never_falls_back_when_stale(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, _ = _workspace(tmp_path, ["hello"])
    _review_all_sources(path)
    _install_cues_and_worksheet(path, ["hello"])
    translate = _next(path)
    _apply(
        path,
        {
            "batch_id": translate["batch_id"],
            "policy_hash": translate["policy_hash"],
            "translations": {"1": "你好"},
            "source_fixes": [],
            "glossary_updates": [],
        },
    )
    assert _next(path)["action"] == "finish"
    export_command(
        _ctx(),
        workspace=str(path),
        to="zh",
        mode=exportlib.ExportMode.BILINGUAL,
        fmt="ass",
        output="out/zh.ass",
        ass_preset=exportlib.AssPreset.FANSUB,
        allow_missing=False,
        allow_unreviewed=True,
        allow_quality_warnings=False,
    )
    capsys.readouterr()
    video = path / "out" / "zh-burned.mp4"
    video.write_bytes(b"burned")
    ws.record_artifact_provenance(
        path,
        video,
        Stage.BURN,
        inputs=[Path(ws.read_manifest(path).source.ref), path / "out" / "zh.ass"],
    )
    ws.record_stage(
        path,
        ws.read_manifest(path),
        Stage.BURN,
        StageState(status=StageStatus.DONE, artifact="out/zh-burned.mp4"),
    )

    ready = assess_delivery(path, ws.read_manifest(path), lang="zh")
    assert ready.ready is True
    assert ready.gates["translation_audit"] is True

    session = ws.read_agent_session_optional(path, "zh")
    assert session is not None
    session.translation_evidence[1].policy_hash = "stale"
    ws.write_agent_session(path, session)
    stale = assess_delivery(path, ws.read_manifest(path), lang="zh")
    assert stale.ready is False
    assert any(issue.code == "agent_session_stale" for issue in stale.issues)
    assert not any(issue.code == "translation_audit_incomplete" for issue in stale.issues)

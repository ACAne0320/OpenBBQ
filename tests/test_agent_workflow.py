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
from openbbq.cli.output import Output
from openbbq.core import agent_workflow
from openbbq.core import export as exportlib
from openbbq.core import glossary as glossarylib
from openbbq.core import glossary_overlay
from openbbq.core import review as reviewlib
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
    ReviewStatus,
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
    path, manifest = ws.init_workspace(str(video), workspace=str(tmp_path / "work"))
    session = agent_workflow.create_session(path, "zh")
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


def _write_overlay_updates(path: Path, updates: list[Any]) -> None:
    overlay, _ = glossary_overlay.prepare_updates(path, updates)
    glossary_overlay.write(path, overlay)


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
    ws.write_text_atomic(
        cues_path,
        cues.model_dump_json(indent=2, exclude_none=True),
    )
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


def _collapse_word_timestamps(path: Path) -> None:
    transcript = ws.read_transcript(path / "transcript.json")
    for segment in transcript.segments:
        assert segment.words is not None
        for word in segment.words:
            word.start = segment.end
            word.end = segment.end
    ws.write_text_atomic(path / "transcript.json", transcript.model_dump_json(indent=2))


def _translate_batch(
    path: Path,
    action: dict[str, Any],
    *,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return _apply(
        path,
        {
            "batch_id": action["batch_id"],
            "policy_hash": action["policy_hash"],
            "translations": {
                str(item_id): f"第{item_id}条译文" for item_id in action["selected_ids"]
            },
            "source_fixes": [],
            "glossary_updates": [],
            "warnings": warnings or [],
        },
    )


def test_ordinary_transcript_goes_directly_to_segment(tmp_path: Path) -> None:
    path, _ = _workspace(tmp_path, [f"ordinary source {index}" for index in range(21)])

    first = _next(path)
    repeated = _next(path)

    assert first == repeated
    assert first == {
        "action": "run_command",
        "argv": ["openbbq", "--json", "segment", "--workspace", str(path)],
        "reason": "build source cues once",
        "execution": {
            "sandbox": "inside_allowed",
            "accelerator": "none",
            "cpu_fallback": "not_applicable",
            "reason_code": "workspace_local_operation",
            "concurrency": "wait_and_reuse_completed_stage",
        },
        "terminal": False,
        "must_continue": True,
    }


def test_low_confidence_words_are_advisory_and_do_not_trigger_source_review(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, _ = _workspace(tmp_path, ["uncertain token"])
    transcript = ws.read_transcript(path / "transcript.json")
    assert transcript.segments[0].words is not None
    transcript.segments[0].words[0].prob = 0.1
    ws.write_text_atomic(path / "transcript.json", transcript.model_dump_json(indent=2))

    assert _next(path)["argv"][2] == "segment"
    segment_command(
        _ctx(),
        workspace=str(path),
        lang=None,
        glossary=None,
        max_cps=None,
        max_chars_per_line=None,
        max_lines=None,
        min_dur=None,
        max_dur=None,
        min_gap=None,
        pause_threshold=None,
    )
    result = json.loads(capsys.readouterr().out)
    assert result["asr_advisory_ids"]
    assert ws.read_manifest(path).stages[Stage.SEGMENT].status is StageStatus.DONE


def test_structural_source_review_lease_is_bounded_idempotent_and_strict(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, [f"damaged source {index}" for index in range(21)])
    _collapse_word_timestamps(path)

    first = _next(path)
    repeated = _next(path)

    assert first == repeated
    assert first["action"] == "review_source"
    assert 0 < len(first["selected_segment_ids"]) <= 20
    assert all(
        item["code"] == "collapsed_word_timestamps" for item in first["detector_issues"]
    )
    with pytest.raises(OpenBBQError) as id_error:
        _apply(
            path,
            {
                "batch_id": first["batch_id"],
                "reviewed_segment_ids": [],
                "issue_decisions": {},
                "source_fixes": [],
                "glossary_updates": [],
            },
        )
    assert id_error.value.code == "agent_id_set_mismatch"

    with pytest.raises(OpenBBQError) as issue_error:
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
    assert issue_error.value.code == "agent_issue_set_mismatch"

    result = _apply(
        path,
        {
            "batch_id": first["batch_id"],
            "reviewed_segment_ids": list(reversed(first["selected_segment_ids"])),
            "issue_decisions": {
                item["id"]: {
                    "action": "drop",
                    "reason": "collapsed timing cannot produce a safe cue",
                }
                for item in first["detector_issues"]
            },
            "source_fixes": [],
            "glossary_updates": [],
        },
    )
    assert result["reviewed_segments"] == len(first["selected_segment_ids"])
    second = _next(path)
    assert second["action"] == "review_source"
    assert 0 < len(second["selected_segment_ids"]) <= 20
    assert set(second["selected_segment_ids"]).isdisjoint(first["selected_segment_ids"])


def test_new_session_skips_glossary_selection_and_returns_mechanical_argv(
    tmp_path: Path,
) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    path, manifest = ws.init_workspace(str(video), workspace=str(tmp_path / "work"))
    session = agent_workflow.create_session(path, "zh")

    command = agent_workflow.next_action(path, manifest, session)

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
        "execution": {
            "sandbox": "inside_allowed",
            "accelerator": "none",
            "cpu_fallback": "not_applicable",
            "reason_code": "workspace_local_operation",
            "concurrency": "wait_and_reuse_completed_stage",
        },
        "terminal": False,
        "must_continue": True,
    }
    stored = ws.read_agent_session_optional(path, "zh")
    assert stored is not None
    sidecar = json.loads(ws.agent_session_path(path, "zh").read_text())
    assert sidecar["schema"] == "openbbq/agent-session@2"


def test_fetch_and_transcribe_commands_declare_host_execution_policy(
    tmp_path: Path,
) -> None:
    url_path, url_manifest = ws.init_workspace(
        "https://www.youtube.com/watch?v=test",
        workspace=str(tmp_path / "url-work"),
    )
    url_session = agent_workflow.create_session(url_path, "zh")

    fetch = agent_workflow.next_action(url_path, url_manifest, url_session)

    assert fetch["execution"] == {
        "sandbox": "outside_required",
        "accelerator": "none",
        "cpu_fallback": "not_applicable",
        "reason_code": "host_network_and_auth_state",
        "concurrency": "wait_and_reuse_completed_stage",
    }

    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    path, manifest = ws.init_workspace(
        str(video), workspace=str(tmp_path / "local-work")
    )
    agent_workflow.create_session(path, "zh")
    audio = path / "media" / "audio.16k.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")
    ws.record_stage(
        path,
        manifest,
        Stage.EXTRACT_AUDIO,
        StageState(status=StageStatus.DONE, artifact="media/audio.16k.wav"),
    )

    transcribe = _next(path)

    assert "--gpu" in transcribe["argv"]
    assert transcribe["execution"] == {
        "sandbox": "outside_required",
        "accelerator": "gpu",
        "cpu_fallback": "only_after_outside_gpu_failure",
        "reason_code": "native_gpu_and_model_cache",
        "concurrency": "wait_and_reuse_completed_stage",
    }


def test_fetched_url_auto_binds_a_stable_author_glossary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / ".openbbq-home"))
    path, manifest = ws.init_workspace(
        "https://www.youtube.com/watch?v=test",
        workspace=str(tmp_path / "work"),
    )
    session = agent_workflow.create_session(path, "zh")
    media_path = path / "media" / "source.mp4"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(b"video")
    manifest.source.author = "Example 创作者"
    ws.write_manifest(path, manifest)
    ws.record_stage(
        path,
        manifest,
        Stage.FETCH,
        StageState(status=StageStatus.DONE, artifact="media/source.mp4"),
    )

    action = agent_workflow.next_action(path, ws.read_manifest(path), session)

    assert action["argv"][2] == "extract-audio"
    assert ws.read_manifest(path).glossary is None
    overlay = glossary_overlay.read_optional(path)
    assert overlay is not None
    bound = overlay.base_name
    assert bound is not None
    assert bound.startswith("author-example-")
    assert "-zh-" in bound
    assert overlay.context is not None
    assert not glossarylib.glossary_path(bound).exists()
    effective = glossary_overlay.merged(path)
    assert effective is not None
    assert effective.name == bound


def test_author_glossaries_are_isolated_by_target_language(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / ".openbbq-home"))
    names: list[str] = []
    for target_lang in ("zh", "ja"):
        path, manifest = ws.init_workspace(
            "https://www.youtube.com/watch?v=test",
            workspace=str(tmp_path / target_lang),
        )
        session = agent_workflow.create_session(path, target_lang)
        media_path = path / "media" / "source.mp4"
        media_path.parent.mkdir(parents=True)
        media_path.write_bytes(b"video")
        manifest.source.author = "Example Creator"
        ws.write_manifest(path, manifest)
        ws.record_stage(
            path,
            manifest,
            Stage.FETCH,
            StageState(status=StageStatus.DONE, artifact="media/source.mp4"),
        )

        agent_workflow.next_action(path, ws.read_manifest(path), session)

        overlay = glossary_overlay.read_optional(path)
        assert overlay is not None
        assert overlay.base_name is not None
        names.append(overlay.base_name)

    assert names[0] != names[1]
    assert "-zh-" in names[0]
    assert "-ja-" in names[1]


def test_translation_v1_migrates_in_place_and_preserves_targets(tmp_path: Path) -> None:
    path, _ = _workspace(tmp_path, ["hello"])
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


def test_translate_exposes_only_local_reference_disagreement_and_matching_glossary(
    tmp_path: Path,
) -> None:
    source = (
        "improving your combo improving your accuracy improving your miscount "
        "adding mods to your scores"
    )
    reference = source.replace("miscount", "miss count")
    path, _ = _workspace(tmp_path, [source])
    _write_overlay_updates(
        path,
        [
            agent_workflow.AgentGlossaryUpdate(
                source="miss count",
                target="失误数",
                reusable=True,
                evidence="stable domain term",
            )
        ],
    )
    _install_cues_and_worksheet(path, [source])
    timed_words = "".join(
        f"<00:00:{index * 0.100:06.3f}><c> {word}</c>"
        for index, word in enumerate(reference.split(), start=1)
    )
    ws.write_reference_caption(
        path,
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n" + timed_words + "\n",
    )

    action = _next(path)

    assert action["action"] == "translate"
    assert action["items"][0]["reference_evidence"]["differences"] == [
        {"source": "miscount", "reference": "miss count"}
    ]
    assert action["reference_policy"]
    assert action["glossary"] == [
        {
            "source": "miss count",
            "target": "失误数",
            "aliases": [],
            "keep": False,
        }
    ]
    assert (
        "smallest exact source span"
        in action["response_schema"]["source_fixes"][0]["find"]
    )
    assert (
        "surrounding grammar"
        in action["response_schema"]["source_fixes"][0]["reusable"]
    )


def test_translate_requires_exact_ids_policy_and_syncs_cue_scoped_source_fix(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["codex is useful"])
    _install_cues_and_worksheet(path, ["codex is useful"])
    action = _next(path)
    assert action["action"] == "translate"
    assert len(action["selected_ids"]) <= 20
    assert action["response_schema"]["warnings"]

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
                    "reusable": True,
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

    finish = _next(path)
    assert finish["action"] == "finish"
    assert finish["quality"] == "draft"
    assert finish["human_reviewed"] is False
    assert _next(path) == finish


def test_cue_scoped_source_fix_allows_empty_replacement_to_delete_noise(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["*Pewds* welcome"])
    _install_cues_and_worksheet(path, ["*Pewds* welcome"])
    action = _next(path)

    _apply(
        path,
        {
            "batch_id": action["batch_id"],
            "policy_hash": action["policy_hash"],
            "translations": {"1": "欢迎"},
            "source_fixes": [
                {
                    "cue_id": 1,
                    "find": "*Pewds*",
                    "replacement": "",
                    "reusable": False,
                    "evidence": "the token is a non-speech subtitle artifact",
                }
            ],
            "glossary_updates": [],
        },
    )

    cues = ws.read_cues(path / "cues.json")
    worksheet = ws.read_translation(ws.worksheet_path(path, "zh"))
    assert "*Pewds*" not in cues.cues[0].source
    assert cues.cues[0].source.strip() == "welcome"
    assert worksheet.items[0].source == cues.cues[0].source
    assert _next(path)["action"] == "finish"


def test_source_fix_automatically_records_and_promotes_glossary_candidate(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["Usu is difficult"])
    _install_cues_and_worksheet(path, ["Usu is difficult"])
    action = _next(path)

    result = _apply(
        path,
        {
            "batch_id": action["batch_id"],
            "policy_hash": action["policy_hash"],
            "translations": {"1": "osu! 很难"},
            "source_fixes": [
                {
                    "cue_id": 1,
                    "find": "Usu",
                    "replacement": "osu!",
                    "reusable": True,
                    "evidence": "The title and neighboring discussion identify the game osu!.",
                }
            ],
            "glossary_updates": [],
        },
    )

    overlay = glossary_overlay.read_optional(path)
    assert overlay is not None
    assert result["glossary_candidates"] == 1
    assert [
        (item.source, item.alias, item.reusable) for item in overlay.candidates
    ] == [("osu!", "Usu", True)]
    assert [(entry.term.source, entry.term.aliases) for entry in overlay.entries] == [
        ("osu!", ["Usu"])
    ]


def test_glossary_update_does_not_require_a_same_batch_source_fix(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["code x works"])
    _install_cues_and_worksheet(path, ["code x works"])
    action = _next(path)

    result = _apply(
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
                    "evidence": "a reusable pronunciation observed in this video",
                }
            ],
        },
    )

    assert result["glossary_updates"] == 1
    assert result["alias_normalized_cues"] == 1
    effective = glossary_overlay.merged(path)
    assert effective is not None
    assert effective.terms[0].source == "Codex"
    assert effective.terms[0].aliases == ["code x"]
    cues = ws.read_cues(path / "cues.json")
    worksheet = ws.read_translation(ws.worksheet_path(path, "zh"))
    assert cues.cues[0].source == "Codex works"
    assert worksheet.items[0].source == "Codex works"
    assert worksheet.glossary[0].aliases == ["code x"]
    assert _next(path)["action"] == "finish"


def test_new_reusable_alias_normalizes_later_cues_without_retranslating_neighbor(
    tmp_path: Path,
) -> None:
    sources = [f"Fallon appears in scene {index}" for index in range(1, 22)]
    path, _ = _workspace(tmp_path, sources)
    _install_cues_and_worksheet(path, sources)
    first = _next(path)

    result = _apply(
        path,
        {
            "batch_id": first["batch_id"],
            "policy_hash": first["policy_hash"],
            "translations": {
                str(item_id): f"法琳出现在第 {item_id} 个场景"
                for item_id in first["selected_ids"]
            },
            "source_fixes": [],
            "glossary_updates": [
                {
                    "source": "Falin",
                    "aliases": ["Fallon"],
                    "target": "法琳",
                    "reusable": True,
                    "evidence": "the recurring character uses the canonical name Falin",
                }
            ],
        },
    )

    assert result["alias_normalized_cues"] == 21
    cues = ws.read_cues(path / "cues.json")
    assert all(cue.source.startswith("Falin ") for cue in cues.cues)
    stage = ws.read_manifest(path).stages[Stage.TRANSLATE]
    assert stage.status is StageStatus.RUNNING
    assert stage.progress is not None
    assert (stage.progress.done, stage.progress.total) == (20, 21)

    second = _next(path)
    assert second["selected_ids"] == [21]
    assert second["glossary"] == [
        {
            "source": "Falin",
            "target": "法琳",
            "aliases": ["Fallon"],
            "keep": False,
        }
    ]


def test_semantic_warnings_are_recorded_but_do_not_block_finish(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["Codex can do this"])
    _write_overlay_updates(
        path,
        [
            agent_workflow.AgentGlossaryUpdate(
                source="Codex",
                target="Codex",
                reusable=True,
                evidence="official product name",
            )
        ],
    )
    _install_cues_and_worksheet(path, ["Codex can do this"])
    action = _next(path)

    result = _apply(
        path,
        {
            "batch_id": action["batch_id"],
            "policy_hash": action["policy_hash"],
            "translations": {"1": "可以这样做"},
            "source_fixes": [],
            "glossary_updates": [],
            "warnings": ["The product name may be intentionally omitted."],
        },
    )

    assert result["warnings"] == 1
    assert result["mechanical_warnings"]["term_ids"] == [1]
    assert _next(path)["action"] == "finish"
    session = ws.read_agent_session_optional(path, "zh")
    assert session is not None
    assert session.warnings[0].code == "translation_advisory"


def test_human_review_blocks_retranslation_and_can_replace_agent_evidence(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["hello"])
    _install_cues_and_worksheet(path, ["hello"])
    worksheet_path = ws.worksheet_path(path, "zh")
    worksheet = ws.read_translation(worksheet_path)
    worksheet.items[0].target = "人工精修译文"
    ws.write_text_atomic(worksheet_path, worksheet.model_dump_json(indent=2))
    review = reviewlib.ReviewSession.open(path, "zh")

    with pytest.raises(OpenBBQError) as incomplete:
        _next(path)
    assert incomplete.value.code == "review_incomplete"
    assert ws.read_translation(worksheet_path).items[0].target == "人工精修译文"

    snapshot = review.snapshot()
    review.set_status(
        1,
        ReviewStatus.REVIEWED,
        base_revision=snapshot.revision,
        op_id="review-cue-1",
    )

    finish = _next(path)
    assert finish["action"] == "finish"
    assert finish["quality"] == "human-reviewed"
    assert finish["human_reviewed"] is True
    assert ws.read_translation(worksheet_path).items[0].target == "人工精修译文"
    session = ws.read_agent_session_optional(path, "zh")
    assert session is not None
    assert session.translation_evidence == {}


def test_starting_human_review_invalidates_an_active_finish_lease(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["hello"])
    _install_cues_and_worksheet(path, ["hello"])
    _translate_batch(path, _next(path))
    finish = _next(path)
    assert finish["action"] == "finish"

    reviewlib.ReviewSession.open(path, "zh")

    with pytest.raises(OpenBBQError) as incomplete:
        _next(path)
    assert incomplete.value.code == "review_incomplete"
    session = ws.read_agent_session_optional(path, "zh")
    assert session is not None
    assert session.active_lease is None


def test_agent_translation_batches_are_cli_enforced_to_20(tmp_path: Path) -> None:
    sources = [f"ordinary source {index}" for index in range(21)]
    path, _ = _workspace(tmp_path, sources)
    _install_cues_and_worksheet(path, sources)

    first = _next(path)
    assert first["selected_ids"] == list(range(1, 21))
    assert [item["id"] for item in first["items"]] == list(range(1, 21))
    assert first["neighbor_context"] == [{"id": 21, "source": "ordinary source 20"}]
    _translate_batch(path, first)

    second = _next(path)
    assert second["action"] == "translate"
    assert second["selected_ids"] == [21]
    assert second["neighbor_context"] == [
        {
            "id": 20,
            "source": "ordinary source 19",
            "target": "第20条译文",
        }
    ]


def test_translation_lease_becomes_stale_after_external_worksheet_change(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["hello"])
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


def test_upstream_transcript_change_invalidates_translation_lease_and_rebuilds_cues(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["hello"])
    _install_cues_and_worksheet(path, ["hello"])
    translate = _next(path)
    transcript = ws.read_transcript(path / "transcript.json")
    transcript.segments[0].text = "hello again"
    ws.write_text_atomic(path / "transcript.json", transcript.model_dump_json(indent=2))

    reopened = _next(path)

    assert translate["batch_id"] != reopened.get("batch_id")
    assert reopened["action"] == "run_command"
    assert reopened["argv"][2] == "segment"
    assert reopened["reason"] == "rebuild source cues because an input changed"


def test_cue_scoped_source_fix_rolls_back_all_documents_on_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, _ = _workspace(tmp_path, ["codex works"])
    _install_cues_and_worksheet(path, ["codex works"])
    action = _next(path)
    cues_path = path / "cues.json"
    worksheet_path = ws.worksheet_path(path, "zh")
    overlay_path = glossary_overlay.path(path)
    originals = {
        cues_path: cues_path.read_text(encoding="utf-8"),
        worksheet_path: worksheet_path.read_text(encoding="utf-8"),
        overlay_path: overlay_path.read_text(encoding="utf-8"),
    }
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
                        "reusable": True,
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

    for target, original in originals.items():
        assert target.read_text(encoding="utf-8") == original


def test_workspace_lock_prevents_concurrent_next_from_creating_two_batches(
    tmp_path: Path,
) -> None:
    path, _ = _workspace(tmp_path, ["hello"])
    _install_cues_and_worksheet(path, ["hello"])

    def call_next() -> str:
        with ws.agent_workspace_lock(path):
            session = ws.read_agent_session_optional(path, "zh")
            assert session is not None
            action = agent_workflow.next_action(path, ws.read_manifest(path), session)
            return str(action["batch_id"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        batch_ids = list(pool.map(lambda _value: call_next(), range(2)))

    assert batch_ids[0] == batch_ids[1]


def test_glossary_overlay_is_immediate_and_publishes_without_midtask_global_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / "home"))
    base = Glossary(
        name="series",
        context="AI tooling",
        terms=[Term(source="OpenAI", keep=True)],
    )
    glossarylib.save(base)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    glossary_overlay.initialize(workspace, base_name="series")

    _write_overlay_updates(
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
    assert [term.source for term in effective.terms] == ["OpenAI", "Codex"]
    assert glossary_overlay.publish(workspace).published is True
    assert [term.source for term in glossarylib.load("series").terms] == [
        "OpenAI",
        "Codex",
    ]
    assert glossary_overlay.publish(workspace).published is True


def test_later_overlay_alias_patch_preserves_an_existing_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    glossary_overlay.initialize(workspace, base_name=None)
    _write_overlay_updates(
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
    _write_overlay_updates(
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


def test_overlay_alias_patch_preserves_base_translation_after_reload(
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
    _write_overlay_updates(
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
    _write_overlay_updates(
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


def test_glossary_publish_merges_safe_alias_and_preserves_existing_note(
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
    _write_overlay_updates(
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
    _write_overlay_updates(
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
    _install_cues_and_worksheet(path, ["hello"])
    _translate_batch(path, _next(path))
    assert _next(path)["action"] == "finish"
    calls = {"export": 0, "burn": 0}
    presets: list[str] = []

    def fake_export(_ctx, **kwargs) -> None:
        calls["export"] += 1
        presets.append(kwargs["ass_preset"].value)
        with ws.agent_workspace_lock(path):
            pass
        subtitle = path / "out" / "zh.ass"
        subtitle.parent.mkdir(parents=True, exist_ok=True)
        subtitle.write_text(
            exportlib.render_ass(
                ws.read_cues(path / "cues.json"),
                exportlib.ExportMode.BILINGUAL,
                translation=ws.read_translation(path / "translation.zh.json"),
                preset=kwargs["ass_preset"],
                translation_lang="zh",
            ),
            encoding="utf-8",
        )
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
            inputs=[Path(ws.read_manifest(path).source.ref), path / "out" / "zh.ass"],
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

    assert first["artifact_ready"] is True
    assert first["quality"] == "draft"
    assert first["human_reviewed"] is False
    assert second["artifact_ready"] is True
    assert calls == {"export": 1, "burn": 1}
    assert presets == ["fansub"]
    translate_stage = ws.read_manifest(path).stages[Stage.TRANSLATE]
    assert translate_stage.status is StageStatus.DONE
    assert translate_stage.progress is not None
    assert (translate_stage.progress.done, translate_stage.progress.total) == (1, 1)


def test_finish_replaces_a_fresh_but_wrong_export_recipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, _ = _workspace(tmp_path, ["hello"])
    cues, _worksheet = _install_cues_and_worksheet(path, ["hello"])
    _translate_batch(path, _next(path))
    worksheet = ws.read_translation(path / "translation.zh.json")
    assert _next(path)["action"] == "finish"
    export_command(
        _ctx(),
        workspace=str(path),
        to=None,
        mode=exportlib.ExportMode.SOURCE,
        fmt="ass",
        output="out/zh.ass",
        ass_preset=exportlib.AssPreset.FANSUB,
        allow_missing=False,
        allow_unreviewed=True,
    )
    capsys.readouterr()

    def fake_burn(_ctx, **_kwargs) -> None:
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

    monkeypatch.setattr("openbbq.cli.commands.agent.burn_command", fake_burn)
    monkeypatch.setattr(
        "openbbq.cli.commands.agent.assess_delivery",
        lambda *_args, **_kwargs: SimpleNamespace(ready=True, issues=[], next=None),
    )

    finish_command(_ctx(), workspace=str(path), to="zh")

    actual = (path / "out" / "zh.ass").read_text(encoding="utf-8")
    expected = exportlib.render_ass(
        cues,
        exportlib.ExportMode.BILINGUAL,
        translation=worksheet,
        preset=exportlib.AssPreset.FANSUB,
        translation_lang="zh",
    )
    assert actual == expected

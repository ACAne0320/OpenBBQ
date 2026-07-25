from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer

from openbbq.cli.commands.translate import audit as audit_cmd
from openbbq.cli.commands.translate import audit_apply as audit_apply_cmd
from openbbq.cli.output import Output
from openbbq.core import segment as seg
from openbbq.core import translation_audit as auditlib
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    ASRInfo,
    Budget,
    Cue,
    Cues,
    Manifest,
    Segment,
    SegmentParams,
    Source,
    Stage,
    StageState,
    StageStatus,
    Transcript,
    Translation,
    TranslationAuditDecision,
    TranslationItem,
    Word,
)

ZH = seg.LANGUAGE_PROFILES["zh"]
PARAMS = SegmentParams(
    max_cps=ZH.max_cps,
    max_chars_per_line=ZH.max_chars_per_line,
    max_lines=ZH.max_lines,
    min_dur=ZH.min_dur,
    max_dur=ZH.max_dur,
    min_gap=ZH.min_gap,
    pause_threshold=ZH.pause_threshold,
)


def _item(id: int, source: str, target: str, *, max_chars: int = 32) -> TranslationItem:
    return TranslationItem(
        id=id,
        source=source,
        target=target,
        budget=Budget(max_chars=max_chars, seconds=3.0),
    )


def _documents(*items: TranslationItem) -> tuple[Cues, Translation]:
    cues = Cues(
        source_lang="en",
        params=PARAMS,
        cues=[
            Cue(id=item.id, start=(item.id - 1) * 3, end=item.id * 3, source=item.source)
            for item in items
        ],
    )
    worksheet = Translation(
        source_lang="en",
        target_lang="zh",
        params=PARAMS,
        items=list(items),
    )
    return cues, worksheet


def _ctx() -> typer.Context:
    return cast(typer.Context, SimpleNamespace(obj=Output(json_mode=True)))


def _workspace(tmp_path: Path, cues: Cues, worksheet: Translation) -> Path:
    path = tmp_path / "ws"
    path.mkdir()
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    (path / "cues.json").write_text(cues.model_dump_json(), encoding="utf-8")
    (path / "translation.zh.json").write_text(
        worksheet.model_dump_json(), encoding="utf-8"
    )
    ws.write_manifest(
        path,
        Manifest(
            created_at=datetime.now(timezone.utc),
            source=Source(type="local_audio", ref=str(source)),
            stages={
                Stage.SEGMENT: StageState(
                    status=StageStatus.DONE,
                    artifact="cues.json",
                ),
                Stage.TRANSLATE: StageState(
                    status=StageStatus.RUNNING,
                    artifact="translation.zh.json",
                ),
            },
        ),
    )
    return path


def test_risk_ranking_surfaces_real_failure_patterns() -> None:
    cues, worksheet = _documents(
        _item(1, "Garnt from Trash Taste went there too.", "Garnt也去过那里。"),
        _item(2, "If it worked out for them, why not me?", "如果ta能成功，为什么我不行？"),
        _item(
            3,
            "The idea made me love the craft of it.",
            "而这个想法让我爱上了这门口的传统技艺呀。",
            max_chars=20,
        ),
    )

    risks = auditlib.risk_items(cues, worksheet, None)
    by_id = {risk.id: set(risk.risk_codes) for risk in risks}

    assert "name_omission" in by_id[1]
    assert "target_extra_latin" in by_id[2]
    assert "shortened_translation" not in by_id.get(3, set())


def test_fitting_budget_alone_is_not_a_translation_risk() -> None:
    cues, worksheet = _documents(
        _item(1, "A concise and faithful line.", "一句简洁忠实的译文。", max_chars=10)
    )

    assert auditlib.risk_items(cues, worksheet, None) == []


def test_target_latin_allows_simple_source_singular_plural_variants() -> None:
    cues, worksheet = _documents(
        _item(1, "Agents can execute this task.", "Agent 可以执行这个任务。")
    )

    risks = auditlib.risk_items(cues, worksheet, None)

    assert all("target_extra_latin" not in item.risk_codes for item in risks)


def test_first_draft_extreme_shortening_is_a_risk_without_full_audit() -> None:
    cues, worksheet = _documents(
        _item(
            1,
            "This detailed procedure has several important conditions that users must always follow carefully.",
            "好的",
        )
    )

    risks = auditlib.risk_items(cues, worksheet, None)

    assert risks[0].id == 1
    assert "shortened_translation" in risks[0].risk_codes


def test_three_near_duplicate_targets_are_surfaced_as_translation_risks() -> None:
    cues, worksheet = _documents(
        _item(1, "Open the settings page now.", "现在打开设置页面。"),
        _item(2, "Restart the worker after saving.", "现在打开设置页。"),
        _item(3, "Verify the deployment status.", "请现在打开设置页面。"),
    )

    risks = auditlib.risk_items(cues, worksheet, None)

    assert {risk.id for risk in risks} == {1, 2, 3}
    assert all(
        "near_repeated_translation" in risk.risk_codes for risk in risks
    )


def test_suspicious_source_repetition_and_unknown_acronym_are_risks() -> None:
    cues, worksheet = _documents(
        _item(1, "It is stuck. stuck. again.", "它又卡住了。"),
        _item(2, "Run SSHN to connect.", "运行 SSHN 建立连接。"),
        _item(3, "Then wait to B before continuing.", "然后等待 B 再继续。"),
    )

    risks = auditlib.risk_items(cues, worksheet, None)
    by_id = {item.id: set(item.risk_codes) for item in risks}

    assert "source_repetition" in by_id[1]
    assert "source_token_anomaly" in by_id[2]
    assert "source_token_anomaly" in by_id[3]


def test_missing_technical_literal_is_a_translation_risk() -> None:
    cues, worksheet = _documents(
        _item(
            1,
            "Press Ctrl+K and rerun with --verbose.",
            "按下快捷键，然后以详细模式重新运行。",
        )
    )

    risks = auditlib.risk_items(cues, worksheet, None)

    assert risks[0].id == 1
    assert "technical_literal_omission" in risks[0].risk_codes


def test_full_coverage_adds_semantic_review_and_neighbor_context() -> None:
    cues, worksheet = _documents(
        _item(1, "This is not the first time.", "这不是第一次。"),
        _item(2, "Any human has asked this question.", "人类问过这个问题。"),
        _item(3, "There is a field called education.", "这个领域叫教育。"),
    )

    items = auditlib.audit_items(cues, worksheet, None, coverage="all")

    assert [item.id for item in items] == [1, 2, 3]
    middle = items[1]
    assert middle.risk_codes == ("semantic_review",)
    assert middle.previous is not None
    assert middle.previous.source == "This is not the first time."
    assert middle.next is not None
    assert middle.next.target == "这个领域叫教育。"


def test_neighbor_change_invalidates_context_bound_semantic_review() -> None:
    cues, worksheet = _documents(
        _item(1, "Before.", "前文。"),
        _item(2, "Locally, I can ask the team.", "我可以在本地询问团队。"),
        _item(3, "After.", "后文。"),
    )
    items = auditlib.audit_items(cues, worksheet, None, coverage="all")
    report = auditlib.apply_decisions(
        cues,
        worksheet,
        None,
        items,
        {
            1: TranslationAuditDecision(action="accept", reason="Meaning preserved."),
            2: TranslationAuditDecision(action="accept", reason="Meaning preserved."),
            3: TranslationAuditDecision(action="accept", reason="Meaning preserved."),
        },
        coverage="all",
    )

    assert auditlib.pending_items(
        items, worksheet, report.audit, require_context=True
    ) == []

    worksheet.items[0].target = "修改后的前文。"
    updated = auditlib.audit_items(cues, worksheet, report.audit, coverage="all")
    pending = auditlib.pending_items(
        updated, worksheet, report.audit, require_context=True
    )

    assert [item.id for item in pending] == [1, 2]


def test_name_omission_ignores_fully_localized_place_names() -> None:
    cues, worksheet = _documents(
        _item(1, "We stayed in China for two weeks.", "我们在中国待了两周。"),
        _item(
            2,
            "We went to Universal Beijing.",
            "我们去了北京环球影城。",
        ),
    )

    assert auditlib.risk_items(cues, worksheet, None) == []


def test_mid_confidence_proper_name_marks_overlapping_cue_uncertain() -> None:
    cues, _ = _documents(_item(1, "I saw one person, Mew.", "我看到Mew这个人。"))
    transcript = Transcript(
        language="en",
        duration=3,
        asr=ASRInfo(
            backend="test", model="test", created_at=datetime.now(timezone.utc)
        ),
        segments=[
            Segment(
                id=0,
                start=0,
                end=2,
                text="I saw one person, Mew.",
                words=[
                    Word(word="I", start=0, end=0.2, prob=0.99),
                    Word(word="saw", start=0.2, end=0.4, prob=0.99),
                    Word(word="one", start=0.4, end=0.6, prob=0.99),
                    Word(word="person,", start=0.6, end=0.9, prob=0.99),
                    Word(word="Mew.", start=0.9, end=1.2, prob=0.72),
                ],
            )
        ],
    )

    assert auditlib.uncertain_cue_ids(cues, transcript) == {1}


def test_over_budget_shortening_is_preserved_as_audit_risk() -> None:
    _, before = _documents(
        _item(1, "A detailed source list.", "这是一个非常非常长的完整译文。", max_chars=8)
    )
    after = before.model_copy(deep=True)
    after.items[0].target = "短译文"

    audit = auditlib.record_overwrites(before, after, None)
    flag = audit.flags[1]

    assert set(flag.codes) == {"budget_rewrite", "shortened_translation"}
    assert flag.content_hash == auditlib.item_hash(after.items[0])


def test_review_is_tied_to_current_cue_content() -> None:
    cues, worksheet = _documents(
        _item(1, "Garnt from Trash Taste went there too.", "Garnt也去过那里。")
    )
    risks = auditlib.risk_items(cues, worksheet, None)
    report = auditlib.apply_decisions(
        cues,
        worksheet,
        None,
        risks,
        {
            1: TranslationAuditDecision(
                action="accept",
                reason="The omitted show name is visible immediately before this cue.",
            )
        },
    )

    assert auditlib.is_reviewed(worksheet.items[0], report.audit) is True
    worksheet.items[0].target = "Garnt也去过。"
    assert auditlib.is_reviewed(worksheet.items[0], report.audit) is False


def test_revision_is_applied_and_reviewed_at_new_content_hash() -> None:
    cues, worksheet = _documents(
        _item(1, "If it worked out for them, why not me?", "如果ta能成功，为什么我不行？")
    )
    risks = auditlib.risk_items(cues, worksheet, None)
    report = auditlib.apply_decisions(
        cues,
        worksheet,
        None,
        risks,
        {
            1: TranslationAuditDecision(
                action="revise",
                target="如果对方能成功，为什么我不行？",
                reason="Replace unlocalized pinyin with natural Chinese.",
            )
        },
    )

    assert worksheet.items[0].target == "如果对方能成功，为什么我不行？"
    assert report.revised == 1
    assert auditlib.is_reviewed(worksheet.items[0], report.audit) is True


def test_invalid_revision_does_not_mutate_worksheet() -> None:
    cues, worksheet = _documents(
        _item(1, "If it worked out for them, why not me?", "如果ta能成功，为什么我不行？")
    )
    risks = auditlib.risk_items(cues, worksheet, None)
    original = worksheet.model_dump_json()

    with pytest.raises(OpenBBQError) as raised:
        auditlib.apply_decisions(
            cues,
            worksheet,
            None,
            risks,
            {
                1: TranslationAuditDecision(
                    action="revise",
                    target="If it worked out for them, why not me?",
                    reason="Invalid source-copy revision used to test rollback.",
                )
            },
        )

    assert raised.value.code == "translation_audit_revision_invalid"
    assert worksheet.model_dump_json() == original


def test_translation_audit_rejects_unbounded_bulk_decisions() -> None:
    cues, worksheet = _documents(
        *[
            _item(index, f"Source cue {index}.", f"译文{index}")
            for index in range(1, 22)
        ]
    )
    items = auditlib.audit_items(cues, worksheet, None, coverage="all")

    with pytest.raises(OpenBBQError) as raised:
        auditlib.apply_decisions(
            cues,
            worksheet,
            None,
            items,
            {
                item.id: TranslationAuditDecision(
                    action="accept",
                    reason=f"Cue {item.id} preserves the source meaning in context.",
                )
                for item in items
            },
            coverage="all",
        )

    assert raised.value.code == "translation_audit_batch_too_large"


def test_cli_audit_is_bounded_and_revision_clears_pending_risk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cues, worksheet = _documents(
        _item(1, "If it worked out for them, why not me?", "如果ta能成功，为什么我不行？")
    )
    path = _workspace(tmp_path, cues, worksheet)

    audit_cmd(_ctx(), lang="zh", workspace=str(path), offset=0, limit=1)
    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_ids"] == [1]
    assert payload["pending"] == 1
    assert payload["ready"] is False

    decisions = tmp_path / "audit.json"
    decisions.write_text(
        json.dumps(
            {
                "1": {
                    "action": "revise",
                    "target": "如果对方能成功，为什么我不行？",
                    "reason": "Use natural Chinese instead of unlocalized pinyin.",
                }
            }
        ),
        encoding="utf-8",
    )
    audit_apply_cmd(
        _ctx(), lang="zh", decisions=str(decisions), workspace=str(path)
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["revised"] == 1
    assert payload["pending"] == 0
    assert payload["ready"] is True
    assert ws.read_translation(path / "translation.zh.json").items[0].target == (
        "如果对方能成功，为什么我不行？"
    )

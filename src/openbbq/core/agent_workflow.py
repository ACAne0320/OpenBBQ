"""Authoritative single-next agent workflow.

Mechanical work is returned as exact argv.  Semantic work is leased in bounded,
persistent batches and can only be committed by ``apply_response``.  This keeps
model judgement outside OpenBBQ while making ordering, coverage, staleness and
write integrity deterministic across harnesses.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from openbbq.core import asr_review as asrlib
from openbbq.core import glossary as glossarylib
from openbbq.core import glossary_overlay
from openbbq.core import translate as translatelib
from openbbq.core import translation_audit as auditlib
from openbbq.core import translation_rules
from openbbq.core import workspace as ws
from openbbq.errors import OpenBBQError
from openbbq.schemas import (
    AgentCueSourceFix,
    AgentFinished,
    AgentGlossaryUpdate,
    AgentLease,
    AgentSession,
    AgentSourceFix,
    AsrDecision,
    Cues,
    GlossaryRef,
    Manifest,
    OpenBBQModel,
    RiskReviewEvidence,
    SourceReviewEvidence,
    Stage,
    StageStatus,
    Translation,
    TranslationAuditDecision,
    TranslationEvidence,
    TranslationItem,
)

MAX_SEMANTIC_BATCH = 20
_SOURCE_POLICY = "contextual-source-review@2"


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_json(value: Any) -> str:
    return _hash_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _model_hash(value: OpenBBQModel) -> str:
    return _hash_json(value.model_dump(mode="json", exclude_none=False))


def create_session(
    workspace: Path,
    target_lang: str,
    *,
    glossary_name: str | None = None,
    glossary_selected: bool = False,
) -> AgentSession:
    target_lang = ws.validate_lang(target_lang)
    if ws.read_agent_session_optional(workspace, target_lang) is not None:
        raise OpenBBQError(
            "agent_session_exists",
            lang=target_lang,
            fix=f"continue with openbbq agent next --workspace {workspace}",
        )
    session = AgentSession(
        target_lang=target_lang,
        glossary_selected=glossary_selected,
        glossary_name=glossary_name,
    )
    if glossary_selected:
        glossary_overlay.initialize(workspace, base_name=glossary_name)
    ws.write_agent_session(workspace, session)
    return session


def session_languages(workspace: Path) -> list[str]:
    root = workspace / ".openbbq"
    if not root.is_dir():
        return []
    prefix = "agent-session."
    suffix = ".json"
    return sorted(
        item.name[len(prefix) : -len(suffix)]
        for item in root.glob("agent-session.*.json")
    )


def resolve_session_lang(workspace: Path, explicit: str | None = None) -> str:
    if explicit is not None:
        return ws.validate_lang(explicit)
    available = session_languages(workspace)
    if not available:
        raise OpenBBQError(
            "agent_session_not_found",
            fix="start with openbbq agent init <source> --to zh",
        )
    if len(available) != 1:
        raise OpenBBQError(
            "ambiguous_lang",
            langs=available,
            fix="pass --to <lang>",
        )
    return ws.validate_lang(available[0])


def _workspace_argv(workspace: Path, *parts: str) -> list[str]:
    return ["openbbq", "--json", *parts, "--workspace", str(workspace)]


def _run_command(workspace: Path, reason: str, *parts: str) -> dict[str, Any]:
    return {
        "action": "run_command",
        "argv": _workspace_argv(workspace, *parts),
        "reason": reason,
    }


def _stage_done(workspace: Path, manifest: Manifest, stage: Stage) -> bool:
    state = manifest.stages.get(stage)
    if state is None or state.status is not StageStatus.DONE or not state.artifact:
        return False
    artifact = Path(state.artifact)
    if not artifact.is_absolute():
        artifact = workspace / artifact
    return artifact.is_file()


def _reference_texts(manifest: Manifest) -> list[str]:
    if manifest.source.type != "url":
        return []
    return [text for text in (manifest.source.title, manifest.source.author) if text]


def _transcript_context(workspace: Path, manifest: Manifest):
    path = ws.require_artifact(
        workspace,
        manifest,
        Stage.TRANSCRIBE,
        fix="openbbq transcribe",
    )
    transcript = ws.read_transcript(path)
    review = ws.read_asr_review_optional(workspace)
    caption_source = ws.read_reference_caption_optional(workspace)
    reference_words = (
        asrlib.parse_reference_words(caption_source)
        if caption_source is not None
        else []
    )
    return transcript, review, _reference_texts(manifest), reference_words


@dataclass(frozen=True)
class _SourceView:
    id: int
    start: float
    end: float
    raw: str
    after_asr: str
    after_glossary: str
    dropped: bool
    word_count: int
    words: list[dict[str, Any]]

    @property
    def words_omitted(self) -> int:
        return self.word_count - len(self.words)

    @property
    def evidence_hash(self) -> str:
        # Glossary entries learned during translation are intended for future
        # tasks and must not rewind the source-review state machine.  ASR review
        # corrections are the source evidence; segmentation applies the final
        # overlay once after this review is complete.
        return _hash_json(
            {
                "id": self.id,
                "start": self.start,
                "end": self.end,
                "after_asr": self.after_asr,
                "dropped": self.dropped,
                "policy": _SOURCE_POLICY,
            }
        )


def _source_views(
    workspace: Path,
    manifest: Manifest,
) -> tuple[list[_SourceView], Any, Any, list[str], list[Any]]:
    transcript, review, reference_texts, reference_words = _transcript_context(
        workspace, manifest
    )
    resolved = asrlib.resolved_transcript(
        transcript,
        review,
        reference_texts=reference_texts,
        reference_words=reference_words,
    )
    by_id = {segment.id: segment for segment in resolved.segments}
    effective_glossary = glossary_overlay.merged(workspace, manifest.glossary)
    correct = glossarylib.corrector(effective_glossary)
    views: list[_SourceView] = []
    for raw in transcript.segments:
        active = by_id.get(raw.id)
        after_asr = "" if active is None else active.text
        active_words = list(active.words or []) if active is not None else []
        attention_words = [
            (index, word)
            for index, word in enumerate(active_words)
            if (word.prob is not None and word.prob < 0.8)
            or word.end <= word.start + 1e-6
            or word.start < raw.start - 0.01
            or word.end > raw.end + 0.01
        ]
        views.append(
            _SourceView(
                id=raw.id,
                start=raw.start,
                end=raw.end,
                raw=raw.text,
                after_asr=after_asr,
                after_glossary=correct(after_asr),
                dropped=active is None,
                word_count=len(active_words),
                words=[
                    {
                        "index": index,
                        "word": word.word,
                        "start": word.start,
                        "end": word.end,
                        "prob": word.prob,
                    }
                    for index, word in attention_words
                ],
            )
        )
    return views, transcript, review, reference_texts, reference_words


def _source_state_hash(workspace: Path, manifest: Manifest) -> str:
    views, transcript, review, reference_texts, reference_words = _source_views(
        workspace, manifest
    )
    report = asrlib.check(
        transcript,
        review,
        reference_texts=reference_texts,
        reference_words=reference_words,
    )
    return _hash_json(
        {
            "transcript": report.transcript_hash,
            "review": None if review is None else _model_hash(review),
            "segments": [view.evidence_hash for view in views],
            "unresolved": report.unresolved_ids,
            "reference_words": _hash_json(
                [word.model_dump(mode="json") for word in reference_words]
            ),
            "policy": _SOURCE_POLICY,
        }
    )


def _issue_segment_ids(issue: Any) -> list[int]:
    if hasattr(issue, "segment_id"):
        return [int(issue.segment_id)]
    return [int(value) for value in issue.segment_ids]


def _issue_payload(issue: Any) -> dict[str, Any]:
    if hasattr(issue, "word_index"):
        return {
            "id": issue.id,
            "kind": "word",
            "segment_id": issue.segment_id,
            "word_index": issue.word_index,
            "word": issue.word,
            "prob": issue.prob,
            "start": issue.start,
            "end": issue.end,
            "segment": issue.segment_text,
            "context": [
                {"index": word.index, "word": word.word, "prob": word.prob}
                for word in issue.context
            ],
        }
    return {
        "id": issue.id,
        "kind": "anomaly",
        "segment_ids": list(issue.segment_ids),
        "start": issue.start,
        "end": issue.end,
        "segment": issue.text,
        "code": issue.code,
        "severity": issue.severity,
        "previous": issue.previous_text,
        "next": issue.next_text,
        "find": issue.find,
        "replacement": issue.replacement,
        "reference_text": issue.reference_text,
        "allowed_actions": (
            ["replace", "drop"]
            if issue.code
            in {"collapsed_word_timestamps", "reference_timeline_mismatch"}
            else ["accept", "replace", "drop", "keep_first"]
        ),
    }


def _relevant_glossary_payload(
    workspace: Path,
    manifest: Manifest,
    texts: list[str],
) -> dict[str, Any]:
    glossary = glossary_overlay.merged(workspace, manifest.glossary)
    if glossary is None:
        return {"name": None, "context": None, "terms": []}
    terms = [
        term.model_dump(mode="json", exclude_none=True)
        for term in glossary.terms
        if any(
            glossarylib.contains_term(text, form)
            for text in texts
            for form in (term.source, *term.aliases)
        )
    ]
    return {"name": glossary.name, "context": glossary.context, "terms": terms}


def _reference_caption_for(
    workspace: Path,
    *,
    start: float,
    end: float,
) -> str | None:
    raw = ws.read_reference_caption_optional(workspace)
    if raw is None:
        return None
    captions = asrlib.parse_reference_captions(raw)
    return asrlib.reference_caption_text(captions, start=start, end=end)


def _glossary_options() -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for name in glossarylib.list_names():
        try:
            glossary = glossarylib.load(name)
        except OpenBBQError:
            options.append({"name": name, "valid": False})
        else:
            options.append(
                {
                    "name": name,
                    "valid": True,
                    "context": glossary.context,
                    "terms": len(glossary.terms),
                    "hash": glossary_overlay.glossary_hash(glossary),
                }
            )
    return options


def _selection_hash(manifest: Manifest) -> str:
    return _hash_json(
        {
            "source": manifest.source.model_dump(mode="json"),
            "available": _glossary_options(),
        }
    )


def _new_lease(
    session: AgentSession,
    *,
    action: Literal[
        "select_glossary", "review_source", "translate", "review_risks", "finish"
    ],
    selected_ids: list[int],
    issue_ids: list[str],
    source_hash: str,
    worksheet_hash: str | None,
    policy_hash: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    batch_id = str(uuid.uuid4())
    payload = {**payload, "action": action, "batch_id": batch_id}
    session.active_lease = AgentLease(
        action=action,
        batch_id=batch_id,
        selected_ids=selected_ids,
        issue_ids=issue_ids,
        source_hash=source_hash,
        worksheet_hash=worksheet_hash,
        policy_hash=policy_hash,
        payload=payload,
    )
    return payload


def _brief_for(worksheet: Translation, manifest: Manifest, workspace: Path):
    if worksheet.brief is not None:
        return worksheet.brief
    glossary = glossary_overlay.merged(workspace, manifest.glossary)
    return translation_rules.build_brief(
        worksheet.source_lang,
        worksheet.target_lang,
        title=manifest.source.title,
        author=manifest.source.author,
        glossary_context=None if glossary is None else glossary.context,
    )


def _worksheet_glossary(glossary) -> list[GlossaryRef]:
    if glossary is None:
        return []
    return [
        GlossaryRef(
            source=term.source,
            target=term.target,
            note=term.note,
            keep=term.keep,
        )
        for term in glossary.terms
    ]


def _ensure_translation_v2(
    workspace: Path,
    manifest: Manifest,
    worksheet: Translation,
) -> Translation:
    if worksheet.schema_ == "openbbq/translation@2":
        return worksheet
    glossary = glossary_overlay.merged(workspace, manifest.glossary)
    brief = translation_rules.build_brief(
        worksheet.source_lang,
        worksheet.target_lang,
        title=manifest.source.title,
        author=manifest.source.author,
        glossary_context=None if glossary is None else glossary.context,
    )
    migrated = worksheet.model_copy(
        update={
            "schema_": "openbbq/translation@2",
            "brief": brief,
            "glossary": _worksheet_glossary(glossary),
        }
    )
    migrated = Translation.model_validate(migrated.model_dump(by_alias=True))
    ws.write_text_atomic(
        ws.worksheet_path(workspace, worksheet.target_lang),
        migrated.model_dump_json(indent=2) + "\n",
    )
    return migrated


def _cue_glossary_refs(worksheet: Translation, cue_id: int) -> list[GlossaryRef]:
    indexes = {item.id: index for index, item in enumerate(worksheet.items)}
    index = indexes[cue_id]
    low = max(index - 1, 0)
    high = min(index + 2, len(worksheet.items))
    texts = [item.source for item in worksheet.items[low:high]]
    return [
        ref
        for ref in worksheet.glossary
        if any(glossarylib.contains_term(text, ref.source) for text in texts)
    ]


def _glossary_refs_hash(refs: list[GlossaryRef]) -> str:
    return _hash_json(
        [ref.model_dump(mode="json", exclude_none=False) for ref in refs]
    )


def _translation_evidence_valid(
    session: AgentSession,
    worksheet: Translation,
    item: TranslationItem,
    policy_hash: str,
) -> bool:
    evidence = session.translation_evidence.get(item.id)
    return (
        evidence is not None
        and translatelib.is_filled(item.target)
        and evidence.cue_hash == auditlib.item_hash(item)
        and evidence.source_hash == _hash_text(item.source)
        and evidence.target_hash == _hash_text(item.target or "")
        and evidence.policy_hash == policy_hash
        and evidence.glossary_hash
        == _glossary_refs_hash(_cue_glossary_refs(worksheet, item.id))
    )


def _translation_state_hash(
    workspace: Path,
    manifest: Manifest,
    cues: Cues,
    worksheet: Translation,
    policy_hash: str,
) -> str:
    return _hash_json(
        {
            "cues": cues.model_dump(mode="json", exclude_none=False),
            "worksheet": worksheet.model_dump(mode="json", exclude_none=False),
            "policy_hash": policy_hash,
            "source_state_hash": _source_state_hash(workspace, manifest),
        }
    )


def _translation_batch_payload(
    worksheet: Translation,
    selected_ids: list[int],
) -> tuple[list[dict[str, Any]], list[GlossaryRef]]:
    indexes = {item.id: index for index, item in enumerate(worksheet.items)}
    selected_indexes = {indexes[item_id] for item_id in selected_ids}
    included: set[int] = set()
    for index in selected_indexes:
        included.update(
            range(max(0, index - 1), min(len(worksheet.items), index + 2))
        )
    items = [
        {
            "id": worksheet.items[index].id,
            "source": worksheet.items[index].source,
            "target": worksheet.items[index].target,
            "budget": worksheet.items[index].budget.model_dump(mode="json"),
            "selected": index in selected_indexes,
        }
        for index in sorted(included)
    ]
    texts = [worksheet.items[index].source for index in sorted(included)]
    refs = [
        ref
        for ref in worksheet.glossary
        if any(glossarylib.contains_term(text, ref.source) for text in texts)
    ]
    return items, refs


def _risk_items(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
    cues: Cues,
    worksheet: Translation,
) -> list[auditlib.RiskItem]:
    audit = ws.read_translation_audit_optional(workspace, worksheet.target_lang)
    base = auditlib.audit_items(
        cues,
        worksheet,
        audit,
        # Balanced source review already covers every transcript segment and
        # resolves detector issues. Replaying raw ASR confidence here creates a
        # second, lower-value review of accepted evidence.
        uncertain_ids=set(),
        coverage="risks",
    )
    by_id = {item.id: item for item in base}
    report = translatelib.check(cues, worksheet, worksheet.target_lang)
    additions: dict[int, set[str]] = {}
    for cue_id in report.over_budget:
        additions.setdefault(cue_id, set()).add("over_budget")
    for cue_id in report.zero_budget:
        additions.setdefault(cue_id, set()).add("zero_budget")
    for issue in report.term_issues:
        additions.setdefault(issue.id, set()).add("glossary_inconsistent")
    for cue_id in session.source_fixed_cue_ids:
        additions.setdefault(cue_id, set()).add("source_changed")
    indexes = {item.id: index for index, item in enumerate(worksheet.items)}
    weights = {
        "zero_budget": 120,
        "source_changed": 110,
        "glossary_inconsistent": 105,
        "over_budget": 90,
    }
    for cue_id, codes in additions.items():
        item = next((value for value in worksheet.items if value.id == cue_id), None)
        if item is None or not translatelib.is_filled(item.target):
            continue
        existing = by_id.get(cue_id)
        index = indexes[cue_id]
        combined = set(existing.risk_codes if existing is not None else ()) | codes
        by_id[cue_id] = auditlib.RiskItem(
            id=cue_id,
            source=item.source,
            target=item.target or "",
            used_chars=translatelib.count_target_chars(worksheet, item.target or ""),
            max_chars=item.budget.max_chars,
            risk_codes=tuple(sorted(combined)),
            score=(existing.score if existing is not None else 0)
            + sum(weights.get(code, 0) for code in codes),
            previous=(
                auditlib.AuditContext(
                    id=worksheet.items[index - 1].id,
                    source=worksheet.items[index - 1].source,
                    target=worksheet.items[index - 1].target or "",
                )
                if index > 0
                else None
            ),
            next=(
                auditlib.AuditContext(
                    id=worksheet.items[index + 1].id,
                    source=worksheet.items[index + 1].source,
                    target=worksheet.items[index + 1].target or "",
                )
                if index + 1 < len(worksheet.items)
                else None
            ),
        )
    return sorted(by_id.values(), key=lambda item: (-item.score, item.id))


def _risk_evidence_valid(
    session: AgentSession,
    item: TranslationItem,
    policy_hash: str,
) -> bool:
    evidence = session.risk_reviews.get(item.id)
    return (
        evidence is not None
        and evidence.item_hash == auditlib.item_hash(item)
        and evidence.policy_hash == policy_hash
    )


@dataclass(frozen=True)
class BalancedGate:
    ready: bool
    problems: tuple[str, ...]
    pending_risk_ids: tuple[int, ...]


@dataclass(frozen=True)
class SourceReviewGate:
    ready: bool
    pending_segment_ids: tuple[int, ...]
    unresolved_issue_ids: tuple[str, ...]


def source_review_gate(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
) -> SourceReviewGate:
    views, transcript, review, reference_texts, reference_words = _source_views(
        workspace, manifest
    )
    report = asrlib.check(
        transcript,
        review,
        reference_texts=reference_texts,
        reference_words=reference_words,
    )
    pending = tuple(
        view.id
        for view in views
        if session.source_reviews.get(view.id) is None
        or session.source_reviews[view.id].segment_hash != view.evidence_hash
    )
    unresolved = tuple(report.unresolved_ids)
    return SourceReviewGate(
        ready=not pending and report.ready,
        pending_segment_ids=pending,
        unresolved_issue_ids=unresolved,
    )


def balanced_gate(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
    cues: Cues,
    worksheet: Translation,
) -> BalancedGate:
    problems: list[str] = []
    if session.mode != "balanced":
        problems.append("agent session is not balanced")
    try:
        cues_path = ws.require_artifact(
            workspace,
            manifest,
            Stage.SEGMENT,
            fix="openbbq segment",
        )
        ws.require_fresh_artifact(workspace, cues_path, Stage.SEGMENT)
    except OpenBBQError as error:
        problems.append(f"segmented source is missing or stale: {error.code}")
    try:
        views, transcript, review, reference_texts, reference_words = _source_views(
            workspace, manifest
        )
        asr = asrlib.check(
            transcript,
            review,
            reference_texts=reference_texts,
            reference_words=reference_words,
        )
    except OpenBBQError as error:
        problems.append(f"source review unavailable: {error.code}")
        views = []
        asr = None
    if asr is not None and not asr.ready:
        problems.append("ASR detector issues are unresolved")
    stale_segments = [
        view.id
        for view in views
        if session.source_reviews.get(view.id) is None
        or session.source_reviews[view.id].segment_hash != view.evidence_hash
    ]
    if stale_segments:
        problems.append(f"source review missing or stale: {stale_segments[:20]}")

    brief = _brief_for(worksheet, manifest, workspace)
    policy = translation_rules.policy_hash(brief)
    invalid_translation = [
        item.id
        for item in worksheet.items
        if not _translation_evidence_valid(session, worksheet, item, policy)
    ]
    if invalid_translation:
        problems.append(
            f"translation evidence missing or stale: {invalid_translation[:20]}"
        )
    risks = _risk_items(workspace, manifest, session, cues, worksheet)
    by_id = {item.id: item for item in worksheet.items}
    pending_risks = [
        risk.id
        for risk in risks
        if not _risk_evidence_valid(session, by_id[risk.id], policy)
    ]
    if pending_risks:
        problems.append(f"risk review missing or stale: {pending_risks[:20]}")
    return BalancedGate(
        ready=not problems,
        problems=tuple(problems),
        pending_risk_ids=tuple(pending_risks),
    )


def semantic_inputs_hash(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
    cues: Cues,
    worksheet: Translation,
) -> str:
    brief = _brief_for(worksheet, manifest, workspace)
    return _hash_json(
        {
            "cues": cues.model_dump(mode="json", exclude_none=False),
            "worksheet": worksheet.model_dump(mode="json", exclude_none=False),
            "source_reviews": {
                key: value.model_dump(mode="json")
                for key, value in session.source_reviews.items()
            },
            "translation_evidence": {
                key: value.model_dump(mode="json")
                for key, value in session.translation_evidence.items()
            },
            "risk_reviews": {
                key: value.model_dump(mode="json")
                for key, value in session.risk_reviews.items()
            },
            "policy_hash": translation_rules.policy_hash(brief),
            "source_state_hash": _source_state_hash(workspace, manifest),
        }
    )


def _finished_is_fresh(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
    cues: Cues,
    worksheet: Translation,
) -> bool:
    finished = session.finished
    if finished is None:
        return False
    if finished.inputs_hash != semantic_inputs_hash(
        workspace, manifest, session, cues, worksheet
    ):
        return False
    subtitle = workspace / finished.subtitle
    video = workspace / finished.video
    try:
        ws.require_fresh_artifact(workspace, subtitle, Stage.EXPORT)
        ws.require_fresh_artifact(workspace, video, Stage.BURN)
    except OpenBBQError:
        return False
    return True


def active_lease_fresh(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
) -> bool:
    lease = session.active_lease
    if lease is None:
        return False
    if lease.action == "select_glossary":
        return lease.source_hash == _selection_hash(manifest)
    if lease.action == "review_source":
        try:
            return lease.source_hash == _source_state_hash(workspace, manifest)
        except OpenBBQError:
            return False
    if lease.action in {"translate", "review_risks", "finish"}:
        try:
            cues_path = ws.require_artifact(
                workspace, manifest, Stage.SEGMENT, fix="openbbq segment"
            )
            ws.require_fresh_artifact(workspace, cues_path, Stage.SEGMENT)
            cues = ws.read_cues(cues_path)
            worksheet = ws.read_translation(
                ws.worksheet_path(workspace, session.target_lang)
            )
            brief = _brief_for(worksheet, manifest, workspace)
            policy = translation_rules.policy_hash(brief)
            state_hash = _translation_state_hash(
                workspace, manifest, cues, worksheet, policy
            )
            if lease.action == "finish":
                state_hash = semantic_inputs_hash(
                    workspace, manifest, session, cues, worksheet
                )
        except OpenBBQError:
            return False
        return (
            lease.source_hash == state_hash
            and (lease.policy_hash is None or lease.policy_hash == policy)
        )
    return False


def next_action(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
) -> dict[str, Any]:
    """Return and persist exactly one authoritative next action."""

    if session.active_lease is not None:
        if active_lease_fresh(workspace, manifest, session):
            return dict(session.active_lease.payload)
        session.active_lease = None
        ws.write_agent_session(workspace, session)

    # URL metadata makes glossary selection materially better, while fetch does
    # not itself need glossary context.  Local files already have a stem title.
    if manifest.source.type == "url" and not _stage_done(
        workspace, manifest, Stage.FETCH
    ):
        return _run_command(workspace, "fetch source media and metadata", "fetch")

    if not session.glossary_selected:
        payload = _new_lease(
            session,
            action="select_glossary",
            selected_ids=[],
            issue_ids=[],
            source_hash=_selection_hash(manifest),
            worksheet_hash=None,
            policy_hash=None,
            payload={
                "available_glossaries": _glossary_options(),
                "source": manifest.source.model_dump(mode="json", exclude_none=True),
                "response_schema": {
                    "batch_id": "exact batch_id",
                    "choice": "existing | create | none",
                    "name": "required for existing/create",
                    "context": "optional for create",
                },
            },
        )
        ws.write_agent_session(workspace, session)
        return payload

    if not _stage_done(workspace, manifest, Stage.EXTRACT_AUDIO):
        return _run_command(workspace, "normalize source audio", "extract-audio")
    if not _stage_done(workspace, manifest, Stage.TRANSCRIBE):
        return _run_command(workspace, "transcribe with the selected glossary context", "transcribe")

    views, transcript, review, reference_texts, reference_words = _source_views(
        workspace, manifest
    )
    asr = asrlib.check(
        transcript,
        review,
        reference_texts=reference_texts,
        reference_words=reference_words,
    )
    pending_views = [
        view
        for view in views
        if session.source_reviews.get(view.id) is None
        or session.source_reviews[view.id].segment_hash != view.evidence_hash
    ]
    if pending_views:
        selected = pending_views[:MAX_SEMANTIC_BATCH]
        selected_ids = [view.id for view in selected]
        unresolved = set(asr.unresolved_ids)
        issues = [
            issue
            for issue in asr.issues
            if issue.id in unresolved
            and set(_issue_segment_ids(issue)).intersection(selected_ids)
        ]
        by_index = {view.id: index for index, view in enumerate(views)}
        selected_payload: list[dict[str, Any]] = []
        for view in selected:
            index = by_index[view.id]
            selected_payload.append(
                {
                    "id": view.id,
                    "start": view.start,
                    "end": view.end,
                    "raw_source": view.raw if view.raw != view.after_asr else None,
                    "source": view.after_asr,
                    "after_glossary": (
                        view.after_glossary
                        if view.after_glossary != view.after_asr
                        else None
                    ),
                    "dropped": view.dropped,
                    "previous": views[index - 1].after_glossary if index > 0 else None,
                    "next": (
                        views[index + 1].after_glossary
                        if index + 1 < len(views)
                        else None
                    ),
                    "words": view.words,
                    "word_count": view.word_count,
                    "words_omitted": view.words_omitted,
                    "reference_caption": _reference_caption_for(
                        workspace, start=view.start, end=view.end
                    ),
                }
            )
        payload = _new_lease(
            session,
            action="review_source",
            selected_ids=selected_ids,
            issue_ids=[issue.id for issue in issues],
            source_hash=_source_state_hash(workspace, manifest),
            worksheet_hash=None,
            policy_hash=_SOURCE_POLICY,
            payload={
                "policy": [
                    "review every selected segment using full context, not confidence alone",
                    "detector issues require an explicit decision",
                    "source_fixes are occurrence-scoped; only reusable glossary aliases apply across segments",
                    "mark a glossary update reusable only when the canonical term should help future related videos",
                    "timeline anomalies cannot be accepted; use the timed reference replacement or explicitly drop the corrupted segment",
                ],
                "selected_segment_ids": selected_ids,
                "source_metadata": {
                    "title": manifest.source.title,
                    "author": manifest.source.author,
                },
                "segments": selected_payload,
                "detector_issues": [_issue_payload(issue) for issue in issues],
                "glossary": _relevant_glossary_payload(
                    workspace,
                    manifest,
                    [view.after_glossary for view in selected],
                ),
                "response_schema": {
                    "batch_id": "exact batch_id",
                    "reviewed_segment_ids": selected_ids,
                    "issue_decisions": {
                        "detector issue id": {
                            "action": "accept | replace | drop | keep_first",
                            "reason": "short evidence",
                            "find": "required for word replacement",
                            "replacement": "required for replacement",
                        }
                    },
                    "source_fixes": [
                        {
                            "segment_id": "selected segment id",
                            "find": "exact occurrence phrase",
                            "replacement": "correct phrase",
                            "evidence": "short contextual evidence",
                        }
                    ],
                    "glossary_updates": [
                        {
                            "source": "canonical term",
                            "aliases": ["reusable ASR mishearing"],
                            "target": "optional canonical translation",
                            "keep": False,
                            "note": "optional rule",
                            "reusable": True,
                            "evidence": "why this generalizes",
                        }
                    ],
                },
            },
        )
        ws.write_agent_session(workspace, session)
        return payload

    if not asr.ready:
        # Defensive recovery for an externally modified review: force the
        # affected segment back through the same source-review interface.
        affected = {
            segment_id
            for issue in asr.issues
            if issue.id in set(asr.unresolved_ids)
            for segment_id in _issue_segment_ids(issue)
        }
        for segment_id in affected:
            session.source_reviews.pop(segment_id, None)
        ws.write_agent_session(workspace, session)
        return next_action(workspace, manifest, session)

    if not _stage_done(workspace, manifest, Stage.SEGMENT):
        return _run_command(workspace, "build reviewed source cues once", "segment")

    cues_path = ws.require_artifact(
        workspace, manifest, Stage.SEGMENT, fix="openbbq segment"
    )
    try:
        ws.require_fresh_artifact(workspace, cues_path, Stage.SEGMENT)
    except OpenBBQError:
        return _run_command(
            workspace,
            "rebuild source cues because a reviewed input changed",
            "segment",
        )
    cues = ws.read_cues(cues_path)
    worksheet_path = ws.worksheet_path(workspace, session.target_lang)
    if not worksheet_path.is_file():
        return _run_command(
            workspace,
            "create the translation@2 worksheet and target-language brief",
            "translate",
            "init",
            session.target_lang,
        )
    worksheet = _ensure_translation_v2(
        workspace,
        manifest,
        ws.read_translation(worksheet_path),
    )
    translatelib.verify_integrity(cues, worksheet, session.target_lang)
    brief = _brief_for(worksheet, manifest, workspace)
    policy = translation_rules.policy_hash(brief)
    missing_evidence = [
        item.id
        for item in worksheet.items
        if not _translation_evidence_valid(session, worksheet, item, policy)
    ]
    if missing_evidence:
        selected_ids = missing_evidence[:MAX_SEMANTIC_BATCH]
        items, refs = _translation_batch_payload(worksheet, selected_ids)
        state_hash = _translation_state_hash(
            workspace, manifest, cues, worksheet, policy
        )
        payload = _new_lease(
            session,
            action="translate",
            selected_ids=selected_ids,
            issue_ids=[],
            source_hash=state_hash,
            worksheet_hash=_model_hash(worksheet),
            policy_hash=policy,
            payload={
                "policy_hash": policy,
                "brief": brief.model_dump(mode="json", exclude_none=True),
                "selected_ids": selected_ids,
                "items": items,
                "glossary": [
                    ref.model_dump(mode="json", exclude_none=True) for ref in refs
                ],
                "response_schema": {
                    "batch_id": "exact batch_id",
                    "policy_hash": policy,
                    "translations": {str(item_id): "target text" for item_id in selected_ids},
                    "source_fixes": [
                        {
                            "cue_id": "selected cue id",
                            "find": "exact source phrase",
                            "replacement": "correct source phrase",
                            "occurrence": 1,
                            "evidence": "short contextual evidence",
                        }
                    ],
                    "glossary_updates": [
                        {
                            "source": "canonical term",
                            "aliases": ["reusable ASR mishearing"],
                            "target": "optional canonical translation",
                            "keep": False,
                            "note": "optional translation or casing rule",
                            "reusable": True,
                            "evidence": "why this generalizes",
                        }
                    ],
                },
            },
        )
        ws.write_agent_session(workspace, session)
        return payload

    risks = _risk_items(workspace, manifest, session, cues, worksheet)
    by_id = {item.id: item for item in worksheet.items}
    pending_risks = [
        risk
        for risk in risks
        if not _risk_evidence_valid(session, by_id[risk.id], policy)
    ]
    if pending_risks:
        selected = pending_risks[:MAX_SEMANTIC_BATCH]
        selected_ids = [risk.id for risk in selected]
        _risk_context_items, risk_refs = _translation_batch_payload(
            worksheet, selected_ids
        )
        state_hash = _translation_state_hash(
            workspace, manifest, cues, worksheet, policy
        )
        payload = _new_lease(
            session,
            action="review_risks",
            selected_ids=selected_ids,
            issue_ids=[],
            source_hash=state_hash,
            worksheet_hash=_model_hash(worksheet),
            policy_hash=policy,
            payload={
                "policy_hash": policy,
                "brief": brief.model_dump(mode="json", exclude_none=True),
                "glossary": [
                    ref.model_dump(mode="json", exclude_none=True)
                    for ref in risk_refs
                ],
                "selected_ids": selected_ids,
                "items": [
                    {
                        "id": risk.id,
                        "source": risk.source,
                        "target": risk.target,
                        "used_chars": risk.used_chars,
                        "max_chars": risk.max_chars,
                        "risk_codes": list(risk.risk_codes),
                        "previous": (
                            None
                            if risk.previous is None
                            else {
                                "id": risk.previous.id,
                                "source": risk.previous.source,
                                "target": risk.previous.target,
                            }
                        ),
                        "next": (
                            None
                            if risk.next is None
                            else {
                                "id": risk.next.id,
                                "source": risk.next.source,
                                "target": risk.next.target,
                            }
                        ),
                    }
                    for risk in selected
                ],
                "response_schema": {
                    "batch_id": "exact batch_id",
                    "policy_hash": policy,
                    "decisions": {
                        str(item_id): {
                            "action": "accept | revise",
                            "target": "required only for revise",
                            "reason": "required only for revise; short is enough",
                        }
                        for item_id in selected_ids
                    },
                    "source_fixes": [
                        {
                            "cue_id": "selected cue id",
                            "find": "exact occurrence phrase",
                            "replacement": "correct phrase",
                            "occurrence": 1,
                            "evidence": "short contextual evidence",
                        }
                    ],
                    "glossary_updates": [
                        {
                            "source": "canonical term",
                            "aliases": ["reusable ASR mishearing"],
                            "target": "optional canonical translation",
                            "keep": False,
                            "note": "optional translation or casing rule",
                            "reusable": True,
                            "evidence": "why this generalizes",
                        }
                    ],
                },
            },
        )
        ws.write_agent_session(workspace, session)
        return payload

    gate = balanced_gate(workspace, manifest, session, cues, worksheet)
    if not gate.ready:
        raise OpenBBQError(
            "agent_state_inconsistent",
            problems=list(gate.problems),
            fix=f"rerun openbbq agent next --workspace {workspace}",
        )
    if _finished_is_fresh(workspace, manifest, session, cues, worksheet):
        finished = session.finished
        assert finished is not None
        return {
            "action": "done",
            "workspace": str(workspace),
            "target_lang": session.target_lang,
            "subtitle": str(workspace / finished.subtitle),
            "video": str(workspace / finished.video),
            "glossary_published": finished.glossary_published,
            "warnings": [warning.model_dump(mode="json") for warning in session.warnings],
        }
    session.finished = None
    inputs_hash = semantic_inputs_hash(
        workspace, manifest, session, cues, worksheet
    )
    payload = _new_lease(
        session,
        action="finish",
        selected_ids=[],
        issue_ids=[],
        source_hash=inputs_hash,
        worksheet_hash=_model_hash(worksheet),
        policy_hash=policy,
        payload={
            "argv": _workspace_argv(
                workspace, "agent", "finish", "--to", session.target_lang
            ),
            "outputs": {
                "subtitle": f"out/{session.target_lang}.ass",
                "video": f"out/{session.target_lang}-burned.mp4",
            },
            "note": "exports and burns once; no visual QA or fansub-compact pass",
        },
    )
    ws.write_agent_session(workspace, session)
    return payload


class _SelectResponse(OpenBBQModel):
    batch_id: str
    choice: Literal["existing", "create", "none"]
    name: str | None = None
    context: str | None = None

    @model_validator(mode="after")
    def validate_choice(self):
        if self.choice in {"existing", "create"} and not (self.name or "").strip():
            raise ValueError("existing/create choices require name")
        if self.choice == "none" and (self.name is not None or self.context is not None):
            raise ValueError("none choice cannot include name/context")
        return self


class _SourceResponse(OpenBBQModel):
    batch_id: str
    reviewed_segment_ids: list[int]
    issue_decisions: dict[str, AsrDecision] = Field(default_factory=dict)
    source_fixes: list[AgentSourceFix] = Field(default_factory=list)
    glossary_updates: list[AgentGlossaryUpdate] = Field(default_factory=list)


class _TranslateResponse(OpenBBQModel):
    batch_id: str
    policy_hash: str
    translations: dict[int, str]
    source_fixes: list[AgentCueSourceFix] = Field(default_factory=list)
    glossary_updates: list[AgentGlossaryUpdate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_targets(self):
        if any(not target.strip() for target in self.translations.values()):
            raise ValueError("translations must be non-blank")
        return self


class _RiskDecision(OpenBBQModel):
    action: Literal["accept", "revise"]
    target: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_decision(self):
        if self.action == "accept":
            if self.target is not None:
                raise ValueError("accept cannot include target")
            return self
        self.target = (self.target or "").strip()
        self.reason = (self.reason or "").strip()
        if not self.target or not self.reason:
            raise ValueError("revise requires target and a short reason")
        return self


class _RiskResponse(OpenBBQModel):
    batch_id: str
    policy_hash: str
    decisions: dict[int, _RiskDecision]
    source_fixes: list[AgentCueSourceFix] = Field(default_factory=list)
    glossary_updates: list[AgentGlossaryUpdate] = Field(default_factory=list)


def _parse_response(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise OpenBBQError(
            "agent_response_invalid",
            detail="response is not valid JSON",
        ) from error
    if not isinstance(value, dict):
        raise OpenBBQError(
            "agent_response_invalid",
            detail="response must be a JSON object",
        )
    return value


def _validate_lease_for_apply(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
    response: dict[str, Any],
) -> AgentLease:
    lease = session.active_lease
    if lease is None or lease.action == "finish":
        raise OpenBBQError(
            "agent_no_active_batch",
            fix=f"run openbbq agent next --workspace {workspace}",
        )
    if response.get("batch_id") != lease.batch_id:
        raise OpenBBQError(
            "agent_batch_mismatch",
            expected=lease.batch_id,
            received=response.get("batch_id"),
            fix="apply the exact response for the active agent next batch",
        )
    if not active_lease_fresh(workspace, manifest, session):
        session.active_lease = None
        ws.write_agent_session(workspace, session)
        raise OpenBBQError(
            "agent_lease_stale",
            fix=f"rerun openbbq agent next --workspace {workspace}",
        )
    return lease


def _set_manifest_glossary(
    workspace: Path,
    manifest: Manifest,
    name: str | None,
) -> None:
    current = ws.read_manifest(workspace)
    current.glossary = name
    ws.write_manifest(workspace, current)
    manifest.glossary = name


def _apply_select(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
    response: _SelectResponse,
) -> dict[str, Any]:
    if response.choice == "none":
        name = None
        context = None
        session.glossary_disabled = True
    else:
        assert response.name is not None
        name = glossary_overlay.validate_name(response.name.strip())
        candidate = glossarylib.glossary_path(name)
        if response.choice == "existing":
            glossarylib.load(name)
            context = None
        else:
            if candidate.exists():
                raise OpenBBQError(
                    "glossary_exists",
                    name=name,
                    fix="choose it as existing or use a new name",
                )
            context = response.context
        session.glossary_disabled = False
    _set_manifest_glossary(workspace, manifest, name)
    glossary_overlay.initialize(workspace, base_name=name, context=context)
    session.glossary_selected = True
    session.glossary_name = name
    session.active_lease = None
    session.finished = None
    ws.write_agent_session(workspace, session)
    return {"applied": "select_glossary", "glossary": name}


def _merge_all_issue_decisions(
    transcript,
    review,
    decisions: dict[str, AsrDecision],
    reference_texts: list[str],
    reference_words: list[Any],
):
    current = review
    entries = list(decisions.items())
    for offset in range(0, len(entries), asrlib.MAX_DECISION_BATCH):
        current = asrlib.merge_decisions(
            transcript,
            current,
            dict(entries[offset : offset + asrlib.MAX_DECISION_BATCH]),
            reference_texts=reference_texts,
            reference_words=reference_words,
        )
    if current is None:
        current = asrlib.merge_decisions(
            transcript,
            None,
            {},
            reference_texts=reference_texts,
            reference_words=reference_words,
        )
    return current


def _apply_source(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
    lease: AgentLease,
    response: _SourceResponse,
) -> dict[str, Any]:
    if (
        len(response.reviewed_segment_ids) != len(lease.selected_ids)
        or set(response.reviewed_segment_ids) != set(lease.selected_ids)
    ):
        raise OpenBBQError(
            "agent_id_set_mismatch",
            expected=lease.selected_ids,
            received=response.reviewed_segment_ids,
        )
    if set(response.issue_decisions) != set(lease.issue_ids):
        raise OpenBBQError(
            "agent_issue_set_mismatch",
            expected=lease.issue_ids,
            received=sorted(response.issue_decisions),
        )
    if len(response.source_fixes) > MAX_SEMANTIC_BATCH:
        raise OpenBBQError(
            "agent_batch_too_large",
            count=len(response.source_fixes),
            max=MAX_SEMANTIC_BATCH,
        )
    if len(response.glossary_updates) > MAX_SEMANTIC_BATCH:
        raise OpenBBQError(
            "agent_batch_too_large",
            count=len(response.glossary_updates),
            max=MAX_SEMANTIC_BATCH,
        )
    invalid_fix_ids = sorted(
        {fix.segment_id for fix in response.source_fixes} - set(lease.selected_ids)
    )
    if invalid_fix_ids:
        raise OpenBBQError(
            "agent_source_fix_out_of_batch",
            ids=invalid_fix_ids,
        )
    transcript, review, reference_texts, reference_words = _transcript_context(
        workspace, manifest
    )
    merged = _merge_all_issue_decisions(
        transcript,
        review,
        response.issue_decisions,
        reference_texts,
        reference_words,
    )
    if response.source_fixes:
        amendments = [
            asrlib.AsrAmendment(
                segment_id=fix.segment_id,
                find=fix.find,
                replacement=fix.replacement,
                reason=fix.evidence,
            )
            for fix in response.source_fixes
        ]
        merged, _ = asrlib.merge_amendments(transcript, merged, amendments)
    updated_overlay, _ = glossary_overlay.prepare_updates(
        workspace, response.glossary_updates
    )
    documents = {
        ws.asr_review_path(workspace): merged.model_dump_json(indent=2) + "\n",
    }
    if any(update.reusable for update in response.glossary_updates):
        documents[glossary_overlay.path(workspace)] = (
            updated_overlay.model_dump_json(indent=2) + "\n"
        )
    ws.write_texts_atomic(documents)
    transcribe_state = manifest.stages.get(Stage.TRANSCRIBE)
    if transcribe_state is not None:
        ws.record_stage(workspace, manifest, Stage.TRANSCRIBE, transcribe_state)

    # Evidence is sampled after both occurrence fixes and overlay changes are
    # accepted, but remains tied to the ASR view rather than future aliases.
    refreshed_manifest = ws.read_manifest(workspace)
    views, _, _, _, _ = _source_views(workspace, refreshed_manifest)
    by_id = {view.id: view for view in views}
    for segment_id in lease.selected_ids:
        session.source_reviews[segment_id] = SourceReviewEvidence(
            segment_hash=by_id[segment_id].evidence_hash,
            batch_id=lease.batch_id,
        )
    session.active_lease = None
    session.finished = None
    ws.write_agent_session(workspace, session)
    return {
        "applied": "review_source",
        "reviewed_segments": len(lease.selected_ids),
        "source_fixes": len(response.source_fixes),
        "glossary_updates": len(
            [update for update in response.glossary_updates if update.reusable]
        ),
    }


def _replace_occurrence(source: str, fix: AgentCueSourceFix) -> str:
    matches = list(re.finditer(re.escape(fix.find), source))
    if fix.occurrence > len(matches):
        raise OpenBBQError(
            "source_fix_requires_review",
            cue_id=fix.cue_id,
            find=fix.find,
            occurrence=fix.occurrence,
            detail="the exact phrase occurrence is not contained in this cue",
            fix="return to openbbq agent next; cross-cue/timeline fixes need explicit source review",
        )
    match = matches[fix.occurrence - 1]
    return source[: match.start()] + fix.replacement + source[match.end() :]


def _contains_exact_form(text: str, form: str) -> bool:
    left = r"(?<![A-Za-z0-9])" if form[:1].isascii() and form[:1].isalnum() else ""
    right = r"(?![A-Za-z0-9])" if form[-1:].isascii() and form[-1:].isalnum() else ""
    return re.search(left + re.escape(form) + right, text) is not None


def _apply_translate(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
    lease: AgentLease,
    response: _TranslateResponse,
) -> dict[str, Any]:
    if response.policy_hash != lease.policy_hash:
        raise OpenBBQError(
            "agent_policy_hash_mismatch",
            expected=lease.policy_hash,
            received=response.policy_hash,
        )
    if set(response.translations) != set(lease.selected_ids):
        raise OpenBBQError(
            "agent_id_set_mismatch",
            expected=lease.selected_ids,
            received=sorted(response.translations),
        )
    if len(response.translations) > MAX_SEMANTIC_BATCH:
        raise OpenBBQError(
            "agent_batch_too_large",
            count=len(response.translations),
            max=MAX_SEMANTIC_BATCH,
        )
    if len(response.source_fixes) > MAX_SEMANTIC_BATCH:
        raise OpenBBQError(
            "agent_batch_too_large",
            count=len(response.source_fixes),
            max=MAX_SEMANTIC_BATCH,
        )
    if len(response.glossary_updates) > MAX_SEMANTIC_BATCH:
        raise OpenBBQError(
            "agent_batch_too_large",
            count=len(response.glossary_updates),
            max=MAX_SEMANTIC_BATCH,
        )
    fix_ids = {fix.cue_id for fix in response.source_fixes}
    if not fix_ids.issubset(lease.selected_ids):
        raise OpenBBQError(
            "agent_source_fix_out_of_batch",
            ids=sorted(fix_ids - set(lease.selected_ids)),
        )

    cues_path = ws.require_artifact(
        workspace, manifest, Stage.SEGMENT, fix="openbbq segment"
    )
    cues = ws.read_cues(cues_path)
    worksheet_path = ws.worksheet_path(workspace, session.target_lang)
    worksheet = ws.read_translation(worksheet_path)
    translatelib.verify_integrity(cues, worksheet, session.target_lang)
    candidate_cues = cues.model_copy(deep=True)
    candidate_worksheet = worksheet.model_copy(deep=True)
    cue_by_id = {cue.id: cue for cue in candidate_cues.cues}
    item_by_id = {item.id: item for item in candidate_worksheet.items}
    for fix in response.source_fixes:
        cue = cue_by_id.get(fix.cue_id)
        if cue is None:
            raise OpenBBQError("unknown_cue_ids", ids=[fix.cue_id])
        corrected = _replace_occurrence(cue.source, fix)
        cue.source = corrected
        item_by_id[fix.cue_id].source = corrected
    original_by_id = {item.id: item for item in worksheet.items}
    for update in response.glossary_updates:
        if not update.reusable:
            continue
        for alias in update.aliases:
            for item_id in lease.selected_ids:
                before = original_by_id[item_id].source
                after = item_by_id[item_id].source
                if not _contains_exact_form(before, alias):
                    continue
                if _contains_exact_form(after, alias) or not _contains_exact_form(
                    after, update.source
                ):
                    raise OpenBBQError(
                        "source_fix_requires_review",
                        cue_id=item_id,
                        alias=alias,
                        canonical=update.source,
                        detail="a newly declared ASR alias still occurs in the current cue",
                        fix="submit a cue-scoped source_fix in this translation response",
                    )
    translatelib.apply_targets(candidate_worksheet, response.translations)

    updated_overlay, _ = glossary_overlay.prepare_updates(
        workspace, response.glossary_updates
    )
    effective = glossary_overlay.merged_overlay(
        workspace, updated_overlay, manifest.glossary
    )
    candidate_worksheet.glossary = _worksheet_glossary(effective)
    # Validate the complete candidate before either canonical product is
    # replaced.  This gives source-fix + translation logical atomicity.
    translatelib.verify_integrity(
        candidate_cues,
        candidate_worksheet,
        session.target_lang,
    )
    documents = {
        worksheet_path: candidate_worksheet.model_dump_json(indent=2) + "\n"
    }
    if response.source_fixes:
        # Preserve this order so the rollback test exercises the cross-document
        # boundary rather than a single worksheet replacement.
        documents = {
            cues_path: candidate_cues.model_dump_json(indent=2, exclude_none=True)
            + "\n",
            **documents,
        }
    if any(update.reusable for update in response.glossary_updates):
        documents[glossary_overlay.path(workspace)] = (
            updated_overlay.model_dump_json(indent=2) + "\n"
        )
    ws.write_texts_atomic(documents)
    if response.source_fixes:
        ws.refresh_artifact_provenance(workspace, cues_path, Stage.SEGMENT)
    for item_id in lease.selected_ids:
        item = item_by_id[item_id]
        session.translation_evidence[item_id] = TranslationEvidence(
            cue_hash=auditlib.item_hash(item),
            source_hash=_hash_text(item.source),
            target_hash=_hash_text(item.target or ""),
            glossary_hash=_glossary_refs_hash(
                _cue_glossary_refs(candidate_worksheet, item_id)
            ),
            policy_hash=response.policy_hash,
            batch_id=lease.batch_id,
        )
    session.source_fixed_cue_ids = sorted(
        set(session.source_fixed_cue_ids) | fix_ids
    )
    session.active_lease = None
    session.finished = None
    ws.write_agent_session(workspace, session)
    report = translatelib.check(
        candidate_cues,
        candidate_worksheet,
        session.target_lang,
    )
    return {
        "applied": "translate",
        "translated": len(lease.selected_ids),
        "source_fixes": len(response.source_fixes),
        "glossary_updates": len(
            [update for update in response.glossary_updates if update.reusable]
        ),
        "mechanical_warnings": {
            "over_budget": report.over_budget,
            "zero_budget": report.zero_budget,
            "term_ids": sorted({issue.id for issue in report.term_issues}),
            "quality_ids": sorted({issue.id for issue in report.quality_issues}),
        },
    }


def _apply_risks(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
    lease: AgentLease,
    response: _RiskResponse,
) -> dict[str, Any]:
    if response.policy_hash != lease.policy_hash:
        raise OpenBBQError(
            "agent_policy_hash_mismatch",
            expected=lease.policy_hash,
            received=response.policy_hash,
        )
    if set(response.decisions) != set(lease.selected_ids):
        raise OpenBBQError(
            "agent_id_set_mismatch",
            expected=lease.selected_ids,
            received=sorted(response.decisions),
        )
    if len(response.source_fixes) > MAX_SEMANTIC_BATCH:
        raise OpenBBQError(
            "agent_batch_too_large",
            count=len(response.source_fixes),
            max=MAX_SEMANTIC_BATCH,
        )
    if len(response.glossary_updates) > MAX_SEMANTIC_BATCH:
        raise OpenBBQError(
            "agent_batch_too_large",
            count=len(response.glossary_updates),
            max=MAX_SEMANTIC_BATCH,
        )
    fix_ids = {fix.cue_id for fix in response.source_fixes}
    if not fix_ids.issubset(lease.selected_ids):
        raise OpenBBQError(
            "agent_source_fix_out_of_batch",
            ids=sorted(fix_ids - set(lease.selected_ids)),
        )
    cues_path = ws.require_artifact(
        workspace, manifest, Stage.SEGMENT, fix="openbbq segment"
    )
    cues = ws.read_cues(cues_path)
    worksheet_path = ws.worksheet_path(workspace, session.target_lang)
    worksheet = ws.read_translation(worksheet_path)
    translatelib.verify_integrity(cues, worksheet, session.target_lang)
    audit = ws.read_translation_audit_optional(workspace, session.target_lang)
    risks = _risk_items(workspace, manifest, session, cues, worksheet)
    current_ids = {risk.id for risk in risks}
    if not set(lease.selected_ids).issubset(current_ids):
        raise OpenBBQError(
            "agent_lease_stale",
            fix=f"rerun openbbq agent next --workspace {workspace}",
        )
    candidate_cues = cues.model_copy(deep=True)
    candidate_worksheet = worksheet.model_copy(deep=True)
    cue_by_id = {cue.id: cue for cue in candidate_cues.cues}
    item_by_id = {item.id: item for item in candidate_worksheet.items}
    for fix in response.source_fixes:
        cue = cue_by_id.get(fix.cue_id)
        if cue is None:
            raise OpenBBQError("unknown_cue_ids", ids=[fix.cue_id])
        corrected = _replace_occurrence(cue.source, fix)
        cue.source = corrected
        item_by_id[fix.cue_id].source = corrected

    original_by_id = {item.id: item for item in worksheet.items}
    for update in response.glossary_updates:
        if not update.reusable:
            continue
        for alias in update.aliases:
            for item_id in lease.selected_ids:
                before = original_by_id[item_id].source
                after = item_by_id[item_id].source
                if not _contains_exact_form(before, alias):
                    continue
                if _contains_exact_form(after, alias) or not _contains_exact_form(
                    after, update.source
                ):
                    raise OpenBBQError(
                        "source_fix_requires_review",
                        cue_id=item_id,
                        alias=alias,
                        canonical=update.source,
                        detail="a newly declared ASR alias still occurs in the current cue",
                        fix="submit a cue-scoped source_fix in this risk response",
                    )

    updated_overlay, _ = glossary_overlay.prepare_updates(
        workspace, response.glossary_updates
    )
    effective = glossary_overlay.merged_overlay(
        workspace, updated_overlay, manifest.glossary
    )
    candidate_worksheet.glossary = _worksheet_glossary(effective)
    decisions = {
        cue_id: TranslationAuditDecision(
            action=decision.action,
            target=decision.target,
            reason=decision.reason or "checked against source and context",
        )
        for cue_id, decision in response.decisions.items()
    }
    report = auditlib.apply_decisions(
        candidate_cues,
        candidate_worksheet,
        audit,
        risks,
        decisions,
        coverage="risks",
    )
    translatelib.verify_integrity(
        candidate_cues,
        candidate_worksheet,
        session.target_lang,
    )
    documents = {
        worksheet_path: candidate_worksheet.model_dump_json(indent=2) + "\n",
        ws.translation_audit_path(workspace, session.target_lang): (
            report.audit.model_dump_json(indent=2) + "\n"
        ),
    }
    if response.source_fixes:
        documents[cues_path] = (
            candidate_cues.model_dump_json(indent=2, exclude_none=True) + "\n"
        )
    if any(update.reusable for update in response.glossary_updates):
        documents[glossary_overlay.path(workspace)] = (
            updated_overlay.model_dump_json(indent=2) + "\n"
        )
    ws.write_texts_atomic(documents)
    if response.source_fixes:
        ws.refresh_artifact_provenance(workspace, cues_path, Stage.SEGMENT)
    by_id = {item.id: item for item in candidate_worksheet.items}
    for cue_id in lease.selected_ids:
        item = by_id[cue_id]
        session.risk_reviews[cue_id] = RiskReviewEvidence(
            item_hash=auditlib.item_hash(item),
            policy_hash=response.policy_hash,
            batch_id=lease.batch_id,
        )
        if response.decisions[cue_id].action == "revise" or cue_id in fix_ids:
            session.translation_evidence[cue_id] = TranslationEvidence(
                cue_hash=auditlib.item_hash(item),
                source_hash=_hash_text(item.source),
                target_hash=_hash_text(item.target or ""),
                glossary_hash=_glossary_refs_hash(
                    _cue_glossary_refs(candidate_worksheet, cue_id)
                ),
                policy_hash=response.policy_hash,
                batch_id=lease.batch_id,
            )
    session.source_fixed_cue_ids = sorted(
        set(session.source_fixed_cue_ids) | fix_ids
    )
    session.active_lease = None
    session.finished = None
    ws.write_agent_session(workspace, session)
    return {
        "applied": "review_risks",
        "reviewed": report.reviewed,
        "revised": report.revised,
        "source_fixes": len(response.source_fixes),
        "glossary_updates": len(
            [update for update in response.glossary_updates if update.reusable]
        ),
    }


def apply_response(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
    raw: str,
) -> dict[str, Any]:
    value = _parse_response(raw)
    lease = _validate_lease_for_apply(
        workspace,
        manifest,
        session,
        value,
    )
    try:
        if lease.action == "select_glossary":
            parsed = _SelectResponse.model_validate(value)
            return _apply_select(workspace, manifest, session, parsed)
        if lease.action == "review_source":
            parsed = _SourceResponse.model_validate(value)
            return _apply_source(
                workspace, manifest, session, lease, parsed
            )
        if lease.action == "translate":
            parsed = _TranslateResponse.model_validate(value)
            return _apply_translate(
                workspace, manifest, session, lease, parsed
            )
        if lease.action == "review_risks":
            parsed = _RiskResponse.model_validate(value)
            return _apply_risks(workspace, manifest, session, lease, parsed)
    except ValidationError as error:
        raise OpenBBQError(
            "agent_response_invalid",
            action=lease.action,
            detail=str(error),
        ) from error
    raise OpenBBQError("agent_response_invalid", action=lease.action)


def record_finished(
    workspace: Path,
    session: AgentSession,
    *,
    inputs_hash: str,
    subtitle: str,
    video: str,
    preset: Literal["fansub", "mobile"],
    glossary_published: bool,
) -> None:
    session.finished = AgentFinished(
        inputs_hash=inputs_hash,
        subtitle=subtitle,
        video=video,
        preset=preset,
        glossary_published=glossary_published,
    )
    session.finish_pid = None
    session.active_lease = None
    ws.write_agent_session(workspace, session)

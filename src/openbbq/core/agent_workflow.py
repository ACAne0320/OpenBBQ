"""Authoritative one-shot workflow for producing an editable subtitle draft.

OpenBBQ owns ordering, bounded batches, stale-response protection, atomic
writes, and artifact freshness.  The external agent owns the only routine
semantic task: translation.  Source repair is requested only when a structural
ASR failure prevents safe segmentation; ordinary semantic suspicions remain
advisory and never create another mandatory review pass.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from openbbq.core import asr_review as asrlib
from openbbq.core import glossary as glossarylib
from openbbq.core import glossary_overlay
from openbbq.core import review as reviewlib
from openbbq.core import translate as translatelib
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
    AgentWarning,
    AsrDecision,
    Cues,
    GlossaryRef,
    Manifest,
    OpenBBQModel,
    Progress,
    Stage,
    StageState,
    StageStatus,
    Translation,
    TranslationEvidence,
    TranslationItem,
)

MAX_AGENT_BATCH = 20
_SOURCE_POLICY = "structural-source-repair@1"


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
    )
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


def _execution_policy(command: str) -> dict[str, str]:
    if command == "fetch":
        return {
            "sandbox": "outside_required",
            "accelerator": "none",
            "cpu_fallback": "not_applicable",
            "reason_code": "host_network_and_auth_state",
            "concurrency": "wait_and_reuse_completed_stage",
        }
    if command == "transcribe":
        return {
            "sandbox": "outside_required",
            "accelerator": "gpu",
            "cpu_fallback": "only_after_outside_gpu_failure",
            "reason_code": "native_gpu_and_model_cache",
            "concurrency": "wait_and_reuse_completed_stage",
        }
    return {
        "sandbox": "inside_allowed",
        "accelerator": "none",
        "cpu_fallback": "not_applicable",
        "reason_code": "workspace_local_operation",
        "concurrency": "wait_and_reuse_completed_stage",
    }


def _run_command(workspace: Path, reason: str, *parts: str) -> dict[str, Any]:
    return {
        "action": "run_command",
        "argv": _workspace_argv(workspace, *parts),
        "reason": reason,
        "execution": _execution_policy(parts[0]),
        "terminal": False,
        "must_continue": True,
    }


def _stage_done(workspace: Path, manifest: Manifest, stage: Stage) -> bool:
    state = manifest.stages.get(stage)
    if state is None or state.status is not StageStatus.DONE or not state.artifact:
        return False
    artifact = Path(state.artifact)
    if not artifact.is_absolute():
        artifact = workspace / artifact
    return artifact.is_file()


def _author_glossary_name(author: str, target_lang: str) -> str:
    """Build a stable creator glossary name scoped to one target language."""

    key = author.strip().casefold()
    lang_key = ws.validate_lang(target_lang).casefold()
    words = re.findall(r"[a-z0-9]+", key)
    label = "-".join(words)[:40].strip("-") or "creator"
    lang_label = "-".join(re.findall(r"[a-z0-9]+", lang_key))[:16] or "target"
    digest = hashlib.sha256(f"{key}\0{lang_key}".encode("utf-8")).hexdigest()[:10]
    return glossary_overlay.validate_name(f"author-{label}-{lang_label}-{digest}")


def _bind_default_glossary(
    workspace: Path,
    manifest: Manifest,
    target_lang: str,
) -> None:
    """Attach a reusable creator glossary to the task-local overlay.

    ``manifest.glossary`` remains reserved for an explicit, existing global
    binding. Keeping an unpublished derived name in the overlay avoids a
    dangling manifest reference while still letting every agent stage consume
    the existing base glossary when one is available.
    """

    if (
        manifest.glossary is not None
        or manifest.source.type != "url"
        or not (manifest.source.author or "").strip()
    ):
        return
    overlay = glossary_overlay.read_optional(workspace)
    if overlay is not None and overlay.entries:
        # Never rebind learned entries whose intended global owner is unknown.
        return
    author = (manifest.source.author or "").strip()
    name = _author_glossary_name(author, target_lang)
    context = (
        None
        if glossarylib.glossary_path(name).is_file()
        else f"Recurring names, products, and terminology in videos by {author}."
    )
    glossary_overlay.initialize(
        workspace,
        base_name=name,
        context=context,
    )


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
    return transcript, review, reference_words


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


def _source_views(
    workspace: Path,
    manifest: Manifest,
) -> tuple[list[_SourceView], Any, Any, list[Any]]:
    transcript, review, reference_words = _transcript_context(workspace, manifest)
    resolved = asrlib.resolved_transcript(
        transcript,
        review,
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
    return views, transcript, review, reference_words


def _source_state_hash(workspace: Path, manifest: Manifest) -> str:
    transcript, review, reference_words = _transcript_context(workspace, manifest)
    report = asrlib.check(
        transcript,
        review,
        reference_words=reference_words,
    )
    return _hash_json(
        {
            "transcript": report.transcript_hash,
            "review": None if review is None else _model_hash(review),
            "blocking_unresolved": asrlib.blocking_unresolved_ids(report),
            "reference_words": _hash_json(
                [word.model_dump(mode="json") for word in reference_words]
            ),
            "policy": _SOURCE_POLICY,
        }
    )


def _issue_segment_ids(issue: asrlib.Anomaly) -> list[int]:
    return [int(value) for value in issue.segment_ids]


def _issue_payload(issue: asrlib.Anomaly) -> dict[str, Any]:
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
    *,
    canonical_references: set[str] | None = None,
) -> dict[str, Any]:
    glossary = glossary_overlay.merged(workspace, manifest.glossary)
    if glossary is None:
        return {"name": None, "context": None, "terms": []}
    reference_keys = {value.casefold() for value in (canonical_references or set())}
    terms = [
        term.model_dump(mode="json", exclude_none=True)
        for term in glossary.terms
        if term.source.casefold() in reference_keys
        or any(
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


def _new_lease(
    session: AgentSession,
    *,
    action: Literal["review_source", "translate", "finish"],
    selected_ids: list[int],
    issue_ids: list[str],
    source_hash: str,
    policy_hash: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    batch_id = str(uuid.uuid4())
    payload = {
        **payload,
        "action": action,
        "batch_id": batch_id,
        "terminal": False,
        "must_continue": True,
    }
    session.active_lease = AgentLease(
        action=action,
        batch_id=batch_id,
        selected_ids=selected_ids,
        issue_ids=issue_ids,
        source_hash=source_hash,
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
            aliases=list(term.aliases),
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
    item = next(item for item in worksheet.items if item.id == cue_id)
    return [
        ref
        for ref in worksheet.glossary
        if translatelib.glossary_ref_matches(item.source, ref)
    ]


def _glossary_refs_hash(refs: list[GlossaryRef]) -> str:
    # Aliases decide whether a term is relevant to a cue, but do not change the
    # translation instruction once the source has been canonicalized. Adding a
    # new ASR spelling therefore must not invalidate an already translated cue.
    return _hash_json(
        [
            {
                "source": ref.source,
                "target": ref.target,
                "note": ref.note,
                "keep": ref.keep,
            }
            for ref in refs
        ]
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
        and evidence.cue_hash == translatelib.item_hash(item)
        and evidence.policy_hash == policy_hash
        and evidence.glossary_hash
        == _glossary_refs_hash(_cue_glossary_refs(worksheet, item.id))
    )


def stale_translation_evidence_ids(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
    worksheet: Translation,
) -> tuple[int, ...]:
    """Return cues whose current source/target/policy lack matching evidence."""

    policy = translation_rules.policy_hash(_brief_for(worksheet, manifest, workspace))
    return tuple(
        item.id
        for item in worksheet.items
        if not _translation_evidence_valid(session, worksheet, item, policy)
    )


def record_translation_progress(
    workspace: Path,
    manifest: Manifest,
    worksheet: Translation,
    *,
    complete: bool,
) -> None:
    """Keep the manifest work log in sync with the authoritative worksheet."""

    filled = sum(1 for item in worksheet.items if translatelib.is_filled(item.target))
    ws.record_stage(
        workspace,
        manifest,
        Stage.TRANSLATE,
        StageState(
            status=StageStatus.DONE if complete else StageStatus.RUNNING,
            artifact=ws.worksheet_path(workspace, worksheet.target_lang).name,
            updated_at=datetime.now(timezone.utc),
            progress=Progress(done=filled, total=len(worksheet.items)),
        ),
        # Every apply already invalidates stale exports. Marking the completed
        # translation must not invalidate a fresh idempotent finish result.
        invalidate_later=not complete,
    )


def _review_state_hash(workspace: Path, target_lang: str) -> str | None:
    """Hash optional human-review state so an open lease cannot cross it."""

    path = reviewlib.review_path(workspace, target_lang)
    if not path.is_file():
        return None
    try:
        return _hash_text(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise OpenBBQError(
            "review_unreadable",
            path=str(path),
            fix=f"openbbq review --workspace {workspace} --to {target_lang}",
        ) from error


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
            "review_state_hash": _review_state_hash(
                workspace,
                worksheet.target_lang,
            ),
        }
    )


def _translation_batch_payload(
    worksheet: Translation,
    selected_ids: list[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[GlossaryRef]]:
    indexes = {item.id: index for index, item in enumerate(worksheet.items)}
    selected_indexes = {indexes[item_id] for item_id in selected_ids}
    neighbor_indexes: set[int] = set()
    for index in selected_indexes:
        neighbor_indexes.update({index - 1, index + 1})
    neighbor_indexes = {
        index
        for index in neighbor_indexes
        if 0 <= index < len(worksheet.items) and index not in selected_indexes
    }
    items: list[dict[str, Any]] = []
    for index in sorted(selected_indexes):
        item = worksheet.items[index]
        payload = {
            "id": item.id,
            "source": item.source,
            "budget": item.budget.model_dump(mode="json"),
        }
        if item.target is not None:
            payload["target"] = item.target
        items.append(payload)
    neighbors: list[dict[str, Any]] = []
    for index in sorted(neighbor_indexes):
        item = worksheet.items[index]
        payload = {"id": item.id, "source": item.source}
        if item.target is not None:
            payload["target"] = item.target
        neighbors.append(payload)
    included_indexes = selected_indexes | neighbor_indexes
    texts = [worksheet.items[index].source for index in sorted(included_indexes)]
    refs = [
        ref
        for ref in worksheet.glossary
        if any(translatelib.glossary_ref_matches(text, ref) for text in texts)
    ]
    return items, neighbors, refs


@dataclass(frozen=True)
class DraftGate:
    """Hard workflow contract for a complete, editable AI draft."""

    ready: bool
    problems: tuple[str, ...]


def draft_gate(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
    cues: Cues,
    worksheet: Translation,
) -> DraftGate:
    """Check only invariants that can make the draft incomplete or stale."""

    problems: list[str] = []
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
        transcript, review, reference_words = _transcript_context(workspace, manifest)
        asr = asrlib.check(
            transcript,
            review,
            reference_words=reference_words,
        )
    except OpenBBQError as error:
        problems.append(f"ASR source unavailable: {error.code}")
    else:
        blocking = asrlib.blocking_unresolved_ids(asr)
        if blocking:
            problems.append(f"structural ASR issues are unresolved: {blocking[:20]}")

    try:
        translatelib.verify_integrity(cues, worksheet, session.target_lang)
    except OpenBBQError as error:
        problems.append(f"translation worksheet is invalid: {error.code}")
    try:
        human_reviewed = human_review_is_complete(workspace, cues, worksheet)
    except OpenBBQError as error:
        problems.append(f"human review is incomplete: {error.code}")
        human_reviewed = False
    if not human_reviewed:
        invalid_translation = stale_translation_evidence_ids(
            workspace,
            manifest,
            session,
            worksheet,
        )
        if invalid_translation:
            problems.append(
                f"translation evidence missing or stale: {invalid_translation[:20]}"
            )
    return DraftGate(
        ready=not problems,
        problems=tuple(problems),
    )


def human_review_is_complete(
    workspace: Path,
    cues: Cues,
    worksheet: Translation,
) -> bool:
    """Return whether a present human review is complete and current.

    Absence means the agent draft remains authoritative. Once a review file is
    created, incomplete or stale review raises instead of silently allowing an
    agent to overwrite human edits.
    """

    review_path = reviewlib.review_path(workspace, worksheet.target_lang)
    if not review_path.is_file():
        return False
    missing = [
        item.id for item in worksheet.items if not translatelib.is_filled(item.target)
    ]
    if missing:
        raise OpenBBQError(
            "translation_incomplete",
            ids=missing[:20],
            fix=(
                f"openbbq review --workspace {workspace} --to {worksheet.target_lang}"
            ),
        )
    reviewlib.require_complete_review(
        workspace,
        cues,
        worksheet,
        worksheet.target_lang,
    )
    return True


def draft_warnings(cues: Cues, worksheet: Translation) -> list[dict[str, Any]]:
    """Return concise advisory findings without turning them into workflow."""

    report = translatelib.check(cues, worksheet, worksheet.target_lang)
    warnings: list[dict[str, Any]] = []
    groups: list[tuple[str, list[int], str]] = [
        (
            "over_budget",
            report.over_budget,
            "target text exceeds the suggested display budget",
        ),
        (
            "zero_budget",
            report.zero_budget,
            "cue timing leaves no suggested target-language capacity",
        ),
        (
            "glossary",
            sorted({issue.id for issue in report.term_issues}),
            "target may not follow a matching glossary entry",
        ),
    ]
    for code, cue_ids, detail in groups:
        if cue_ids:
            warnings.append({"code": code, "cue_ids": cue_ids, "detail": detail})
    return warnings


def draft_inputs_hash(
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
            "translation_evidence": {
                key: value.model_dump(mode="json")
                for key, value in session.translation_evidence.items()
            },
            "policy_hash": translation_rules.policy_hash(brief),
            "source_state_hash": _source_state_hash(workspace, manifest),
            "review_state_hash": _review_state_hash(
                workspace,
                worksheet.target_lang,
            ),
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
    if finished.inputs_hash != draft_inputs_hash(
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
    if lease.action == "review_source":
        try:
            return (
                lease.policy_hash == _SOURCE_POLICY
                and lease.source_hash == _source_state_hash(workspace, manifest)
            )
        except OpenBBQError:
            return False
    if lease.action in {"translate", "finish"}:
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
                state_hash = draft_inputs_hash(
                    workspace, manifest, session, cues, worksheet
                )
        except OpenBBQError:
            return False
        return lease.source_hash == state_hash and (lease.policy_hash == policy)
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

    if manifest.source.type == "url" and not _stage_done(
        workspace, manifest, Stage.FETCH
    ):
        return _run_command(workspace, "fetch source media and metadata", "fetch")

    _bind_default_glossary(workspace, manifest, session.target_lang)

    if not _stage_done(workspace, manifest, Stage.EXTRACT_AUDIO):
        return _run_command(workspace, "normalize source audio", "extract-audio")
    if not _stage_done(workspace, manifest, Stage.TRANSCRIBE):
        return _run_command(
            workspace,
            "transcribe with the selected glossary context",
            "transcribe",
            "--gpu",
        )

    views, transcript, review, reference_words = _source_views(workspace, manifest)
    asr = asrlib.check(
        transcript,
        review,
        reference_words=reference_words,
    )
    blocking_ids = set(asrlib.blocking_unresolved_ids(asr))
    if blocking_ids:
        issues = [issue for issue in asr.anomalies if issue.id in blocking_ids][
            :MAX_AGENT_BATCH
        ]
        selected_ids = sorted(
            {segment_id for issue in issues for segment_id in _issue_segment_ids(issue)}
        )[:MAX_AGENT_BATCH]
        selected_id_set = set(selected_ids)
        selected = [view for view in views if view.id in selected_id_set]
        by_index = {view.id: index for index, view in enumerate(views)}
        selected_indexes = {by_index[view.id] for view in selected}
        neighbor_indexes: set[int] = set()
        for index in selected_indexes:
            neighbor_indexes.update({index - 1, index + 1})
        neighbor_indexes = {
            index
            for index in neighbor_indexes
            if 0 <= index < len(views) and index not in selected_indexes
        }
        neighbor_context = [
            {"id": views[index].id, "source": views[index].after_glossary}
            for index in sorted(neighbor_indexes)
        ]
        selected_payload: list[dict[str, Any]] = []
        for view in selected:
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
            policy_hash=_SOURCE_POLICY,
            payload={
                "policy": [
                    "resolve only the listed structural ASR blockers",
                    "accept repeated speech only when the neighboring context shows it is intentional",
                    "timeline anomalies require a timed replacement or an explicit drop",
                    "optional source_fixes are occurrence-scoped; set reusable only when the correction is a stable term for future related videos",
                ],
                "selected_segment_ids": selected_ids,
                "source_metadata": {
                    "title": manifest.source.title,
                    "author": manifest.source.author,
                },
                "segments": selected_payload,
                "neighbor_context": neighbor_context,
                "detector_issues": [_issue_payload(issue) for issue in issues],
                "glossary": _relevant_glossary_payload(
                    workspace,
                    manifest,
                    [
                        views[index].after_glossary
                        for index in sorted(selected_indexes | neighbor_indexes)
                    ],
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
                            "replacement": "correct phrase; may be empty to delete noise",
                            "reusable": "true only for a stable recurring name or term; otherwise false",
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

    if not _stage_done(workspace, manifest, Stage.SEGMENT):
        return _run_command(workspace, "build source cues once", "segment")

    cues_path = ws.require_artifact(
        workspace, manifest, Stage.SEGMENT, fix="openbbq segment"
    )
    try:
        ws.require_fresh_artifact(workspace, cues_path, Stage.SEGMENT)
    except OpenBBQError:
        return _run_command(
            workspace,
            "rebuild source cues because an input changed",
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
    human_reviewed = human_review_is_complete(workspace, cues, worksheet)
    missing_evidence = (
        []
        if human_reviewed
        else [
            item.id
            for item in worksheet.items
            if not _translation_evidence_valid(session, worksheet, item, policy)
        ]
    )
    if missing_evidence:
        selected_ids = missing_evidence[:MAX_AGENT_BATCH]
        items, neighbor_context, refs = _translation_batch_payload(
            worksheet, selected_ids
        )
        state_hash = _translation_state_hash(
            workspace, manifest, cues, worksheet, policy
        )
        payload = _new_lease(
            session,
            action="translate",
            selected_ids=selected_ids,
            issue_ids=[],
            source_hash=state_hash,
            policy_hash=policy,
            payload={
                "policy_hash": policy,
                "brief": brief.model_dump(mode="json", exclude_none=True),
                "selected_ids": selected_ids,
                "items": items,
                "neighbor_context": neighbor_context,
                "glossary": [
                    ref.model_dump(mode="json", exclude_none=True) for ref in refs
                ],
                "response_schema": {
                    "batch_id": "exact batch_id",
                    "policy_hash": policy,
                    "translations": {
                        str(item_id): "target text" for item_id in selected_ids
                    },
                    "source_fixes": [
                        {
                            "cue_id": "selected cue id",
                            "find": "exact source phrase",
                            "replacement": "correct phrase; may be empty to delete noise",
                            "occurrence": 1,
                            "reusable": "true only for a stable recurring name or term; otherwise false",
                            "evidence": "short contextual evidence",
                        }
                    ],
                    "warnings": [
                        "optional concise uncertainty that should not block the draft"
                    ],
                    "glossary_updates": [
                        {
                            "source": "new canonical term not already represented by a source_fix",
                            "aliases": ["optional reusable alternate form"],
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

    gate = draft_gate(workspace, manifest, session, cues, worksheet)
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
            "artifact_ready": True,
            "quality": "human-reviewed" if human_reviewed else "draft",
            "human_reviewed": human_reviewed,
            "glossary_published": finished.glossary_published,
            "quality_warnings": draft_warnings(cues, worksheet),
            "warnings": [
                warning.model_dump(mode="json") for warning in session.warnings
            ],
            "terminal": True,
            "must_continue": False,
        }
    session.finished = None
    inputs_hash = draft_inputs_hash(workspace, manifest, session, cues, worksheet)
    payload = _new_lease(
        session,
        action="finish",
        selected_ids=[],
        issue_ids=[],
        source_hash=inputs_hash,
        policy_hash=policy,
        payload={
            "argv": _workspace_argv(
                workspace, "agent", "finish", "--to", session.target_lang
            ),
            "execution": {
                "sandbox": "outside_required",
                "accelerator": "none",
                "cpu_fallback": "not_applicable",
                "reason_code": "media_encode_and_glossary_publish",
            },
            "outputs": {
                "subtitle": f"out/{session.target_lang}.ass",
                "video": f"out/{session.target_lang}-burned.mp4",
            },
            "quality": "human-reviewed" if human_reviewed else "draft",
            "human_reviewed": human_reviewed,
            "quality_warnings": draft_warnings(cues, worksheet),
            "note": "exports and burns once; no visual QA or fansub-compact pass",
        },
    )
    ws.write_agent_session(workspace, session)
    return payload


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
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_targets(self):
        if any(not target.strip() for target in self.translations.values()):
            raise ValueError("translations must be non-blank")
        self.warnings = list(
            dict.fromkeys(
                warning.strip() for warning in self.warnings if warning.strip()
            )
        )
        if len(self.warnings) > MAX_AGENT_BATCH:
            raise ValueError(f"at most {MAX_AGENT_BATCH} warnings are allowed")
        return self


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


def _apply_source(
    workspace: Path,
    manifest: Manifest,
    session: AgentSession,
    lease: AgentLease,
    response: _SourceResponse,
) -> dict[str, Any]:
    if len(response.reviewed_segment_ids) != len(lease.selected_ids) or set(
        response.reviewed_segment_ids
    ) != set(lease.selected_ids):
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
    if len(response.source_fixes) > MAX_AGENT_BATCH:
        raise OpenBBQError(
            "agent_batch_too_large",
            count=len(response.source_fixes),
            max=MAX_AGENT_BATCH,
        )
    if len(response.glossary_updates) > MAX_AGENT_BATCH:
        raise OpenBBQError(
            "agent_batch_too_large",
            count=len(response.glossary_updates),
            max=MAX_AGENT_BATCH,
        )
    invalid_fix_ids = sorted(
        {fix.segment_id for fix in response.source_fixes} - set(lease.selected_ids)
    )
    if invalid_fix_ids:
        raise OpenBBQError(
            "agent_source_fix_out_of_batch",
            ids=invalid_fix_ids,
        )
    transcript, review, reference_words = _transcript_context(workspace, manifest)
    merged = asrlib.merge_decisions(
        transcript,
        review,
        response.issue_decisions,
        reference_words=reference_words,
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
    updated_overlay, _, candidate_count = (
        glossary_overlay.prepare_updates_with_candidates(
            workspace,
            response.glossary_updates,
            response.source_fixes,
            origin="review_source",
        )
    )
    documents = {
        ws.asr_review_path(workspace): merged.model_dump_json(indent=2) + "\n",
    }
    if candidate_count or any(update.reusable for update in response.glossary_updates):
        documents[glossary_overlay.path(workspace)] = (
            updated_overlay.model_dump_json(indent=2) + "\n"
        )
    ws.write_texts_atomic(documents)
    transcribe_state = manifest.stages.get(Stage.TRANSCRIBE)
    if transcribe_state is not None:
        ws.record_stage(workspace, manifest, Stage.TRANSCRIBE, transcribe_state)

    session.active_lease = None
    session.finished = None
    ws.write_agent_session(workspace, session)
    return {
        "applied": "review_source",
        "reviewed_segments": len(lease.selected_ids),
        "source_fixes": len(response.source_fixes),
        "glossary_candidates": candidate_count,
        "glossary_updates": len(
            [update for update in response.glossary_updates if update.reusable]
        )
        + len([fix for fix in response.source_fixes if fix.reusable]),
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
    if len(response.translations) > MAX_AGENT_BATCH:
        raise OpenBBQError(
            "agent_batch_too_large",
            count=len(response.translations),
            max=MAX_AGENT_BATCH,
        )
    if len(response.source_fixes) > MAX_AGENT_BATCH:
        raise OpenBBQError(
            "agent_batch_too_large",
            count=len(response.source_fixes),
            max=MAX_AGENT_BATCH,
        )
    if len(response.glossary_updates) > MAX_AGENT_BATCH:
        raise OpenBBQError(
            "agent_batch_too_large",
            count=len(response.glossary_updates),
            max=MAX_AGENT_BATCH,
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
    source_changed_ids: set[int] = set()
    for fix in response.source_fixes:
        cue = cue_by_id.get(fix.cue_id)
        if cue is None:
            raise OpenBBQError("unknown_cue_ids", ids=[fix.cue_id])
        corrected = _replace_occurrence(cue.source, fix)
        cue.source = corrected
        item_by_id[fix.cue_id].source = corrected
        source_changed_ids.add(fix.cue_id)
    translatelib.apply_targets(candidate_worksheet, response.translations)

    updated_overlay, _, candidate_count = (
        glossary_overlay.prepare_updates_with_candidates(
            workspace,
            response.glossary_updates,
            response.source_fixes,
            origin="translate",
        )
    )
    effective = glossary_overlay.merged_overlay(
        workspace, updated_overlay, manifest.glossary
    )
    candidate_worksheet.glossary = _worksheet_glossary(effective)
    # A reusable alias is an explicit declaration that the spelling is safe to
    # canonicalize across this task. Apply the effective glossary immediately
    # so later batches do not have to rediscover the same ASR error cue by cue.
    normalize_source = glossarylib.corrector(effective)
    for cue in candidate_cues.cues:
        normalized = normalize_source(cue.source)
        if normalized == cue.source:
            continue
        cue.source = normalized
        item_by_id[cue.id].source = normalized
        source_changed_ids.add(cue.id)
    # Validate the complete candidate before either canonical product is
    # replaced.  This gives source-fix + translation logical atomicity.
    translatelib.verify_integrity(
        candidate_cues,
        candidate_worksheet,
        session.target_lang,
    )
    documents = {worksheet_path: candidate_worksheet.model_dump_json(indent=2) + "\n"}
    if source_changed_ids:
        # Preserve this order so the rollback test exercises the cross-document
        # boundary rather than a single worksheet replacement.
        documents = {
            cues_path: candidate_cues.model_dump_json(indent=2, exclude_none=True)
            + "\n",
            **documents,
        }
    if candidate_count or any(update.reusable for update in response.glossary_updates):
        documents[glossary_overlay.path(workspace)] = (
            updated_overlay.model_dump_json(indent=2) + "\n"
        )
    ws.write_texts_atomic(documents)
    if source_changed_ids:
        ws.refresh_artifact_provenance(workspace, cues_path, Stage.SEGMENT)
    for item_id in lease.selected_ids:
        item = item_by_id[item_id]
        session.translation_evidence[item_id] = TranslationEvidence(
            cue_hash=translatelib.item_hash(item),
            glossary_hash=_glossary_refs_hash(
                _cue_glossary_refs(candidate_worksheet, item_id)
            ),
            policy_hash=response.policy_hash,
            batch_id=lease.batch_id,
        )
    known_warnings = {(warning.code, warning.detail) for warning in session.warnings}
    session.warnings.extend(
        AgentWarning(code="translation_advisory", detail=detail)
        for detail in response.warnings
        if ("translation_advisory", detail) not in known_warnings
    )
    session.active_lease = None
    session.finished = None
    ws.write_agent_session(workspace, session)
    record_translation_progress(
        workspace,
        manifest,
        candidate_worksheet,
        complete=False,
    )
    report = translatelib.check(
        candidate_cues,
        candidate_worksheet,
        session.target_lang,
    )
    return {
        "applied": "translate",
        "translated": len(lease.selected_ids),
        "source_fixes": len(response.source_fixes),
        "glossary_candidates": candidate_count,
        "alias_normalized_cues": len(source_changed_ids - fix_ids),
        "glossary_updates": len(
            [update for update in response.glossary_updates if update.reusable]
        )
        + len([fix for fix in response.source_fixes if fix.reusable]),
        "warnings": len(response.warnings),
        "mechanical_warnings": {
            "over_budget": report.over_budget,
            "zero_budget": report.zero_budget,
            "term_ids": sorted({issue.id for issue in report.term_issues}),
        },
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
        if lease.action == "review_source":
            parsed = _SourceResponse.model_validate(value)
            return _apply_source(workspace, manifest, session, lease, parsed)
        if lease.action == "translate":
            parsed = _TranslateResponse.model_validate(value)
            return _apply_translate(workspace, manifest, session, lease, parsed)
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
    glossary_published: bool,
) -> None:
    session.finished = AgentFinished(
        inputs_hash=inputs_hash,
        subtitle=subtitle,
        video=video,
        glossary_published=glossary_published,
    )
    session.finish_pid = None
    session.active_lease = None
    ws.write_agent_session(workspace, session)

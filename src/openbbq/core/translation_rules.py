"""Target-language translation briefs.

The brief is intentionally small, fixed and data-driven.  It is sent with
every agent batch, so correctness does not depend on a harness remembering a
long Skill document.  The first specialised policy is Simplified Chinese;
all other targets use a clearly labelled generic fallback.
"""

from __future__ import annotations

import hashlib

from openbbq.schemas.translation import TranslationBrief

_ZH_HANS_TARGETS = {"zh", "zh-hans", "zh-cn"}

_ZH_HANS_RULES = [
    "输出忠实、自然、简洁的简体中文并使用中文标点；保留否定、数字、实体、条件和关键关系。",
    "每个 ID 只翻译当前 source；相邻 cue 仅用于理解上下文，不得在 ID 之间移动内容。",
    "glossary 只在语境明确匹配时使用；命令、代码、路径、flag、URL、产品名和模型名保持精确，除非 glossary 明确指定译名。",
    "明显的 ASR 错误用当前 cue 的 source_fix 提交；不确定时按当前原文翻译并给出 warning。",
    "每条译文必须能单行显示：宽度不超过 line_limit.max_width（全角字符记 1，半角字母、数字和空格记 0.6）。不必事先自行计算宽度：超宽时 apply 会指出具体 cue 与宽度，只改这些 cue 后重交同一批即可。翻译时就按字幕习惯精炼：保留事实、数字、否定和关键关系，删去口头禅、重复和冗余修饰；items[].budget.max_chars 是按语速给出的阅读参考，可略超。",
]

_GENERIC_RULES = [
    "Translate faithfully, naturally, and concisely into the target language; preserve negation, numbers, entities, conditions, and key relationships.",
    "Translate only the current source for each ID; use neighboring cues only as context and never move content between IDs.",
    "Use glossary entries only when the context clearly matches; keep commands, code, paths, flags, URLs, product names, and model names exact unless the glossary explicitly provides a translation.",
    "Submit a cue-scoped source_fix for an obvious ASR error; when uncertain, translate the current source and return a warning.",
    "Every target must fit on one subtitle line: its width must not exceed line_limit.max_width (see line_limit.counting). No need to measure widths yourself beforehand: an over-wide target makes apply return the exact cue ids and widths, so revise only those and resubmit the same batch. Condense as subtitlers do while translating: keep facts, numbers, negation, and key relationships; drop fillers, repetition, and redundant modifiers. items[].budget.max_chars is a reading-speed reference and may be slightly exceeded.",
]


def build_brief(
    source_lang: str,
    target_lang: str,
    *,
    title: str | None = None,
    author: str | None = None,
    glossary_context: str | None = None,
) -> TranslationBrief:
    """Build the stable policy for ``target_lang``.

    Traditional Chinese variants deliberately do not fall through to the
    Simplified Chinese ruleset.
    """

    normalized = target_lang.strip().lower().replace("_", "-")
    if normalized in _ZH_HANS_TARGETS:
        ruleset = "zh-Hans@2"
        generic = False
        rules = _ZH_HANS_RULES
    else:
        ruleset = "generic@2"
        generic = True
        rules = _GENERIC_RULES
    return TranslationBrief(
        source_lang=source_lang,
        target_lang=target_lang,
        ruleset=ruleset,
        generic_translation_rules=generic,
        title=title,
        author=author,
        domain_context=glossary_context,
        rules=list(rules),
    )


def policy_hash(brief: TranslationBrief) -> str:
    """Hash the exact brief so stale semantic evidence is detectable."""

    payload = brief.model_dump_json(by_alias=True, exclude_none=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

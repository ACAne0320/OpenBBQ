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
    "输出自然、简洁的简体中文，并使用中文标点。",
    "准确保留否定、程度、数字、实体、因果关系和操作步骤。",
    "相邻 cue 只用于消歧；译文必须与当前 cue 对齐，不得把内容漂移到其他 ID。",
    "严格遵守 glossary 的 target、keep、note 和官方大小写。",
    "命令、代码、路径、flag、URL、快捷键、产品名和模型名保持准确，除非 glossary 明确指定译名。",
    "可以压缩无语义 filler，但不得删除态度、条件或关键信息。",
    "含义和 cue 对齐优先于字符预算；无法安全压缩时标记风险，不得静默漏译。",
    "疑似 ASR 错误必须提交 source_fix，不能依据错误原文强行猜译。",
]

_GENERIC_RULES = [
    "Translate naturally and concisely into the target language, using its normal punctuation.",
    "Preserve negation, degree, numbers, entities, causality, and procedural steps.",
    "Use neighboring cues only for disambiguation; keep each translation aligned to the current cue ID.",
    "Follow every glossary target, keep instruction, note, and official casing.",
    "Keep commands, code, paths, flags, URLs, shortcuts, product names, and model names exact unless the glossary says otherwise.",
    "Meaning and cue alignment outrank the character budget; report a risk instead of silently omitting meaning.",
    "Return a source_fix for suspected ASR errors instead of guessing a translation from bad source text.",
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
        ruleset = "zh-Hans@1"
        generic = False
        rules = _ZH_HANS_RULES
    else:
        ruleset = "generic@1"
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

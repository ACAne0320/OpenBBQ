"""Subtitle rendering: join cues with an optional translation worksheet into a
subtitle file (SRT or ASS).

Source/target split (DESIGN translate spec): cues.json carries the timeline +
source, the per-language worksheet carries target. Export renders one visual
line per language: source/target modes emit one line, bilingual emits target
over source. Cue length belongs upstream in segmentation and translation budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import cast

from openbbq.core.translate import is_filled, verify_integrity
from openbbq.errors import OpenBBQError
from openbbq.schemas import Cue, Cues, Translation


class ExportMode(StrEnum):
    SOURCE = "source"  # original text only
    TARGET = "target"  # translated text only
    BILINGUAL = "bilingual"  # target line over source line


class AssPreset(StrEnum):
    DEFAULT = "default"
    COMPACT = "compact"
    FANSUB = "fansub"
    MOBILE = "mobile"


SUPPORTED_FORMATS = ("srt", "ass")
SUPPORTED_ASS_PRESETS = tuple(p.value for p in AssPreset)


def default_mode(to: str | None) -> ExportMode:
    """No --to -> source-only subtitles; otherwise the translated side."""
    return ExportMode.SOURCE if to is None else ExportMode.TARGET


def output_lang(cues: Cues, translation: Translation | None, mode: ExportMode) -> str:
    """Language label for the default out/<lang>.srt filename."""
    if mode is ExportMode.SOURCE or translation is None:
        return cues.source_lang
    return translation.target_lang


def _targets(translation: Translation | None) -> dict[int, str | None]:
    return {it.id: it.target for it in translation.items} if translation else {}


def missing_targets(
    cues: Cues, translation: Translation | None, mode: ExportMode
) -> list[int]:
    """Cue ids lacking a (non-blank) target, for a mode that needs one."""
    if mode is ExportMode.SOURCE:
        return []
    tg = _targets(translation)
    return [c.id for c in cues.cues if not is_filled(tg.get(c.id))]


def _timestamp(seconds: float) -> str:
    """Seconds -> SRT timecode HH:MM:SS,mmm (clamped at zero)."""
    ms_total = max(0, round(seconds * 1000))
    ms = ms_total % 1000
    s = ms_total // 1000 % 60
    m = ms_total // 60_000 % 60
    h = ms_total // 3_600_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_timestamp(seconds: float) -> str:
    """Seconds -> ASS timecode H:MM:SS.cc (centiseconds)."""
    cs_total = max(0, round(seconds * 100))
    cs = cs_total % 100
    s = cs_total // 100 % 60
    m = cs_total // 6_000 % 60
    h = cs_total // 360_000
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


_WHITESPACE_RE = re.compile(r"\s+")
_CJK_LANGS = {"zh", "ja"}
_CJK_PAUSE_PUNCT = "。．，,、；;：:"
_CJK_TERMINAL_STRIP = "。．，,、；;：:"
_LATIN_TERMINAL_STRIP = ",;:"


def _base_lang(lang: str) -> str:
    return lang.split("-", 1)[0].lower()


def _one_line(text: str, lang: str) -> str:
    """Collapse edited subtitle text to one rendered line.

    Explicit newlines are authoring conveniences, not SRT line breaks. CJK
    subtitles use lighter punctuation: pause marks become spaces and terminal
    sentence/pause marks are stripped, while semantic ?/! remain. Latin text
    keeps punctuation and only normalizes whitespace.
    """
    line = _WHITESPACE_RE.sub(" ", text.strip())
    if _base_lang(lang) in _CJK_LANGS:
        line = line.rstrip(_CJK_TERMINAL_STRIP)
        line = line.translate(str.maketrans({ch: " " for ch in _CJK_PAUSE_PUNCT}))
        line = _WHITESPACE_RE.sub(" ", line.strip())
    else:
        line = line.rstrip(_LATIN_TERMINAL_STRIP)
    return line


def _lines(
    cue: Cue,
    cues: Cues,
    translation: Translation | None,
    targets: dict[int, str | None],
    mode: ExportMode,
) -> list[str]:
    """Rendered text lines for one cue. Untranslated cues fall back to source."""
    source = _one_line(cue.source, cues.source_lang)
    if mode is ExportMode.SOURCE or translation is None:
        return [source]
    raw = targets.get(cue.id)
    target = (
        _one_line(cast("str", raw), translation.target_lang) if is_filled(raw) else None
    )
    if mode is ExportMode.TARGET:
        return [target] if target is not None else [source]  # allow_missing fallback
    # bilingual: translated line above the source line, matching common video subtitles.
    return [target, source] if target is not None else [source]


def _checked_targets(
    cues: Cues,
    translation: Translation | None,
    mode: ExportMode,
    allow_missing: bool,
    translation_lang: str | None,
) -> dict[int, str | None]:
    if mode is not ExportMode.SOURCE and translation is not None:
        verify_integrity(cues, translation, translation_lang or translation.target_lang)
    missing = missing_targets(cues, translation, mode)
    if missing and not allow_missing:
        raise OpenBBQError(
            "incomplete_translation",
            mode=mode.value,
            missing=missing[:20],  # bound the error-context size
            missing_count=len(missing),
            fix="translate the remaining cues, or pass --allow-missing to fall back to source",
        )
    return _targets(translation)


def render_srt(
    cues: Cues,
    mode: ExportMode,
    *,
    translation: Translation | None = None,
    allow_missing: bool = False,
    translation_lang: str | None = None,
) -> str:
    """Render cues (+ optional translation) to an SRT string. Raises
    incomplete_translation when a target/bilingual export has untranslated cues
    and --allow-missing is unset.
    """
    targets = _checked_targets(cues, translation, mode, allow_missing, translation_lang)
    blocks: list[str] = []
    for i, cue in enumerate(cues.cues, 1):
        body = "\n".join(_lines(cue, cues, translation, targets, mode))
        blocks.append(
            f"{i}\n{_timestamp(cue.start)} --> {_timestamp(cue.end)}\n{body}\n"
        )
    return "\n".join(blocks)


@dataclass(frozen=True)
class _AssStyle:
    name: str
    font: str
    size: int
    primary: str
    outline: str
    outline_width: int
    shadow: int
    margin_l: int
    margin_r: int
    margin_v: int
    bold: int = 0


@dataclass(frozen=True)
class _AssPresetConfig:
    play_res_x: int
    play_res_y: int
    styles: tuple[_AssStyle, ...]


_WHITE = "&H00FFFFFF"
_YELLOW = "&H0068F8FF"  # ASS uses AABBGGRR; this is warm yellow.
_SOFT_BLUE = "&H00FFD680"
_ASS_SECONDARY = "&H000000FF"
_BLACK = "&H00000000"
_BACK = "&H80000000"


def _style(
    name: str,
    font: str,
    size: int,
    *,
    margin_v: int,
    outline_width: int,
    primary: str = _WHITE,
    outline: str = _BLACK,
    shadow: int = 0,
    margin_x: int = 80,
    bold: int = 0,
) -> _AssStyle:
    return _AssStyle(
        name=name,
        font=font,
        size=size,
        primary=primary,
        outline=outline,
        outline_width=outline_width,
        shadow=shadow,
        margin_l=margin_x,
        margin_r=margin_x,
        margin_v=margin_v,
        bold=bold,
    )


_ASS_PRESETS: dict[AssPreset, _AssPresetConfig] = {
    AssPreset.DEFAULT: _AssPresetConfig(
        play_res_x=1920,
        play_res_y=1080,
        styles=(
            _style("ZH", "Hiragino Sans GB", 60, margin_v=46, outline_width=3),
            _style("ZH_TOP", "Hiragino Sans GB", 60, margin_v=96, outline_width=3),
            _style("EN", "Arial", 38, margin_v=32, outline_width=2),
            _style("EN_TOP", "Arial", 38, margin_v=88, outline_width=2),
            _style("DEFAULT", "Arial", 46, margin_v=42, outline_width=2),
            _style("DEFAULT_TOP", "Arial", 46, margin_v=92, outline_width=2),
        ),
    ),
    AssPreset.COMPACT: _AssPresetConfig(
        play_res_x=1920,
        play_res_y=1080,
        styles=(
            _style("ZH", "Hiragino Sans GB", 52, margin_v=34, outline_width=3),
            _style("ZH_TOP", "Hiragino Sans GB", 52, margin_v=78, outline_width=3),
            _style("EN", "Arial", 32, margin_v=24, outline_width=2),
            _style("EN_TOP", "Arial", 32, margin_v=70, outline_width=2),
            _style("DEFAULT", "Arial", 40, margin_v=32, outline_width=2),
            _style("DEFAULT_TOP", "Arial", 40, margin_v=76, outline_width=2),
        ),
    ),
    AssPreset.FANSUB: _AssPresetConfig(
        play_res_x=1920,
        play_res_y=1080,
        styles=(
            _style(
                "ZH",
                "Hiragino Sans GB",
                64,
                margin_v=48,
                outline_width=4,
                primary=_YELLOW,
            ),
            _style(
                "ZH_TOP",
                "Hiragino Sans GB",
                64,
                margin_v=104,
                outline_width=4,
                primary=_YELLOW,
            ),
            _style("EN", "Arial", 38, margin_v=30, outline_width=2, primary=_WHITE),
            _style("EN_TOP", "Arial", 38, margin_v=90, outline_width=2),
            _style(
                "DEFAULT",
                "Arial",
                48,
                margin_v=44,
                outline_width=3,
                primary=_SOFT_BLUE,
            ),
            _style(
                "DEFAULT_TOP",
                "Arial",
                48,
                margin_v=98,
                outline_width=3,
                primary=_SOFT_BLUE,
            ),
        ),
    ),
    AssPreset.MOBILE: _AssPresetConfig(
        play_res_x=1080,
        play_res_y=1920,
        styles=(
            _style(
                "ZH",
                "Hiragino Sans GB",
                52,
                margin_v=250,
                outline_width=4,
                margin_x=72,
            ),
            _style(
                "ZH_TOP",
                "Hiragino Sans GB",
                52,
                margin_v=320,
                outline_width=4,
                margin_x=72,
            ),
            _style(
                "EN",
                "Arial",
                31,
                margin_v=218,
                outline_width=3,
                margin_x=72,
            ),
            _style(
                "EN_TOP",
                "Arial",
                31,
                margin_v=292,
                outline_width=3,
                margin_x=72,
            ),
            _style(
                "DEFAULT",
                "Arial",
                42,
                margin_v=240,
                outline_width=3,
                margin_x=72,
            ),
            _style(
                "DEFAULT_TOP",
                "Arial",
                42,
                margin_v=312,
                outline_width=3,
                margin_x=72,
            ),
        ),
    ),
}


def _ass_style_line(style: _AssStyle) -> str:
    return (
        f"Style: {style.name},{style.font},{style.size},{style.primary},"
        f"{_ASS_SECONDARY},{style.outline},{_BACK},{style.bold},0,0,0,100,100,0,0,"
        f"1,{style.outline_width},{style.shadow},2,"
        f"{style.margin_l},{style.margin_r},{style.margin_v},1"
    )


def _ass_header(preset: AssPreset = AssPreset.DEFAULT) -> str:
    config = _ASS_PRESETS[preset]
    styles = "\n".join(_ass_style_line(style) for style in config.styles)
    return f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
PlayResX: {config.play_res_x}
PlayResY: {config.play_res_y}
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_style(lang: str, *, top: bool = False) -> str:
    base = _base_lang(lang)
    if base in _CJK_LANGS:
        style = "ZH"
    elif base == "en":
        style = "EN"
    else:
        style = "DEFAULT"
    return f"{style}_TOP" if top else style


def _ass_text(text: str) -> str:
    """Escape text that could be parsed as ASS override markup."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def render_ass(
    cues: Cues,
    mode: ExportMode,
    *,
    translation: Translation | None = None,
    allow_missing: bool = False,
    preset: AssPreset = AssPreset.DEFAULT,
    translation_lang: str | None = None,
) -> str:
    """Render cues (+ optional translation) to ASS.

    Bilingual ASS emits separate Dialogue events for target/source so each side
    can use independent font size, outline, and vertical position.
    """
    targets = _checked_targets(cues, translation, mode, allow_missing, translation_lang)
    events: list[str] = []
    for cue in cues.cues:
        start = _ass_timestamp(cue.start)
        end = _ass_timestamp(cue.end)
        source = _one_line(cue.source, cues.source_lang)
        raw = targets.get(cue.id)
        target = (
            _one_line(cast("str", raw), translation.target_lang)
            if translation is not None and is_filled(raw)
            else None
        )
        if mode is ExportMode.SOURCE or translation is None:
            rows = [(0, _ass_style(cues.source_lang), source)]
        elif mode is ExportMode.TARGET:
            rows = [(0, _ass_style(translation.target_lang), target or source)]
        else:
            rows = (
                [
                    (1, _ass_style(translation.target_lang, top=True), target),
                    (0, _ass_style(cues.source_lang), source),
                ]
                if target is not None
                else [(0, _ass_style(cues.source_lang), source)]
            )
        for layer, style, text in rows:
            events.append(
                f"Dialogue: {layer},{start},{end},{style},,0,0,0,,{_ass_text(text)}"
            )
    return _ass_header(preset) + "\n".join(events) + ("\n" if events else "")

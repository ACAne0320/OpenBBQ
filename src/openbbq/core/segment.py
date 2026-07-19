"""Source-side cue splitting: deterministic timeline arithmetic that turns the
ASR transcript's natural sentences into subtitle cues under language-aware
constraints (CPS / line width / duration / pauses).

A pure-function pipeline (DESIGN §8.1): group words into sentences, split any
that overflow, merge fragments, then finalize timing and warning counts. The
command shell (cli/commands/segment.py) wires this to the workspace; nothing
here touches I/O.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace

from openbbq.errors import OpenBBQError
from openbbq.schemas import Cue, Transcript, Word

_IDENTITY: Callable[[str], str] = lambda s: s  # noqa: E731 — default "no glossary" corrector

# Sentence-final vs. mid-sentence punctuation (latin + CJK), and closing
# quotes/brackets to look past when testing a word's terminal punctuation.
_SENTENCE_END = ".!?。！？…"
_SECONDARY = ",;:、；："
_TRAILING_CLOSERS = "\"'”’」』）)】]}>"
_MIN_COLLAPSED_WORDS = 3
_MIN_BOUNDARY_PILEUP_WORDS = 5


# --- language profiles --------------------------------------------------------


@dataclass(frozen=True)
class LanguageProfile:
    """Per-language cue constraints + the char-counting class (DESIGN §8.3)."""

    max_cps: float
    max_chars_per_line: int
    max_lines: int
    min_dur: float
    max_dur: float
    min_gap: float
    pause_threshold: float
    cjk: bool  # zh/ja: count full-width glyphs, no inter-word spaces


# Web-leaning defaults (YouTube/Bilibili horizontal), not broadcast-strict:
# one visual line per language, sized for the full subtitle-safe width rather
# than conservative two-line broadcast wraps. Keep natural sentences whole
# unless they exceed the real single-line screen budget or max duration.
# Pass --max-chars-per-line / --max-cps / ... for broadcast-strict subtitling.
LANGUAGE_PROFILES: dict[str, LanguageProfile] = {
    "en": LanguageProfile(21, 90, 1, 1.0, 7.0, 0.083, 0.3, cjk=False),
    "zh": LanguageProfile(11, 32, 1, 1.0, 7.0, 0.083, 0.3, cjk=True),
    "ja": LanguageProfile(5, 30, 1, 1.0, 7.0, 0.083, 0.3, cjk=True),
    "ko": LanguageProfile(14, 32, 1, 1.0, 7.0, 0.083, 0.3, cjk=False),  # per-char
}
DEFAULT_PROFILE = LANGUAGE_PROFILES["en"]  # generic latin fallback

_OVERRIDABLE = (
    "max_cps",
    "max_chars_per_line",
    "max_lines",
    "min_dur",
    "max_dur",
    "min_gap",
    "pause_threshold",
)


def resolve_profile(lang: str) -> tuple[LanguageProfile, bool]:
    """(profile, generic): generic=True when we fell back to the latin default.

    Matches on the base language subtag (``zh-Hans`` -> ``zh``).
    """
    key = lang.split("-")[0].lower()
    profile = LANGUAGE_PROFILES.get(key)
    if profile is None:
        return DEFAULT_PROFILE, True
    return profile, False


def apply_overrides(
    profile: LanguageProfile, **flags: float | int | None
) -> LanguageProfile:
    """Override profile fields from non-None CLI flags; return a new frozen profile."""
    changes = {k: v for k, v in flags.items() if k in _OVERRIDABLE and v is not None}
    return replace(profile, **changes) if changes else profile


def count_chars(text: str, profile: LanguageProfile) -> int:
    """Subtitle character count for CPS / line budgeting.

    CJK (zh/ja): count non-whitespace glyphs (each full-width char is one unit;
    CJK text carries no meaningful inter-word spaces). Otherwise count every
    character including spaces (Netflix latin convention).
    """
    if profile.cjk:
        return sum(1 for ch in text if not ch.isspace())
    return len(text)


# --- text reconstruction + line wrapping --------------------------------------


def _join(words: list[Word], profile: LanguageProfile) -> str:
    """Rebuild cue text from normalized words.

    ``Word.word`` is already normalized by the whisper.cpp adapter (leading
    spaces stripped, trailing punctuation attached to the preceding word), so
    CJK joins without spaces and latin joins with single spaces.
    """
    sep = "" if profile.cjk else " "
    return sep.join(w.word for w in words)


def pack_lines(tokens: list[str], profile: LanguageProfile) -> list[str]:
    """Greedy line packing: each line <= max_chars_per_line (by count_chars).

    Packing never breaks inside a token, so a token longer than the per-line cap
    lands on its own over-long line (caught by wrap_feasible). Used by segment
    for source-side feasibility; export renders each language as one line.
    """
    sep = "" if profile.cjk else " "
    lines: list[str] = []
    cur: list[str] = []
    for t in tokens:
        if cur and count_chars(sep.join([*cur, t]), profile) > profile.max_chars_per_line:
            lines.append(sep.join(cur))
            cur = [t]
        else:
            cur.append(t)
    if cur:
        lines.append(sep.join(cur))
    return lines


def wrap_lines(words: list[Word], profile: LanguageProfile) -> list[str]:
    """Greedy line packing over normalized words (feasibility side of pack_lines)."""
    return pack_lines([w.word for w in words], profile)


def wrap_feasible(words: list[Word], profile: LanguageProfile) -> bool:
    """Can these words pack into <= max_lines lines, each <= max_chars_per_line?"""
    lines = wrap_lines(words, profile)
    return len(lines) <= profile.max_lines and all(
        count_chars(line, profile) <= profile.max_chars_per_line for line in lines
    )


# --- pipeline -----------------------------------------------------------------


@dataclass(frozen=True)
class SegmentOutcome:
    """build_cues result: cues plus the warning counts the command surfaces.

    Counts ride the return value because Cue has no cps/warning field.
    """

    cues: list[Cue]
    over_cps: int  # cues exceeding max_cps (DESIGN §5 contract field)
    over_cap: int  # cues that couldn't be wrapped into the line budget


def invalid_cue_ids(cues: list[Cue]) -> list[int]:
    """Return cues whose timing cannot be rendered as a real subtitle span."""

    return [
        cue.id
        for cue in cues
        if not math.isfinite(cue.start)
        or not math.isfinite(cue.end)
        or cue.start < 0
        or cue.end <= cue.start
    ]


def require_valid_cue_timeline(cues: list[Cue]) -> None:
    invalid = invalid_cue_ids(cues)
    if invalid:
        raise OpenBBQError(
            "invalid_cue_timeline",
            ids=invalid[:20],
            total=len(invalid),
            fix="repair the ASR word timing and rerun openbbq segment",
        )


def _collapsed_segment_ids(transcript: Transcript) -> list[int]:
    invalid: list[int] = []
    for source_segment in transcript.segments:
        words = source_segment.words or []
        collapsed = sum(word.end <= word.start + 1e-6 for word in words)
        boundary = sum(
            abs(word.start - source_segment.end) <= 0.005
            or abs(word.end - source_segment.end) <= 0.005
            for word in words
        )
        if collapsed >= max(_MIN_COLLAPSED_WORDS, (len(words) + 4) // 5) or (
            boundary
            >= max(_MIN_BOUNDARY_PILEUP_WORDS, (len(words) + 3) // 4)
        ):
            invalid.append(source_segment.id)
    return invalid


def _duration(words: list[Word]) -> float:
    return words[-1].end - words[0].start


def _ends_with(text: str, marks: str) -> bool:
    """Does text end with one of ``marks``, looking past closing quotes/brackets?"""
    stripped = text.rstrip(_TRAILING_CLOSERS)
    return bool(stripped) and stripped[-1] in marks


def _reasonable_punctuation_split(k: int, n: int) -> bool:
    """Avoid splitting long sentences at a leading aside like "No," or "Well,"."""
    return n < 8 or (k >= 3 and n - k >= 3)


def _fits(words: list[Word], profile: LanguageProfile) -> bool:
    if not wrap_feasible(words, profile):
        return False
    if _duration(words) <= profile.max_dur:
        return True
    # Over max_dur, but a duration split is only sensible when there's enough
    # text to redistribute into readable cues. Text that fits a single line
    # can't be split into two cues without making fragments, so an over-long
    # span there is bogus timing (e.g. ASR swallowing trailing silence into the
    # last word) — keep it whole; finalize clamps the display duration.
    return count_chars(_join(words, profile), profile) <= profile.max_chars_per_line


def group_sentences(words: list[Word]) -> list[list[Word]]:
    """① Cut the word stream into sentences at sentence-final punctuation."""
    sentences: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        cur.append(w)
        if _ends_with(w.word, _SENTENCE_END):
            sentences.append(cur)
            cur = []
    if cur:
        sentences.append(cur)
    return sentences


def _best_split(words: list[Word], profile: LanguageProfile) -> int:
    """Pick the word-boundary split index (1..len-1) for an overflowing piece.

    Priority: secondary punctuation nearest the midpoint -> largest pause above
    threshold -> greedy by the overflowing dimension. Always returns a real
    split for len >= 2, so split_long makes progress and terminates.
    """
    n = len(words)
    mid = n / 2

    punct_ks = [
        i + 1
        for i in range(n - 1)
        if _ends_with(words[i].word, _SECONDARY)
        and _reasonable_punctuation_split(i + 1, n)
    ]
    if punct_ks:
        return min(punct_ks, key=lambda k: abs(k - mid))

    gap, gap_k = max(
        ((words[i + 1].start - words[i].end, i + 1) for i in range(n - 1)),
        key=lambda g: g[0],
    )
    if gap > profile.pause_threshold:
        return gap_k

    # Greedy fallback: split at the feasible word boundary nearest the character
    # midpoint, balancing the two pieces rather than cramming the first and
    # stranding a one-word widow (the remainder is then >= ~half, so it never
    # bottoms out as a tiny tail). A single oversized first word is peeled off so
    # we always make progress.
    over_lines = not wrap_feasible(words, profile)
    over_dur = _duration(words) > profile.max_dur
    total = count_chars(_join(words, profile), profile)
    best: tuple[int, int] | None = None  # (distance from midpoint, cand)
    for cand in range(1, n):
        prefix = words[:cand]
        if over_lines and not wrap_feasible(prefix, profile):
            continue
        if over_dur and _duration(prefix) > profile.max_dur:
            continue
        chars = count_chars(_join(prefix, profile), profile)
        key = (abs(2 * chars - total), cand)  # 2*chars-total == 2*(chars - total/2)
        if best is None or key < best:
            best = key
    return best[1] if best is not None else 1


def split_long(words: list[Word], profile: LanguageProfile) -> list[list[Word]]:
    """② Recursively split a sentence until each piece fits (or is one word)."""
    if len(words) <= 1 or _fits(words, profile):
        return [words]
    k = _best_split(words, profile)
    return split_long(words[:k], profile) + split_long(words[k:], profile)


def merge_short(
    pieces: list[list[Word]], profile: LanguageProfile
) -> list[list[Word]]:
    """③ Fold sub-min_dur pieces into the smaller-gap neighbor when it still fits."""
    result = [list(p) for p in pieces]
    i = 0
    while i < len(result):
        if _duration(result[i]) >= profile.min_dur or len(result) == 1:
            i += 1
            continue
        piece = result[i]
        prev_ok = i > 0 and _fits(result[i - 1] + piece, profile)
        next_ok = i < len(result) - 1 and _fits(piece + result[i + 1], profile)
        sentence_prefix = (
            i > 0
            and _ends_with(result[i - 1][-1].word, _SENTENCE_END)
            and not _ends_with(piece[-1].word, _SENTENCE_END)
        )
        if sentence_prefix:
            prev_ok = False
        prev_gap = piece[0].start - result[i - 1][-1].end if i > 0 else float("inf")
        next_gap = (
            result[i + 1][0].start - piece[-1].end
            if i < len(result) - 1
            else float("inf")
        )
        if prev_ok and (not next_ok or prev_gap <= next_gap):
            result[i - 1 : i + 1] = [result[i - 1] + piece]
            i = max(0, i - 1)  # re-check the merged piece (may still be short)
        elif next_ok:
            result[i : i + 2] = [piece + result[i + 1]]
        else:
            i += 1  # unmergeable; leave short (finalize is best-effort)
    return result


def finalize(
    pieces: list[list[Word]],
    profile: LanguageProfile,
    correct: Callable[[str], str] = _IDENTITY,
) -> SegmentOutcome:
    """④ Assign ids, resolve duration/gap, count warnings, build cues.

    Conflict policy (DESIGN §8.1): clamp to max_dur, extend toward min_dur only
    into available room, enforce min_gap by trimming the earlier end — never
    crossing a cue's own start, so no overlaps or negative durations are created.
    min_dur is therefore best-effort.

    ``correct`` is the glossary's ``alias -> source`` fixer, applied to the
    reconstructed cue text before CPS/warning counting so counts reflect what's
    actually displayed; default identity = no glossary (DESIGN glossary spec §6.2).
    """
    n = len(pieces)
    starts = [p[0].start for p in pieces]
    ends = [p[-1].end for p in pieces]

    for idx in range(n):
        dur = ends[idx] - starts[idx]
        if dur > profile.max_dur:
            ends[idx] = starts[idx] + profile.max_dur
        elif dur < profile.min_dur:
            limit = starts[idx + 1] - profile.min_gap if idx < n - 1 else float("inf")
            ends[idx] = min(starts[idx] + profile.min_dur, limit)
            if ends[idx] < starts[idx]:  # no room — keep the natural end
                ends[idx] = pieces[idx][-1].end

    for idx in range(1, n):
        if starts[idx] - ends[idx - 1] < profile.min_gap:
            trimmed = starts[idx] - profile.min_gap
            if trimmed >= starts[idx - 1]:  # never cross the cue's own start
                ends[idx - 1] = trimmed

    for idx in range(n - 1):
        # ASR word timestamps can already overlap; never let a cue cross the next.
        ends[idx] = min(ends[idx], starts[idx + 1])

    cues: list[Cue] = []
    over_cps = 0
    over_cap = 0
    for idx, piece in enumerate(pieces):
        start, end = starts[idx], ends[idx]
        text = correct(_join(piece, profile))
        dur = end - start
        cps = count_chars(text, profile) / dur if dur > 0 else float("inf")
        if cps > profile.max_cps:
            over_cps += 1
        if not wrap_feasible(piece, profile):
            over_cap += 1
        cues.append(Cue(id=idx + 1, start=start, end=end, source=text))
    require_valid_cue_timeline(cues)
    return SegmentOutcome(cues=cues, over_cps=over_cps, over_cap=over_cap)


def build_cues(
    transcript: Transcript,
    profile: LanguageProfile,
    correct: Callable[[str], str] = _IDENTITY,
) -> SegmentOutcome:
    """Source-side splitting entry point. Raises on missing word timestamps.

    ``correct`` (glossary fixer, default identity) is applied to each cue's
    reconstructed source text in ``finalize``.
    """
    collapsed = _collapsed_segment_ids(transcript)
    if collapsed:
        raise OpenBBQError(
            "invalid_word_timeline",
            segment_ids=collapsed[:20],
            total=len(collapsed),
            fix="resolve the ASR timeline anomaly before segmenting",
        )

    words: list[Word] = []
    for seg in transcript.segments:
        if not seg.words:
            raise OpenBBQError(
                "missing_word_timestamps",
                fix="re-transcribe with a word-capable backend",
            )
        words.extend(seg.words)
    if not words:
        return SegmentOutcome(cues=[], over_cps=0, over_cap=0)

    pieces: list[list[Word]] = []
    for sentence in group_sentences(words):
        pieces.extend(split_long(sentence, profile))
    pieces = merge_short(pieces, profile)
    return finalize(pieces, profile, correct)

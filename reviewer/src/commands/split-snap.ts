import type { TimedWord } from "../api/types";

export interface SplitSnap {
  time: number;
  word: TimedWord;
  edge: "start" | "end";
}

/**
 * Word-boundary snapping for split (§7): the default cut point aligns to the
 * nearest word boundary within `windowSeconds` of the playhead, as long as
 * the boundary stays strictly inside the cue.
 */
export function snapSplitPoint(
  at: number,
  words: TimedWord[],
  cueStart: number,
  cueEnd: number,
  windowSeconds = 0.5,
): SplitSnap | null {
  let best: SplitSnap | null = null;
  let bestDistance = Infinity;
  for (const word of words) {
    for (const edge of ["start", "end"] as const) {
      const time = edge === "start" ? word.start : word.end;
      if (time <= cueStart || time >= cueEnd) continue;
      const distance = Math.abs(time - at);
      if (distance > windowSeconds || distance >= bestDistance) continue;
      best = { time, word, edge };
      bestDistance = distance;
    }
  }
  return best;
}

/**
 * Maps a snapped word boundary to a character index in the cue's source
 * text: the occurrence of the word closest to the playhead-ratio guess.
 * Returns null when the word text cannot be located (fallback to cursor).
 */
export function sourceIndexForSnap(
  source: string,
  snap: SplitSnap,
  ratioGuess: number,
): number | null {
  const needle = snap.word.word;
  if (!needle) return null;
  const guess = Math.round(source.length * ratioGuess);
  let bestIndex: number | null = null;
  let bestDistance = Infinity;
  let from = 0;
  for (;;) {
    const index = source.indexOf(needle, from);
    if (index < 0) break;
    const boundary = snap.edge === "end" ? index + needle.length : index;
    const distance = Math.abs(boundary - guess);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = boundary;
    }
    from = index + needle.length;
  }
  return bestIndex;
}

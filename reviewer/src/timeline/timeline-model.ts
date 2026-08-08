export type NudgeTarget = "body" | "start" | "end";

export interface CueRange {
  start: number;
  end: number;
}

export interface CueBounds {
  minimum: number;
  maximum: number;
}

const MIN_CUE_DURATION = 0.05;
export const MAX_TIMELINE_ZOOM = 96;

function milliseconds(value: number): number {
  return Number(value.toFixed(3));
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

export function nudgeCueRange(
  range: CueRange,
  target: NudgeTarget,
  delta: number,
  mediaDuration: number,
  bounds: CueBounds = { minimum: 0, maximum: mediaDuration },
): CueRange {
  let nudged: CueRange;
  if (target === "body") {
    const cueDuration = range.end - range.start;
    const start = clamp(range.start + delta, 0, Math.max(0, mediaDuration - cueDuration));
    nudged = { start: milliseconds(start), end: milliseconds(start + cueDuration) };
  } else if (target === "start") {
    nudged = {
      start: milliseconds(clamp(range.start + delta, 0, range.end - MIN_CUE_DURATION)),
      end: milliseconds(range.end),
    };
  } else {
    nudged = {
      start: milliseconds(range.start),
      end: milliseconds(clamp(range.end + delta, range.start + MIN_CUE_DURATION, mediaDuration)),
    };
  }
  return constrainCueRange(nudged, target, bounds);
}

export function constrainCueRange(
  range: CueRange,
  target: NudgeTarget,
  bounds: CueBounds,
): CueRange {
  if (target === "body") {
    const cueDuration = range.end - range.start;
    const start = clamp(range.start, bounds.minimum, Math.max(bounds.minimum, bounds.maximum - cueDuration));
    return { start: milliseconds(start), end: milliseconds(start + cueDuration) };
  }
  if (target === "start") {
    return {
      start: milliseconds(clamp(range.start, bounds.minimum, range.end - MIN_CUE_DURATION)),
      end: milliseconds(range.end),
    };
  }
  return {
    start: milliseconds(range.start),
    end: milliseconds(clamp(range.end, range.start + MIN_CUE_DURATION, bounds.maximum)),
  };
}

export function cueMovementBounds(
  ranges: CueRange[],
  index: number,
  mediaDuration: number,
): CueBounds {
  const gaps = ranges
    .slice(1)
    .map((range, rangeIndex) => milliseconds(range.start - ranges[rangeIndex].end))
    .filter((gap) => gap >= 0);
  const minimumGap = gaps.length > 0 ? Math.min(...gaps) : 0;
  return {
    minimum: index > 0 ? milliseconds(ranges[index - 1].end + minimumGap) : 0,
    maximum:
      index >= 0 && index < ranges.length - 1
        ? milliseconds(ranges[index + 1].start - minimumGap)
        : mediaDuration,
  };
}

export function fitCueZoom(mediaDuration: number, range: CueRange): number {
  const cueDuration = Math.max(MIN_CUE_DURATION, range.end - range.start);
  const contextualWindow = Math.max(2, cueDuration * 3);
  return Math.max(
    1,
    Math.min(MAX_TIMELINE_ZOOM, Number((mediaDuration / contextualWindow).toFixed(1))),
  );
}

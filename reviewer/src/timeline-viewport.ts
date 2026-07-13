export interface TimelineViewRange {
  start: number;
  end: number;
}

const FOLLOW_MARGIN_RATIO = 1 / 12;

export function timelineViewRange(
  center: number,
  duration: number,
  viewDuration: number,
): TimelineViewRange {
  const width = Math.max(0, Math.min(duration, viewDuration));
  const start = Math.max(0, Math.min(Math.max(0, duration - width), center - width / 2));
  return { start, end: Math.min(duration, start + width) };
}

export function followTimelineCenter(
  center: number,
  playbackTime: number,
  duration: number,
  viewDuration: number,
): number {
  const range = timelineViewRange(center, duration, viewDuration);
  const margin = (range.end - range.start) * FOLLOW_MARGIN_RATIO;
  return playbackTime < range.start + margin || playbackTime > range.end - margin
    ? playbackTime
    : center;
}

export function timelineDataRange(
  center: number,
  duration: number,
  viewDuration: number,
): TimelineViewRange {
  const bucketWidth = Math.max(0.001, Math.min(duration, viewDuration));
  const dataWidth = Math.min(duration, bucketWidth * 3);
  const bucketCenter = (Math.floor(center / bucketWidth) + 0.5) * bucketWidth;
  const start = Math.max(0, Math.min(Math.max(0, duration - dataWidth), bucketCenter - dataWidth / 2));
  return { start, end: Math.min(duration, start + dataWidth) };
}

export function waveformPeakTime(
  index: number,
  peakCount: number,
  start: number,
  end: number,
): number {
  if (peakCount <= 1) return (start + end) / 2;
  return start + (index / (peakCount - 1)) * (end - start);
}

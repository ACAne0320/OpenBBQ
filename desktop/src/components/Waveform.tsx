import { clsx } from "clsx";

import { formatRange } from "../lib/format";
import type { Segment, WaveformBar } from "../lib/types";

type WaveformProps = {
  activeSegmentId: string;
  durationMs: number;
  segments: Segment[];
  waveform: WaveformBar[];
  onSelectSegment: (segmentId: string) => void;
};

function boundedPercent(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }

  return Math.min(100, Math.max(0, value));
}

function segmentPosition(segment: Segment, durationMs: number) {
  if (durationMs <= 0) {
    return { left: "0%", width: "0%" };
  }

  const segmentStart = Math.min(segment.startMs, segment.endMs);
  const segmentEnd = Math.max(segment.startMs, segment.endMs);
  const clippedStart = Math.min(durationMs, Math.max(0, segmentStart));
  const clippedEnd = Math.min(durationMs, Math.max(0, segmentEnd));
  const left = boundedPercent((clippedStart / durationMs) * 100);
  const rawWidth = boundedPercent(((clippedEnd - clippedStart) / durationMs) * 100);
  const width = Math.min(rawWidth, 100 - left);

  return {
    left: `${left}%`,
    width: `${Math.max(0, width)}%`
  };
}

export function Waveform({ activeSegmentId, durationMs, onSelectSegment, segments, waveform }: WaveformProps) {
  return (
    <div className="relative h-32 overflow-hidden rounded-lg bg-paper-muted shadow-control">
      <div className="absolute inset-x-4 top-1/2 h-px bg-[#d6c7ae]" />

      <div className="absolute inset-x-[18px] bottom-5 top-5 flex items-center gap-[3px]" aria-hidden="true">
        {waveform.map((bar) => (
          <span
            key={bar.id}
            data-testid="waveform-bar"
            className="w-1 flex-1 rounded-sm bg-[#b9a98e]"
            style={{ height: `${Math.max(8, Math.min(96, bar.level))}%` }}
          />
        ))}
      </div>

      {segments.map((segment) => {
        const active = segment.id === activeSegmentId;

        return (
          <button
            key={segment.id}
            type="button"
            aria-label={`Waveform segment ${segment.index}, ${formatRange(segment.startMs, segment.endMs)}`}
            aria-pressed={active}
            data-testid="waveform-segment-overlay"
            onClick={() => onSelectSegment(segment.id)}
            className={clsx(
              "absolute top-3 h-[104px] rounded-md transition-transform duration-150 active:scale-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
              active ? "bg-accent/30 shadow-selected" : "bg-accent/15 shadow-control [@media(hover:hover)]:hover:bg-accent/25"
            )}
            style={segmentPosition(segment, durationMs)}
          >
            <span className="sr-only">Select segment {segment.index}</span>
          </button>
        );
      })}
    </div>
  );
}

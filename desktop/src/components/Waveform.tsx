import { clsx } from "clsx";
import { type MouseEvent, useEffect, useMemo, useRef } from "react";

import { formatRange } from "../lib/format";
import type { Segment, WaveformBar } from "../lib/types";

type WaveformProps = {
  activeSegmentId: string;
  currentMs: number;
  durationMs: number;
  pixelsPerSecond: number;
  segments: Segment[];
  waveform: WaveformBar[];
  onSelectSegment: (segmentId: string) => void;
  onSeekMs: (timeMs: number) => void;
};

function boundedNumber(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }

  return Math.max(0, value);
}

function timelineWidth(durationMs: number, pixelsPerSecond: number): number {
  if (durationMs <= 0 || pixelsPerSecond <= 0) {
    return 1;
  }

  return Math.max(1, Math.round((durationMs / 1000) * pixelsPerSecond));
}

function segmentPosition(segment: Segment, durationMs: number, pixelsPerSecond: number) {
  if (durationMs <= 0 || pixelsPerSecond <= 0) {
    return { left: "0px", width: "0px" };
  }

  const segmentStart = Math.min(segment.startMs, segment.endMs);
  const segmentEnd = Math.max(segment.startMs, segment.endMs);
  const clippedStart = Math.min(durationMs, Math.max(0, segmentStart));
  const clippedEnd = Math.min(durationMs, Math.max(0, segmentEnd));
  const left = boundedNumber((clippedStart / 1000) * pixelsPerSecond);
  const width = boundedNumber(((clippedEnd - clippedStart) / 1000) * pixelsPerSecond);

  return {
    left: `${left}px`,
    width: `${width}px`
  };
}

function clampTime(timeMs: number, durationMs: number): number {
  if (!Number.isFinite(timeMs)) {
    return 0;
  }

  return Math.min(Math.max(0, durationMs), Math.max(0, timeMs));
}

export function Waveform({
  activeSegmentId,
  currentMs,
  durationMs,
  onSeekMs,
  onSelectSegment,
  pixelsPerSecond,
  segments,
  waveform
}: WaveformProps) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const widthPx = useMemo(() => timelineWidth(durationMs, pixelsPerSecond), [durationMs, pixelsPerSecond]);
  const playheadLeft = (clampTime(currentMs, durationMs) / 1000) * Math.max(0, pixelsPerSecond);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller || scroller.clientWidth <= 0) {
      return;
    }

    const leftEdge = scroller.scrollLeft;
    const rightEdge = leftEdge + scroller.clientWidth;
    if (playheadLeft < leftEdge + 48 || playheadLeft > rightEdge - 96) {
      scroller.scrollLeft = Math.max(0, playheadLeft - scroller.clientWidth * 0.35);
    }
  }, [playheadLeft]);

  function handleTrackClick(event: MouseEvent<HTMLDivElement>) {
    const track = trackRef.current;
    if (!track || pixelsPerSecond <= 0) {
      return;
    }

    const rect = track.getBoundingClientRect();
    const localX = event.clientX - rect.left;
    onSeekMs(clampTime((localX / pixelsPerSecond) * 1000, durationMs));
  }

  return (
    <div
      ref={scrollerRef}
      className="relative h-32 w-full min-w-0 overflow-x-auto overflow-y-hidden rounded-lg bg-paper-muted shadow-control"
    >
      <div
        ref={trackRef}
        data-testid="timeline-track"
        className="relative h-full cursor-crosshair"
        style={{ minWidth: `${widthPx}px` }}
        onClick={handleTrackClick}
      >
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
              onClick={(event) => {
                event.stopPropagation();
                onSelectSegment(segment.id);
              }}
              className={clsx(
                "absolute top-3 h-[104px] rounded-md transition-transform duration-150 active:scale-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                active ? "bg-accent/30 shadow-selected" : "bg-accent/15 shadow-control [@media(hover:hover)]:hover:bg-accent/25"
              )}
              style={segmentPosition(segment, durationMs, pixelsPerSecond)}
            >
              <span className="sr-only">Select segment {segment.index}</span>
            </button>
          );
        })}

        <div
          aria-hidden="true"
          className="pointer-events-none absolute bottom-3 top-3 w-px bg-log-bg shadow-[0_0_0_1px_rgba(255,248,234,0.8)]"
          style={{ left: `${playheadLeft}px` }}
        />
      </div>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { readTimelinePalette } from "./palette";
import { constrainCueRange, cueMovementBounds, type CueBounds } from "./timeline-model";
import {
  followTimelineCenter,
  timelineDataRange,
  timelineViewRange,
  waveformPeakTime,
} from "./timeline-viewport";
import type { Cue, TimedWord, WaveformResponse } from "../api/types";

interface Props {
  cues: Cue[];
  currentTime: number;
  duration: number;
  selectedId: number | null;
  zoom: number;
  large: boolean;
  snapEnabled: boolean;
  theme: "light" | "dark";
  ariaLabel: string;
  isPlaying: boolean;
  getPlaybackTime: () => number;
  onSeek: (time: number) => void;
  onSelect: (id: number) => void;
  onTimeChange: (id: number, start: number, end: number) => Promise<void>;
  /** Reports fetched word timings (consumed by split word-boundary snapping). */
  onWordsLoaded?: (words: TimedWord[], range: { start: number; end: number }) => void;
}

type DragMode = "start" | "end" | "body";

/**
 * Interaction state machine (design §5.4):
 * idle → (pointerdown on cue) pending → (≥4px move) dragging-edge/body;
 * pointerup from pending = plain click (selection only, zero mutation);
 * pointercancel always returns to idle without mutating.
 * Empty-track pointerdown seeks immediately (seeking is instantaneous).
 */
interface DragState {
  cue: Cue;
  bounds: CueBounds;
  mode: DragMode;
  active: boolean;
  pointerStartX: number;
  pointerStartTime: number;
  draftStart: number;
  draftEnd: number;
  snapGuide: number | null;
}

const DRAG_THRESHOLD_PX = 4;

export function Timeline({
  cues,
  currentTime,
  duration,
  selectedId,
  zoom,
  large,
  snapEnabled,
  theme,
  ariaLabel,
  isPlaying,
  getPlaybackTime,
  onSeek,
  onSelect,
  onTimeChange,
  onWordsLoaded,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const baseCanvasRef = useRef<HTMLCanvasElement>(null);
  const overlayCanvasRef = useRef<HTMLCanvasElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const overlayDrawRef = useRef<() => void>(() => undefined);
  const wheelContextRef = useRef({ zoom, duration, viewDuration: 2, width: 1 });
  const [size, setSize] = useState({ width: 900, height: large ? 250 : 168 });
  const [waveform, setWaveform] = useState<WaveformResponse | null>(null);
  const [words, setWords] = useState<TimedWord[]>([]);
  const [dragCueId, setDragCueId] = useState<number | null>(null);
  const [viewCenter, setViewCenter] = useState(currentTime);
  const [palette, setPalette] = useState(() => readTimelinePalette(theme));
  // Re-read in a passive effect: by then the ThemeProvider's layout effect has
  // applied the theme class, so getComputedStyle sees the NEW theme (reading
  // during render samples the pre-toggle class — one theme behind).
  useEffect(() => {
    setPalette(readTimelinePalette(theme));
  }, [theme]);
  const viewDuration = Math.max(2, duration / zoom);
  const { start: viewStart, end: viewEnd } = timelineViewRange(viewCenter, duration, viewDuration);
  const { start: dataStart, end: dataEnd } = timelineDataRange(viewCenter, duration, viewDuration);
  const dataPixels = Math.min(
    10_000,
    Math.max(100, Math.round(size.width * ((dataEnd - dataStart) / (viewEnd - viewStart || 1)))),
  );

  useEffect(() => {
    setViewCenter(currentTime);
  }, [zoom]);

  useEffect(() => {
    setViewCenter((center) => followTimelineCenter(center, currentTime, duration, viewDuration));
  }, [currentTime, duration, viewDuration]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(([entry]) => {
      setSize({
        width: Math.max(320, Math.round(entry.contentRect.width)),
        height: large ? 250 : 168,
      });
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [large]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      Promise.all([api.waveform(dataStart, dataEnd, dataPixels), api.words(dataStart, dataEnd)])
        .then(([peaks, wordResponse]) => {
          if (!controller.signal.aborted) {
            setWaveform(peaks);
            setWords(wordResponse.words);
            onWordsLoaded?.(wordResponse.words, { start: dataStart, end: dataEnd });
          }
        })
        .catch(() => {
          if (!controller.signal.aborted) setWaveform(null);
        });
    }, 80);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [dataStart, dataEnd, dataPixels, onWordsLoaded]);

  const visibleCues = useMemo(
    () => cues.filter((cue) => cue.end >= viewStart && cue.start <= viewEnd),
    [cues, viewStart, viewEnd],
  );

  const xFor = (time: number) => ((time - viewStart) / (viewEnd - viewStart || 1)) * size.width;
  const timeFor = (x: number) => viewStart + (x / size.width) * (viewEnd - viewStart);

  const snap = (
    time: number,
    cueId: number,
    options: { includePlayhead?: boolean; thresholdPixels?: number } = {},
  ) => {
    const clamped = Math.max(0, Math.min(duration, time));
    if (!snapEnabled) return { time: clamped, guide: null };
    const threshold = ((viewEnd - viewStart) / size.width) * (options.thresholdPixels ?? 10);
    const candidates = options.includePlayhead === false ? [] : [currentTime];
    for (const cue of visibleCues) {
      if (cue.id !== cueId) candidates.push(cue.start, cue.end);
    }
    for (const word of words) candidates.push(word.start, word.end);
    let best = clamped;
    let distance = threshold;
    for (const candidate of candidates) {
      const candidateDistance = Math.abs(candidate - clamped);
      if (candidateDistance < distance) {
        distance = candidateDistance;
        best = candidate;
      }
    }
    return { time: best, guide: best === clamped ? null : best };
  };

  useEffect(() => {
    const canvas = baseCanvasRef.current;
    if (!canvas) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(size.width * ratio);
    canvas.height = Math.round(size.height * ratio);
    const context = canvas.getContext("2d");
    if (!context) return;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, size.width, size.height);
    context.fillStyle = palette.background;
    context.fillRect(0, 0, size.width, size.height);

    const rulerHeight = 27;
    const cueTop = size.height - 49;
    const cueHeight = 34;
    const waveformTop = rulerHeight + 5;
    const waveformBottom = cueTop - 9;
    const waveformCenter = (waveformTop + waveformBottom) / 2;

    context.strokeStyle = palette.grid;
    context.fillStyle = palette.muted;
    context.font = '10px "JetBrains Mono Variable", ui-monospace, monospace';
    const tick = viewDuration <= 10 ? 1 : viewDuration <= 60 ? 5 : viewDuration <= 300 ? 30 : 60;
    for (let time = Math.ceil(viewStart / tick) * tick; time <= viewEnd; time += tick) {
      const x = xFor(time);
      context.beginPath();
      context.moveTo(x, rulerHeight - 4);
      context.lineTo(x, size.height);
      context.stroke();
      context.fillText(formatRuler(time), x + 4, 16);
    }

    if (waveform?.peaks.length) {
      context.beginPath();
      waveform.peaks.forEach((peak, index) => {
        const x = xFor(waveformPeakTime(index, waveform.peaks.length, waveform.start, waveform.end));
        const y = waveformCenter - peak[1] * (waveformBottom - waveformTop) * 0.46;
        if (index === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      });
      for (let index = waveform.peaks.length - 1; index >= 0; index--) {
        const peak = waveform.peaks[index];
        const x = xFor(waveformPeakTime(index, waveform.peaks.length, waveform.start, waveform.end));
        const y = waveformCenter - peak[0] * (waveformBottom - waveformTop) * 0.46;
        context.lineTo(x, y);
      }
      context.closePath();
      context.fillStyle = palette.waveformFill;
      context.fill();
      context.strokeStyle = palette.waveform;
      context.lineWidth = 1;
      context.stroke();
    }

    for (const word of words) {
      const x = xFor(word.start);
      context.strokeStyle = palette.word;
      context.beginPath();
      context.moveTo(x, waveformBottom - 8);
      context.lineTo(x, waveformBottom);
      context.stroke();
    }

    for (const cue of visibleCues) {
      if (cue.id === dragCueId) continue;
      const start = cue.start;
      const end = cue.end;
      const x = xFor(start);
      const width = Math.max(3, xFor(end) - x);
      const selected = cue.id === selectedId;
      context.fillStyle = selected
        ? palette.selected
        : cue.status === "reviewed"
          ? palette.reviewed
          : cue.status === "flagged"
            ? palette.flagged
            : palette.cue;
      context.fillRect(x, cueTop, width, cueHeight);
      context.strokeStyle = selected ? palette.selectedBorder : palette.grid;
      context.lineWidth = selected ? 1.5 : 1;
      context.strokeRect(x + 0.5, cueTop + 0.5, Math.max(2, width - 1), cueHeight - 1);
      context.fillStyle = palette.foreground;
      context.font = '10px "Geist Variable", system-ui, sans-serif';
      context.save();
      context.beginPath();
      context.rect(x + 7, cueTop, Math.max(0, width - 14), cueHeight);
      context.clip();
      context.fillText(`#${cue.id} ${cue.source}`, x + 8, cueTop + 21);
      context.restore();
      if (selected) {
        context.fillStyle = palette.handle;
        roundRect(context, x - 3, cueTop + 5, 7, 24, 3);
        roundRect(context, x + width - 4, cueTop + 5, 7, 24, 3);
      }
    }
  }, [size, waveform, words, visibleCues, selectedId, dragCueId, viewStart, viewEnd, palette, viewDuration]);

  useEffect(() => {
    const canvas = overlayCanvasRef.current;
    if (!canvas) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(size.width * ratio);
    canvas.height = Math.round(size.height * ratio);
  }, [size]);

  useEffect(() => {
    let animationFrame = 0;
    const paintOverlay = () => {
      const canvas = overlayCanvasRef.current;
      if (!canvas) return;
      const ratio = window.devicePixelRatio || 1;
      const context = canvas.getContext("2d");
      if (!context) return;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, size.width, size.height);
      const xForOverlay = (time: number) => ((time - viewStart) / (viewEnd - viewStart || 1)) * size.width;
      const drag = dragRef.current;
      if (drag?.active) {
        const cueTop = size.height - 49;
        const cueHeight = 34;
        const x = xForOverlay(drag.draftStart);
        const width = Math.max(3, xForOverlay(drag.draftEnd) - x);
        context.fillStyle = palette.selected;
        context.fillRect(x, cueTop, width, cueHeight);
        context.strokeStyle = palette.selectedBorder;
        context.lineWidth = 1.5;
        context.strokeRect(x + 0.5, cueTop + 0.5, Math.max(2, width - 1), cueHeight - 1);
        context.fillStyle = palette.foreground;
        context.font = '10px "Geist Variable", system-ui, sans-serif';
        context.save();
        context.beginPath();
        context.rect(x + 7, cueTop, Math.max(0, width - 14), cueHeight);
        context.clip();
        context.fillText(`#${drag.cue.id} ${drag.cue.source}`, x + 8, cueTop + 21);
        context.restore();
        context.fillStyle = palette.handle;
        roundRect(context, x - 3, cueTop + 5, 7, 24, 3);
        roundRect(context, x + width - 4, cueTop + 5, 7, 24, 3);
        if (drag.snapGuide != null) {
          const guideX = xForOverlay(drag.snapGuide);
          context.strokeStyle = palette.selectedBorder;
          context.setLineDash([3, 3]);
          context.beginPath();
          context.moveTo(guideX, 27);
          context.lineTo(guideX, size.height);
          context.stroke();
          context.setLineDash([]);
        }
      }
      const playbackTime = getPlaybackTime();
      const playheadX = xForOverlay(playbackTime);
      if (playheadX >= 0 && playheadX <= size.width) {
        context.strokeStyle = palette.playhead;
        context.lineWidth = 1.5;
        context.beginPath();
        context.moveTo(playheadX, 0);
        context.lineTo(playheadX, size.height);
        context.stroke();
        context.fillStyle = palette.playhead;
        context.beginPath();
        context.moveTo(playheadX - 5, 0);
        context.lineTo(playheadX + 5, 0);
        context.lineTo(playheadX, 7);
        context.closePath();
        context.fill();
      }
    };
    const animateOverlay = () => {
      paintOverlay();
      if (isPlaying) animationFrame = window.requestAnimationFrame(animateOverlay);
    };
    overlayDrawRef.current = paintOverlay;
    animateOverlay();
    return () => {
      window.cancelAnimationFrame(animationFrame);
      if (overlayDrawRef.current === paintOverlay) overlayDrawRef.current = () => undefined;
    };
  }, [getPlaybackTime, isPlaying, palette, size, viewEnd, viewStart]);

  useEffect(() => {
    overlayDrawRef.current();
  }, [currentTime]);

  // Wheel pan via a native non-passive listener so preventDefault works; the
  // pan distance follows the wheel delta magnitude (trackpad-friendly).
  useEffect(() => {
    wheelContextRef.current = { zoom, duration, viewDuration, width: size.width };
  });

  useEffect(() => {
    const canvas = overlayCanvasRef.current;
    if (!canvas) return;
    const onWheel = (event: WheelEvent) => {
      const context = wheelContextRef.current;
      if (context.zoom <= 1 || context.width <= 0) return;
      const delta = event.deltaX || event.deltaY;
      if (delta === 0) return;
      event.preventDefault();
      const secondsPerPixel = context.viewDuration / context.width;
      setViewCenter((center) =>
        Math.max(0, Math.min(context.duration, center + delta * secondsPerPixel)),
      );
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, []);

  const pointerPosition = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return Math.max(0, Math.min(size.width, event.clientX - rect.left));
  };

  const hitAt = (x: number) => {
    const time = timeFor(x);
    return [...visibleCues].reverse().find((cue) => time >= cue.start && time <= cue.end);
  };

  const boundsFor = (cue: Cue) => {
    const index = cues.findIndex((item) => item.id === cue.id);
    return cueMovementBounds(cues, index, duration);
  };

  const handlePointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const x = pointerPosition(event);
    const time = timeFor(x);
    const hit = hitAt(x);
    if (!hit) {
      onSeek(time);
      return;
    }
    onSelect(hit.id);
    const leftDistance = Math.abs(x - xFor(hit.start));
    const rightDistance = Math.abs(x - xFor(hit.end));
    const mode: DragMode = leftDistance <= 10 ? "start" : rightDistance <= 10 ? "end" : "body";
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      cue: hit,
      bounds: boundsFor(hit),
      mode,
      active: false,
      pointerStartX: x,
      pointerStartTime: time,
      draftStart: hit.start,
      draftEnd: hit.end,
      snapGuide: null,
    };
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const x = pointerPosition(event);
    const drag = dragRef.current;
    if (!drag) {
      const hit = hitAt(x);
      if (!hit) event.currentTarget.style.cursor = "crosshair";
      else if (Math.abs(x - xFor(hit.start)) <= 10 || Math.abs(x - xFor(hit.end)) <= 10) {
        event.currentTarget.style.cursor = "ew-resize";
      } else event.currentTarget.style.cursor = "grab";
      return;
    }
    if (!drag.active) {
      if (Math.abs(x - drag.pointerStartX) < DRAG_THRESHOLD_PX) return;
      drag.active = true;
      event.currentTarget.style.cursor = drag.mode === "body" ? "grabbing" : "ew-resize";
      setDragCueId(drag.cue.id);
    }
    const time = timeFor(x);
    const delta = time - drag.pointerStartTime;
    if (drag.mode === "start") {
      const result = snap(time, drag.cue.id);
      const constrained = constrainCueRange(
        { start: Math.min(drag.draftEnd - 0.05, result.time), end: drag.draftEnd },
        "start",
        drag.bounds,
      );
      dragRef.current = { ...drag, draftStart: constrained.start, snapGuide: result.guide };
    } else if (drag.mode === "end") {
      const result = snap(time, drag.cue.id);
      const constrained = constrainCueRange(
        { start: drag.draftStart, end: Math.max(drag.draftStart + 0.05, result.time) },
        "end",
        drag.bounds,
      );
      dragRef.current = { ...drag, draftEnd: constrained.end, snapGuide: result.guide };
    } else {
      const length = drag.cue.end - drag.cue.start;
      const result = snap(drag.cue.start + delta, drag.cue.id, {
        includePlayhead: false,
        thresholdPixels: 3,
      });
      const constrained = constrainCueRange(
        { start: result.time, end: result.time + length },
        "body",
        drag.bounds,
      );
      dragRef.current = {
        ...drag,
        draftStart: constrained.start,
        draftEnd: constrained.end,
        snapGuide: result.guide,
      };
    }
    overlayDrawRef.current();
  };

  const resetDrag = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    event.currentTarget.style.cursor = "crosshair";
    dragRef.current = null;
    setDragCueId(null);
    overlayDrawRef.current();
  };

  const handlePointerUp = async (event: React.PointerEvent<HTMLCanvasElement>) => {
    const completed = dragRef.current;
    if (!completed) return;
    resetDrag(event);
    // Sub-threshold press = plain click: selection already happened, no mutation.
    if (!completed.active) return;
    const start = Number(completed.draftStart.toFixed(3));
    const end = Number(completed.draftEnd.toFixed(3));
    if (start === completed.cue.start && end === completed.cue.end) return;
    await onTimeChange(completed.cue.id, start, end);
  };

  const handlePointerCancel = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!dragRef.current) return;
    resetDrag(event);
  };

  return (
    <div
      ref={containerRef}
      className={`timeline-stack ${large ? "timeline-large" : ""}`}
      style={{ height: size.height }}
    >
      <canvas ref={baseCanvasRef} className="timeline timeline-base" aria-hidden="true" />
      <canvas
        ref={overlayCanvasRef}
        className="timeline timeline-overlay"
        tabIndex={0}
        aria-label={ariaLabel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={(event) => void handlePointerUp(event)}
        onPointerCancel={handlePointerCancel}
      />
    </div>
  );
}

function roundRect(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  context.beginPath();
  context.roundRect(x, y, width, height, radius);
  context.fill();
}

function formatRuler(seconds: number) {
  const minute = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${String(minute).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

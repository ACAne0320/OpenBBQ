import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { constrainCueRange, cueMovementBounds, type CueBounds } from "./timeline-model";
import {
  followTimelineCenter,
  timelineDataRange,
  timelineViewRange,
  waveformPeakTime,
} from "./timeline-viewport";
import type { Cue, TimedWord, WaveformResponse } from "./types";

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
}

type DragMode = "start" | "end" | "body";

interface DragState {
  cue: Cue;
  bounds: CueBounds;
  mode: DragMode;
  pointerStart: number;
  draftStart: number;
  draftEnd: number;
  snapGuide: number | null;
}

const PALETTES = {
  dark: {
    background: "#101315",
    foreground: "#e9e9e7",
    muted: "#8b9396",
    waveform: "#b7bec0",
    waveformFill: "rgba(183, 190, 192, .17)",
    cue: "#263238",
    reviewed: "#244235",
    flagged: "#5a3e27",
    selected: "#9f3024",
    selectedBorder: "#f05a43",
    playhead: "#f05a43",
    grid: "rgba(255,255,255,.08)",
    word: "rgba(255,255,255,.14)",
    handle: "#f05a43",
  },
  light: {
    background: "#f5f5f3",
    foreground: "#1d2224",
    muted: "#70787b",
    waveform: "#596469",
    waveformFill: "rgba(89, 100, 105, .15)",
    cue: "#dfe5e7",
    reviewed: "#d7e8df",
    flagged: "#f1dfca",
    selected: "#f7d7d1",
    selectedBorder: "#d9412d",
    playhead: "#d9412d",
    grid: "rgba(19,28,32,.09)",
    word: "rgba(19,28,32,.17)",
    handle: "#d9412d",
  },
} as const;

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
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const baseCanvasRef = useRef<HTMLCanvasElement>(null);
  const overlayCanvasRef = useRef<HTMLCanvasElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const overlayDrawRef = useRef<() => void>(() => undefined);
  const [size, setSize] = useState({ width: 900, height: large ? 250 : 168 });
  const [waveform, setWaveform] = useState<WaveformResponse | null>(null);
  const [words, setWords] = useState<TimedWord[]>([]);
  const [dragCueId, setDragCueId] = useState<number | null>(null);
  const [viewCenter, setViewCenter] = useState(currentTime);
  const palette = PALETTES[theme];
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
      Promise.all([
        api.waveform(dataStart, dataEnd, dataPixels),
        api.words(dataStart, dataEnd),
      ])
        .then(([peaks, wordResponse]) => {
          if (!controller.signal.aborted) {
            setWaveform(peaks);
            setWords(wordResponse.words);
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
  }, [dataStart, dataEnd, dataPixels]);

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
      if (drag) {
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
    event.currentTarget.style.cursor = mode === "body" ? "grabbing" : "ew-resize";
    dragRef.current = {
      cue: hit,
      bounds: boundsFor(hit),
      mode,
      pointerStart: time,
      draftStart: hit.start,
      draftEnd: hit.end,
      snapGuide: null,
    };
    setDragCueId(hit.id);
    overlayDrawRef.current();
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
    const time = timeFor(x);
    const delta = time - drag.pointerStart;
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
      const result = snap(drag.cue.start + delta, drag.cue.id, { includePlayhead: false, thresholdPixels: 3 });
      const constrained = constrainCueRange(
        { start: result.time, end: result.time + length },
        "body",
        drag.bounds,
      );
      dragRef.current = { ...drag, draftStart: constrained.start, draftEnd: constrained.end, snapGuide: result.guide };
    }
    overlayDrawRef.current();
  };

  const handlePointerUp = async (event: React.PointerEvent<HTMLCanvasElement>) => {
    const completed = dragRef.current;
    if (!completed) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    event.currentTarget.style.cursor = "crosshair";
    dragRef.current = null;
    setDragCueId(null);
    overlayDrawRef.current();
    await onTimeChange(
      completed.cue.id,
      Number(completed.draftStart.toFixed(3)),
      Number(completed.draftEnd.toFixed(3)),
    );
  };

  const handleWheel = (event: React.WheelEvent<HTMLCanvasElement>) => {
    if (zoom <= 1) return;
    event.preventDefault();
    const delta = event.deltaX || event.deltaY;
    const nextCenter = viewCenter + Math.sign(delta) * Math.max(0.1, viewDuration * 0.1);
    setViewCenter(Math.max(0, Math.min(duration, nextCenter)));
  };

  return (
    <div ref={containerRef} className={`timeline-stack ${large ? "timeline-large" : ""}`} style={{ height: size.height }}>
      <canvas ref={baseCanvasRef} className="timeline timeline-base" aria-hidden="true" />
      <canvas
        ref={overlayCanvasRef}
        className="timeline timeline-overlay"
        tabIndex={0}
        aria-label={ariaLabel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onWheel={handleWheel}
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

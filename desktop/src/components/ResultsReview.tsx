import { clsx } from "clsx";
import { Download } from "lucide-react";
import { type SyntheticEvent, useEffect, useMemo, useRef, useState } from "react";

import { formatRange, formatTimestamp } from "../lib/format";
import type { ReviewModel, Segment } from "../lib/types";
import { Button } from "./Button";
import { Waveform } from "./Waveform";

type ResultsReviewProps = {
  model: ReviewModel;
  onSegmentChange: (segment: Segment) => Promise<void> | void;
};

type SaveSegmentCallback = ResultsReviewProps["onSegmentChange"];

type DraftSegment = Segment & {
  saveInFlightToken?: number;
  saveToken: number;
};

function toDraftSegments(segments: Segment[]): DraftSegment[] {
  return segments.map((segment) => ({
    ...segment,
    saveToken: 0
  }));
}

function toSegment(segment: DraftSegment): Segment {
  return {
    id: segment.id,
    index: segment.index,
    startMs: segment.startMs,
    endMs: segment.endMs,
    transcript: segment.transcript,
    translation: segment.translation,
    savedState: segment.savedState
  };
}

function saveStatus(segments: DraftSegment[]) {
  if (segments.some((segment) => segment.savedState === "error")) {
    return { label: "Autosave error", tone: "error" as const };
  }

  if (segments.some((segment) => segment.savedState === "saving")) {
    return { label: "Saving", tone: "saving" as const };
  }

  return { label: "Saved", tone: "saved" as const };
}

function segmentStatus(segment: DraftSegment): string {
  if (segment.savedState === "error") {
    return "Autosave error";
  }

  if (segment.savedState === "saving") {
    return "Saving";
  }

  return "Saved";
}

function clampPlaybackTime(timeMs: number, durationMs: number): number {
  if (!Number.isFinite(timeMs)) {
    return 0;
  }

  return Math.min(Math.max(0, durationMs), Math.max(0, timeMs));
}

function timelinePixelsPerSecond(input: string): number {
  const value = Number(input);
  if (!Number.isFinite(value)) {
    return 32;
  }

  return Math.min(96, Math.max(16, value));
}

export function ResultsReview({ model, onSegmentChange }: ResultsReviewProps) {
  const [segments, setSegments] = useState<DraftSegment[]>(() => toDraftSegments(model.segments));
  const [activeSegmentId, setActiveSegmentId] = useState(model.activeSegmentId);
  const [currentMs, setCurrentMs] = useState(model.currentMs);
  const [timelineZoomInput, setTimelineZoomInput] = useState("32");
  const cardRefs = useRef<Record<string, HTMLElement | null>>({});
  const mountedRef = useRef(false);
  const onSegmentChangeRef = useRef(onSegmentChange);
  const saveTimerRef = useRef<number | undefined>(undefined);
  const segmentsRef = useRef<DraftSegment[]>(segments);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  onSegmentChangeRef.current = onSegmentChange;
  segmentsRef.current = segments;

  useEffect(() => {
    const cleanupSaveCallback = onSegmentChange;
    setSegments(toDraftSegments(model.segments));
    setActiveSegmentId(model.activeSegmentId);
    setCurrentMs(model.currentMs);

    return () => {
      flushPendingDirtySegments(false, cleanupSaveCallback);
    };
  }, [model]);

  const activeSegment = useMemo(
    () => segments.find((segment) => segment.id === activeSegmentId) ?? segments[0],
    [activeSegmentId, segments]
  );
  const status = saveStatus(segments);
  const previewTime = currentMs;
  const pixelsPerSecond = timelinePixelsPerSecond(timelineZoomInput);

  function segmentAtTime(timeMs: number): DraftSegment | undefined {
    const sortedSegments = [...segmentsRef.current].sort((left, right) => left.startMs - right.startMs);
    const directMatch = sortedSegments.find((segment) => {
      const startMs = Math.min(segment.startMs, segment.endMs);
      const endMs = Math.max(segment.startMs, segment.endMs);
      return timeMs >= startMs && timeMs <= endMs;
    });

    if (directMatch) {
      return directMatch;
    }

    return [...sortedSegments].reverse().find((segment) => timeMs >= Math.min(segment.startMs, segment.endMs)) ?? sortedSegments[0];
  }

  function syncPlaybackTime(timeMs: number, scrollCard = false) {
    const nextTimeMs = clampPlaybackTime(timeMs, model.durationMs);
    const matchingSegment = segmentAtTime(nextTimeMs);
    setCurrentMs(nextTimeMs);

    if (matchingSegment) {
      setActiveSegmentId(matchingSegment.id);
      if (scrollCard) {
        cardRefs.current[matchingSegment.id]?.scrollIntoView?.({ block: "nearest" });
      }
    }
  }

  function seekToMs(timeMs: number, scrollCard = false) {
    const nextTimeMs = clampPlaybackTime(timeMs, model.durationMs);
    if (videoRef.current) {
      videoRef.current.currentTime = nextTimeMs / 1000;
    }
    syncPlaybackTime(nextTimeMs, scrollCard);
  }

  function selectSegment(segmentId: string, scrollCard = false, seekPlayback = true) {
    const selectedSegment = segmentsRef.current.find((segment) => segment.id === segmentId);
    setActiveSegmentId(segmentId);
    if (selectedSegment) {
      if (seekPlayback) {
        seekToMs(selectedSegment.startMs, scrollCard);
      } else {
        setCurrentMs(selectedSegment.startMs);
      }
    }
    if (scrollCard) {
      cardRefs.current[segmentId]?.scrollIntoView?.({ block: "nearest" });
    }
  }

  function updateSegment(segmentId: string, patch: Partial<Pick<Segment, "transcript" | "translation">>) {
    setActiveSegmentId(segmentId);
    setSegments((current) =>
      current.map((segment) =>
        segment.id === segmentId
          ? {
              ...segment,
              ...patch,
              saveInFlightToken: undefined,
              savedState: "saving",
              saveToken: segment.saveToken + 1
            }
          : segment
      )
    );
  }

  function handleVideoTimeUpdate(event: SyntheticEvent<HTMLVideoElement>) {
    syncPlaybackTime(event.currentTarget.currentTime * 1000, true);
  }

  function handleTimelineZoomChange(value: string) {
    setTimelineZoomInput(value.replace(/[^\d.]/g, ""));
  }

  function pendingDirtySegments() {
    return segmentsRef.current.filter(
      (segment) =>
        segment.savedState === "saving" && segment.saveToken > 0 && segment.saveInFlightToken !== segment.saveToken
    );
  }

  function saveSegment(segment: DraftSegment, updateState: boolean, saveCallback: SaveSegmentCallback = onSegmentChangeRef.current) {
    const token = segment.saveToken;
    void Promise.resolve()
      .then(() => saveCallback(toSegment(segment)))
      .then(() => {
        if (!updateState || !mountedRef.current) {
          return;
        }

        setSegments((current) =>
          current.map((item) =>
            item.id === segment.id && item.saveToken === token
              ? { ...item, saveInFlightToken: undefined, savedState: "saved" }
              : item
          )
        );
      })
      .catch(() => {
        if (!updateState || !mountedRef.current) {
          return;
        }

        setSegments((current) =>
          current.map((item) =>
            item.id === segment.id && item.saveToken === token
              ? { ...item, saveInFlightToken: undefined, savedState: "error" }
              : item
          )
        );
      });
  }

  function clearSaveTimer() {
    if (saveTimerRef.current === undefined) {
      return;
    }

    window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = undefined;
  }

  function flushPendingDirtySegments(updateState: boolean, saveCallback: SaveSegmentCallback = onSegmentChangeRef.current) {
    clearSaveTimer();
    for (const segment of pendingDirtySegments()) {
      saveSegment(segment, updateState, saveCallback);
    }
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    const pending = pendingDirtySegments();
    if (pending.length === 0) {
      return undefined;
    }

    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = undefined;
      setSegments((current) =>
        current.map((item) => {
          const pendingSegment = pending.find((segment) => segment.id === item.id);
          return pendingSegment && item.saveToken === pendingSegment.saveToken
            ? { ...item, saveInFlightToken: pendingSegment.saveToken }
            : item;
        })
      );

      for (const segment of pending) {
        saveSegment(segment, true);
      }
    }, 350);

    return clearSaveTimer;
  }, [segments]);

  return (
    <section aria-label="Results review" className="grid min-h-[calc(100vh-84px)] grid-rows-[auto_minmax(0,1fr)] gap-4">
      <header className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-end sm:gap-4">
        <div className="min-w-0">
          <p className="text-[11px] uppercase text-muted">Review results</p>
          <h1 className="mt-2 truncate font-serif text-[38px] leading-none text-ink-brown">{model.title}</h1>
          <p className="mt-1.5 text-sm text-muted">Completed - edits autosave as you review.</p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-3">
          <span
            className={clsx(
              "flex items-center gap-1.5 text-xs font-semibold",
              status.tone === "saved" ? "text-ready" : status.tone === "saving" ? "text-[#8c4d29]" : "text-accent"
            )}
            aria-live="polite"
          >
            <span
              className={clsx(
                "h-2 w-2 rounded-full",
                status.tone === "saved" ? "bg-ready" : status.tone === "saving" ? "bg-accent" : "bg-accent"
              )}
              aria-hidden="true"
            />
            {status.label}
          </span>
          <Button variant="primary">
            <Download className="mr-2 h-4 w-4" aria-hidden="true" />
            Export SRT
          </Button>
        </div>
      </header>

      <section
        aria-label="Results review layout"
        className="grid min-h-0 grid-cols-1 gap-[18px] xl:h-[calc(100vh-176px)] xl:grid-cols-[minmax(420px,1.06fr)_minmax(360px,0.94fr)]"
      >
        <div className="grid min-h-0 min-w-0 content-start gap-3.5">
          <section className="min-w-0 rounded-lg bg-paper-muted p-4 shadow-control" aria-label="Video preview panel">
            <div
              aria-label="Video preview"
              className="relative aspect-video min-w-0 overflow-hidden rounded-lg bg-log-bg shadow-inner"
            >
              {model.videoSrc ? (
                <video
                  ref={videoRef}
                  aria-label="Media playback"
                  className="absolute inset-0 h-full w-full bg-black object-contain"
                  controls
                  onSeeked={handleVideoTimeUpdate}
                  onTimeUpdate={handleVideoTimeUpdate}
                  src={model.videoSrc}
                />
              ) : (
                <div
                  className="absolute inset-0 bg-[linear-gradient(135deg,rgba(255,250,240,0.08),rgba(182,99,47,0.18)_55%,rgba(45,36,29,0.2))]"
                />
              )}
              <div className="pointer-events-none absolute left-5 top-[18px] rounded-sm bg-black/35 px-2 py-1 font-mono text-xs text-[#d7c4a7]">
                {formatTimestamp(previewTime)} / {formatTimestamp(model.durationMs)}
              </div>
              <div className="pointer-events-none absolute left-5 top-14 text-xs uppercase text-[#d7c4a7]">Preview</div>
              <div
                data-testid="preview-subtitle-overlay"
                className="pointer-events-none absolute inset-x-12 bottom-16 rounded-md bg-black/70 px-3 py-2 text-center text-[15px] leading-snug text-[#fff8ea] shadow-control"
              >
                {activeSegment?.translation}
              </div>
            </div>
          </section>

          <section className="min-w-0 rounded-lg bg-paper-muted px-4 py-3.5 shadow-control" aria-label="Timeline panel">
            <div className="mb-2.5 flex items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase text-muted">Timeline</p>
                <p className="mt-1 text-xs text-muted">Subtitle regions follow playback and align to audio loudness.</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <label className="flex items-center gap-1.5 text-xs font-semibold text-[#8c4d29]">
                  <span>Zoom</span>
                  <input
                    aria-label="Timeline zoom"
                    inputMode="numeric"
                    value={timelineZoomInput}
                    onChange={(event) => handleTimelineZoomChange(event.target.value)}
                    className="h-7 w-14 rounded-sm bg-paper px-2 text-right font-mono text-xs text-ink shadow-inner focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  />
                  <span>px/s</span>
                </label>
                <span className="rounded-sm bg-paper-selected px-2 py-1 text-xs font-semibold text-[#8c4d29]">
                  Segment {activeSegment?.index}
                </span>
              </div>
            </div>
            <Waveform
              activeSegmentId={activeSegmentId}
              currentMs={currentMs}
              durationMs={model.durationMs}
              pixelsPerSecond={pixelsPerSecond}
              segments={segments.map(toSegment)}
              waveform={model.waveform}
              onSeekMs={(timeMs) => seekToMs(timeMs, true)}
              onSelectSegment={(segmentId) => selectSegment(segmentId, true)}
            />
          </section>
        </div>

        <aside className="grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] rounded-lg bg-paper-muted p-4 shadow-control">
          <div className="mb-3 flex items-center justify-between gap-4">
            <div>
              <p className="text-xs uppercase text-muted">Editable segments</p>
              <p className="mt-1 text-sm text-muted">Transcript and translation autosave.</p>
            </div>
            <span
              className={clsx(
                "text-xs font-semibold",
                status.tone === "saved" ? "text-ready" : status.tone === "saving" ? "text-[#8c4d29]" : "text-accent"
              )}
              aria-live="polite"
            >
              {status.label}
            </span>
          </div>

          <div aria-label="Segment list" className="grid min-h-0 content-start gap-2.5 overflow-y-auto pr-1">
            {segments.map((segment) => {
              const active = segment.id === activeSegmentId;
              const transcriptId = `${segment.id}-transcript`;
              const translationId = `${segment.id}-translation`;

              return (
                <article
                  key={segment.id}
                  ref={(node) => {
                    cardRefs.current[segment.id] = node;
                  }}
                  aria-label={`Segment ${segment.index}`}
                  data-active={active ? "true" : "false"}
                  onClick={() => selectSegment(segment.id)}
                  onFocusCapture={() => selectSegment(segment.id)}
                  className={clsx(
                    "rounded-lg p-3 shadow-control",
                    active ? "bg-paper-selected shadow-selected" : "bg-paper [@media(hover:hover)]:hover:bg-[#fff6e8]"
                  )}
                >
                  <div
                    className={clsx(
                      "flex items-center justify-between gap-3 text-xs font-semibold",
                      active ? "text-[#8c4d29]" : "text-[#8c7b61]"
                    )}
                  >
                    <span className="font-mono">{formatRange(segment.startMs, segment.endMs)}</span>
                    <span>Segment {segment.index}</span>
                  </div>

                  <div className="mt-2 grid gap-1.5">
                    <label className="text-[11px] font-semibold text-[#8c7b61]" htmlFor={transcriptId}>
                      Transcript <span className="sr-only">for segment {segment.index}</span>
                    </label>
                    <textarea
                      id={transcriptId}
                      value={segment.transcript}
                      onChange={(event) => updateSegment(segment.id, { transcript: event.target.value })}
                      className="min-h-[64px] resize-none rounded-md bg-paper-muted p-2 text-sm leading-snug text-ink shadow-control focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    />
                  </div>

                  <div className="mt-2 grid gap-1.5">
                    <div className="flex items-center justify-between gap-3">
                      <label className="text-[11px] font-semibold text-[#8c7b61]" htmlFor={translationId}>
                        Translation <span className="sr-only">for segment {segment.index}</span>
                      </label>
                      <span
                        className={clsx(
                          "text-[11px] font-semibold",
                          segmentStatus(segment) === "Saved" ? "text-ready" : "text-[#8c4d29]"
                        )}
                      >
                        {segmentStatus(segment)}
                      </span>
                    </div>
                    <textarea
                      id={translationId}
                      value={segment.translation}
                      onChange={(event) => updateSegment(segment.id, { translation: event.target.value })}
                      className="min-h-[64px] resize-none rounded-md bg-paper-muted p-2 text-sm leading-snug text-ink shadow-control focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    />
                  </div>
                </article>
              );
            })}
          </div>
        </aside>
      </section>
    </section>
  );
}

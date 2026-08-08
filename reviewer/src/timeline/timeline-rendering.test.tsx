import { fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Cue } from "../api/types";

vi.mock("../api/client", () => ({
  api: {
    waveform: vi.fn(async () => ({
      sample_rate: 16_000,
      duration: 120,
      start: 0,
      end: 120,
      peaks: [],
    })),
    words: vi.fn(async () => ({ words: [] })),
  },
}));

import { Timeline } from "./Timeline";

function canvasContext() {
  return {
    beginPath: vi.fn(),
    clearRect: vi.fn(),
    clip: vi.fn(),
    closePath: vi.fn(),
    fill: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    lineTo: vi.fn(),
    moveTo: vi.fn(),
    rect: vi.fn(),
    restore: vi.fn(),
    roundRect: vi.fn(),
    save: vi.fn(),
    setLineDash: vi.fn(),
    setTransform: vi.fn(),
    stroke: vi.fn(),
    strokeRect: vi.fn(),
  };
}

function cue(id: number, start: number, end: number): Cue {
  return {
    id,
    start,
    end,
    duration: end - start,
    source: "Cue",
    source_cps: 1,
    target: null,
    budget: null,
    over_budget: false,
    time_warning: false,
    term_warning: false,
    issues: [],
    status: "unreviewed",
    note: null,
  };
}

interface Rendered {
  overlay: HTMLCanvasElement;
  onTimeChange: ReturnType<typeof vi.fn>;
  onSelect: ReturnType<typeof vi.fn>;
  onSeek: ReturnType<typeof vi.fn>;
}

function renderTimeline(overrides: { zoom?: number; cues?: Cue[] } = {}): Rendered {
  vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  const context = canvasContext();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    context as unknown as CanvasRenderingContext2D,
  );
  HTMLCanvasElement.prototype.setPointerCapture = vi.fn();
  HTMLCanvasElement.prototype.releasePointerCapture = vi.fn();
  HTMLCanvasElement.prototype.hasPointerCapture = vi.fn(() => true);

  const onTimeChange = vi.fn(async () => undefined);
  const onSelect = vi.fn();
  const onSeek = vi.fn();
  const { container } = render(
    <Timeline
      cues={overrides.cues ?? [cue(1, 8, 12)]}
      currentTime={10}
      duration={120}
      selectedId={1}
      zoom={overrides.zoom ?? 4}
      large={false}
      snapEnabled={false}
      theme="light"
      ariaLabel="Timeline"
      isPlaying={false}
      getPlaybackTime={() => 10}
      onSeek={onSeek}
      onSelect={onSelect}
      onTimeChange={onTimeChange}
    />,
  );
  const overlay = container.querySelector(".timeline-overlay") as HTMLCanvasElement;
  vi.spyOn(overlay, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 900,
    bottom: 168,
    width: 900,
    height: 168,
    toJSON: () => ({}),
  });
  return { overlay, onTimeChange, onSelect, onSeek };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("timeline rendering", () => {
  it("uses a lightweight animation layer for the live playhead", () => {
    const animationFrame = vi.fn(() => 1);
    vi.stubGlobal("requestAnimationFrame", animationFrame);
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const context = canvasContext();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      context as unknown as CanvasRenderingContext2D,
    );
    const { container } = render(
      <Timeline
        cues={[]}
        currentTime={10}
        duration={120}
        selectedId={null}
        zoom={4}
        large={false}
        snapEnabled
        theme="light"
        ariaLabel="Timeline"
        isPlaying
        getPlaybackTime={() => 10.25}
        onSeek={() => undefined}
        onSelect={() => undefined}
        onTimeChange={async () => undefined}
      />,
    );
    expect(container.querySelector(".timeline-base")).toBeInTheDocument();
    expect(container.querySelector(".timeline-overlay")).toBeInTheDocument();
    expect(animationFrame).toHaveBeenCalled();
  });

  it("keeps the waveform layer untouched during drag pointer moves", () => {
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const baseContext = canvasContext();
    const overlayContext = canvasContext();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(function (
      this: HTMLCanvasElement,
    ) {
      return (this.classList.contains("timeline-base") ? baseContext : overlayContext) as unknown as CanvasRenderingContext2D;
    });
    HTMLCanvasElement.prototype.setPointerCapture = vi.fn();
    HTMLCanvasElement.prototype.releasePointerCapture = vi.fn();
    HTMLCanvasElement.prototype.hasPointerCapture = vi.fn(() => true);

    const { container } = render(
      <Timeline
        cues={[cue(1, 8, 12)]}
        currentTime={10}
        duration={120}
        selectedId={1}
        zoom={4}
        large={false}
        snapEnabled={false}
        theme="light"
        ariaLabel="Timeline"
        isPlaying={false}
        getPlaybackTime={() => 10}
        onSeek={() => undefined}
        onSelect={() => undefined}
        onTimeChange={async () => undefined}
      />,
    );
    const overlay = container.querySelector(".timeline-overlay") as HTMLCanvasElement;
    vi.spyOn(overlay, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 900,
      bottom: 168,
      width: 900,
      height: 168,
      toJSON: () => ({}),
    });

    fireEvent.pointerDown(overlay, { clientX: 300, pointerId: 1 });
    // First move past the 4px threshold activates the drag: the base layer
    // redraws exactly once to hide the original cue under the drag ghost.
    fireEvent.pointerMove(overlay, { clientX: 320, pointerId: 1 });
    const drawsAfterActivation = baseContext.clearRect.mock.calls.length;
    fireEvent.pointerMove(overlay, { clientX: 340, pointerId: 1 });
    fireEvent.pointerMove(overlay, { clientX: 360, pointerId: 1 });
    fireEvent.pointerMove(overlay, { clientX: 380, pointerId: 1 });
    expect(baseContext.clearRect).toHaveBeenCalledTimes(drawsAfterActivation);
    expect(overlayContext.clearRect.mock.calls.length).toBeGreaterThan(2);
  });
});

describe("timeline interaction state machine", () => {
  it("plain click selects the cue and sends zero mutation", () => {
    const { overlay, onTimeChange, onSelect } = renderTimeline();
    fireEvent.pointerDown(overlay, { clientX: 300, pointerId: 1 });
    fireEvent.pointerUp(overlay, { clientX: 300, pointerId: 1 });
    expect(onSelect).toHaveBeenCalledWith(1);
    expect(onTimeChange).not.toHaveBeenCalled();
  });

  it("sub-threshold movement is still a click, not a drag", () => {
    const { overlay, onTimeChange } = renderTimeline();
    fireEvent.pointerDown(overlay, { clientX: 300, pointerId: 1 });
    fireEvent.pointerMove(overlay, { clientX: 302, pointerId: 1 });
    fireEvent.pointerUp(overlay, { clientX: 302, pointerId: 1 });
    expect(onTimeChange).not.toHaveBeenCalled();
  });

  it("dragging the body past the threshold commits the new range", () => {
    const { overlay, onTimeChange } = renderTimeline();
    fireEvent.pointerDown(overlay, { clientX: 300, pointerId: 1 });
    fireEvent.pointerMove(overlay, { clientX: 330, pointerId: 1 });
    fireEvent.pointerUp(overlay, { clientX: 330, pointerId: 1 });
    expect(onTimeChange).toHaveBeenCalledTimes(1);
    const [id, start, end] = onTimeChange.mock.calls[0] as [number, number, number];
    expect(id).toBe(1);
    expect(start).toBeCloseTo(9, 1);
    expect(end).toBeCloseTo(13, 1);
  });

  it("pointer cancel never mutates, even mid-drag", () => {
    const { overlay, onTimeChange } = renderTimeline();
    fireEvent.pointerDown(overlay, { clientX: 300, pointerId: 1 });
    fireEvent.pointerMove(overlay, { clientX: 330, pointerId: 1 });
    fireEvent.pointerCancel(overlay, { pointerId: 1 });
    expect(onTimeChange).not.toHaveBeenCalled();
  });

  it("a drag landing back on the original range sends no mutation", () => {
    const { overlay, onTimeChange } = renderTimeline();
    fireEvent.pointerDown(overlay, { clientX: 300, pointerId: 1 });
    fireEvent.pointerMove(overlay, { clientX: 330, pointerId: 1 });
    fireEvent.pointerMove(overlay, { clientX: 300, pointerId: 1 });
    fireEvent.pointerUp(overlay, { clientX: 300, pointerId: 1 });
    expect(onTimeChange).not.toHaveBeenCalled();
  });

  it("clicking empty track seeks without selecting", () => {
    const { overlay, onSeek, onSelect } = renderTimeline();
    fireEvent.pointerDown(overlay, { clientX: 30, pointerId: 1 });
    expect(onSeek).toHaveBeenCalledWith(1);
    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe("timeline wheel panning", () => {
  it("preventDefaults via a non-passive native listener when zoomed in", () => {
    const { overlay } = renderTimeline({ zoom: 4 });
    const event = new WheelEvent("wheel", { deltaY: 120, cancelable: true, bubbles: true });
    overlay.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("ignores the wheel at zoom 1", () => {
    const { overlay } = renderTimeline({ zoom: 1 });
    const event = new WheelEvent("wheel", { deltaY: 120, cancelable: true, bubbles: true });
    overlay.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });
});

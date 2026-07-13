import { fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  api: {
    waveform: vi.fn(async () => ({ sample_rate: 16_000, duration: 120, start: 0, end: 120, peaks: [] })),
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

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("timeline rendering", () => {
  it("uses a lightweight animation layer for the live playhead", () => {
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
    });
    const animationFrame = vi.fn(() => 1);
    vi.stubGlobal("requestAnimationFrame", animationFrame);
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const context = canvasContext();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);

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

  it("does not redraw the waveform layer for every drag pointer move", () => {
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
    });
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const baseContext = canvasContext();
    const overlayContext = canvasContext();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(function (this: HTMLCanvasElement) {
      return (this.classList.contains("timeline-base") ? baseContext : overlayContext) as unknown as CanvasRenderingContext2D;
    });
    HTMLCanvasElement.prototype.setPointerCapture = vi.fn();
    HTMLCanvasElement.prototype.releasePointerCapture = vi.fn();
    HTMLCanvasElement.prototype.hasPointerCapture = vi.fn(() => true);

    const { container } = render(
      <Timeline
        cues={[{
          id: 1,
          start: 8,
          end: 12,
          duration: 4,
          source: "Cue",
          source_cps: 1,
          target: null,
          budget: null,
          over_budget: false,
          time_warning: false,
          term_warning: false,
          status: "unreviewed",
          note: null,
        }]}
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
    const drawsAfterPointerDown = baseContext.clearRect.mock.calls.length;
    fireEvent.pointerMove(overlay, { clientX: 320, pointerId: 1 });

    expect(baseContext.clearRect).toHaveBeenCalledTimes(drawsAfterPointerDown);
    expect(overlayContext.clearRect.mock.calls.length).toBeGreaterThan(1);
  });
});

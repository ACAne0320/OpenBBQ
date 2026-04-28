import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { reviewModel } from "../../lib/mockData";
import type { Segment } from "../../lib/types";
import { ResultsReview } from "../ResultsReview";
import { Waveform } from "../Waveform";

afterEach(() => {
  vi.useRealTimers();
});

describe("ResultsReview", () => {
  it("renders video preview, waveform overlays, and editable segment cards", () => {
    render(<ResultsReview model={reviewModel} onSegmentChange={vi.fn()} />);

    expect(screen.getByLabelText("Video preview")).toBeInTheDocument();
    expect(screen.getByText("Timeline")).toBeInTheDocument();
    expect(screen.getByText("Editable segments")).toBeInTheDocument();
    expect(screen.queryByText("Generated subtitle")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("waveform-bar").length).toBeGreaterThan(reviewModel.waveform.length);
    expect(screen.getAllByTestId("waveform-segment-overlay")).toHaveLength(reviewModel.segments.length);

    const segment = screen.getByRole("article", { name: "Segment 3" });
    expect(within(segment).getByText("00:12.100 -> 00:16.580")).toBeInTheDocument();
    expect(within(segment).getByLabelText("Transcript for segment 3")).toHaveValue(
      "Each result is saved as an editable versioned segment."
    );
    expect(within(segment).getByLabelText("Translation for segment 3")).toHaveValue(
      "Each result is saved as an editable versioned segment."
    );
    expect(within(segment).getByText("Saving")).toBeInTheDocument();
  });

  it("autosaves transcript and translation edits without manual save UI", async () => {
    const user = userEvent.setup();
    const onSegmentChange = vi.fn().mockResolvedValue(undefined);
    render(<ResultsReview model={reviewModel} onSegmentChange={onSegmentChange} />);

    const transcript = screen.getByLabelText("Transcript for segment 3");
    const translation = screen.getByLabelText("Translation for segment 3");

    await user.clear(transcript);
    await user.type(transcript, "Cleaner original transcript.");
    await user.clear(translation);
    await user.type(translation, "Cleaner translated subtitle.");

    expect(screen.queryByRole("button", { name: /save changes/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/edited cards mark the result as unsaved/i)).not.toBeInTheDocument();

    await waitFor(() => {
      expect(onSegmentChange).toHaveBeenCalledWith(
        expect.objectContaining({
          id: "seg-03",
          transcript: "Cleaner original transcript.",
          translation: "Cleaner translated subtitle."
        })
      );
    });
  });

  it("flushes dirty segment edits when unmounted before the debounce fires", async () => {
    const user = userEvent.setup();
    const onSegmentChange = vi.fn().mockResolvedValue(undefined);
    const { unmount } = render(<ResultsReview model={reviewModel} onSegmentChange={onSegmentChange} />);

    await user.clear(screen.getByLabelText("Translation for segment 3"));
    await user.type(screen.getByLabelText("Translation for segment 3"), "Saved during navigation.");

    unmount();

    await waitFor(() => {
      expect(onSegmentChange).toHaveBeenCalledWith(
        expect.objectContaining({
          id: "seg-03",
          translation: "Saved during navigation."
        })
      );
    });
  });

  it("flushes dirty segment edits when a replacement model arrives before the debounce fires", async () => {
    const user = userEvent.setup();
    const onSegmentChange = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(<ResultsReview model={reviewModel} onSegmentChange={onSegmentChange} />);

    await user.clear(screen.getByLabelText("Transcript for segment 3"));
    await user.type(screen.getByLabelText("Transcript for segment 3"), "Saved before model swap.");

    rerender(<ResultsReview model={{ ...reviewModel, title: "replacement-review" }} onSegmentChange={onSegmentChange} />);

    await waitFor(() => {
      expect(onSegmentChange).toHaveBeenCalledWith(
        expect.objectContaining({
          id: "seg-03",
          transcript: "Saved before model swap."
        })
      );
    });
  });

  it("flushes dirty drafts through the callback that owned the replaced model", async () => {
    const onSegmentChangeA = vi.fn().mockResolvedValue(undefined);
    const onSegmentChangeB = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(<ResultsReview model={reviewModel} onSegmentChange={onSegmentChangeA} />);

    fireEvent.change(screen.getByLabelText("Translation for segment 3"), {
      target: { value: "Old model dirty edit." }
    });

    rerender(
      <ResultsReview
        model={{ ...reviewModel, activeSegmentId: "seg-02", title: "replacement-review" }}
        onSegmentChange={onSegmentChangeB}
      />
    );

    await waitFor(() => {
      expect(onSegmentChangeA).toHaveBeenCalledWith(
        expect.objectContaining({
          id: "seg-03",
          translation: "Old model dirty edit."
        })
      );
    });
    expect(onSegmentChangeB).not.toHaveBeenCalled();
  });

  it("preserves incoming saving state until a local save completes", async () => {
    vi.useFakeTimers();
    const onSegmentChange = vi.fn().mockResolvedValue(undefined);
    render(<ResultsReview model={reviewModel} onSegmentChange={onSegmentChange} />);

    const segment = screen.getByRole("article", { name: "Segment 3" });
    expect(within(segment).getByText("Saving")).toBeInTheDocument();

    fireEvent.change(within(segment).getByLabelText("Translation for segment 3"), {
      target: { value: "New local text." }
    });

    await act(async () => {
      vi.advanceTimersByTime(350);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(within(segment).getByText("Saved")).toBeInTheDocument();
  });

  it("catches synchronous save failures and shows autosave error state", async () => {
    vi.useFakeTimers();
    const onSegmentChange = vi.fn(() => {
      throw new Error("write failed");
    });
    render(<ResultsReview model={reviewModel} onSegmentChange={onSegmentChange} />);

    fireEvent.change(screen.getByLabelText("Translation for segment 3"), {
      target: { value: "Cannot save." }
    });

    await act(async () => {
      vi.advanceTimersByTime(350);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getAllByText("Autosave error")).not.toHaveLength(0);
  });

  it("selects a waveform segment and updates the active card and preview subtitle", async () => {
    const user = userEvent.setup();
    render(<ResultsReview model={reviewModel} onSegmentChange={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /waveform segment 4/i }));

    expect(screen.getByLabelText("Video preview")).toHaveTextContent("Export the final SRT after the result is reviewed.");
    expect(screen.getByRole("article", { name: "Segment 4" })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("button", { name: /waveform segment 4/i })).toHaveAttribute("aria-pressed", "true");
  });

  it("selects the matching waveform and preview subtitle when a card receives focus", async () => {
    const user = userEvent.setup();
    render(<ResultsReview model={reviewModel} onSegmentChange={vi.fn()} />);

    await user.click(screen.getByLabelText("Transcript for segment 2"));

    expect(screen.getByLabelText("Video preview")).toHaveTextContent("The reviewed subtitle file will be generated after approval.");
    expect(screen.getByRole("article", { name: "Segment 2" })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("button", { name: /waveform segment 2/i })).toHaveAttribute("aria-pressed", "true");
  });

  it("uses a responsive results grid without manual save copy", () => {
    render(<ResultsReview model={reviewModel} onSegmentChange={vi.fn()} />);

    const layout = screen.getByLabelText("Results review layout");
    expect(layout).toHaveClass("grid-cols-1", "xl:grid-cols-[minmax(420px,1.06fr)_minmax(360px,0.94fr)]", "xl:h-[calc(100vh-176px)]");
    expect(screen.getByLabelText("Segment list")).toHaveClass("overflow-y-auto");
    expect(screen.queryByRole("button", { name: /save changes/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/edited cards mark the result as unsaved/i)).not.toBeInTheDocument();
  });

  it("syncs active subtitle and cards from video playback time", () => {
    render(<ResultsReview model={{ ...reviewModel, videoSrc: "openbbq-file://artifact/video" }} onSegmentChange={vi.fn()} />);

    const video = screen.getByLabelText("Media playback") as HTMLVideoElement;
    fireEvent.timeUpdate(video, { target: { currentTime: 17.4 } });

    expect(screen.getByLabelText("Video preview")).toHaveTextContent("Export the final SRT after the result is reviewed.");
    expect(screen.getByRole("article", { name: "Segment 4" })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("button", { name: /waveform segment 4/i })).toHaveAttribute("aria-pressed", "true");
  });

  it("renders native video controls without pointer-blocking subtitle overlays", () => {
    render(<ResultsReview model={{ ...reviewModel, videoSrc: "openbbq-file://artifact/video" }} onSegmentChange={vi.fn()} />);

    const video = screen.getByLabelText("Media playback") as HTMLVideoElement;
    expect(video.controls).toBe(true);
    expect(screen.getByTestId("preview-subtitle-overlay")).toHaveClass("pointer-events-none");
  });

  it("zooms the timeline and keeps only a local time window visible by default", async () => {
    const user = userEvent.setup();
    render(<ResultsReview model={reviewModel} onSegmentChange={vi.fn()} />);

    expect(screen.getByLabelText("Timeline zoom")).toHaveValue("64");
    expect(screen.getByTestId("timeline-track")).toHaveStyle({ minWidth: "14619px" });

    await user.clear(screen.getByLabelText("Timeline zoom"));
    await user.type(screen.getByLabelText("Timeline zoom"), "48");

    expect(screen.getByTestId("timeline-track")).toHaveStyle({ minWidth: "10964px" });
  });
});

describe("Waveform", () => {
  function renderWaveform(
    segments: Segment[],
    durationMs = 1000,
    waveform = [{ id: "bar-01", level: 50 }]
  ) {
    render(
      <Waveform
        activeSegmentId={segments[0]?.id ?? ""}
        currentMs={segments[0]?.startMs ?? 0}
        durationMs={durationMs}
        pixelsPerSecond={32}
        onSelectSegment={vi.fn()}
        onSeekMs={vi.fn()}
        segments={segments}
        waveform={waveform}
      />
    );
  }

  it("keeps visible segment overlays aligned to clipped time ranges", () => {
    renderWaveform([
      {
        id: "late",
        index: 1,
        startMs: 900,
        endMs: 1200,
        transcript: "",
        translation: "",
        savedState: "saved"
      },
      {
        id: "reversed",
        index: 2,
        startMs: 800,
        endMs: 600,
        transcript: "",
        translation: "",
        savedState: "saved"
      },
      {
        id: "early",
        index: 3,
        startMs: -100,
        endMs: 100,
        transcript: "",
        translation: "",
        savedState: "saved"
      }
    ]);

    const overlays = screen.getAllByTestId("waveform-segment-overlay");
    expect(overlays[0]).toHaveStyle({ left: "28.8px", width: "3.2px" });
    expect(overlays[1]).toHaveStyle({ left: "19.2px", width: "6.4px" });
    expect(overlays[2]).toHaveStyle({ left: "0px", width: "3.2px" });
    for (const overlay of overlays) {
      expect(overlay).not.toHaveClass("min-w-10");
    }
  });

  it("renders deterministic zero-width overlays for invalid duration or zero-length segments", () => {
    renderWaveform(
      [
        {
          id: "zero",
          index: 1,
          startMs: 500,
          endMs: 500,
          transcript: "",
          translation: "",
          savedState: "saved"
        }
      ],
      0
    );

    expect(screen.getByTestId("waveform-segment-overlay")).toHaveStyle({ left: "0px", width: "0px" });
  });

  it("renders dense narrow waveform bars instead of stretching source samples", () => {
    renderWaveform(
      [
        {
          id: "seg-1",
          index: 1,
          startMs: 0,
          endMs: 10_000,
          transcript: "",
          translation: "",
          savedState: "saved"
        }
      ],
      10_000
    );

    const bars = screen.getAllByTestId("waveform-bar");
    expect(bars.length).toBeGreaterThan(80);
    expect(bars[0]).toHaveStyle({ width: "1px" });
  });

  it("renders zero-level waveform bars as visible silent gaps", () => {
    renderWaveform(
      [
        {
          id: "seg-1",
          index: 1,
          startMs: 0,
          endMs: 10_000,
          transcript: "",
          translation: "",
          savedState: "saved"
        }
      ],
      10_000,
      [
        { id: "bar-silent", level: 0 },
        { id: "bar-loud", level: 96 }
      ]
    );

    const bars = screen.getAllByTestId("waveform-bar");
    expect(bars[0]).toHaveStyle({ height: "0%", opacity: "0", width: "1px" });
    expect(bars[bars.length - 1]).toHaveStyle({ opacity: "1" });
  });
});

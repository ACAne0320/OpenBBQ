import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { reviewModel } from "../../lib/mockData";
import { ResultsReview } from "../ResultsReview";

describe("ResultsReview", () => {
  it("renders video preview, waveform overlays, and editable segment cards", () => {
    render(<ResultsReview model={reviewModel} onSegmentChange={vi.fn()} />);

    expect(screen.getByLabelText("Video preview")).toBeInTheDocument();
    expect(screen.getByText("Audio loudness")).toBeInTheDocument();
    expect(screen.getByText("Editable segments")).toBeInTheDocument();
    expect(screen.getAllByTestId("waveform-bar")).toHaveLength(reviewModel.waveform.length);
    expect(screen.getAllByTestId("waveform-segment-overlay")).toHaveLength(reviewModel.segments.length);

    const segment = screen.getByRole("article", { name: "Segment 3" });
    expect(within(segment).getByText("00:12.100 -> 00:16.580")).toBeInTheDocument();
    expect(within(segment).getByLabelText("Transcript for segment 3")).toHaveValue(
      "Each result is saved as an editable versioned segment."
    );
    expect(within(segment).getByLabelText("Translation for segment 3")).toHaveValue(
      "Each result is saved as an editable versioned segment."
    );
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
});

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "./i18n";
import { ThemeProvider } from "./theme";

const mockApi = vi.hoisted(() => ({
  session: vi.fn(),
  cues: vi.fn(),
  updateCue: vi.fn(),
}));

vi.mock("./Timeline", () => ({
  Timeline: () => <div data-testid="timeline-canvas" />,
}));

vi.mock("./api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    payload: Record<string, unknown>;

    constructor(status: number, payload: Record<string, unknown>) {
      super(String(payload.error ?? `HTTP ${status}`));
      this.status = status;
      this.payload = payload;
    }
  },
  authenticateFromFragment: vi.fn(async () => undefined),
  opId: vi.fn(() => "test-op"),
  api: mockApi,
}));

import { ApiError } from "./api";
import { App } from "./App";

const cue = (
  id: number,
  source: string,
  start: number,
  end: number,
  status: "unreviewed" | "reviewed" = "unreviewed",
) => ({
  id,
  start,
  end,
  duration: end - start,
  source,
  source_cps: 2.5,
  target: `目标 ${id}`,
  budget: null,
  over_budget: false,
  time_warning: false,
  term_warning: false,
  status,
  note: null,
});

const response = (
  revision: string,
  firstSource: string,
  firstStatus: "unreviewed" | "reviewed" = "unreviewed",
) => ({
  revision,
  changed: [1],
  progress: { reviewed: 0, flagged: 0, unreviewed: 2, total: 2 },
  cues: [cue(1, firstSource, 10, 14, firstStatus), cue(2, "Second cue", 20, 24)],
});

describe("review autosave", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.session.mockResolvedValue({
      workspace: "/tmp/review",
      title: "Autosave test",
      source_type: "local_video",
      source_lang: "en",
      target_lang: "zh",
      languages: ["zh"],
      revision: "r1",
      progress: { reviewed: 0, flagged: 0, unreviewed: 2, total: 2 },
      media: {
        kind: "video",
        url: "/api/media",
        name: "test.mp4",
        duration: 120,
        playable: true,
        preview_status: "ready",
        preview_error: null,
      },
    });
    mockApi.cues.mockResolvedValue(response("r1", "First cue"));
  });

  it("serializes newer edits and never moves a dirty draft to the playback cue", async () => {
    let resolveFirstSave!: (value: ReturnType<typeof response>) => void;
    const firstSave = new Promise<ReturnType<typeof response>>((resolve) => {
      resolveFirstSave = resolve;
    });
    mockApi.updateCue
      .mockImplementationOnce(() => firstSave)
      .mockResolvedValueOnce(response("r3", "Edit B"));

    render(
      <I18nProvider initialLocale="en">
        <ThemeProvider initialTheme="dark">
          <App />
        </ThemeProvider>
      </I18nProvider>,
    );

    const source = await screen.findByRole("textbox", { name: "Source" });
    fireEvent.change(source, { target: { value: "Edit A" } });
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 450));
    });
    expect(mockApi.updateCue).toHaveBeenCalledTimes(1);
    expect(mockApi.updateCue).toHaveBeenLastCalledWith(
      1,
      expect.objectContaining({ base_revision: "r1", source: "Edit A" }),
    );

    fireEvent.change(source, { target: { value: "Edit B" } });
    const media = document.querySelector("video") as HTMLVideoElement;
    media.currentTime = 21;
    fireEvent.timeUpdate(media);
    expect(screen.getByRole("region", { name: "Selected cue #1" })).toBeInTheDocument();

    await act(async () => {
      resolveFirstSave(response("r2", "Edit A"));
    });

    await waitFor(() => expect(mockApi.updateCue).toHaveBeenCalledTimes(2));
    expect(mockApi.updateCue).toHaveBeenLastCalledWith(
      1,
      expect.objectContaining({ base_revision: "r2", source: "Edit B" }),
    );
    await waitFor(() => {
      expect(screen.getByText("Edit B")).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "Selected cue #2" })).toBeInTheDocument();
    });
  });

  it("only discards a conflicted draft after an explicit reload", async () => {
    mockApi.updateCue.mockRejectedValueOnce(
      new ApiError(409, { error: "review_conflict" }),
    );

    render(
      <I18nProvider initialLocale="en">
        <ThemeProvider initialTheme="dark">
          <App />
        </ThemeProvider>
      </I18nProvider>,
    );

    const source = await screen.findByRole("textbox", { name: "Source" });
    fireEvent.change(source, { target: { value: "Local conflict" } });
    const reload = await screen.findByRole("button", {
      name: "Discard edits and reload",
    });
    expect(source).toHaveValue("Local conflict");

    const latest = response("r2", "Externally reviewed", "reviewed");
    latest.progress = { reviewed: 1, flagged: 0, unreviewed: 1, total: 2 };
    mockApi.cues.mockResolvedValueOnce(latest);
    fireEvent.click(reload);

    await waitFor(() => {
      expect(screen.getByRole("region", { name: "Selected cue #2" })).toBeInTheDocument();
      expect(screen.getByRole("textbox", { name: "Source" })).toHaveValue("Second cue");
    });
    expect(mockApi.updateCue).toHaveBeenCalledTimes(1);
  });
});

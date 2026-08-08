import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Cue, Progress, Snapshot } from "../api/types";
import { I18nProvider } from "./i18n";
import { ThemeProvider } from "./theme";

const mockApi = vi.hoisted(() => ({
  session: vi.fn(),
  cues: vi.fn(),
  updateCue: vi.fn(),
  setStatus: vi.fn(),
  undo: vi.fn(),
  redo: vi.fn(),
  split: vi.fn(),
  merge: vi.fn(),
  insert: vi.fn(),
  deleteCue: vi.fn(),
  switchTarget: vi.fn(),
  previewStatus: vi.fn(async () => ({ status: "ready", error: null })),
  startPreview: vi.fn(async () => ({ status: "building", error: null })),
  waveform: vi.fn(),
  words: vi.fn(),
}));

vi.mock("../timeline/Timeline", () => ({
  Timeline: () => <div data-testid="timeline-canvas" />,
}));

vi.mock("../api/client", () => ({
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

import { ApiError } from "../api/client";
import { App } from "./App";

const progress: Progress = { reviewed: 0, flagged: 0, unreviewed: 2, total: 2 };

function cue(
  id: number,
  source: string,
  start: number,
  end: number,
  status: "unreviewed" | "reviewed" = "unreviewed",
): Cue {
  return {
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
    issues: [],
    status,
    note: null,
  };
}

function snapshot(
  revision: string,
  firstSource: string,
  firstStatus: "unreviewed" | "reviewed" = "unreviewed",
): Snapshot {
  return {
    revision,
    changed: [1],
    progress,
    suggestions: [],
    cues: [cue(1, firstSource, 10, 14, firstStatus), cue(2, "Second cue", 20, 24)],
  };
}

function renderApp() {
  return render(
    <I18nProvider initialLocale="en">
      <ThemeProvider initialTheme="dark">
        <App />
      </ThemeProvider>
    </I18nProvider>,
  );
}

describe("review workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    mockApi.session.mockResolvedValue({
      workspace: "/tmp/review",
      title: "App test",
      source_type: "local_video",
      source_lang: "en",
      target_lang: "zh",
      languages: ["zh"],
      revision: "r1",
      progress,
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
    mockApi.cues.mockResolvedValue(snapshot("r1", "First cue"));
  });

  it("lays out the three-zone workbench with a full-width timeline dock", async () => {
    renderApp();
    const playback = await screen.findByRole("group", { name: "Playback controls" });

    // Three zones + two drag resizers + bottom dock.
    expect(document.querySelector(".list-pane")).not.toBeNull();
    expect(document.querySelector(".center-pane")).not.toBeNull();
    expect(document.querySelector(".editor-pane")).not.toBeNull();
    expect(screen.getAllByRole("separator")).toHaveLength(2);
    const dock = document.querySelector(".timeline-dock");
    expect(dock).not.toBeNull();
    expect(screen.getByTestId("timeline-canvas").closest(".timeline-dock")).not.toBeNull();

    // Player controls are persistent and live on the media panel.
    expect(playback.closest(".media-panel")).not.toBeNull();
    expect(within(playback).getByRole("button", { name: "Play" })).toBeInTheDocument();
    expect(within(playback).getByRole("button", { name: "Playback speed" })).toBeInTheDocument();
    expect(within(playback).getByRole("group", { name: "Playback progress" })).toBeInTheDocument();
    const volume = within(playback).getByRole("slider", { name: "Volume" });
    expect(volume).toHaveAttribute("aria-orientation", "vertical");
    expect(playback.querySelector(".speed-control > .speed-popover")).toBeInTheDocument();
    expect(playback.querySelector(".timecode")).toHaveTextContent("00:00:10 / 00:02:00");
    expect(within(playback).getByRole("button", { name: "Fullscreen" })).toBeInTheDocument();
    expect(within(playback).queryByRole("button", { name: "Loop current cue" })).toBeNull();

    // Structural editing lives in the dock's edit toolbar.
    const editToolbar = document.querySelector(".edit-toolbar") as HTMLElement;
    expect(editToolbar.closest(".timeline-dock")).not.toBeNull();
    expect(within(editToolbar).queryByRole("button", { name: "Play" })).toBeNull();
    expect(within(editToolbar).getByRole("button", { name: "Split cue at playhead" })).toBeInTheDocument();

    // Timeline toolbar keeps zoom/snap controls.
    expect(screen.getByRole("group", { name: "Waveform · Cue Track" })).toHaveAttribute(
      "data-slot",
      "slider",
    );
    expect(screen.getByRole("switch", { name: "Snapping on" })).toBeInTheDocument();

    // The editor is its own zone with the language picker next to translation.
    const editor = screen.getByRole("region", { name: "Selected cue #1" });
    expect(editor.closest(".editor-pane")).not.toBeNull();
    const reviewLanguage = screen.getByRole("combobox", { name: "Subtitle language" });
    expect(reviewLanguage.closest(".translation-field")).not.toBeNull();
    expect(reviewLanguage.closest(".topbar")).toBeNull();

    // Cue list: one shared grid template, filters, search, follow toggle.
    const head = document.querySelector(".cue-table-head");
    const row = document.querySelector(".cue-summary");
    expect(head?.classList.contains("cue-grid")).toBe(true);
    expect(row?.classList.contains("cue-grid")).toBe(true);
    const filters = document.querySelector(".filter-row") as HTMLElement;
    expect(within(filters).getByRole("button", { name: "Unreviewed 2" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search or #ID" })).toBeInTheDocument();
    const followButton = screen.getByRole("button", { name: "Following playback" });
    fireEvent.click(followButton);
    expect(screen.getByRole("button", { name: "Resume follow" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    // Precision strip uses localized IN/OUT labels.
    const precision = document.querySelector(".precision-strip") as HTMLElement;
    expect(within(precision).getByText("#1")).toBeInTheDocument();
    expect(within(precision).getByText("IN")).toBeInTheDocument();
    expect(within(precision).getByText("OUT")).toBeInTheDocument();
    expect(within(precision).getByText("00:10.000")).toBeInTheDocument();
    expect(within(precision).getByText("4.00s")).toBeInTheDocument();

    // Topbar keeps locale/theme toggles, save state, and progress.
    const localeToggle = screen.getByRole("button", { name: "Switch interface to Chinese" });
    expect(localeToggle.closest(".topbar-actions")).not.toBeNull();
    expect(screen.getByText("Reviewed 0/2")).toBeInTheDocument();
  });

  it("confirms deletes with a localized dialog", async () => {
    mockApi.deleteCue.mockResolvedValue({
      ...snapshot("r2", "First cue"),
      changed: [],
      cues: [cue(2, "Second cue", 20, 24)],
    });
    renderApp();
    await screen.findByRole("region", { name: "Selected cue #1" });
    const editToolbar = document.querySelector(".edit-toolbar") as HTMLElement;
    fireEvent.click(within(editToolbar).getByRole("button", { name: "Delete cue" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Delete cue #1? You can undo immediately.")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(mockApi.deleteCue).not.toHaveBeenCalled();

    fireEvent.click(within(editToolbar).getByRole("button", { name: "Delete cue" }));
    const dialogAgain = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialogAgain).getByRole("button", { name: "Delete cue" }));
    await waitFor(() => expect(mockApi.deleteCue).toHaveBeenCalledTimes(1));
  });

  it("supports familiar media keyboard controls outside text fields", async () => {
    renderApp();
    await screen.findByRole("group", { name: "Playback controls" });
    const media = document.querySelector("video") as HTMLVideoElement;
    const play = vi.spyOn(media, "play").mockResolvedValue();
    expect(media.currentTime).toBe(10);

    fireEvent.click(media);
    expect(play).toHaveBeenCalledOnce();

    play.mockClear();
    const filterButton = screen.getByRole("button", { name: "Unreviewed 2" });
    fireEvent.keyDown(filterButton, { key: " ", code: "Space" });
    expect(play).not.toHaveBeenCalled();
    fireEvent.keyDown(filterButton, { key: "Enter", code: "Enter" });
    expect(mockApi.setStatus).not.toHaveBeenCalled();

    const source = screen.getByRole("textbox", { name: "Source" });
    fireEvent.keyDown(source, { key: "z", code: "KeyZ", metaKey: true });
    expect(mockApi.undo).not.toHaveBeenCalled();

    vi.useFakeTimers();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    fireEvent.keyUp(window, { key: "ArrowRight" });
    expect(media.currentTime).toBe(15);

    media.volume = 1;
    fireEvent.keyDown(window, { key: "ArrowDown" });
    expect(media.volume).toBeCloseTo(0.95);

    fireEvent.keyDown(window, { key: "ArrowRight" });
    act(() => vi.advanceTimersByTime(351));
    expect(media.playbackRate).toBe(2);
    expect(play).toHaveBeenCalled();
    expect(document.querySelector(".playback-notice")).toHaveTextContent("2×");
    fireEvent.keyUp(window, { key: "ArrowRight" });
    expect(media.playbackRate).toBe(1);
    vi.clearAllTimers();
    vi.useRealTimers();

    fireEvent.error(media);
    expect(mockApi.startPreview).toHaveBeenCalledOnce();
  });

  it("serializes newer edits and never moves a dirty draft to the playback cue", async () => {
    let resolveFirstSave!: (value: Snapshot) => void;
    const firstSave = new Promise<Snapshot>((resolve) => {
      resolveFirstSave = resolve;
    });
    mockApi.updateCue
      .mockImplementationOnce(() => firstSave)
      .mockResolvedValueOnce(snapshot("r3", "Edit B"));

    renderApp();
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
      resolveFirstSave(snapshot("r2", "Edit A"));
    });

    await waitFor(() => expect(mockApi.updateCue).toHaveBeenCalledTimes(2));
    expect(mockApi.updateCue).toHaveBeenLastCalledWith(
      1,
      expect.objectContaining({ base_revision: "r2", source: "Edit B" }),
    );
    // The selection stays on the edited cue: follow tracks playhead movement,
    // and a still playhead (paused seek during the dirty window) never yanks it.
    await waitFor(() => {
      expect(screen.getByRole("region", { name: "Selected cue #1" })).toBeInTheDocument();
      expect(screen.getByRole("textbox", { name: "Source" })).toHaveValue("Edit B");
    });
  });

  it("only discards a conflicted draft after an explicit reload", async () => {
    mockApi.updateCue.mockRejectedValueOnce(new ApiError(409, { error: "review_conflict" }));

    renderApp();
    const source = await screen.findByRole("textbox", { name: "Source" });
    fireEvent.change(source, { target: { value: "Local conflict" } });
    const reload = await screen.findByRole("button", { name: "Discard edits and reload" });
    expect(source).toHaveValue("Local conflict");

    const latest = snapshot("r2", "Externally reviewed", "reviewed");
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

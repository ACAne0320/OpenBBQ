import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "./i18n";
import { ThemeProvider } from "./theme";

vi.mock("./Timeline", () => ({
  Timeline: () => <div data-testid="timeline-canvas" />,
}));

vi.mock("./api", () => ({
  ApiError: class ApiError extends Error {
    status = 500;
    payload = {};
  },
  authenticateFromFragment: vi.fn(async () => undefined),
  opId: vi.fn(() => "test-op"),
  api: {
    session: vi.fn(async () => ({
      workspace: "/tmp/review",
      title: "Layout test",
      source_type: "local_video",
      source_lang: "en",
      target_lang: "zh",
      languages: ["zh"],
      revision: "r1",
      progress: { reviewed: 0, flagged: 0, unreviewed: 1, total: 1 },
      media: {
        kind: "video",
        url: "/api/media",
        name: "test.mp4",
        duration: 120,
        playable: true,
        preview_status: "ready",
        preview_error: null,
      },
    })),
    cues: vi.fn(async () => ({
      revision: "r1",
      changed: [],
      progress: { reviewed: 0, flagged: 0, unreviewed: 1, total: 1 },
      cues: [
        {
          id: 1,
          start: 10,
          end: 14,
          duration: 4,
          source: "Source cue",
          source_cps: 2.5,
          target: "目标字幕",
          budget: null,
          over_budget: false,
          time_warning: false,
          term_warning: false,
          status: "unreviewed",
          note: null,
        },
      ],
    })),
    undo: vi.fn(async () => ({
      revision: "r2",
      changed: [],
      progress: { reviewed: 0, flagged: 0, unreviewed: 1, total: 1 },
      cues: [],
    })),
    setStatus: vi.fn(async () => ({
      revision: "r2",
      changed: [],
      progress: { reviewed: 1, flagged: 0, unreviewed: 0, total: 1 },
      cues: [],
    })),
    startPreview: vi.fn(async () => ({ status: "building", error: null })),
  },
}));

import { api } from "./api";
import { App } from "./App";

describe("review workspace layout", () => {
  it("keeps playback controls on the media overlay and structural editing below", async () => {
    render(
      <I18nProvider initialLocale="en">
        <ThemeProvider initialTheme="dark">
          <App />
        </ThemeProvider>
      </I18nProvider>,
    );

    const playback = await screen.findByRole("group", { name: "Playback controls" });
    expect(playback.closest(".media-panel")).not.toBeNull();
    expect(within(playback).getByRole("button", { name: "Play" })).toBeInTheDocument();
    expect(within(playback).getByRole("button", { name: "Playback speed" })).toBeInTheDocument();
    expect(within(playback).getByRole("group", { name: "Playback progress" })).toBeInTheDocument();
    const volume = within(playback).getByRole("slider", { name: "Volume" });
    expect(volume).toHaveAttribute("aria-orientation", "vertical");
    expect(volume.querySelector(".volume-track")).toBeInTheDocument();
    expect(volume.querySelector(".volume-thumb")).toBeInTheDocument();
    expect(playback.querySelector(".speed-control > .speed-popover")).toBeInTheDocument();
    expect(playback.querySelector(".timecode")).toHaveTextContent("00:00:10 / 00:02:00");
    expect(playback.querySelector(".timecode")).not.toHaveTextContent(".");
    expect(within(playback).getByRole("button", { name: "Fullscreen" })).toBeInTheDocument();
    expect(within(playback).queryByRole("button", { name: "Loop current cue" })).toBeNull();
    const playerButtons = within(playback.querySelector(".player-control-row") as HTMLElement).getAllByRole("button");
    expect(playerButtons[0]).toHaveAccessibleName("Play");
    expect(playerButtons.at(-1)).toHaveAccessibleName("Fullscreen");

    const editToolbar = document.querySelector(".edit-toolbar");
    expect(editToolbar).not.toBeNull();
    expect(within(editToolbar as HTMLElement).queryByRole("button", { name: "Play" })).toBeNull();
    expect(within(editToolbar as HTMLElement).getByRole("button", { name: "Split cue at playhead" })).toBeInTheDocument();

    expect(
      screen.getByRole("group", { name: "Waveform · Cue Track" }),
    ).toHaveAttribute("data-slot", "slider");

    const reviewLanguage = screen.getByRole("combobox", { name: "Subtitle language" });
    expect(reviewLanguage.closest(".translation-field")).not.toBeNull();
    expect(reviewLanguage.closest(".topbar")).toBeNull();
    expect(screen.getByText("Translation")).toBeInTheDocument();
    const localeToggle = screen.getByRole("button", { name: "Switch interface to Chinese" });
    expect(localeToggle.closest(".topbar-actions")).not.toBeNull();
    expect(localeToggle.querySelector("svg")).not.toBeNull();
    expect(localeToggle).not.toHaveTextContent("UI");

    const filters = document.querySelector(".filter-row") as HTMLElement;
    expect(within(filters).getByRole("button", { name: "Unreviewed 1" })).toHaveTextContent("1");
    expect(within(filters).getByRole("button", { name: "Reviewed 0" })).toHaveTextContent("0");
    expect(within(filters).getByRole("button", { name: "Flagged 0" })).toHaveTextContent("0");
    expect(within(filters).getByRole("button", { name: "All 1" })).toHaveTextContent("1");
    expect(within(filters).getByText("Unreviewed")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search or #ID" })).toBeInTheDocument();
    const followButton = screen.getByRole("button", { name: "Following playback" });
    expect(followButton).toHaveTextContent("Following playback");
    expect(followButton).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(followButton);
    const resumeFollow = screen.getByRole("button", { name: "Resume follow" });
    expect(resumeFollow).toHaveTextContent("Resume follow");
    expect(resumeFollow).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Reviewed 0/1")).toBeInTheDocument();

    const precision = document.querySelector(".precision-strip") as HTMLElement;
    expect(within(precision).getByText("#1")).toBeInTheDocument();
    expect(within(precision).getByText("IN")).toBeInTheDocument();
    expect(within(precision).getByText("OUT")).toBeInTheDocument();
    expect(within(precision).getByText("00:10.000")).toBeInTheDocument();
    expect(within(precision).getByText("00:14.000")).toBeInTheDocument();
    expect(within(precision).getByText("4.00s")).toBeInTheDocument();
    expect(within(precision).queryByText("Selected cue")).not.toBeInTheDocument();
    expect(within(precision).queryByText("Duration")).not.toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Snapping on" })).toBeInTheDocument();
  });

  it("supports familiar media keyboard controls outside text fields", async () => {
    render(
      <I18nProvider initialLocale="en">
        <ThemeProvider initialTheme="dark">
          <App />
        </ThemeProvider>
      </I18nProvider>,
    );

    await screen.findByRole("group", { name: "Playback controls" });
    const media = document.querySelector("video") as HTMLVideoElement;
    const play = vi.spyOn(media, "play").mockResolvedValue();
    expect(media.currentTime).toBe(10);

    fireEvent.click(media);
    expect(play).toHaveBeenCalledOnce();

    play.mockClear();
    const filterButton = screen.getByRole("button", { name: "Unreviewed 1" });
    fireEvent.keyDown(filterButton, { key: " ", code: "Space" });
    expect(play).not.toHaveBeenCalled();
    fireEvent.keyDown(filterButton, { key: "Enter", code: "Enter" });
    expect(api.setStatus).not.toHaveBeenCalled();

    const source = screen.getByRole("textbox", { name: "Source" });
    fireEvent.keyDown(source, { key: "z", code: "KeyZ", metaKey: true });
    expect(api.undo).not.toHaveBeenCalled();

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
    expect(api.startPreview).toHaveBeenCalledOnce();
  });
});

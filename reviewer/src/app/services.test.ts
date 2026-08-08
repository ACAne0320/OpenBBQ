import { describe, expect, it } from "vitest";
import type { Api } from "../api/client";
import type { Cue } from "../api/types";
import { createAppServices } from "./services";

function cue(id: number, start: number, end: number): Cue {
  return {
    id,
    start,
    end,
    duration: end - start,
    source: `Source ${id}`,
    source_cps: 2.5,
    target: `目标 ${id}`,
    budget: null,
    over_budget: false,
    time_warning: false,
    term_warning: false,
    issues: [],
    status: "unreviewed",
    note: null,
  };
}

const cues = [cue(1, 0, 4), cue(2, 5, 9), cue(3, 10, 14)];

function setup() {
  // Watchers under test are installed by createAppServices; api is unused here.
  return createAppServices({} as Api).store;
}

describe("selection follows playhead movement", () => {
  it("tracks the active cue while playing, parking at the last cue across gaps", () => {
    const store = setup();
    store.setState({ cues, isPlaying: true, currentTime: 1, selectedId: 1, selection: [1] });
    store.setState({ currentTime: 6 });
    expect(store.getState().selectedId).toBe(2);
    // Gap between cue 2 and 3: selection stays on the last active cue.
    store.setState({ currentTime: 9.5 });
    expect(store.getState().selectedId).toBe(2);
    store.setState({ currentTime: 11 });
    expect(store.getState().selectedId).toBe(3);
  });

  it("tracks a seek while paused, then leaves the user's selection alone", () => {
    const store = setup();
    // Paused + playhead jump = scrub/seek: selection follows the landing cue.
    store.setState({ cues, isPlaying: false, currentTime: 6, selectedId: 1, selection: [1] });
    expect(store.getState().selectedId).toBe(2);
    // A still playhead never moves the selection again.
    store.setState({ selectedId: 1, selection: [1] });
    store.setState({ search: "anything" });
    expect(store.getState().selectedId).toBe(1);
  });

  it("suspends tracking while a draft is dirty", () => {
    const store = setup();
    store.setState({
      cues,
      isPlaying: true,
      currentTime: 1,
      selectedId: 1,
      selection: [1],
      dirty: true,
    });
    store.setState({ currentTime: 6 });
    expect(store.getState().selectedId).toBe(1);
  });

  it("never stomps an active multi-selection", () => {
    const store = setup();
    store.setState({
      cues,
      isPlaying: true,
      currentTime: 1,
      selectedId: 1,
      selection: [1, 2],
    });
    store.setState({ currentTime: 6 });
    expect(store.getState().selectedId).toBe(1);
    expect(store.getState().selection).toEqual([1, 2]);
  });

  it("re-engages the detached list view when playback starts", () => {
    const store = setup();
    store.setState({ viewDetached: true, isPlaying: false });
    store.setState({ isPlaying: true });
    expect(store.getState().viewDetached).toBe(false);
  });
});

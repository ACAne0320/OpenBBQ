import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type Api } from "../api/client";
import type { Cue, Progress, Session, Snapshot } from "../api/types";
import { CommandCenter } from "./commands";
import { PlayerController } from "../player/controller";
import { defaultPrefs } from "../store/prefs";
import { createAppStore, type AppStore, type Draft } from "../store/state";

const progress: Progress = { reviewed: 0, flagged: 0, unreviewed: 2, total: 2 };

function cue(id: number, overrides: Partial<Cue> = {}): Cue {
  return {
    id,
    start: id * 10,
    end: id * 10 + 4,
    duration: 4,
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
    ...overrides,
  };
}

function snapshot(revision: string, cues: Cue[]): Snapshot {
  return { revision, changed: [], progress, suggestions: [], cues };
}

function session(): Session {
  return {
    workspace: "/tmp/review",
    title: "Commands test",
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
  };
}

interface Harness {
  store: AppStore;
  commands: CommandCenter;
  api: {
    updateCue: ReturnType<typeof vi.fn>;
    setStatus: ReturnType<typeof vi.fn>;
    cues: ReturnType<typeof vi.fn>;
    session: ReturnType<typeof vi.fn>;
  };
}

function harness(cues: Cue[]): Harness {
  const store = createAppStore(defaultPrefs);
  store.setState({
    session: session(),
    cues,
    revision: "r1",
    progress,
    selectedId: cues[0]?.id ?? null,
    currentTime: cues[0]?.start ?? 0,
  });
  const api = {
    updateCue: vi.fn(),
    setStatus: vi.fn(),
    cues: vi.fn(),
    session: vi.fn(async () => session()),
  };
  const player = new PlayerController(store);
  const commands = new CommandCenter({ store, api: api as unknown as Api, player });
  return { store, commands, api };
}

function seedDraft(store: AppStore, overrides: Partial<Draft> = {}): void {
  const state = store.getState();
  const selected = state.cues.find((item) => item.id === state.selectedId);
  if (!selected) throw new Error("no selected cue");
  store.setState({
    draft: {
      source: selected.source,
      target: selected.target ?? "",
      start: selected.start,
      end: selected.end,
      note: selected.note ?? "",
      ...overrides,
    },
  });
}

async function flushAutosave(ms = 450): Promise<void> {
  await new Promise((resolve) => window.setTimeout(resolve, ms));
}

describe("command layer guards", () => {
  let cues: Cue[];
  beforeEach(() => {
    cues = [cue(1), cue(2)];
  });

  it("sends zero requests when the draft never actually changed", async () => {
    const { store, commands, api } = harness(cues);
    seedDraft(store);
    commands.updateDraft({ source: "Source 1" });
    await flushAutosave();
    expect(api.updateCue).not.toHaveBeenCalled();
    expect(api.setStatus).not.toHaveBeenCalled();
  });

  it("skips the save when an edit is reverted back to the snapshot", async () => {
    const { store, commands, api } = harness(cues);
    seedDraft(store);
    commands.updateDraft({ source: "Changed" });
    commands.updateDraft({ source: "Source 1" });
    await flushAutosave();
    expect(api.updateCue).not.toHaveBeenCalled();
    expect(store.getState().dirty).toBe(false);
    expect(store.getState().saveState).toBe("saved");
  });

  it("setCueTime with an unchanged range sends no request", async () => {
    const { commands, api } = harness(cues);
    await commands.setCueTime(1, 10, 14);
    expect(api.updateCue).not.toHaveBeenCalled();
    await commands.setCueTime(1, 10, 15);
    expect(api.updateCue).toHaveBeenCalledTimes(1);
    expect(api.updateCue).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ base_revision: "r1", start: 10, end: 15 }),
    );
  });

  it("blocks saves with start >= end before any request", async () => {
    const { store, commands, api } = harness(cues);
    seedDraft(store, { start: 14, end: 14 });
    store.setState({ dirty: true });
    await commands.persistDraft().catch(() => undefined);
    expect(api.updateCue).not.toHaveBeenCalled();
    expect(store.getState().saveState).toBe("failed");
    expect(store.getState().banner?.text).toContain("cue.timeOrder");
  });
});

describe("autosave", () => {
  let cues: Cue[];
  beforeEach(() => {
    cues = [cue(1), cue(2)];
  });

  it("debounces rapid edits into a single save with the final value", async () => {
    const { store, commands, api } = harness(cues);
    api.updateCue.mockImplementation(async (_id: number, body: { source: string }) =>
      snapshot("r2", [cue(1, { source: body.source }), cue(2)]),
    );
    seedDraft(store);
    commands.updateDraft({ source: "Edit A" });
    await flushAutosave(100);
    commands.updateDraft({ source: "Edit B" });
    await flushAutosave();
    expect(api.updateCue).toHaveBeenCalledTimes(1);
    expect(api.updateCue).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ base_revision: "r1", source: "Edit B", target: "目标 1" }),
    );
    expect(store.getState().saveState).toBe("saved");
  });

  it("serializes a newer edit behind the in-flight save with the new revision", async () => {
    const { store, commands, api } = harness(cues);
    let resolveFirst!: (value: Snapshot) => void;
    const firstSave = new Promise<Snapshot>((resolve) => {
      resolveFirst = resolve;
    });
    api.updateCue
      .mockImplementationOnce(() => firstSave)
      .mockImplementationOnce(async (_id: number, body: { source: string }) =>
        snapshot("r3", [cue(1, { source: body.source }), cue(2)]),
      );
    seedDraft(store);
    commands.updateDraft({ source: "Edit A" });
    await flushAutosave();
    expect(api.updateCue).toHaveBeenCalledTimes(1);

    commands.updateDraft({ source: "Edit B" });
    await flushAutosave();
    // The second edit must wait for the first save to resolve.
    expect(api.updateCue).toHaveBeenCalledTimes(1);
    resolveFirst(snapshot("r2", [cue(1, { source: "Edit A" }), cue(2)]));
    await vi.waitFor(() => expect(api.updateCue).toHaveBeenCalledTimes(2));
    expect(api.updateCue).toHaveBeenLastCalledWith(
      1,
      expect.objectContaining({ base_revision: "r2", source: "Edit B" }),
    );
    await vi.waitFor(() => expect(store.getState().saveState).toBe("saved"));
  });

  it("saves a note-only edit via setStatus preserving the current status", async () => {
    const reviewed = [cue(1, { status: "reviewed" }), cue(2)];
    const { store, commands, api } = harness(reviewed);
    api.setStatus.mockImplementation(async () => snapshot("r2", reviewed));
    seedDraft(store);
    commands.updateDraft({ note: "check later" });
    await flushAutosave();
    expect(api.updateCue).not.toHaveBeenCalled();
    expect(api.setStatus).toHaveBeenCalledTimes(1);
    expect(api.setStatus).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ status: "reviewed", note: "check later" }),
    );
  });

  it("sends content + note as two requests without resetting status", async () => {
    const reviewed = [cue(1, { status: "reviewed" }), cue(2)];
    const { store, commands, api } = harness(reviewed);
    api.updateCue.mockImplementation(async () => snapshot("r2", reviewed));
    api.setStatus.mockImplementation(async () => snapshot("r3", reviewed));
    seedDraft(store);
    commands.updateDraft({ source: "New source", note: "why" });
    await flushAutosave();
    expect(api.updateCue).toHaveBeenCalledTimes(1);
    expect(api.setStatus).toHaveBeenCalledTimes(1);
    expect(api.setStatus).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ base_revision: "r2", status: "reviewed", note: "why" }),
    );
  });
});

describe("conflict handling", () => {
  it("409 pauses autosave, shows a banner, and recovers via discard-and-reload", async () => {
    const cues = [cue(1), cue(2)];
    const { store, commands, api } = harness(cues);
    api.updateCue.mockRejectedValueOnce(new ApiError(409, { error: "review_conflict" }));
    seedDraft(store);
    commands.updateDraft({ source: "Local conflict" });
    await flushAutosave();
    expect(api.updateCue).toHaveBeenCalledTimes(1);
    expect(store.getState().saveState).toBe("conflict");
    expect(store.getState().banner?.danger).toBe(true);

    // Autosave is paused while conflicted.
    commands.updateDraft({ source: "Still local" });
    await flushAutosave();
    expect(api.updateCue).toHaveBeenCalledTimes(1);
    expect(store.getState().draft?.source).toBe("Still local");

    // Discard-and-reload swaps in the latest server state.
    const latest = snapshot("r9", [cue(1, { source: "Server version", status: "reviewed" }), cue(2)]);
    api.cues.mockResolvedValueOnce(latest);
    await commands.reloadDiscard();
    expect(api.cues).toHaveBeenCalled();
    expect(store.getState().saveState).toBe("saved");
    expect(store.getState().banner).toBeNull();
    expect(store.getState().dirty).toBe(false);
    expect(store.getState().revision).toBe("r9");
    expect(store.getState().cues[0].source).toBe("Server version");
  });
});

describe("review actions", () => {
  it("mark reviewed jumps to the next unreviewed cue", async () => {
    const cues = [cue(1), cue(2)];
    const { store, commands, api } = harness(cues);
    const after = snapshot("r2", [cue(1, { status: "reviewed" }), cue(2)]);
    api.setStatus.mockImplementation(async () => after);
    seedDraft(store);
    await commands.mark("reviewed");
    expect(api.setStatus).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ status: "reviewed", note: null }),
    );
    expect(store.getState().selectedId).toBe(2);
    expect(store.getState().currentTime).toBe(20);
  });
});

describe("explicit navigation during playback", () => {
  it("selectCue pauses a watch-through so follow can't yank the selection", async () => {
    const pause = vi.spyOn(PlayerController.prototype, "pause");
    const cues = [cue(1), cue(2)];
    const { store, commands } = harness(cues);
    store.setState({ isPlaying: true });
    await commands.selectCue(cues[1]);
    expect(store.getState().selectedId).toBe(2);
    expect(pause).toHaveBeenCalledTimes(1);
    pause.mockRestore();
  });

  it("selectCue does not pause when the video is already paused", async () => {
    const pause = vi.spyOn(PlayerController.prototype, "pause");
    const cues = [cue(1), cue(2)];
    const { commands } = harness(cues);
    await commands.selectCue(cues[1]);
    expect(pause).not.toHaveBeenCalled();
    pause.mockRestore();
  });
});

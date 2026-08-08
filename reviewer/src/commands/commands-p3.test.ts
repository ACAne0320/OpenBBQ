import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Api } from "../api/client";
import type {
  BatchDryRunResult,
  Cue,
  CueIssue,
  Progress,
  Session,
  Snapshot,
  Suggestion,
} from "../api/types";
import { CommandCenter } from "./commands";
import { PlayerController } from "../player/controller";
import { defaultPrefs } from "../store/prefs";
import { createAppStore, type AppStore } from "../store/state";

const progress: Progress = { reviewed: 0, flagged: 0, unreviewed: 3, total: 3 };

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

function issue(kind: CueIssue["kind"], overrides: Partial<CueIssue> = {}): CueIssue {
  return {
    cue_id: 1,
    kind,
    severity: "warning",
    message: kind,
    detail: {},
    source: "rule",
    dismissed: false,
    suggestion_ids: [],
    ...overrides,
  };
}

function suggestion(id: string, cueId: number, overrides: Partial<Suggestion> = {}): Suggestion {
  return {
    id,
    cue_id: cueId,
    kind: "agent_note",
    severity: "info",
    message: `suggestion ${id}`,
    patch: { target: `proposed ${id}` },
    content_hash: "sha256:" + "0".repeat(64),
    status: "pending",
    created_at: "2026-08-04T00:00:00Z",
    resolved_at: null,
    ...overrides,
  };
}

function snapshot(revision: string, cues: Cue[], suggestions: Suggestion[] = []): Snapshot {
  return { revision, changed: [], progress, suggestions, cues };
}

function session(): Session {
  return {
    workspace: "/tmp/review",
    title: "P3 commands test",
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

type MockedApi = {
  [K in
    | "dismissIssue"
    | "acceptSuggestion"
    | "rejectSuggestion"
    | "reopenSuggestion"
    | "batchPreview"
    | "batchReplace"
    | "batchStatus"
    | "batchDelete"
    | "addGlossaryTerm"
    | "split"]: ReturnType<typeof vi.fn>;
};

interface Harness {
  store: AppStore;
  commands: CommandCenter;
  api: MockedApi;
}

function harness(cues: Cue[], suggestions: Suggestion[] = []): Harness {
  const store = createAppStore(defaultPrefs);
  store.setState({
    session: session(),
    cues,
    revision: "r1",
    progress,
    suggestions,
    selectedId: cues[0]?.id ?? null,
    selection: cues[0] ? [cues[0].id] : [],
    currentTime: cues[0]?.start ?? 0,
  });
  const api: MockedApi = {
    dismissIssue: vi.fn(async () => snapshot("r2", cues)),
    acceptSuggestion: vi.fn(async () => snapshot("r2", cues)),
    rejectSuggestion: vi.fn(async () => snapshot("r2", cues)),
    reopenSuggestion: vi.fn(async () => snapshot("r2", cues)),
    batchPreview: vi.fn(async (): Promise<BatchDryRunResult> => ({ matches: [], revision: "r1" })),
    batchReplace: vi.fn(async () => snapshot("r2", cues)),
    batchStatus: vi.fn(async () => snapshot("r2", cues)),
    batchDelete: vi.fn(async () => snapshot("r2", cues.slice(0, 1))),
    addGlossaryTerm: vi.fn(async () => ({
      ...snapshot("r2", cues),
      glossary: "ws",
      term_report: { added: ["Hello"], updated: [], unchanged: [], aliases_added: 0 },
    })),
    split: vi.fn(async () => snapshot("r2", cues)),
  };
  const player = new PlayerController(store);
  const commands = new CommandCenter({ store, api: api as unknown as Api, player });
  return { store, commands, api };
}

function seedDraft(store: AppStore): void {
  const state = store.getState();
  const selected = state.cues.find((item) => item.id === state.selectedId);
  if (!selected) throw new Error("no selected cue");
  store.setState({
    draft: {
      source: selected.source,
      target: selected.target ?? "",
      start: selected.start,
      end: selected.end,
      note: "",
    },
  });
}

describe("issue + suggestion commands", () => {
  let cues: Cue[];
  beforeEach(() => {
    cues = [cue(1, { issues: [issue("term")] }), cue(2), cue(3)];
  });

  it("dismissIssue posts the kind with base revision", async () => {
    const { commands, api } = harness(cues);
    await commands.dismissIssue(1, "term");
    expect(api.dismissIssue).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ base_revision: "r1", kind: "term" }),
    );
  });

  it("accept/reject/reopen route to their endpoints with chained revisions", async () => {
    const { commands, api } = harness(cues, [suggestion("s1", 1)]);
    await commands.acceptSuggestion("s1");
    await commands.rejectSuggestion("s1");
    await commands.reopenSuggestion("s1");
    expect(api.acceptSuggestion).toHaveBeenCalledWith(
      "s1",
      expect.objectContaining({ base_revision: "r1" }),
    );
    // Each response bumped the revision to r2, so the next call chains on it.
    expect(api.rejectSuggestion).toHaveBeenCalledWith(
      "s1",
      expect.objectContaining({ base_revision: "r2" }),
    );
    expect(api.reopenSuggestion).toHaveBeenCalledWith(
      "s1",
      expect.objectContaining({ base_revision: "r2" }),
    );
  });

  it("applySuggestionToDraft fills the draft without any mutation", async () => {
    const { store, commands, api } = harness(cues, [
      suggestion("s1", 1, { patch: { target: "proposed", start: 11 } }),
    ]);
    seedDraft(store);
    commands.applySuggestionToDraft(store.getState().suggestions[0]);
    const draft = store.getState().draft;
    expect(draft?.target).toBe("proposed");
    expect(draft?.start).toBe(11);
    expect(draft?.source).toBe("Source 1");
    expect(store.getState().dirty).toBe(true);
    expect(api.acceptSuggestion).not.toHaveBeenCalled();
  });
});

describe("batch commands", () => {
  let cues: Cue[];
  beforeEach(() => {
    cues = [cue(1), cue(2), cue(3)];
  });

  it("previewBatchReplace is a pure read with dry_run semantics", async () => {
    const { store, commands, api } = harness(cues);
    const result = await commands.previewBatchReplace({
      find: "Source",
      replace: "X",
      fields: ["source"],
      caseSensitive: false,
      regex: false,
    });
    expect(api.batchPreview).toHaveBeenCalledWith(
      expect.objectContaining({
        base_revision: "r1",
        find: "Source",
        replace: "X",
        fields: ["source"],
        case_sensitive: false,
        regex: false,
      }),
    );
    expect(result.revision).toBe("r1");
    expect(store.getState().revision).toBe("r1");
  });

  it("preview passes the cue scope when provided", async () => {
    const { commands, api } = harness(cues);
    await commands.previewBatchReplace({
      find: "x",
      replace: "y",
      fields: ["target"],
      caseSensitive: true,
      regex: true,
      cueIds: [2, 3],
    });
    expect(api.batchPreview).toHaveBeenCalledWith(
      expect.objectContaining({ cue_ids: [2, 3], fields: ["target"], regex: true }),
    );
  });

  it("executeBatchReplace mutates through the standard pipeline", async () => {
    const { store, commands, api } = harness(cues);
    await commands.executeBatchReplace({
      find: "Source",
      replace: "X",
      fields: ["source"],
      caseSensitive: false,
      regex: false,
    });
    expect(api.batchReplace).toHaveBeenCalledWith(
      expect.objectContaining({ base_revision: "r1" }),
    );
    expect(store.getState().revision).toBe("r2");
  });

  it("batchStatus marks every selected cue in one call", async () => {
    const { commands, api } = harness(cues);
    await commands.batchStatus([1, 2, 3], "reviewed");
    expect(api.batchStatus).toHaveBeenCalledWith(
      expect.objectContaining({ cue_ids: [1, 2, 3], status: "reviewed" }),
    );
  });

  it("batchDelete removes the set and selects the neighbor", async () => {
    const { store, commands, api } = harness(cues);
    store.setState({ selectedId: 2, selection: [2, 3] });
    await commands.batchDelete([2, 3]);
    expect(api.batchDelete).toHaveBeenCalledWith(
      expect.objectContaining({ cue_ids: [2, 3] }),
    );
    const state = store.getState();
    expect(state.selectedId).toBe(1);
    expect(state.selection).toEqual([1]);
  });
});

describe("glossary commands", () => {
  it("addTerm posts the pair, applies the snapshot, and toasts", async () => {
    const { store, commands, api } = harness([cue(1)]);
    commands.setLocalizer((key, values) =>
      `${key}:${JSON.stringify(values ?? {})}`,
    );
    const ok = await commands.addTerm("  Hello ", " 你好 ", " note ");
    expect(ok).toBe(true);
    expect(api.addGlossaryTerm).toHaveBeenCalledWith(
      expect.objectContaining({
        base_revision: "r1",
        source: "Hello",
        target: "你好",
        note: "note",
      }),
    );
    expect(store.getState().revision).toBe("r2");
    expect(store.getState().addTerm).toBeNull();
    expect(store.getState().toast).toContain("glossary.success");
  });

  it("addTerm rejects blank input without a request", async () => {
    const { commands, api } = harness([cue(1)]);
    expect(await commands.addTerm(" ", "你好")).toBe(false);
    expect(api.addGlossaryTerm).not.toHaveBeenCalled();
  });
});

describe("selection commands", () => {
  let cues: Cue[];
  beforeEach(() => {
    cues = [cue(1), cue(2), cue(3)];
  });

  it("selectRange spans anchor to target in the visible order", () => {
    const { store, commands } = harness(cues);
    commands.selectRange(3, [1, 2, 3]);
    expect(store.getState().selection).toEqual([1, 2, 3]);
    commands.selectRange(1, [1, 2, 3]);
    expect(store.getState().selection).toEqual([1]);
  });

  it("toggleInSelection adds and removes", () => {
    const { store, commands } = harness(cues);
    commands.toggleInSelection(2);
    expect(store.getState().selection).toEqual([1, 2]);
    commands.toggleInSelection(2);
    expect(store.getState().selection).toEqual([1]);
  });

  it("clearSelection falls back to the anchor", () => {
    const { store, commands } = harness(cues);
    commands.toggleInSelection(2);
    commands.toggleInSelection(3);
    commands.clearSelection();
    expect(store.getState().selection).toEqual([1]);
  });
});

describe("split word-boundary snapping", () => {
  it("snaps the cut to a nearby word boundary and splits text at the word", async () => {
    const { store, commands, api } = harness([
      cue(1, { start: 10, end: 14, duration: 4, source: "Hello brave new world" }),
    ]);
    seedDraft(store);
    store.setState({
      currentTime: 12.1,
      transcriptWords: [{ word: "new", start: 12.05, end: 12.45 }],
      wordsRange: { start: 10, end: 14 },
    });
    await commands.splitCurrent();
    expect(api.split).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        at: 12.05,
        source_left: "Hello brave",
        source_right: "new world",
      }),
    );
  });

  it("falls back to the playhead when no word boundary is nearby", async () => {
    const { store, commands, api } = harness([
      cue(1, { start: 10, end: 14, duration: 4, source: "Hello brave new world" }),
    ]);
    seedDraft(store);
    store.setState({ currentTime: 12, transcriptWords: [], wordsRange: null });
    await commands.splitCurrent();
    const call = api.split.mock.calls[0] as [number, { at: number }];
    expect(call[1].at).toBe(12);
  });
});

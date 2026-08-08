import { describe, expect, it } from "vitest";
import type { Cue, CueIssue } from "../api/types";
import { countIssues, cueIssueKinds, filterCues, selectBudgetUsage, selectOverlayCue } from "./selectors";
import { defaultPrefs } from "./prefs";
import { createAppStore } from "./state";

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

describe("cue filtering", () => {
  const cues = [
    cue(1),
    cue(2, { status: "reviewed" }),
    cue(3, { status: "flagged", target: null }),
    cue(4, { over_budget: true }),
    cue(5, { time_warning: true }),
    cue(6, { term_warning: true, target: "  " }),
  ];

  it("filters by status and quality flags", () => {
    expect(filterCues(cues, "all", "")).toHaveLength(6);
    expect(filterCues(cues, "unreviewed", "").map((c) => c.id)).toEqual([1, 4, 5, 6]);
    expect(filterCues(cues, "reviewed", "").map((c) => c.id)).toEqual([2]);
    expect(filterCues(cues, "flagged", "").map((c) => c.id)).toEqual([3]);
    expect(filterCues(cues, "missing", "").map((c) => c.id)).toEqual([3, 6]);
    expect(filterCues(cues, "over_budget", "").map((c) => c.id)).toEqual([4]);
    expect(filterCues(cues, "time_warning", "").map((c) => c.id)).toEqual([5]);
    expect(filterCues(cues, "term_warning", "").map((c) => c.id)).toEqual([6]);
  });

  it("searches text, target, and #id", () => {
    expect(filterCues(cues, "all", "source 2").map((c) => c.id)).toEqual([2]);
    expect(filterCues(cues, "all", "#3").map((c) => c.id)).toEqual([3]);
    expect(filterCues(cues, "all", "3").map((c) => c.id)).toEqual([3]);
    expect(filterCues(cues, "all", "目标 4").map((c) => c.id)).toEqual([4]);
    expect(filterCues(cues, "all", "nothing").map((c) => c.id)).toEqual([]);
  });

  it("combines filter and search", () => {
    expect(filterCues(cues, "unreviewed", "source 4").map((c) => c.id)).toEqual([4]);
    expect(filterCues(cues, "reviewed", "source 4").map((c) => c.id)).toEqual([]);
  });
});

describe("issue derivations", () => {
  it("counts non-dismissed issues by kind", () => {
    const cues = [
      cue(1, {
        issues: [issue("term"), issue("budget"), issue("budget", { dismissed: true })],
      }),
      cue(2, { issues: [issue("agent_note", { source: "agent", severity: "info" })] }),
    ];
    const counts = countIssues(cues);
    expect(counts.total).toBe(3);
    expect(counts.byKind).toEqual({ term: 1, budget: 1, agent_note: 1 });
  });

  it("dedupes issue kinds per cue and skips dismissed", () => {
    const kinds = cueIssueKinds([
      issue("term"),
      issue("term", { message: "again" }),
      issue("timing", { dismissed: true }),
    ]);
    expect(kinds.map((entry) => entry.kind)).toEqual(["term"]);
  });
});

describe("selectOverlayCue", () => {
  it("shows only the cue at the playhead — empty in gaps, never the selection", () => {
    const store = createAppStore(defaultPrefs);
    store.setState({
      cues: [cue(1, { start: 0, end: 4 }), cue(2, { start: 10, end: 14 })],
      selectedId: 1,
    });
    // Playhead inside cue 2: shows cue 2 (even though cue 1 is selected).
    store.setState({ currentTime: 12 });
    expect(selectOverlayCue(store.getState())?.id).toBe(2);
    // Playhead in the gap between cues: empty, no fallback to the selection.
    store.setState({ currentTime: 7 });
    expect(selectOverlayCue(store.getState())).toBeNull();
    // Hidden mode suppresses even an active cue.
    store.setState({ currentTime: 1, prefs: { ...defaultPrefs, overlay: "hidden" } });
    expect(selectOverlayCue(store.getState())).toBeNull();
  });
});

describe("selectBudgetUsage", () => {
  it("derives live usage from the draft and returns a stable snapshot", () => {
    const store = createAppStore(defaultPrefs);
    store.setState({
      cues: [cue(1, { budget: { max_chars: 10, seconds: 4 } })],
      selectedId: 1,
      draft: { source: "Source 1", target: "目标 1", start: 10, end: 14, note: "" },
    });
    const state = store.getState();
    const first = selectBudgetUsage(state);
    expect(first).toEqual({ used: 4, limit: 10, over: false });
    // useSyncExternalStore requires a cached snapshot identity — a fresh object
    // per call loops the editor render forever (React #185).
    expect(selectBudgetUsage(state)).toBe(first);
    store.setState({ currentTime: 12 });
    expect(selectBudgetUsage(store.getState())).toBe(first);
  });
});

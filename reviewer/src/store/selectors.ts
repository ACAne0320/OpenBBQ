import type { Cue, CueIssue, IssueKind } from "../api/types";
import type { AppState, CueFilter, Draft } from "./state";

export function findCue(cues: Cue[], id: number | null): Cue | null {
  if (id == null) return null;
  return cues.find((cue) => cue.id === id) ?? null;
}

export const selectSelectedCue = (state: AppState): Cue | null =>
  findCue(state.cues, state.selectedId);

/** Primitive selector: re-renders subscribers only when the cue at the playhead changes. */
export const selectActiveCueId = (state: AppState): number | null => {
  const active = state.cues.find(
    (cue) => state.currentTime >= cue.start && state.currentTime <= cue.end,
  );
  return active?.id ?? null;
};

export const selectActiveCue = (state: AppState): Cue | null =>
  findCue(state.cues, selectActiveCueId(state));

/** Subtitle overlay previews the track at the playhead: gaps render empty
 *  (never the selected cue), so what you see is what a viewer would see. */
export const selectOverlayCue = (state: AppState): Cue | null =>
  state.prefs.overlay === "hidden" ? null : selectActiveCue(state);

export function matchesFilter(cue: Cue, filter: CueFilter): boolean {
  if (filter === "all") return true;
  if (filter === "missing") return !cue.target?.trim();
  if (filter === "over_budget") return cue.over_budget;
  if (filter === "time_warning") return cue.time_warning;
  if (filter === "term_warning") return cue.term_warning;
  return cue.status === filter;
}

export function matchesSearch(cue: Cue, query: string): boolean {
  if (!query) return true;
  return (
    String(cue.id) === query.replace(/^#/, "") ||
    cue.source.toLocaleLowerCase().includes(query) ||
    Boolean(cue.target?.toLocaleLowerCase().includes(query))
  );
}

export function filterCues(cues: Cue[], filter: CueFilter, search: string): Cue[] {
  const query = search.trim().toLocaleLowerCase();
  return cues.filter((cue) => matchesFilter(cue, filter) && matchesSearch(cue, query));
}

/** Memoized so list subscribers get a stable array identity between store ticks. */
let filteredCache: { cues: Cue[]; filter: CueFilter; search: string; result: Cue[] } | null = null;

export const selectFilteredCues = (state: AppState): Cue[] => {
  const { cues, search } = state;
  const filter = state.prefs.filter;
  if (
    filteredCache &&
    filteredCache.cues === cues &&
    filteredCache.filter === filter &&
    filteredCache.search === search
  ) {
    return filteredCache.result;
  }
  const result = filterCues(cues, filter, search);
  filteredCache = { cues, filter, search, result };
  return result;
};

export interface IssueCounts {
  total: number;
  byKind: Partial<Record<IssueKind, number>>;
}

export function countIssues(cues: Cue[]): IssueCounts {
  const byKind: Partial<Record<IssueKind, number>> = {};
  let total = 0;
  for (const cue of cues) {
    for (const issue of cue.issues) {
      if (issue.dismissed) continue;
      byKind[issue.kind] = (byKind[issue.kind] ?? 0) + 1;
      total += 1;
    }
  }
  return { total, byKind };
}

let issueCache: { cues: Cue[]; result: IssueCounts } | null = null;

export const selectIssueCounts = (state: AppState): IssueCounts => {
  if (issueCache && issueCache.cues === state.cues) return issueCache.result;
  const result = countIssues(state.cues);
  issueCache = { cues: state.cues, result };
  return result;
};

/** Distinct non-dismissed issue kinds for one cue, in stable order. */
export function cueIssueKinds(issues: CueIssue[]): CueIssue[] {
  const seen = new Set<IssueKind>();
  const result: CueIssue[] = [];
  for (const issue of issues) {
    if (issue.dismissed || seen.has(issue.kind)) continue;
    seen.add(issue.kind);
    result.push(issue);
  }
  return result;
}

export interface BudgetUsage {
  used: number;
  limit: number;
  over: boolean;
}

let budgetCache: { cue: Cue; targetLength: number; result: BudgetUsage } | null = null;

/**
 * Live budget: derived from the local draft, not the server snapshot, so the
 * indicator tracks typing instead of lagging one save behind. Memoized: an
 * uncached fresh object per call loops useSyncExternalStore forever.
 */
export const selectBudgetUsage = (state: AppState): BudgetUsage | null => {
  const cue = selectSelectedCue(state);
  if (!cue?.budget || !state.draft) return null;
  const targetLength = state.draft.target.length;
  if (budgetCache && budgetCache.cue === cue && budgetCache.targetLength === targetLength) {
    return budgetCache.result;
  }
  const result: BudgetUsage = {
    used: targetLength,
    limit: cue.budget.max_chars,
    over: targetLength > cue.budget.max_chars,
  };
  budgetCache = { cue, targetLength, result };
  return result;
};

export function draftEquals(a: Draft, b: Draft): boolean {
  return (
    a.source === b.source &&
    a.target === b.target &&
    a.start === b.start &&
    a.end === b.end &&
    a.note === b.note
  );
}

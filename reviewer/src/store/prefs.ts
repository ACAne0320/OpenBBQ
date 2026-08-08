import type { AppStore, Preferences } from "./state";

const PREFS_KEY = "openbbq-review-prefs";

export const defaultPrefs: Preferences = {
  overlay: "bilingual",
  snap: true,
  zoom: 1,
  largeTimeline: false,
  loopCue: false,
  playbackRate: 1,
  volume: 1,
  muted: false,
  filter: "unreviewed",
  leftTab: "list",
  listWidth: 320,
  editorWidth: 380,
  nudgeStep: 0.1,
};

const OVERLAYS = new Set(["bilingual", "source", "target", "hidden"]);
const FILTERS = new Set([
  "all",
  "unreviewed",
  "reviewed",
  "flagged",
  "missing",
  "over_budget",
  "time_warning",
  "term_warning",
]);

function numberIn(value: unknown, min: number, max: number): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= min && value <= max
    ? value
    : undefined;
}

/** Reads persisted preferences, dropping values that fail validation. */
export function readStoredPrefs(): Partial<Preferences> {
  let raw: Record<string, unknown>;
  try {
    raw = JSON.parse(window.localStorage.getItem(PREFS_KEY) ?? "{}") as Record<string, unknown>;
  } catch {
    return {};
  }
  if (typeof raw !== "object" || raw === null) return {};
  const prefs: Partial<Preferences> = {};
  if (typeof raw.overlay === "string" && OVERLAYS.has(raw.overlay)) {
    prefs.overlay = raw.overlay as Preferences["overlay"];
  }
  if (typeof raw.snap === "boolean") prefs.snap = raw.snap;
  if (typeof raw.largeTimeline === "boolean") prefs.largeTimeline = raw.largeTimeline;
  if (typeof raw.loopCue === "boolean") prefs.loopCue = raw.loopCue;
  if (typeof raw.muted === "boolean") prefs.muted = raw.muted;
  if (typeof raw.filter === "string" && FILTERS.has(raw.filter)) {
    prefs.filter = raw.filter as Preferences["filter"];
  }
  if (raw.leftTab === "list" || raw.leftTab === "issues") prefs.leftTab = raw.leftTab;
  const zoom = numberIn(raw.zoom, 1, 96);
  if (zoom !== undefined) prefs.zoom = zoom;
  const playbackRate = numberIn(raw.playbackRate, 0.25, 4);
  if (playbackRate !== undefined) prefs.playbackRate = playbackRate;
  const volume = numberIn(raw.volume, 0, 1);
  if (volume !== undefined) prefs.volume = volume;
  const nudgeStep = numberIn(raw.nudgeStep, 0.001, 1);
  if (nudgeStep !== undefined) prefs.nudgeStep = nudgeStep;
  const listWidth = numberIn(raw.listWidth, 240, 560);
  if (listWidth !== undefined) prefs.listWidth = listWidth;
  const editorWidth = numberIn(raw.editorWidth, 300, 560);
  if (editorWidth !== undefined) prefs.editorWidth = editorWidth;
  return prefs;
}

export function loadPrefs(): { prefs: Preferences; stored: Partial<Preferences> } {
  const stored = readStoredPrefs();
  return { prefs: { ...defaultPrefs, ...stored }, stored };
}

/** Persists the prefs slice on every change; returns an unsubscribe. */
export function watchPrefs(store: AppStore): () => void {
  let last = store.getState().prefs;
  return store.subscribe(() => {
    const prefs = store.getState().prefs;
    if (prefs === last) return;
    last = prefs;
    window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  });
}

/** Merges a partial prefs update into the store (single write path for UI). */
export function updatePrefs(store: AppStore, patch: Partial<Preferences>): void {
  store.setState((state) => ({ prefs: { ...state.prefs, ...patch } }));
}

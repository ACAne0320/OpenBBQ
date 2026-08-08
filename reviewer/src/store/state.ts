import type {
  Cue,
  Progress,
  ReviewStatus,
  Session,
  Suggestion,
  TimedWord,
} from "../api/types";
import { Store } from "./store";

export type SaveState = "saved" | "saving" | "failed" | "conflict";

export type CueFilter =
  | "all"
  | ReviewStatus
  | "missing"
  | "over_budget"
  | "time_warning"
  | "term_warning";

export type OverlayMode = "bilingual" | "source" | "target" | "hidden";

export type LeftTab = "list" | "issues";

export interface Draft {
  source: string;
  target: string;
  start: number;
  end: number;
  note: string;
}

export interface Banner {
  danger: boolean;
  text: string;
}

/** Prefill for the add-term dialog; null means the dialog is closed. */
export interface AddTermDraft {
  source: string;
  target: string;
  note: string;
}

/** User preferences persisted to localStorage (same mechanism as locale/theme). */
export interface Preferences {
  overlay: OverlayMode;
  snap: boolean;
  zoom: number;
  largeTimeline: boolean;
  loopCue: boolean;
  playbackRate: number;
  volume: number;
  muted: boolean;
  filter: CueFilter;
  leftTab: LeftTab;
  listWidth: number;
  editorWidth: number;
  nudgeStep: number;
}

export interface AppState {
  session: Session | null;
  cues: Cue[];
  revision: string;
  progress: Progress;
  suggestions: Suggestion[];
  selectedId: number | null;
  /** Multi-selection set (anchor is always `selectedId`). */
  selection: number[];
  currentTime: number;
  draft: Draft | null;
  dirty: boolean;
  saveState: SaveState;
  banner: Banner | null;
  /** Transient success toast (auto-expires). */
  toast: string | null;
  search: string;
  prefs: Preferences;
  isPlaying: boolean;
  playbackNotice: string | null;
  deleteOpen: boolean;
  showNote: boolean;
  findOpen: boolean;
  helpOpen: boolean;
  addTerm: AddTermDraft | null;
  /** Completion banner dismissed for the current completed streak. */
  completedDismissed: boolean;
  /** Issues-view processed sections, keyed by issue kind (in-memory only). */
  processedExpanded: Record<string, boolean>;
  /** Word timings fetched for the timeline's current data window. */
  transcriptWords: TimedWord[];
  wordsRange: { start: number; end: number } | null;
  /** User scrolled the list away: auto-scroll detaches (session-only, unlike
   *  selection-follow which is derived from playback and needs no state). */
  viewDetached: boolean;
}

export type AppStore = Store<AppState>;

export function createAppStore(prefs: Preferences): AppStore {
  return new Store<AppState>({
    session: null,
    cues: [],
    revision: "",
    progress: { reviewed: 0, flagged: 0, unreviewed: 0, total: 0 },
    suggestions: [],
    selectedId: null,
    selection: [],
    currentTime: 0,
    draft: null,
    dirty: false,
    saveState: "saved",
    banner: null,
    toast: null,
    search: "",
    prefs,
    isPlaying: false,
    playbackNotice: null,
    deleteOpen: false,
    showNote: false,
    findOpen: false,
    helpOpen: false,
    addTerm: null,
    completedDismissed: false,
    processedExpanded: {},
    transcriptWords: [],
    wordsRange: null,
    viewDetached: false,
  });
}

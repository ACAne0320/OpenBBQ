import { createContext, useContext, useRef, type ReactNode } from "react";
import { useSyncExternalStore } from "react";
import { api, type Api } from "../api/client";
import { CommandCenter } from "../commands/commands";
import { PlayerController } from "../player/controller";
import { loadPrefs, watchPrefs } from "../store/prefs";
import { draftEquals } from "../store/selectors";
import { createAppStore, type AppState, type AppStore } from "../store/state";
export interface AppServices {
  store: AppStore;
  player: PlayerController;
  commands: CommandCenter;
  api: Api;
}

/**
 * Keeps the draft in sync with the selected cue: when the selection or the
 * server snapshot changes and nothing is dirty, the draft mirrors the cue.
 * Replaces the old mirror-during-render ref pattern.
 */
function watchDraftReset(store: AppStore): () => void {
  let last = store.getState();
  return store.subscribe(() => {
    const state = store.getState();
    const selectionChanged = state.selectedId !== last.selectedId;
    const cuesChanged = state.cues !== last.cues;
    const dirtyCleared = last.dirty && !state.dirty;
    last = state;
    if (state.dirty || (!selectionChanged && !cuesChanged && !dirtyCleared)) return;
    const cue = state.cues.find((item) => item.id === state.selectedId) ?? null;
    const draft = cue
      ? {
          source: cue.source,
          target: cue.target ?? "",
          start: cue.start,
          end: cue.end,
          note: cue.note ?? "",
        }
      : null;
    const unchanged =
      (draft === null && state.draft === null) ||
      (draft !== null && state.draft !== null && draftEquals(draft, state.draft));
    if (unchanged && (!selectionChanged || !state.showNote)) return;
    store.setState({
      ...(unchanged ? {} : { draft }),
      ...(selectionChanged ? { showNote: false } : {}),
    });
  });
}

/**
 * Selection follows playhead MOVEMENT, not playhead position: while playing
 * (or right after a seek) the selected cue tracks the cue under the playhead;
 * a still playhead leaves the selection entirely to the user. A dirty draft
 * (edit in progress) or an active multi-selection suspends tracking.
 */
function watchFollowPlayback(store: AppStore): () => void {
  let lastActiveId: number | null = null;
  let lastTime = store.getState().currentTime;
  return store.subscribe(() => {
    const state = store.getState();
    const timeMoved = state.currentTime !== lastTime;
    lastTime = state.currentTime;
    if (state.dirty || state.selection.length > 1) return;
    if (!state.isPlaying && !timeMoved) return;
    const active =
      state.cues.find(
        (cue) => state.currentTime >= cue.start && state.currentTime <= cue.end,
      ) ?? null;
    const activeId = active?.id ?? null;
    if (activeId === lastActiveId) return;
    lastActiveId = activeId;
    if (activeId != null && activeId !== state.selectedId) {
      store.setState({ selectedId: activeId, selection: [activeId] });
    }
  });
}

/** Starting playback re-engages the list's auto-scroll (watching again). */
function watchPlayReengagesView(store: AppStore): () => void {
  let wasPlaying = store.getState().isPlaying;
  return store.subscribe(() => {
    const playing = store.getState().isPlaying;
    if (playing && !wasPlaying && store.getState().viewDetached) {
      store.setState({ viewDetached: false });
    }
    wasPlaying = playing;
  });
}

/** Re-arms the completion banner after the workspace drops out of complete. */
function watchCompletion(store: AppStore): () => void {
  const isComplete = () => {
    const progress = store.getState().progress;
    return progress.total > 0 && progress.reviewed === progress.total;
  };
  let wasComplete = isComplete();
  return store.subscribe(() => {
    const complete = isComplete();
    if (complete === wasComplete) return;
    wasComplete = complete;
    if (!complete && store.getState().completedDismissed) {
      store.setState({ completedDismissed: false });
    }
  });
}

export function createAppServices(apiClient: Api = api): AppServices {
  const { prefs, stored } = loadPrefs();
  const store = createAppStore(prefs);
  const player = new PlayerController(store);
  const commands = new CommandCenter({
    store,
    api: apiClient,
    player,
    hadStoredZoom: stored.zoom !== undefined,
  });
  watchPrefs(store);
  watchDraftReset(store);
  watchFollowPlayback(store);
  watchPlayReengagesView(store);
  watchCompletion(store);
  return { store, player, commands, api: apiClient };
}

const ServicesContext = createContext<AppServices | null>(null);

export function ServicesProvider({
  services,
  children,
}: {
  services: AppServices;
  children: ReactNode;
}) {
  return <ServicesContext.Provider value={services}>{children}</ServicesContext.Provider>;
}

export function useServices(): AppServices {
  const services = useContext(ServicesContext);
  if (!services) throw new Error("useServices must be used within ServicesProvider");
  return services;
}

/**
 * Selector subscription: the component re-renders only when the selected
 * slice changes (Object.is by default), so high-frequency store fields like
 * `currentTime` never re-render the cue list or the editor.
 */
export function useAppSelector<T>(
  selector: (state: AppState) => T,
  isEqual: (a: T, b: T) => boolean = Object.is,
): T {
  const { store } = useServices();
  const cache = useRef<{ value: T } | null>(null);
  return useSyncExternalStore(store.subscribe, () => {
    const next = selector(store.getState());
    if (cache.current !== null && isEqual(cache.current.value, next)) {
      return cache.current.value;
    }
    cache.current = { value: next };
    return next;
  });
}

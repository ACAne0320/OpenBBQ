import { useEffect } from "react";
import type { MessageKey } from "./i18n";
import type { AppServices } from "./services";

/**
 * Single source of truth for keyboard bindings (design §5.5): the table both
 * drives execution and renders the shortcut help overlay (`?`), so keys and
 * help can never drift. `displayOnly` entries document pointer gestures.
 */
export type ShortcutSection = "transport" | "editing" | "cues" | "tools";

export interface ShortcutSpec {
  id: string;
  /** Display label, e.g. "Space", "⇧⌘Z". */
  keys: string;
  descriptionKey: MessageKey;
  section: ShortcutSection;
  /** Keydown predicate; omitted for hold-driven or pointer bindings. */
  match?: (event: KeyboardEvent) => boolean;
  /** Runs the binding; omitted for `hold`/`displayOnly` entries. */
  run?: (services: AppServices) => void;
  /** Hold-driven arrow bindings are executed by the hold engine. */
  hold?: boolean;
  /** Fires even while typing in inputs (find, escape). */
  allowInInputs?: boolean;
  /** Pointer gesture shown in help only (multi-select). */
  displayOnly?: boolean;
}

const plain = (key: string) => (event: KeyboardEvent) =>
  event.key.toLowerCase() === key && !event.metaKey && !event.ctrlKey && !event.altKey;

export const SHORTCUTS: readonly ShortcutSpec[] = [
  {
    id: "toggle-play",
    keys: "Space",
    descriptionKey: "shortcut.togglePlay",
    section: "transport",
    match: (event) => event.code === "Space",
    run: ({ player }) => player.togglePlay(),
  },
  { id: "seek-back", keys: "←", descriptionKey: "shortcut.seek", section: "transport", hold: true },
  { id: "seek-forward", keys: "→", descriptionKey: "shortcut.seek", section: "transport", hold: true },
  {
    id: "volume-up",
    keys: "↑",
    descriptionKey: "shortcut.volume",
    section: "transport",
    match: (event) => event.key === "ArrowUp",
    run: ({ player, store }) => player.setVolume(store.getState().prefs.volume + 0.05),
  },
  {
    id: "volume-down",
    keys: "↓",
    descriptionKey: "shortcut.volume",
    section: "transport",
    match: (event) => event.key === "ArrowDown",
    run: ({ player, store }) => player.setVolume(store.getState().prefs.volume - 0.05),
  },
  {
    id: "mute",
    keys: "M",
    descriptionKey: "transport.mute",
    section: "transport",
    match: plain("m"),
    run: ({ player }) => player.toggleMute(),
  },
  {
    id: "fullscreen",
    keys: "F",
    descriptionKey: "transport.fullscreen",
    section: "transport",
    match: (event) => plain("f")(event) && !event.shiftKey,
    run: ({ player }) => player.toggleFullscreen(),
  },
  {
    id: "play-slower",
    keys: "J",
    descriptionKey: "shortcut.playSlower",
    section: "transport",
    match: plain("j"),
    run: ({ player }) => {
      player.seek(player.getPlaybackTime() - 2);
      player.setPlaybackRate(0.75);
      player.play();
    },
  },
  {
    id: "pause",
    keys: "K",
    descriptionKey: "transport.pause",
    section: "transport",
    match: plain("k"),
    run: ({ player }) => player.pause(),
  },
  {
    id: "play-faster",
    keys: "L",
    descriptionKey: "shortcut.playFaster",
    section: "transport",
    match: plain("l"),
    run: ({ player }) => {
      player.setPlaybackRate(1.5);
      player.play();
    },
  },
  {
    id: "undo",
    keys: "⌘Z",
    descriptionKey: "action.undo",
    section: "editing",
    match: (event) =>
      (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z" && !event.shiftKey,
    run: ({ commands }) => void commands.undo(),
  },
  {
    id: "redo",
    keys: "⇧⌘Z",
    descriptionKey: "action.redo",
    section: "editing",
    match: (event) =>
      (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z" && event.shiftKey,
    run: ({ commands }) => void commands.redo(),
  },
  {
    id: "split",
    keys: "S",
    descriptionKey: "action.split",
    section: "editing",
    match: plain("s"),
    run: ({ commands }) => void commands.splitCurrent(),
  },
  {
    id: "set-start",
    keys: "[",
    descriptionKey: "shortcut.setInOut",
    section: "editing",
    match: (event) => event.key === "[",
    run: ({ commands, player }) => commands.updateDraft({ start: player.getPlaybackTime() }),
  },
  {
    id: "set-end",
    keys: "]",
    descriptionKey: "shortcut.setInOut",
    section: "editing",
    match: (event) => event.key === "]",
    run: ({ commands, player }) => commands.updateDraft({ end: player.getPlaybackTime() }),
  },
  {
    id: "review-next",
    keys: "Enter",
    descriptionKey: "shortcut.reviewNext",
    section: "cues",
    match: (event) => event.key === "Enter" && !event.shiftKey,
    run: ({ commands }) => void commands.mark("reviewed"),
  },
  {
    id: "save-next",
    keys: "⇧Enter",
    descriptionKey: "shortcut.saveNext",
    section: "cues",
    match: (event) => event.key === "Enter" && event.shiftKey,
    run: ({ commands }) => void commands.saveAndNext(),
  },
  {
    id: "flag",
    keys: "⇧F",
    descriptionKey: "action.flag",
    section: "cues",
    match: (event) => plain("f")(event) && event.shiftKey,
    run: ({ commands }) => void commands.mark("flagged"),
  },
  {
    id: "multi-select",
    keys: "⇧/⌘+Click",
    descriptionKey: "shortcut.multiSelect",
    section: "cues",
    displayOnly: true,
  },
  {
    id: "find",
    keys: "⌘F",
    descriptionKey: "shortcut.find",
    section: "tools",
    allowInInputs: true,
    match: (event) => (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f",
    run: ({ store }) => store.setState((state) => ({ findOpen: !state.findOpen })),
  },
  {
    id: "escape",
    keys: "Esc",
    descriptionKey: "shortcut.escape",
    section: "tools",
    allowInInputs: true,
    match: (event) => event.key === "Escape",
    run: ({ store, commands }) => {
      const state = store.getState();
      if (state.helpOpen) store.setState({ helpOpen: false });
      else if (state.findOpen) store.setState({ findOpen: false });
      else if (state.addTerm) store.setState({ addTerm: null });
      else if (state.selection.length > 1) commands.clearSelection();
    },
  },
  {
    id: "help",
    keys: "?",
    descriptionKey: "shortcut.help",
    section: "tools",
    match: (event) => event.key === "?",
    run: ({ store }) => store.setState((state) => ({ helpOpen: !state.helpOpen })),
  },
];

export const SHORTCUT_SECTIONS: readonly ShortcutSection[] = [
  "transport",
  "editing",
  "cues",
  "tools",
];

function isInteractiveTarget(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    Boolean(
      target.closest(
        "input, textarea, select, button, a[href], [contenteditable='true'], [role='button'], [role='slider'], [role='switch'], [role='combobox'], [role='menuitem'], [role='menuitemradio'], [role='option']",
      ),
    )
  );
}

const HOLD_DELAY_MS = 350;
const REWIND_INTERVAL_MS = 100;
const REWIND_STEP_SECONDS = 0.2;
const HOLD_FAST_RATE = 2;
const SHORT_SEEK_SECONDS = 5;

interface ArrowHold {
  direction: -1 | 1;
  timer: number;
  interval: number | null;
  long: boolean;
  previousRate: number;
}

/** Installs the shortcut table plus the stateful arrow-key hold engine. */
export function useGlobalShortcuts(services: AppServices): void {
  useEffect(() => {
    let hold: ArrowHold | null = null;

    const finishHold = (event: KeyboardEvent) => {
      if (!hold || event.key !== (hold.direction === 1 ? "ArrowRight" : "ArrowLeft")) return;
      const current = hold;
      hold = null;
      window.clearTimeout(current.timer);
      if (current.interval != null) window.clearInterval(current.interval);
      const { player } = services;
      if (!current.long) {
        player.seek(player.getPlaybackTime() + current.direction * SHORT_SEEK_SECONDS);
        player.showNotice(current.direction > 0 ? "+5s" : "−5s");
      } else {
        if (current.direction === 1) player.setPlaybackRate(current.previousRate);
        player.showNotice(null);
      }
    };

    const onKeyDown = (event: KeyboardEvent) => {
      const interactive = isInteractiveTarget(event.target);

      // Arrow-key hold engine: short press seeks ±5s; holding past 350ms
      // fast-forwards at 2× or rewinds in 0.2s steps.
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        if (interactive) return;
        event.preventDefault();
        if (event.repeat || hold) return;
        const direction: -1 | 1 = event.key === "ArrowRight" ? 1 : -1;
        const current: ArrowHold = {
          direction,
          timer: 0,
          interval: null,
          long: false,
          previousRate: services.store.getState().prefs.playbackRate,
        };
        current.timer = window.setTimeout(() => {
          if (hold !== current) return;
          current.long = true;
          const { player } = services;
          if (direction === 1) {
            player.setPlaybackRate(HOLD_FAST_RATE);
            player.showNotice(`${HOLD_FAST_RATE}×`);
            player.play();
          } else {
            player.showNotice("−2×");
            current.interval = window.setInterval(() => {
              player.seek(Math.max(0, player.getPlaybackTime() - REWIND_STEP_SECONDS));
            }, REWIND_INTERVAL_MS);
          }
        }, HOLD_DELAY_MS);
        hold = current;
        return;
      }

      for (const shortcut of SHORTCUTS) {
        if (!shortcut.match || !shortcut.run) continue;
        if (interactive && !shortcut.allowInInputs) continue;
        if (shortcut.match(event)) {
          event.preventDefault();
          shortcut.run(services);
          return;
        }
      }
    };

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", finishHold);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", finishHold);
      if (hold) {
        window.clearTimeout(hold.timer);
        if (hold.interval != null) window.clearInterval(hold.interval);
        if (hold.long && hold.direction === 1) {
          services.player.setPlaybackRate(hold.previousRate);
        }
        hold = null;
      }
    };
  }, [services]);
}

/**
 * Canvas palette read from CSS custom properties so the timeline stays in
 * sync with the light/dark themes (the old hardcoded per-theme palette
 * drifted from the theme tokens). Values fall back to the legacy constants
 * when a property is unavailable (e.g. jsdom).
 */

export interface TimelinePalette {
  background: string;
  foreground: string;
  muted: string;
  waveform: string;
  waveformFill: string;
  cue: string;
  reviewed: string;
  flagged: string;
  selected: string;
  selectedBorder: string;
  playhead: string;
  grid: string;
  word: string;
  handle: string;
}

const CSS_VARS: Record<keyof TimelinePalette, string> = {
  background: "--timeline-background",
  foreground: "--timeline-foreground",
  muted: "--timeline-muted",
  waveform: "--timeline-waveform",
  waveformFill: "--timeline-waveform-fill",
  cue: "--timeline-cue",
  reviewed: "--timeline-reviewed",
  flagged: "--timeline-flagged",
  selected: "--timeline-selected",
  selectedBorder: "--timeline-selected-border",
  playhead: "--timeline-playhead",
  grid: "--timeline-grid",
  word: "--timeline-word",
  handle: "--timeline-handle",
};

const FALLBACKS: Record<"light" | "dark", TimelinePalette> = {
  dark: {
    background: "#101315",
    foreground: "#e9e9e7",
    muted: "#8b9396",
    waveform: "#b7bec0",
    waveformFill: "rgba(183, 190, 192, .17)",
    cue: "#263238",
    reviewed: "#244235",
    flagged: "#5a3e27",
    selected: "#9f3024",
    selectedBorder: "#f05a43",
    playhead: "#f05a43",
    grid: "rgba(255,255,255,.08)",
    word: "rgba(255,255,255,.14)",
    handle: "#f05a43",
  },
  light: {
    background: "#f5f5f3",
    foreground: "#1d2224",
    muted: "#70787b",
    waveform: "#596469",
    waveformFill: "rgba(89, 100, 105, .15)",
    cue: "#dfe5e7",
    reviewed: "#d7e8df",
    flagged: "#f1dfca",
    selected: "#f7d7d1",
    selectedBorder: "#d9412d",
    playhead: "#d9412d",
    grid: "rgba(19,28,32,.09)",
    word: "rgba(19,28,32,.17)",
    handle: "#d9412d",
  },
};

export function readTimelinePalette(theme: "light" | "dark"): TimelinePalette {
  const fallback = FALLBACKS[theme];
  if (typeof window === "undefined" || typeof window.getComputedStyle !== "function") {
    return fallback;
  }
  const styles = window.getComputedStyle(document.documentElement);
  const palette = { ...fallback };
  for (const [key, cssVar] of Object.entries(CSS_VARS) as Array<
    [keyof TimelinePalette, string]
  >) {
    const value = styles.getPropertyValue(cssVar).trim();
    if (value) palette[key] = value;
  }
  return palette;
}

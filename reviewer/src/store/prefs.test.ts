import { beforeEach, describe, expect, it } from "vitest";
import { createAppStore } from "./state";
import { defaultPrefs, loadPrefs, updatePrefs, watchPrefs } from "./prefs";

const PREFS_KEY = "openbbq-review-prefs";

describe("preference persistence", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("falls back to defaults when nothing is stored", () => {
    const { prefs, stored } = loadPrefs();
    expect(prefs).toEqual(defaultPrefs);
    expect(stored).toEqual({});
  });

  it("persists preference changes to localStorage", () => {
    const store = createAppStore(defaultPrefs);
    const unsubscribe = watchPrefs(store);
    updatePrefs(store, { overlay: "target", zoom: 8, loopCue: true, listWidth: 400 });
    const raw = JSON.parse(window.localStorage.getItem(PREFS_KEY) ?? "{}") as Record<
      string,
      unknown
    >;
    expect(raw.overlay).toBe("target");
    expect(raw.zoom).toBe(8);
    expect(raw.loopCue).toBe(true);
    expect(raw.listWidth).toBe(400);
    unsubscribe();

    const { prefs, stored } = loadPrefs();
    expect(prefs.overlay).toBe("target");
    expect(prefs.zoom).toBe(8);
    expect(prefs.loopCue).toBe(true);
    expect(prefs.listWidth).toBe(400);
    expect(stored.zoom).toBe(8);
  });

  it("drops invalid stored values instead of crashing", () => {
    window.localStorage.setItem(
      PREFS_KEY,
      JSON.stringify({
        overlay: "sideways",
        zoom: 999,
        volume: 2,
        filter: "term_warning",
        muted: "yes",
        listWidth: 10,
      }),
    );
    const { prefs } = loadPrefs();
    expect(prefs.overlay).toBe(defaultPrefs.overlay);
    expect(prefs.zoom).toBe(defaultPrefs.zoom);
    expect(prefs.volume).toBe(defaultPrefs.volume);
    expect(prefs.filter).toBe("term_warning");
    expect(prefs.muted).toBe(defaultPrefs.muted);
    expect(prefs.listWidth).toBe(defaultPrefs.listWidth);
  });

  it("tolerates corrupt JSON", () => {
    window.localStorage.setItem(PREFS_KEY, "{not json");
    expect(loadPrefs().prefs).toEqual(defaultPrefs);
  });
});

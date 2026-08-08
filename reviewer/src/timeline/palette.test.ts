import { describe, expect, it } from "vitest";
import { readTimelinePalette } from "./palette";

describe("timeline palette", () => {
  it("falls back to the legacy constants when CSS variables are unavailable", () => {
    // jsdom exposes no values for custom properties.
    const light = readTimelinePalette("light");
    const dark = readTimelinePalette("dark");
    expect(light.playhead).toBe("#d9412d");
    expect(dark.playhead).toBe("#f05a43");
    expect(light.background).not.toBe(dark.background);
  });
});

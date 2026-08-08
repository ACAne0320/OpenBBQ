import { describe, expect, it } from "vitest";
import {
  constrainCueRange,
  cueMovementBounds,
  fitCueZoom,
  nudgeCueRange,
  type NudgeTarget,
} from "./timeline-model";

describe("timeline precision model", () => {
  it.each<[NudgeTarget, number, [number, number]]>([
    ["body", 0.1, [5.1, 8.1]],
    ["start", 0.1, [5.1, 8]],
    ["end", -0.1, [5, 7.9]],
  ])("nudges %s by an exact step", (target, delta, expected) => {
    expect(nudgeCueRange({ start: 5, end: 8 }, target, delta, 20)).toEqual({
      start: expected[0],
      end: expected[1],
    });
  });

  it("clamps whole-cue movement to the media while preserving duration", () => {
    expect(nudgeCueRange({ start: 0.02, end: 2.02 }, "body", -0.1, 10)).toEqual({
      start: 0,
      end: 2,
    });
    expect(nudgeCueRange({ start: 8.5, end: 10 }, "body", 0.5, 10)).toEqual({
      start: 8.5,
      end: 10,
    });
  });

  it("keeps edge nudges at or above the minimum cue duration", () => {
    expect(nudgeCueRange({ start: 5, end: 5.08 }, "start", 0.1, 20)).toEqual({
      start: 5.03,
      end: 5.08,
    });
    expect(nudgeCueRange({ start: 5, end: 5.08 }, "end", -0.1, 20)).toEqual({
      start: 5,
      end: 5.05,
    });
  });

  it("fits a cue with context and respects zoom limits", () => {
    expect(fitCueZoom(600, { start: 100, end: 104 })).toBe(50);
    expect(fitCueZoom(600, { start: 100, end: 100.05 })).toBe(96);
    expect(fitCueZoom(60, { start: 10, end: 20 })).toBe(2);
    expect(fitCueZoom(10, { start: 0, end: 10 })).toBe(1);
  });

  it("constrains edge and body drags between adjacent cues", () => {
    const bounds = { minimum: 4, maximum: 10 };
    expect(constrainCueRange({ start: 5, end: 10.8 }, "end", bounds)).toEqual({
      start: 5,
      end: 10,
    });
    expect(constrainCueRange({ start: 3.2, end: 8 }, "start", bounds)).toEqual({
      start: 4,
      end: 8,
    });
    expect(constrainCueRange({ start: 8, end: 11 }, "body", bounds)).toEqual({
      start: 7,
      end: 10,
    });
  });

  it("preserves the workspace's inferred minimum inter-cue gap", () => {
    expect(
      cueMovementBounds(
        [
          { start: 0, end: 1 },
          { start: 1.1, end: 2 },
          { start: 2.1, end: 3 },
        ],
        1,
        5,
      ),
    ).toEqual({ minimum: 1.1, maximum: 2 });
  });
});

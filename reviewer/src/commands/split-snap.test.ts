import { describe, expect, it } from "vitest";
import type { TimedWord } from "../api/types";
import { snapSplitPoint, sourceIndexForSnap } from "./split-snap";

const words: TimedWord[] = [
  { word: "Hello", start: 10.0, end: 10.4 },
  { word: "brave", start: 10.5, end: 10.9 },
  { word: "new", start: 11.0, end: 11.3 },
  { word: "world", start: 11.4, end: 12.0 },
];

describe("snapSplitPoint", () => {
  it("snaps to the nearest word boundary inside the cue", () => {
    const snap = snapSplitPoint(10.45, words, 10, 14);
    expect(snap).toEqual({ time: 10.4, word: words[0], edge: "end" });
    const next = snapSplitPoint(10.75, words, 10, 14);
    expect(next?.time).toBe(10.9);
  });

  it("ignores boundaries outside the ±0.5s window", () => {
    expect(snapSplitPoint(13.4, words, 10, 14)).toBeNull();
  });

  it("ignores boundaries outside the cue", () => {
    // Cue starts at 11.2: word boundaries at or before it are off-limits;
    // the nearest in-cue boundary is "new"'s end at 11.3.
    const snap = snapSplitPoint(11.05, words, 11.2, 14);
    expect(snap?.time).toBe(11.3);
  });

  it("prefers the closer boundary of the same word", () => {
    const snap = snapSplitPoint(11.32, words, 10, 14);
    expect(snap?.time).toBe(11.3);
    expect(snap?.edge).toBe("end");
  });
});

describe("sourceIndexForSnap", () => {
  const source = "Hello brave new world";

  it("locates the word end boundary in the source text", () => {
    const snap = { time: 10.4, word: words[0], edge: "end" as const };
    expect(sourceIndexForSnap(source, snap, 0.2)).toBe(5);
  });

  it("locates the word start boundary", () => {
    const snap = { time: 11.4, word: words[3], edge: "start" as const };
    expect(sourceIndexForSnap(source, snap, 0.7)).toBe(16);
  });

  it("picks the occurrence nearest the ratio guess for repeated words", () => {
    const repeated: TimedWord = { word: "the", start: 5, end: 5.3 };
    const snap = { time: 5.3, word: repeated, edge: "end" as const };
    const text = "the cat sat on the mat";
    // Occurrence ends: 3 and 18; guesses land closest to each in turn.
    expect(sourceIndexForSnap(text, snap, 0.9)).toBe(18);
    expect(sourceIndexForSnap(text, snap, 0.05)).toBe(3);
  });

  it("returns null when the word text is absent", () => {
    const snap = { time: 10.4, word: words[0], edge: "end" as const };
    expect(sourceIndexForSnap("totally different", snap, 0.2)).toBeNull();
  });
});

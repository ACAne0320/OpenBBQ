import { describe, expect, it } from "vitest";
import {
  followTimelineCenter,
  timelineDataRange,
  timelineViewRange,
  waveformPeakTime,
} from "./timeline-viewport";

describe("timeline viewport", () => {
  it("keeps the data window stable while playback remains inside the follow margins", () => {
    const range = timelineViewRange(100, 600, 60);

    expect(range).toEqual({ start: 70, end: 130 });
    expect(followTimelineCenter(100, 75, 600, 60)).toBe(100);
    expect(followTimelineCenter(100, 124, 600, 60)).toBe(100);
  });

  it("recenters only after playback crosses a viewport follow margin", () => {
    expect(followTimelineCenter(100, 126, 600, 60)).toBe(126);
    expect(followTimelineCenter(30, 2, 600, 60)).toBe(2);
  });

  it("clamps ranges at media boundaries", () => {
    expect(timelineViewRange(2, 100, 20)).toEqual({ start: 0, end: 20 });
    expect(timelineViewRange(98, 100, 20)).toEqual({ start: 80, end: 100 });
  });

  it("keeps a three-viewport waveform buffer stable while panning inside a bucket", () => {
    expect(timelineDataRange(75, 600, 60)).toEqual({ start: 0, end: 180 });
    expect(timelineDataRange(119, 600, 60)).toEqual({ start: 0, end: 180 });
    expect(timelineDataRange(121, 600, 60)).toEqual({ start: 60, end: 240 });
  });

  it("maps waveform peaks back to their absolute media time", () => {
    expect(waveformPeakTime(0, 3, 60, 240)).toBe(60);
    expect(waveformPeakTime(1, 3, 60, 240)).toBe(150);
    expect(waveformPeakTime(2, 3, 60, 240)).toBe(240);
  });
});

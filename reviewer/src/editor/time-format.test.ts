import { describe, expect, it } from "vitest";
import { formatTimeInput, parseTimeInput } from "./time-format";

describe("parseTimeInput", () => {
  it.each([
    ["1:23.456", 83.456],
    ["83.456", 83.456],
    ["1:23", 83],
    ["01:23.456", 83.456],
    ["0:05.5", 5.5],
    ["5", 5],
    ["5.0", 5],
    ["1:02:03.500", 3723.5],
    ["12:34", 754],
    [" 1:23.456 ", 83.456],
    ["90", 90],
  ])("parses %s as %f", (input, expected) => {
    expect(parseTimeInput(input)).toBe(expected);
  });

  it.each([
    "",
    "   ",
    "abc",
    "1:2:3:4",
    "-5",
    "1:99",
    "1:2:99",
    "1:23.4567",
    "1..2",
    "1:",
    ":12",
    "NaN",
  ])("rejects %s", (input) => {
    expect(parseTimeInput(input)).toBeNull();
  });
});

describe("formatTimeInput", () => {
  it("formats MM:SS.mmm below an hour", () => {
    expect(formatTimeInput(83.456)).toBe("01:23.456");
    expect(formatTimeInput(0)).toBe("00:00.000");
    expect(formatTimeInput(754)).toBe("12:34.000");
  });

  it("adds an hour segment above one hour", () => {
    expect(formatTimeInput(3723.5)).toBe("01:02:03.500");
  });

  it("round-trips through the parser", () => {
    for (const value of [0, 5.5, 83.456, 754, 3723.5]) {
      expect(parseTimeInput(formatTimeInput(value))).toBe(value);
    }
  });
});

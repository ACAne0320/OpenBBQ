import { describe, expect, it } from "vitest";

import { formatRange, formatTimestamp } from "./format";

describe("formatTimestamp", () => {
  it("floors fractional milliseconds before formatting", () => {
    expect(formatTimestamp(61234.9)).toBe("01:01.234");
  });

  it("clamps negative and non-finite values to zero", () => {
    expect(formatTimestamp(-1)).toBe("00:00.000");
    expect(formatTimestamp(Number.NaN)).toBe("00:00.000");
    expect(formatTimestamp(Number.POSITIVE_INFINITY)).toBe("00:00.000");
  });
});

describe("formatRange", () => {
  it("normalizes both range endpoints", () => {
    expect(formatRange(-20, 999.9)).toBe("00:00.000 -> 00:00.999");
  });
});

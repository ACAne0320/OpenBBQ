import { describe, expect, it } from "vitest";
import { contentHashForCue, sha256Hex } from "./content-hash";

describe("sha256Hex", () => {
  it("matches the FIPS 180-4 test vectors", () => {
    expect(sha256Hex("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    expect(sha256Hex("x".repeat(100) + "中文".repeat(40))).toBe(
      "cfa14b35234a181d5ccb7bdda2cc46007e8924c68946b14eb081ed887f0e70db",
    );
  });
});

// Expected values computed with the backend's `_content_hash` (review.py).
describe("contentHashForCue", () => {
  const cue = { id: 1, start: 10, end: 14.5, source: 'Hello "world"', target: "你好" };

  it("matches the backend recipe with target included", () => {
    expect(contentHashForCue(cue, true)).toBe(
      "sha256:adec5fdede7df9f11f7555ea121815f7c5f0a656630aef3d267b29644f6eaaed",
    );
  });

  it("matches with a null target (worksheet present, cue untranslated)", () => {
    expect(contentHashForCue({ ...cue, target: null }, true)).toBe(
      "sha256:838f31389df23411ed5b5d4e1f2fe37a3d5548e8d1a4117e45e420a09bdbc9eb",
    );
  });

  it("matches with target excluded (source-only review)", () => {
    expect(contentHashForCue({ ...cue, target: null }, false)).toBe(
      "sha256:98a423de35793b0ac7228835d6fae95fabed663bbb7912f242b96c8fc4518003",
    );
  });

  it("changes when any hashed field drifts", () => {
    const base = contentHashForCue(cue, true);
    expect(contentHashForCue({ ...cue, source: "Hello world" }, true)).not.toBe(base);
    expect(contentHashForCue({ ...cue, end: 14.6 }, true)).not.toBe(base);
    expect(contentHashForCue({ ...cue, target: "您好" }, true)).not.toBe(base);
  });
});

import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const electronDir = path.resolve(__dirname, "..");

describe("Electron preload build contract", () => {
  it("loads a CommonJS preload artifact for sandboxed renderer injection", () => {
    const mainSource = fs.readFileSync(path.join(electronDir, "main.ts"), "utf8");
    const preloadSource = fs.readFileSync(path.join(electronDir, "preload.cts"), "utf8");

    expect(mainSource).toContain('"preload.cjs"');
    expect(preloadSource).toContain('contextBridge.exposeInMainWorld("openbbq"');
  });
});

// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { createDesktopRuntimeConfig } from "../config";

vi.mock("electron", () => ({
  app: {
    getPath: vi.fn(() => "C:/Users/alex/AppData/Roaming/openbbq-desktop")
  }
}));

describe("createDesktopRuntimeConfig", () => {
  const originalPlatform = process.platform;
  const originalSidecarCommand = process.env.OPENBBQ_SIDECAR_COMMAND;

  afterEach(() => {
    Object.defineProperty(process, "platform", { value: originalPlatform });
    if (originalSidecarCommand === undefined) {
      delete process.env.OPENBBQ_SIDECAR_COMMAND;
    } else {
      process.env.OPENBBQ_SIDECAR_COMMAND = originalSidecarCommand;
    }
  });

  it("uses the PATH-resolved uv command on Windows", () => {
    Object.defineProperty(process, "platform", { value: "win32" });
    delete process.env.OPENBBQ_SIDECAR_COMMAND;

    expect(createDesktopRuntimeConfig().sidecarCommand).toBe("uv");
  });
});

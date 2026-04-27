// @vitest-environment node
import { describe, expect, it } from "vitest";

import { parseStartupLine, StartupLineError } from "../sidecar";

describe("parseStartupLine", () => {
  it("parses the sidecar startup JSON line", () => {
    expect(parseStartupLine('{"ok":true,"host":"127.0.0.1","port":53124,"pid":12345}')).toEqual({
      host: "127.0.0.1",
      port: 53124,
      pid: 12345
    });
  });

  it("rejects non-json output", () => {
    expect(() => parseStartupLine("INFO waiting for application startup")).toThrow(StartupLineError);
  });

  it("rejects malformed startup payloads", () => {
    expect(() => parseStartupLine('{"ok":true,"host":"127.0.0.1","port":"53124","pid":12345}')).toThrow(
      StartupLineError
    );
  });
});

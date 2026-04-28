// @vitest-environment node
import { EventEmitter } from "node:events";
import { Readable } from "node:stream";
import { afterEach, describe, expect, it, vi } from "vitest";

import { parseStartupLine, SidecarStartupError, startSidecar, StartupLineError } from "../sidecar";

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

class FakeChildProcess extends EventEmitter {
  stdout = new Readable({ read() {} });
  stderr = new Readable({ read() {} });
  killed = false;
  kill = vi.fn(() => {
    this.killed = true;
    this.emit("exit", 0, null);
    return true;
  });
}

describe("startSidecar", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts the sidecar and stops it cleanly", async () => {
    const child = new FakeChildProcess();
    const spawn = vi.fn(() => child as never);
    const healthCheck = vi.fn().mockResolvedValue(undefined);
    const started = startSidecar(
      {
        command: "uv",
        args: ["run", "openbbq", "api", "serve"],
        cwd: "/tmp/github-repo/OpenBBQ",
        workspaceRoot: "/tmp/openbbq-workspace",
        token: "secret",
        allowDevCors: false,
        startupTimeoutMs: 1000
      },
      { spawn, healthCheck }
    );

    child.stdout.push('{"ok":true,"host":"127.0.0.1","port":53124,"pid":12345}\n');
    const sidecar = await started;

    expect(spawn).toHaveBeenCalledWith(
      "uv",
      [
        "run",
        "openbbq",
        "api",
        "serve",
        "--project",
        "/tmp/openbbq-workspace",
        "--token",
        "secret"
      ],
      expect.objectContaining({ cwd: "/tmp/github-repo/OpenBBQ" })
    );
    expect(healthCheck).toHaveBeenCalledWith(expect.objectContaining({ baseUrl: "http://127.0.0.1:53124" }));

    await sidecar.stop();
    expect(child.kill).toHaveBeenCalled();
  });

  it("adds development CORS only when requested", async () => {
    const child = new FakeChildProcess();
    const spawn = vi.fn(() => child as never);
    const started = startSidecar(
      {
        command: "uv",
        args: ["run", "openbbq", "api", "serve"],
        cwd: "/tmp/github-repo/OpenBBQ",
        workspaceRoot: "/tmp/openbbq-workspace",
        token: "secret",
        allowDevCors: true,
        startupTimeoutMs: 1000
      },
      { spawn, healthCheck: vi.fn().mockResolvedValue(undefined) }
    );

    child.stdout.push('{"ok":true,"host":"127.0.0.1","port":53124,"pid":12345}\n');
    await started;

    expect(spawn.mock.calls[0][1]).toContain("--allow-dev-cors");
  });

  it("fails when the sidecar exits before readiness", async () => {
    const child = new FakeChildProcess();
    const spawn = vi.fn(() => child as never);
    const started = startSidecar(
      {
        command: "uv",
        args: ["run", "openbbq", "api", "serve"],
        cwd: "/tmp/github-repo/OpenBBQ",
        workspaceRoot: "/tmp/openbbq-workspace",
        token: "secret",
        allowDevCors: false,
        startupTimeoutMs: 1000
      },
      { spawn, healthCheck: vi.fn().mockResolvedValue(undefined) }
    );

    child.stderr.push("module not found\n");
    child.emit("exit", 1, null);

    await expect(started).rejects.toMatchObject({
      code: "sidecar_exit_before_ready"
    });
    await expect(started).rejects.toBeInstanceOf(SidecarStartupError);
  });

  it("forwards sidecar stderr to the configured log sink", async () => {
    const child = new FakeChildProcess();
    const spawn = vi.fn(() => child as never);
    const logOutput = vi.fn();
    const started = startSidecar(
      {
        command: "uv",
        args: ["run", "openbbq", "api", "serve"],
        cwd: "/tmp/github-repo/OpenBBQ",
        workspaceRoot: "/tmp/openbbq-workspace",
        token: "secret",
        allowDevCors: false,
        startupTimeoutMs: 1000,
        logOutput
      },
      { spawn, healthCheck: vi.fn().mockResolvedValue(undefined) }
    );

    child.stderr.push("Unexpected API error\n");
    child.stdout.push('{"ok":true,"host":"127.0.0.1","port":53124,"pid":12345}\n');
    await started;

    expect(logOutput).toHaveBeenCalledWith("stderr", "Unexpected API error\n");
  });

  it("forwards non-startup stdout lines without logging the startup JSON", async () => {
    const child = new FakeChildProcess();
    const spawn = vi.fn(() => child as never);
    const logOutput = vi.fn();
    const started = startSidecar(
      {
        command: "uv",
        args: ["run", "openbbq", "api", "serve"],
        cwd: "/tmp/github-repo/OpenBBQ",
        workspaceRoot: "/tmp/openbbq-workspace",
        token: "secret",
        allowDevCors: false,
        startupTimeoutMs: 1000,
        logOutput
      },
      { spawn, healthCheck: vi.fn().mockResolvedValue(undefined) }
    );

    child.stdout.push("INFO: waiting for application startup\n");
    child.stdout.push('{"ok":true,"host":"127.0.0.1","port":53124,"pid":12345}\n');
    await started;

    expect(logOutput).toHaveBeenCalledWith("stdout", "INFO: waiting for application startup\n");
    expect(logOutput).not.toHaveBeenCalledWith(
      "stdout",
      '{"ok":true,"host":"127.0.0.1","port":53124,"pid":12345}\n'
    );
  });
});

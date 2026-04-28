import type { ChildProcessWithoutNullStreams, SpawnOptionsWithoutStdio } from "node:child_process";
import { spawn as nodeSpawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";

export type SidecarConnection = {
  host: string;
  port: number;
  pid: number;
  token: string;
  baseUrl: string;
};

export class StartupLineError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StartupLineError";
  }
}

export function parseStartupLine(line: string): Omit<SidecarConnection, "token" | "baseUrl"> {
  let payload: unknown;
  try {
    payload = JSON.parse(line);
  } catch {
    throw new StartupLineError("Sidecar startup line is not JSON.");
  }

  if (
    typeof payload !== "object" ||
    payload === null ||
    !("ok" in payload) ||
    !("host" in payload) ||
    !("port" in payload) ||
    !("pid" in payload)
  ) {
    throw new StartupLineError("Sidecar startup line is missing required fields.");
  }

  const value = payload as Record<string, unknown>;
  if (value.ok !== true || typeof value.host !== "string" || typeof value.port !== "number" || typeof value.pid !== "number") {
    throw new StartupLineError("Sidecar startup line has invalid field types.");
  }

  return {
    host: value.host,
    port: value.port,
    pid: value.pid
  };
}

export type ManagedSidecar = {
  connection: SidecarConnection;
  stderrText(): string;
  stop(): Promise<void>;
};

export type StartSidecarOptions = {
  command: string;
  args: string[];
  cwd: string;
  workspaceRoot: string;
  token?: string;
  allowDevCors: boolean;
  startupTimeoutMs?: number;
  logOutput?: (stream: "stdout" | "stderr", text: string) => void;
};

type StartSidecarDeps = {
  spawn?: (command: string, args: string[], options: SpawnOptionsWithoutStdio) => ChildProcessWithoutNullStreams;
  healthCheck?: (connection: SidecarConnection) => Promise<void>;
};

export class SidecarStartupError extends Error {
  code: "sidecar_start_timeout" | "sidecar_exit_before_ready";
  details: { stderr: string };

  constructor(code: SidecarStartupError["code"], message: string, stderr: string) {
    super(message);
    this.name = "SidecarStartupError";
    this.code = code;
    this.details = { stderr };
  }
}

function newToken(): string {
  return crypto.randomBytes(32).toString("base64url");
}

function appendTail(current: string, chunk: string): string {
  const next = current + chunk;
  return next.length > 8000 ? next.slice(-8000) : next;
}

async function defaultHealthCheck(connection: SidecarConnection): Promise<void> {
  const response = await fetch(`${connection.baseUrl}/health`, {
    headers: { Authorization: `Bearer ${connection.token}` }
  });
  if (!response.ok) {
    throw new Error(`sidecar health check failed with HTTP ${response.status}`);
  }
}

function waitForExit(child: ChildProcessWithoutNullStreams, timeoutMs: number): Promise<void> {
  return new Promise((resolve) => {
    if (child.killed) {
      resolve();
      return;
    }

    let settled = false;
    const finish = () => {
      if (settled) {
        return;
      }
      settled = true;
      resolve();
    };

    child.once("exit", finish);
    child.kill();
    setTimeout(() => {
      if (!child.killed) {
        child.kill("SIGKILL");
      }
      finish();
    }, timeoutMs);
  });
}

export function startSidecar(options: StartSidecarOptions, deps: StartSidecarDeps = {}): Promise<ManagedSidecar> {
  const spawn = deps.spawn ?? nodeSpawn;
  const healthCheck = deps.healthCheck ?? defaultHealthCheck;
  const token = options.token ?? newToken();
  const args = [
    ...options.args,
    "--project",
    options.workspaceRoot,
    "--token",
    token,
    ...(options.allowDevCors ? ["--allow-dev-cors"] : [])
  ];
  fs.mkdirSync(options.workspaceRoot, { recursive: true });

  const child = spawn(options.command, args, {
    cwd: options.cwd,
    env: { ...process.env },
    stdio: "pipe",
    windowsHide: true
  });
  const timeoutMs = options.startupTimeoutMs ?? 15000;
  let stderr = "";
  let stdoutBuffer = "";

  return new Promise((resolve, reject) => {
    let settled = false;
    let managed: ManagedSidecar | null = null;

    function finishReject(error: Error) {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      reject(error);
    }

    function finishResolve(value: ManagedSidecar) {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      managed = value;
      resolve(value);
    }

    const timer = setTimeout(() => {
      child.kill();
      finishReject(new SidecarStartupError("sidecar_start_timeout", "OpenBBQ sidecar startup timed out.", stderr));
    }, timeoutMs);

    child.stderr.on("data", (chunk) => {
      const text = chunk.toString();
      stderr = appendTail(stderr, text);
      options.logOutput?.("stderr", text);
    });

    child.stdout.on("data", (chunk) => {
      stdoutBuffer += chunk.toString();
      const lines = stdoutBuffer.split(/\r?\n/);
      stdoutBuffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.trim()) {
          continue;
        }

        let parsed: Omit<SidecarConnection, "token" | "baseUrl">;
        try {
          parsed = parseStartupLine(line);
        } catch {
          options.logOutput?.("stdout", `${line}\n`);
          continue;
        }

        const connection: SidecarConnection = {
          ...parsed,
          token,
          baseUrl: `http://${parsed.host}:${parsed.port}`
        };

        void healthCheck(connection)
          .then(() =>
            finishResolve({
              connection,
              stderrText: () => stderr,
              stop: () => waitForExit(child, 3000)
            })
          )
          .catch((error: unknown) => finishReject(error instanceof Error ? error : new Error(String(error))));
      }
    });

    child.once("exit", (code) => {
      if (managed || settled) {
        return;
      }

      finishReject(
        new SidecarStartupError(
          "sidecar_exit_before_ready",
          `OpenBBQ sidecar exited before readiness with code ${code ?? "unknown"}.`,
          stderr
        )
      );
    });
  });
}

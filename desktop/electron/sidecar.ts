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

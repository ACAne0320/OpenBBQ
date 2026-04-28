import type { ApiEnvelope } from "./apiTypes.js";
import type { SidecarConnection } from "./sidecar.js";

type RequestOptions = {
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
};

type FetchLike = typeof fetch;

export class SidecarApiError extends Error {
  code: string;
  status: number;
  details: Record<string, unknown>;

  constructor(code: string, message: string, status: number, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "SidecarApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export async function requestJson<T>(
  connection: SidecarConnection,
  path: string,
  options: RequestOptions = {},
  fetchImpl: FetchLike = fetch
): Promise<T> {
  let response: Response;
  try {
    response = await fetchImpl(`${connection.baseUrl}${path}`, {
      method: options.method ?? "GET",
      headers: {
        Authorization: `Bearer ${connection.token}`,
        ...(options.body === undefined ? {} : { "Content-Type": "application/json" })
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body)
    });
  } catch (error) {
    throw new SidecarApiError(
      "sidecar_unreachable",
      error instanceof Error ? error.message : "OpenBBQ sidecar is unreachable.",
      0
    );
  }

  const text = await response.text();
  let envelope: ApiEnvelope<T>;
  try {
    envelope = JSON.parse(text) as ApiEnvelope<T>;
  } catch {
    throw new SidecarApiError("invalid_sidecar_response", "OpenBBQ sidecar returned invalid JSON.", response.status);
  }

  if (!response.ok || envelope.ok === false) {
    const error = envelope.ok === false ? envelope.error : undefined;
    throw new SidecarApiError(
      error?.code ?? "sidecar_http_error",
      error?.message ?? `OpenBBQ sidecar returned HTTP ${response.status}.`,
      response.status,
      error?.details ?? {}
    );
  }

  return envelope.data;
}

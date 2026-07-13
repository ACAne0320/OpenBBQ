import type { CueResponse, Session, TimedWord, WaveformResponse } from "./types";

export class ApiError extends Error {
  status: number;
  payload: Record<string, unknown>;

  constructor(status: number, payload: Record<string, unknown>) {
    super(String(payload.error ?? `HTTP ${status}`));
    this.status = status;
    this.payload = payload;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let payload: Record<string, unknown> = { error: `HTTP ${response.status}` };
    try {
      payload = await response.json();
    } catch {
      // Preserve the HTTP fallback when the response is not JSON.
    }
    throw new ApiError(response.status, payload);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function authenticateFromFragment(): Promise<void> {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const secret = params.get("secret");
  if (!secret) return;
  await request<void>("/api/auth/session", {
    method: "POST",
    body: JSON.stringify({ secret }),
  });
  history.replaceState(null, "", window.location.pathname + window.location.search);
}

export const api = {
  session: () => request<Session>("/api/session"),
  cues: () => request<CueResponse>("/api/cues"),
  waveform: (start: number, end: number, pixels: number) =>
    request<WaveformResponse>(
      `/api/waveform?start=${start.toFixed(3)}&end=${end.toFixed(3)}&pixels=${pixels}`,
    ),
  words: (start: number, end: number) =>
    request<{ words: TimedWord[] }>(
      `/api/transcript/words?start=${start.toFixed(3)}&end=${end.toFixed(3)}`,
    ),
  updateCue: (id: number, body: Record<string, unknown>) =>
    request<CueResponse>(`/api/cues/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  setStatus: (id: number, body: Record<string, unknown>) =>
    request<CueResponse>(`/api/review/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  split: (id: number, body: Record<string, unknown>) =>
    request<CueResponse>(`/api/cues/${id}/split`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  merge: (body: Record<string, unknown>) =>
    request<CueResponse>("/api/cues/merge", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  insert: (body: Record<string, unknown>) =>
    request<CueResponse>("/api/cues", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteCue: (id: number, body: Record<string, unknown>) =>
    request<CueResponse>(`/api/cues/${id}`, {
      method: "DELETE",
      body: JSON.stringify(body),
    }),
  undo: (body: Record<string, unknown>) =>
    request<CueResponse>("/api/undo", { method: "POST", body: JSON.stringify(body) }),
  redo: (body: Record<string, unknown>) =>
    request<CueResponse>("/api/redo", { method: "POST", body: JSON.stringify(body) }),
  switchTarget: (body: Record<string, unknown>) =>
    request<Session & CueResponse>("/api/session/target", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  previewStatus: () =>
    request<{ status: "ready" | "needed" | "building" | "failed"; error: string | null }>(
      "/api/media/preview-status",
    ),
  startPreview: () =>
    request<{ status: "ready" | "needed" | "building" | "failed"; error: string | null }>(
      "/api/media/preview",
      { method: "POST" },
    ),
};

export function opId(label: string): string {
  return `${label}-${crypto.randomUUID()}`;
}

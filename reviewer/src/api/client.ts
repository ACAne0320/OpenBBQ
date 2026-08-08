import type {
  BatchDeleteBody,
  BatchDryRunResult,
  BatchMatch,
  BatchReplaceBody,
  BatchStatusBody,
  CuePatchBody,
  DismissalBody,
  GlossaryTermBody,
  GlossaryTermResult,
  InsertBody,
  MergeBody,
  MutationBase,
  PreviewState,
  Session,
  Snapshot,
  SplitBody,
  StatusPatchBody,
  Suggestion,
  SwitchTargetBody,
  TimedWord,
  WaveformResponse,
} from "./types";

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

function post<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, { method: "POST", body: JSON.stringify(body) });
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
  cues: () => request<Snapshot>("/api/cues"),
  waveform: (start: number, end: number, pixels: number) =>
    request<WaveformResponse>(
      `/api/waveform?start=${start.toFixed(3)}&end=${end.toFixed(3)}&pixels=${pixels}`,
    ),
  words: (start: number, end: number) =>
    request<{ words: TimedWord[] }>(
      `/api/transcript/words?start=${start.toFixed(3)}&end=${end.toFixed(3)}`,
    ),
  updateCue: (id: number, body: CuePatchBody) =>
    request<Snapshot>(`/api/cues/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  setStatus: (id: number, body: StatusPatchBody) =>
    request<Snapshot>(`/api/review/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  split: (id: number, body: SplitBody) =>
    post<Snapshot>(`/api/cues/${id}/split`, body),
  merge: (body: MergeBody) => post<Snapshot>("/api/cues/merge", body),
  insert: (body: InsertBody) => post<Snapshot>("/api/cues", body),
  deleteCue: (id: number, body: MutationBase) =>
    request<Snapshot>(`/api/cues/${id}`, { method: "DELETE", body: JSON.stringify(body) }),
  undo: (body: MutationBase) => post<Snapshot>("/api/undo", body),
  redo: (body: MutationBase) => post<Snapshot>("/api/redo", body),
  switchTarget: (body: SwitchTargetBody) =>
    post<Session & Snapshot>("/api/session/target", body),
  previewStatus: () => request<PreviewState>("/api/media/preview-status"),
  startPreview: () => post<PreviewState>("/api/media/preview", {}),

  // P1 contract additions; P3 builds the UI for these.
  dismissIssue: (id: number, body: DismissalBody) =>
    post<Snapshot>(`/api/cues/${id}/dismissals`, body),
  suggestions: () => request<{ suggestions: Suggestion[] }>("/api/suggestions"),
  acceptSuggestion: (id: string, body: MutationBase) =>
    post<Snapshot>(`/api/suggestions/${encodeURIComponent(id)}/accept`, body),
  rejectSuggestion: (id: string, body: MutationBase) =>
    post<Snapshot>(`/api/suggestions/${encodeURIComponent(id)}/reject`, body),
  reopenSuggestion: (id: string, body: MutationBase) =>
    post<Snapshot>(`/api/suggestions/${encodeURIComponent(id)}/reopen`, body),
  batchPreview: (body: BatchReplaceBody) =>
    post<BatchDryRunResult>("/api/cues/batch", { ...body, dry_run: true }),
  batchReplace: (body: BatchReplaceBody) =>
    post<Snapshot>("/api/cues/batch", { ...body, dry_run: false }),
  batchStatus: (body: BatchStatusBody) => post<Snapshot>("/api/cues/batch-status", body),
  batchDelete: (body: BatchDeleteBody) => post<Snapshot>("/api/cues/batch-delete", body),
  addGlossaryTerm: (body: GlossaryTermBody) =>
    post<GlossaryTermResult>("/api/glossary/terms", body),
};

export type Api = typeof api;

export type { BatchMatch };

export function opId(label: string): string {
  return `${label}-${crypto.randomUUID()}`;
}

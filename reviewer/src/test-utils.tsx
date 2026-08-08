import type { ReactNode } from "react";
import { render } from "@testing-library/react";
import type { Api } from "./api/client";
import type { Cue, CueIssue, Progress, Session, Snapshot, Suggestion } from "./api/types";
import { I18nProvider } from "./app/i18n";
import { createAppServices, ServicesProvider, type AppServices } from "./app/services";

export const testProgress: Progress = { reviewed: 0, flagged: 0, unreviewed: 3, total: 3 };

export function makeCue(id: number, overrides: Partial<Cue> = {}): Cue {
  return {
    id,
    start: id * 10,
    end: id * 10 + 4,
    duration: 4,
    source: `Source ${id}`,
    source_cps: 2.5,
    target: `目标 ${id}`,
    budget: null,
    over_budget: false,
    time_warning: false,
    term_warning: false,
    issues: [],
    status: "unreviewed",
    note: null,
    ...overrides,
  };
}

export function makeIssue(kind: CueIssue["kind"], overrides: Partial<CueIssue> = {}): CueIssue {
  return {
    cue_id: 1,
    kind,
    severity: kind === "asr_confidence" ? "info" : "warning",
    message: kind,
    detail: {},
    source: kind === "agent_note" ? "agent" : "rule",
    dismissed: false,
    suggestion_ids: [],
    ...overrides,
  };
}

export function makeSuggestion(
  id: string,
  cueId: number,
  overrides: Partial<Suggestion> = {},
): Suggestion {
  return {
    id,
    cue_id: cueId,
    kind: "agent_note",
    severity: "info",
    message: `suggestion ${id}`,
    patch: { target: `proposed ${id}` },
    content_hash: "sha256:" + "0".repeat(64),
    status: "pending",
    created_at: "2026-08-04T00:00:00Z",
    resolved_at: null,
    ...overrides,
  };
}

export function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    workspace: "/tmp/review",
    title: "Component test",
    source_type: "local_video",
    source_lang: "en",
    target_lang: "zh",
    languages: ["zh"],
    revision: "r1",
    progress: testProgress,
    media: {
      kind: "video",
      url: "/api/media",
      name: "test.mp4",
      duration: 400,
      playable: true,
      preview_status: "ready",
      preview_error: null,
    },
    ...overrides,
  };
}

export function makeSnapshot(
  revision: string,
  cues: Cue[],
  suggestions: Suggestion[] = [],
): Snapshot {
  return { revision, changed: [], progress: testProgress, suggestions, cues };
}

export interface SeedState {
  cues: Cue[];
  suggestions?: Suggestion[];
  session?: Session;
  selectedId?: number | null;
  selection?: number[];
}

export function createTestServices(seed: SeedState, api: Partial<Api> = {}): AppServices {
  const services = createAppServices(api as Api);
  const session = seed.session ?? makeSession();
  const selectedId = seed.selectedId ?? seed.cues[0]?.id ?? null;
  services.store.setState({
    session,
    cues: seed.cues,
    revision: "r1",
    progress: session.progress,
    suggestions: seed.suggestions ?? [],
    selectedId,
    selection: seed.selection ?? (selectedId != null ? [selectedId] : []),
    currentTime: seed.cues[0]?.start ?? 0,
  });
  return services;
}

export function renderWithServices(node: ReactNode, services: AppServices) {
  return render(
    <I18nProvider initialLocale="en">
      <ServicesProvider services={services}>{node}</ServicesProvider>
    </I18nProvider>,
  );
}

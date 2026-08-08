export type ReviewStatus = "unreviewed" | "reviewed" | "flagged";

export interface Progress {
  reviewed: number;
  flagged: number;
  unreviewed: number;
  total: number;
}

export interface Budget {
  max_chars: number;
  seconds: number;
}

export type IssueKind = "term" | "timing" | "budget" | "asr_confidence" | "agent_note";
export type IssueSeverity = "warning" | "info";
export type IssueSource = "rule" | "agent";

export interface CueIssue {
  cue_id: number;
  kind: IssueKind;
  severity: IssueSeverity;
  message: string;
  detail: Record<string, unknown>;
  source: IssueSource;
  dismissed: boolean;
  suggestion_ids: string[];
}

export interface Cue {
  id: number;
  start: number;
  end: number;
  duration: number;
  source: string;
  source_cps: number;
  target: string | null;
  budget: Budget | null;
  over_budget: boolean;
  time_warning: boolean;
  term_warning: boolean;
  issues: CueIssue[];
  status: ReviewStatus;
  note: string | null;
}

export interface Session {
  workspace: string;
  title: string;
  source_type: "url" | "local_video" | "local_audio";
  source_lang: string;
  target_lang: string | null;
  languages: string[];
  revision: string;
  progress: Progress;
  media: {
    kind: "audio" | "video";
    url: string;
    name: string;
    duration: number;
    playable: boolean;
    preview_status: "ready" | "needed" | "building" | "failed";
    preview_error: string | null;
  };
}

export interface SuggestionPatch {
  source?: string | null;
  target?: string | null;
  start?: number | null;
  end?: number | null;
}

export type SuggestionStatus = "pending" | "accepted" | "rejected";

export interface Suggestion {
  id: string;
  cue_id: number;
  kind: string;
  severity: IssueSeverity;
  message: string;
  patch: SuggestionPatch;
  content_hash: string;
  status: SuggestionStatus;
  created_at: string;
  resolved_at: string | null;
}

export interface Snapshot {
  revision: string;
  changed: number[];
  progress: Progress;
  suggestions: Suggestion[];
  cues: Cue[];
}

export interface WaveformResponse {
  sample_rate: number;
  duration: number;
  start: number;
  end: number;
  peaks: [number, number][];
}

export interface TimedWord {
  word: string;
  start: number;
  end: number;
  prob?: number;
}

export interface PreviewState {
  status: "ready" | "needed" | "building" | "failed";
  error: string | null;
}

export interface BatchMatch {
  cue_id: number;
  field: "source" | "target";
  spans: [number, number][];
  text: string;
}

export interface BatchDryRunResult {
  matches: BatchMatch[];
  revision: string;
}

export interface TermReport {
  added: string[];
  updated: string[];
  unchanged: string[];
  aliases_added: number;
}

export interface GlossaryTermResult extends Snapshot {
  glossary: string;
  term_report: TermReport;
}

export interface MutationBase {
  base_revision: string;
  op_id: string;
}

export interface CuePatchBody extends MutationBase {
  source?: string;
  target?: string;
  start?: number;
  end?: number;
}

export interface StatusPatchBody extends MutationBase {
  status: ReviewStatus;
  note?: string | null;
}

export interface SplitBody extends MutationBase {
  at: number;
  source_left: string;
  source_right: string;
  target_left?: string | null;
  target_right?: string | null;
}

export interface MergeBody extends MutationBase {
  cue_ids: number[];
}

export interface InsertBody extends MutationBase {
  at: number;
}

export interface SwitchTargetBody extends MutationBase {
  target_lang: string | null;
}

export interface DismissalBody extends MutationBase {
  kind: IssueKind;
}

export interface BatchReplaceBody extends MutationBase {
  find: string;
  replace: string;
  fields: Array<"source" | "target">;
  case_sensitive?: boolean;
  regex?: boolean;
  cue_ids?: number[];
}

export interface BatchStatusBody extends MutationBase {
  cue_ids: number[];
  status: ReviewStatus;
  note?: string | null;
}

export interface BatchDeleteBody extends MutationBase {
  cue_ids: number[];
}

export interface GlossaryTermBody extends MutationBase {
  source: string;
  target: string;
  note?: string | null;
  keep?: boolean;
}

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

export interface CueResponse {
  revision: string;
  changed: number[];
  progress: Progress;
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

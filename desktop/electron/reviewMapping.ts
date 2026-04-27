import type { ReviewModel, Segment, WaveformBar } from "../src/lib/types.js";
import type { ApiArtifactPreviewData, ApiArtifactRecord } from "./apiTypes.js";

export class ReviewUnavailableError extends Error {
  code = "review_unavailable";

  constructor(message = "No readable review artifacts are available for this run.") {
    super(message);
    this.name = "ReviewUnavailableError";
  }
}

type RawSegment = {
  start?: number;
  end?: number;
  start_ms?: number;
  end_ms?: number;
  text?: string;
  transcript?: string;
  translation?: string;
};

function isSegmentArtifact(artifact: ApiArtifactRecord): boolean {
  const value = `${artifact.type} ${artifact.name}`.toLowerCase();
  return value.includes("segment") || value.includes("translation") || value.includes("subtitle");
}

function asRawSegments(content: unknown): RawSegment[] {
  if (Array.isArray(content)) {
    return content.filter((item): item is RawSegment => typeof item === "object" && item !== null);
  }

  if (typeof content === "object" && content !== null && Array.isArray((content as { segments?: unknown }).segments)) {
    return (content as { segments: unknown[] }).segments.filter((item): item is RawSegment => typeof item === "object" && item !== null);
  }

  return [];
}

function timeMs(raw: RawSegment, keyMs: "start_ms" | "end_ms", keySeconds: "start" | "end"): number {
  const ms = raw[keyMs];
  if (typeof ms === "number") {
    return Math.round(ms);
  }

  const seconds = raw[keySeconds];
  if (typeof seconds === "number") {
    return Math.round(seconds * 1000);
  }

  return 0;
}

function toSegments(rawSegments: RawSegment[]): Segment[] {
  return rawSegments.map((raw, index) => ({
    id: `seg-${index + 1}`,
    index: index + 1,
    startMs: timeMs(raw, "start_ms", "start"),
    endMs: timeMs(raw, "end_ms", "end"),
    transcript: raw.transcript ?? raw.text ?? "",
    translation: raw.translation ?? raw.text ?? "",
    savedState: "saved"
  }));
}

function waveform(): WaveformBar[] {
  const levels = [24, 40, 62, 48, 72, 56, 80, 34];
  return Array.from({ length: 48 }, (_, index) => ({
    id: `bar-${index.toString().padStart(2, "0")}`,
    level: levels[index % levels.length]
  }));
}

export function toReviewModel(
  runId: string,
  artifacts: ApiArtifactRecord[],
  previewsByVersionId: Map<string, ApiArtifactPreviewData>
): ReviewModel {
  for (const artifact of artifacts.filter(isSegmentArtifact)) {
    const versionId = artifact.current_version_id;
    if (!versionId) {
      continue;
    }

    const preview = previewsByVersionId.get(versionId);
    if (!preview || preview.truncated) {
      continue;
    }

    const segments = toSegments(asRawSegments(preview.content)).filter((segment) => segment.endMs >= segment.startMs);
    if (segments.length === 0) {
      continue;
    }

    const durationMs = Math.max(...segments.map((segment) => segment.endMs), 1);
    return {
      title: `${runId} results`,
      durationMs,
      currentMs: segments[0]?.startMs ?? 0,
      activeSegmentId: segments[0]?.id ?? "",
      waveform: waveform(),
      segments
    };
  }

  throw new ReviewUnavailableError();
}

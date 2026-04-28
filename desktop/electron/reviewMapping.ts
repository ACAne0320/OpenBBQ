import type { ReviewModel, Segment, WaveformBar } from "../src/lib/types.js";
import type { ApiArtifactPreviewData, ApiArtifactRecord } from "./apiTypes.js";
import { artifactFileUrl } from "./mediaUrls.js";
import { waveformFromPcm16WavFile } from "./wavWaveform.js";

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
  source_text?: string;
  transcript?: string;
  translation?: string;
};

function isSegmentArtifact(artifact: ApiArtifactRecord): boolean {
  const value = `${artifact.type} ${artifact.name}`.toLowerCase();
  return value.includes("segment") || value.includes("translation") || value.includes("subtitle");
}

function isSourceSegmentArtifact(artifact: ApiArtifactRecord): boolean {
  return artifact.type === "subtitle_segments" || artifact.type === "asr_transcript";
}

function isTranslationArtifact(artifact: ApiArtifactRecord): boolean {
  return artifact.type === "translation" || artifact.name.toLowerCase().includes("translate.");
}

function isSubtitleArtifact(artifact: ApiArtifactRecord): boolean {
  return artifact.type === "subtitle";
}

function isVideoArtifact(artifact: ApiArtifactRecord): boolean {
  return artifact.type === "video";
}

function isAudioArtifact(artifact: ApiArtifactRecord): boolean {
  return artifact.type === "audio";
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

function rawText(raw: RawSegment | undefined): string {
  return raw?.transcript ?? raw?.source_text ?? raw?.text ?? "";
}

function translatedText(raw: RawSegment | undefined): string {
  return raw?.translation ?? raw?.text ?? "";
}

function toSegments(rawSegments: RawSegment[], translatedSegments: RawSegment[] = []): Segment[] {
  const count = Math.max(rawSegments.length, translatedSegments.length);
  return Array.from({ length: count }, (_, index) => {
    const raw = rawSegments[index];
    const translated = translatedSegments[index];
    const timing = translated ?? raw ?? {};
    return {
    id: `seg-${index + 1}`,
    index: index + 1,
    startMs: timeMs(timing, "start_ms", "start"),
    endMs: timeMs(timing, "end_ms", "end"),
    transcript: rawText(raw) || rawText(translated),
    translation: translatedText(translated) || translatedText(raw),
    savedState: "saved"
    };
  });
}

function placeholderWaveform(barCount = 48): WaveformBar[] {
  const levels = [24, 40, 62, 48, 72, 56, 80, 34];
  return Array.from({ length: barCount }, (_, index) => ({
    id: `bar-${index.toString().padStart(2, "0")}`,
    level: levels[index % levels.length]
  }));
}

function waveformBarCount(durationMs: number): number {
  if (!Number.isFinite(durationMs) || durationMs <= 0) {
    return 240;
  }

  return Math.min(24_000, Math.max(240, Math.ceil(durationMs / 20)));
}

export function toReviewModel(
  runId: string,
  artifacts: ApiArtifactRecord[],
  previewsByVersionId: Map<string, ApiArtifactPreviewData>
): ReviewModel {
  const sourcePreview = firstPreview(artifacts, previewsByVersionId, isSourceSegmentArtifact);
  const translationPreview = firstPreview(artifacts, previewsByVersionId, isTranslationArtifact);
  const fallbackPreview = firstPreview(artifacts, previewsByVersionId, isSegmentArtifact);
  const rawSegments = asRawSegments(sourcePreview?.content);
  const translatedSegments = asRawSegments(translationPreview?.content);
  const segments = toSegments(
    rawSegments.length > 0 ? rawSegments : asRawSegments(fallbackPreview?.content),
    translatedSegments
  ).filter((segment) => segment.endMs >= segment.startMs);
  if (segments.length === 0) {
    throw new ReviewUnavailableError();
  }

  const durationMs = Math.max(...segments.map((segment) => segment.endMs), 1);
  const realWaveform = audioWaveform(artifacts, previewsByVersionId, waveformBarCount(durationMs));
  return {
    title: `${runId} results`,
    durationMs,
    currentMs: segments[0]?.startMs ?? 0,
    activeSegmentId: segments[0]?.id ?? "",
    videoSrc: videoSrc(artifacts, previewsByVersionId),
    subtitleText: subtitleText(artifacts, previewsByVersionId),
    waveform: realWaveform ?? placeholderWaveform(waveformBarCount(durationMs)),
    waveformSource: realWaveform ? "audio_loudness" : "placeholder",
    segments
  };
}

function firstPreview(
  artifacts: ApiArtifactRecord[],
  previewsByVersionId: Map<string, ApiArtifactPreviewData>,
  predicate: (artifact: ApiArtifactRecord) => boolean
): ApiArtifactPreviewData | undefined {
  for (const artifact of artifacts.filter(predicate)) {
    const versionId = artifact.current_version_id;
    if (!versionId) {
      continue;
    }
    const preview = previewsByVersionId.get(versionId);
    if (preview && !preview.truncated) {
      return preview;
    }
  }
  return undefined;
}

function videoSrc(
  artifacts: ApiArtifactRecord[],
  previewsByVersionId: Map<string, ApiArtifactPreviewData>
): string | undefined {
  const preview = firstPreview(artifacts, previewsByVersionId, isVideoArtifact);
  if (!preview) {
    return undefined;
  }
  const contentPath = preview.version.content_path;
  if (!contentPath || preview.version.content_encoding !== "file") {
    return undefined;
  }
  return artifactFileUrl(contentPath, "video/mp4");
}

function audioWaveform(
  artifacts: ApiArtifactRecord[],
  previewsByVersionId: Map<string, ApiArtifactPreviewData>,
  barCount: number
): WaveformBar[] | null {
  const preview = firstPreview(artifacts, previewsByVersionId, isAudioArtifact);
  if (!preview) {
    return null;
  }

  const contentPath = preview.version.content_path;
  if (!contentPath || preview.version.content_encoding !== "file") {
    return null;
  }

  return waveformFromPcm16WavFile(contentPath, barCount);
}

function subtitleText(
  artifacts: ApiArtifactRecord[],
  previewsByVersionId: Map<string, ApiArtifactPreviewData>
): string | undefined {
  const preview = firstPreview(artifacts, previewsByVersionId, isSubtitleArtifact);
  return typeof preview?.content === "string" ? preview.content : undefined;
}

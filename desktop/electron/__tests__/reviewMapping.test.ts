// @vitest-environment node
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { ApiArtifactPreviewData, ApiArtifactRecord } from "../apiTypes";
import { ReviewUnavailableError, toReviewModel } from "../reviewMapping";
import { waveformFromPcm16Wav } from "../wavWaveform";

const artifact: ApiArtifactRecord = {
  id: "art_segments",
  type: "subtitle_segments",
  name: "translate.translation",
  versions: ["av_1"],
  current_version_id: "av_1",
  created_by_step_id: "translate",
  created_at: "2026-04-27T03:15:12.000Z",
  updated_at: "2026-04-27T03:15:12.000Z"
};

const preview: ApiArtifactPreviewData = {
  version: {
    id: "av_1",
    artifact_id: "art_segments",
    version_number: 1,
    content_path: "H:/workspace/.openbbq/artifacts/art_segments/versions/1",
    content_hash: "hash",
    content_encoding: "json",
    content_size: 120,
    metadata: {},
    lineage: {},
    created_at: "2026-04-27T03:15:12.000Z"
  },
  content: [
    { start: 1.2, end: 3.4, text: "Hello", translation: "Hello translated" },
    { start_ms: 4200, end_ms: 6900, transcript: "World", translation: "World translated" }
  ],
  truncated: false,
  content_encoding: "json",
  content_size: 120
};

function pcm16Wav(samples: number[], sampleRate = 16_000): Buffer {
  const dataSize = samples.length * 2;
  const buffer = Buffer.alloc(44 + dataSize);
  buffer.write("RIFF", 0, "ascii");
  buffer.writeUInt32LE(36 + dataSize, 4);
  buffer.write("WAVE", 8, "ascii");
  buffer.write("fmt ", 12, "ascii");
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36, "ascii");
  buffer.writeUInt32LE(dataSize, 40);

  samples.forEach((sample, index) => {
    buffer.writeInt16LE(sample, 44 + index * 2);
  });

  return buffer;
}

describe("toReviewModel", () => {
  it("maps subtitle-like JSON preview content to review segments", () => {
    const model = toReviewModel("run_1", [artifact], new Map([["av_1", preview]]));

    expect(model.title).toBe("run_1 results");
    expect(model.segments).toEqual([
      {
        id: "seg-1",
        index: 1,
        startMs: 1200,
        endMs: 3400,
        transcript: "Hello",
        translation: "Hello translated",
        savedState: "saved"
      },
      {
        id: "seg-2",
        index: 2,
        startMs: 4200,
        endMs: 6900,
        transcript: "World",
        translation: "World translated",
        savedState: "saved"
      }
    ]);
    expect(model.durationMs).toBe(6900);
    expect(model.waveform.length).toBeGreaterThan(100);
  });

  it("throws a typed error when no readable segment artifact exists", () => {
    expect(() => toReviewModel("run_1", [], new Map())).toThrow(ReviewUnavailableError);
  });

  it("combines video, translation, subtitle segment, and SRT artifacts into a real review model", () => {
    const videoArtifact: ApiArtifactRecord = {
      ...artifact,
      id: "art_video",
      type: "video",
      name: "download.video",
      current_version_id: "av_video"
    };
    const sourceArtifact: ApiArtifactRecord = {
      ...artifact,
      id: "art_source_segments",
      type: "subtitle_segments",
      name: "segment.subtitle_segments",
      current_version_id: "av_source"
    };
    const translationArtifact: ApiArtifactRecord = {
      ...artifact,
      id: "art_translation",
      type: "translation",
      name: "translate.translation",
      current_version_id: "av_translation"
    };
    const subtitleArtifact: ApiArtifactRecord = {
      ...artifact,
      id: "art_subtitle",
      type: "subtitle",
      name: "subtitle.subtitle",
      current_version_id: "av_subtitle"
    };
    const previews = new Map<string, ApiArtifactPreviewData>([
      [
        "av_video",
        {
          ...preview,
          version: {
            ...preview.version,
            id: "av_video",
            artifact_id: "art_video",
            content_path: "/workspace/.openbbq/artifacts/video/content",
            content_encoding: "file"
          },
          content: null,
          content_encoding: "file"
        }
      ],
      [
        "av_source",
        {
          ...preview,
          version: { ...preview.version, id: "av_source", artifact_id: "art_source_segments" },
          content: [{ start: 1, end: 2, text: "Source text" }]
        }
      ],
      [
        "av_translation",
        {
          ...preview,
          version: { ...preview.version, id: "av_translation", artifact_id: "art_translation" },
          content: [{ start: 1, end: 2, source_text: "Source from translation", text: "Translated text" }]
        }
      ],
      [
        "av_subtitle",
        {
          ...preview,
          version: { ...preview.version, id: "av_subtitle", artifact_id: "art_subtitle", content_encoding: "text" },
          content: "1\n00:00:01,000 --> 00:00:02,000\nTranslated text\n",
          content_encoding: "text"
        }
      ]
    ]);

    const model = toReviewModel(
      "run_1",
      [videoArtifact, sourceArtifact, translationArtifact, subtitleArtifact],
      previews
    );

    expect(model.videoSrc).toMatch(/^openbbq-file:\/\/artifact\//);
    expect(model.subtitleText).toBe("1\n00:00:01,000 --> 00:00:02,000\nTranslated text\n");
    expect(model.segments[0]).toMatchObject({
      transcript: "Source text",
      translation: "Translated text"
    });
  });

  it("uses a file-backed audio artifact to derive real waveform loudness", () => {
    const tempDir = mkdtempSync(join(tmpdir(), "openbbq-waveform-"));
    const audioPath = join(tempDir, "audio.wav");
    writeFileSync(audioPath, pcm16Wav([...Array(48).fill(900), ...Array(48).fill(28_000)]));

    const audioArtifact: ApiArtifactRecord = {
      ...artifact,
      id: "art_audio",
      type: "audio",
      name: "extract_audio.audio",
      current_version_id: "av_audio"
    };
    const previews = new Map<string, ApiArtifactPreviewData>([
      ["av_1", preview],
      [
        "av_audio",
        {
          ...preview,
          version: {
            ...preview.version,
            id: "av_audio",
            artifact_id: "art_audio",
            content_path: audioPath,
            content_encoding: "file"
          },
          content: null,
          content_encoding: "file"
        }
      ]
    ]);

    const model = toReviewModel("run_1", [artifact, audioArtifact], previews);

    expect(model.waveformSource).toBe("audio_loudness");
    const midpoint = Math.floor(model.waveform.length / 2);
    expect(model.waveform.length).toBeGreaterThan(100);
    expect(Math.max(...model.waveform.slice(0, midpoint - 4).map((bar) => bar.level))).toBeLessThan(
      Math.min(...model.waveform.slice(midpoint + 4).map((bar) => bar.level))
    );
  });

  it("keeps silent audio spans empty in the waveform", () => {
    const waveform = waveformFromPcm16Wav(
      pcm16Wav([...Array(90).fill(24_000), ...Array(90).fill(0), ...Array(90).fill(24_000)]),
      9
    );

    expect(waveform?.map((bar) => bar.level)).toEqual([96, 96, 96, 0, 0, 0, 96, 96, 96]);
  });

  it("samples real waveform data finely enough to expose silence gaps", () => {
    const tempDir = mkdtempSync(join(tmpdir(), "openbbq-waveform-"));
    const audioPath = join(tempDir, "audio.wav");
    writeFileSync(audioPath, pcm16Wav([...Array(230).fill(24_000), ...Array(230).fill(0), ...Array(230).fill(24_000)]));

    const audioArtifact: ApiArtifactRecord = {
      ...artifact,
      id: "art_audio",
      type: "audio",
      name: "extract_audio.audio",
      current_version_id: "av_audio"
    };
    const previews = new Map<string, ApiArtifactPreviewData>([
      ["av_1", preview],
      [
        "av_audio",
        {
          ...preview,
          version: {
            ...preview.version,
            id: "av_audio",
            artifact_id: "art_audio",
            content_path: audioPath,
            content_encoding: "file"
          },
          content: null,
          content_encoding: "file"
        }
      ]
    ]);

    const model = toReviewModel("run_1", [artifact, audioArtifact], previews);
    const silentWindow = model.waveform.slice(
      Math.floor(model.waveform.length * 0.4),
      Math.ceil(model.waveform.length * 0.6)
    );

    expect(model.waveform.length).toBeGreaterThan(300);
    expect(Math.max(...silentWindow.map((bar) => bar.level))).toBe(0);
  });
});

// @vitest-environment node
import { describe, expect, it } from "vitest";

import type { ApiArtifactPreviewData, ApiArtifactRecord } from "../apiTypes";
import { ReviewUnavailableError, toReviewModel } from "../reviewMapping";

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
    expect(model.waveform).toHaveLength(48);
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
});

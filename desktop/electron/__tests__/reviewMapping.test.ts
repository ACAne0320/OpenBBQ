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
});

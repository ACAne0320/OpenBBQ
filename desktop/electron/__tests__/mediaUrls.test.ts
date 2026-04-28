// @vitest-environment node
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { artifactFileResponse, artifactFileUrl } from "../mediaUrls";

const tempDirs: string[] = [];

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

function writeArtifactFile(content: string): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "openbbq-media-url-"));
  tempDirs.push(dir);
  const filePath = path.join(dir, "video.mp4");
  fs.writeFileSync(filePath, content);
  return filePath;
}

async function responseText(response: Response): Promise<string> {
  return await response.text();
}

describe("artifactFileResponse", () => {
  it("serves byte ranges for media playback", async () => {
    const filePath = writeArtifactFile("0123456789abcdef");
    const url = artifactFileUrl(filePath, "video/mp4");

    const response = await artifactFileResponse(url, new Headers({ Range: "bytes=3-7" }));

    expect(response.status).toBe(206);
    expect(response.headers.get("Content-Type")).toBe("video/mp4");
    expect(response.headers.get("Accept-Ranges")).toBe("bytes");
    expect(response.headers.get("Content-Range")).toBe("bytes 3-7/16");
    expect(response.headers.get("Content-Length")).toBe("5");
    expect(await responseText(response)).toBe("34567");
  });

  it("returns 416 for unsatisfiable byte ranges", async () => {
    const filePath = writeArtifactFile("0123456789abcdef");
    const url = artifactFileUrl(filePath, "video/mp4");

    const response = await artifactFileResponse(url, new Headers({ Range: "bytes=30-40" }));

    expect(response.status).toBe(416);
    expect(response.headers.get("Content-Range")).toBe("bytes */16");
  });
});

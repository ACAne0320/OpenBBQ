import path from "node:path";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { Readable } from "node:stream";
import { pathToFileURL } from "node:url";

export const artifactFileScheme = "openbbq-file";

const allowedArtifactFiles = new Map<string, string>();

export function artifactFileUrl(filePath: string, mediaType = "application/octet-stream"): string {
  const resolved = path.resolve(filePath);
  allowedArtifactFiles.set(resolved, mediaType);
  const encoded = Buffer.from(resolved, "utf-8").toString("base64url");
  return `${artifactFileScheme}://artifact/${encoded}`;
}

export function resolveArtifactFileUrl(rawUrl: string): { fileUrl: string; mediaType: string } | null {
  const parsed = new URL(rawUrl);
  if (parsed.protocol !== `${artifactFileScheme}:` || parsed.hostname !== "artifact") {
    return null;
  }
  const encoded = parsed.pathname.replace(/^\/+/, "");
  const resolved = path.resolve(Buffer.from(encoded, "base64url").toString("utf-8"));
  const mediaType = allowedArtifactFiles.get(resolved);
  if (!mediaType) {
    return null;
  }
  return { fileUrl: pathToFileURL(resolved).toString(), mediaType };
}

export async function artifactFileResponse(rawUrl: string, headers: Headers = new Headers()): Promise<Response> {
  const parsed = new URL(rawUrl);
  if (parsed.protocol !== `${artifactFileScheme}:` || parsed.hostname !== "artifact") {
    return new Response("Artifact file is not available.", { status: 404 });
  }

  const encoded = parsed.pathname.replace(/^\/+/, "");
  const resolved = path.resolve(Buffer.from(encoded, "base64url").toString("utf-8"));
  const mediaType = allowedArtifactFiles.get(resolved);
  if (!mediaType) {
    return new Response("Artifact file is not available.", { status: 404 });
  }

  let fileSize: number;
  try {
    fileSize = (await stat(resolved)).size;
  } catch {
    return new Response("Artifact file is not available.", { status: 404 });
  }

  const baseHeaders = {
    "Accept-Ranges": "bytes",
    "Content-Type": mediaType
  };
  const range = parseRange(headers.get("range"), fileSize);

  if (range === "unsatisfiable") {
    return new Response(null, {
      status: 416,
      headers: {
        ...baseHeaders,
        "Content-Range": `bytes */${fileSize}`
      }
    });
  }

  if (range) {
    const length = range.end - range.start + 1;
    return new Response(fileStream(resolved, range.start, range.end), {
      status: 206,
      headers: {
        ...baseHeaders,
        "Content-Length": String(length),
        "Content-Range": `bytes ${range.start}-${range.end}/${fileSize}`
      }
    });
  }

  return new Response(fileSize === 0 ? null : fileStream(resolved), {
    status: 200,
    headers: {
      ...baseHeaders,
      "Content-Length": String(fileSize)
    }
  });
}

type ByteRange = { start: number; end: number };

function parseRange(value: string | null, fileSize: number): ByteRange | "unsatisfiable" | null {
  if (!value) {
    return null;
  }

  const match = /^bytes=(\d*)-(\d*)$/.exec(value.trim());
  if (!match || fileSize <= 0) {
    return "unsatisfiable";
  }

  const [, startText, endText] = match;
  if (!startText && !endText) {
    return "unsatisfiable";
  }

  if (!startText) {
    const suffixLength = Number(endText);
    if (!Number.isSafeInteger(suffixLength) || suffixLength <= 0) {
      return "unsatisfiable";
    }
    return {
      start: Math.max(0, fileSize - suffixLength),
      end: fileSize - 1
    };
  }

  const start = Number(startText);
  const end = endText ? Number(endText) : fileSize - 1;
  if (
    !Number.isSafeInteger(start) ||
    !Number.isSafeInteger(end) ||
    start < 0 ||
    end < start ||
    start >= fileSize
  ) {
    return "unsatisfiable";
  }

  return { start, end: Math.min(end, fileSize - 1) };
}

function fileStream(filePath: string, start?: number, end?: number): ReadableStream<Uint8Array> {
  return Readable.toWeb(createReadStream(filePath, { start, end })) as ReadableStream<Uint8Array>;
}

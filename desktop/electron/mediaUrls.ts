import path from "node:path";
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

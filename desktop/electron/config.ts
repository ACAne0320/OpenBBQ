import { app } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";

const electronDir = path.dirname(fileURLToPath(import.meta.url));

export type DesktopRuntimeConfig = {
  repoRoot: string;
  workspaceRoot: string;
  rendererUrl: string | null;
  sidecarCommand: string;
  sidecarArgs: string[];
  allowDevCors: boolean;
};

function defaultRepoRoot(): string {
  const cwd = process.cwd();
  if (path.basename(cwd) === "desktop") {
    return path.dirname(cwd);
  }

  return path.resolve(electronDir, "..", "..", "..");
}

function defaultWorkspaceRoot(): string {
  return path.join(app.getPath("userData"), "workspace");
}

function uvCommand(): string {
  return "uv";
}

export function createDesktopRuntimeConfig(): DesktopRuntimeConfig {
  const repoRoot = process.env.OPENBBQ_REPO_ROOT ?? defaultRepoRoot();
  const workspaceRoot = process.env.OPENBBQ_DESKTOP_WORKSPACE ?? defaultWorkspaceRoot();
  const rendererUrl = process.env.OPENBBQ_RENDERER_URL ?? null;
  const allowDevCors = rendererUrl !== null;
  const sidecarCommand = process.env.OPENBBQ_SIDECAR_COMMAND ?? uvCommand();
  const sidecarArgs = process.env.OPENBBQ_SIDECAR_ARGS
    ? (JSON.parse(process.env.OPENBBQ_SIDECAR_ARGS) as string[])
    : ["run", "openbbq", "api", "serve"];

  return {
    repoRoot,
    workspaceRoot,
    rendererUrl,
    sidecarCommand,
    sidecarArgs,
    allowDevCors
  };
}

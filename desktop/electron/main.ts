import { app, BrowserWindow, net, protocol } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createDesktopRuntimeConfig } from "./config.js";
import { registerOpenBBQIpc } from "./ipc.js";
import { artifactFileScheme, resolveArtifactFileUrl } from "./mediaUrls.js";
import { startSidecar, type ManagedSidecar } from "./sidecar.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let sidecar: ManagedSidecar | null = null;
let sidecarError: Error | null = null;
let unregisterIpc: (() => void) | null = null;

protocol.registerSchemesAsPrivileged([
  {
    scheme: artifactFileScheme,
    privileges: { standard: true, secure: true, stream: true, supportFetchAPI: true }
  }
]);

function logSidecarOutput(stream: "stdout" | "stderr", text: string) {
  const target = stream === "stderr" ? process.stderr : process.stdout;
  target.write(`[openbbq sidecar:${stream}] ${text}`);
}

function registerArtifactFileProtocol() {
  protocol.handle(artifactFileScheme, async (request) => {
    const resolved = resolveArtifactFileUrl(request.url);
    if (!resolved) {
      return new Response("Artifact file is not available.", { status: 404 });
    }
    const response = await net.fetch(resolved.fileUrl);
    return new Response(response.body, {
      status: response.status,
      headers: { "Content-Type": resolved.mediaType }
    });
  });
}

async function createWindow() {
  const config = createDesktopRuntimeConfig();
  const window = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 980,
    minHeight: 700,
    backgroundColor: "#f3ecd9",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs")
    }
  });

  try {
    sidecar = await startSidecar({
      command: config.sidecarCommand,
      args: config.sidecarArgs,
      cwd: config.repoRoot,
      workspaceRoot: config.workspaceRoot,
      allowDevCors: config.allowDevCors,
      logOutput: logSidecarOutput
    });
  } catch (error) {
    sidecarError = error instanceof Error ? error : new Error(String(error));
  }

  unregisterIpc = registerOpenBBQIpc({
    window,
    getSidecar() {
      if (!sidecar) {
        throw sidecarError ?? new Error("OpenBBQ sidecar is not connected.");
      }
      return sidecar;
    }
  });

  if (config.rendererUrl) {
    await window.loadURL(config.rendererUrl);
  } else {
    await window.loadFile(path.resolve(__dirname, "..", "..", "dist", "index.html"));
  }
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  unregisterIpc?.();
  void sidecar?.stop();
});

void app.whenReady().then(() => {
  registerArtifactFileProtocol();
  return createWindow();
});

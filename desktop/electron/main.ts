import { app, BrowserWindow } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createDesktopRuntimeConfig } from "./config.js";
import { registerOpenBBQIpc } from "./ipc.js";
import { startSidecar, type ManagedSidecar } from "./sidecar.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let sidecar: ManagedSidecar | null = null;
let sidecarError: Error | null = null;
let unregisterIpc: (() => void) | null = null;

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
      preload: path.join(__dirname, "preload.js")
    }
  });

  try {
    sidecar = await startSidecar({
      command: config.sidecarCommand,
      args: config.sidecarArgs,
      cwd: config.repoRoot,
      workspaceRoot: config.workspaceRoot,
      allowDevCors: config.allowDevCors
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

void app.whenReady().then(createWindow);

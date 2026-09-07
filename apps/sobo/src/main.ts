/**
 * Sobo — Electron desktop shell for Soothe Teammates.
 *
 * Simplified from Rakazo desktop: no Docker local-stack management.
 * The app connects to a Soothe Bridge server (oRPC over HTTP/SSE).
 * The bridge serves both the web UI static assets and the RPC endpoints.
 */

import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { app, BrowserWindow, ipcMain, net, shell } from "electron";

const PROBE_TIMEOUT_MS = 8_000;
const SETUP_FILE_NAME = "setup.json";
const DEFAULT_BRIDGE_URL = "http://127.0.0.1:3100";

let mainWindow: BrowserWindow | null = null;
let setupWindow: BrowserWindow | null = null;

// --- Setup store ---
function setupPath() {
  return path.join(app.getPath("userData"), SETUP_FILE_NAME);
}

async function readSetup(): Promise<{ serverUrl: string } | null> {
  try {
    const raw = await readFile(setupPath(), "utf8");
    const parsed = JSON.parse(raw);
    if (typeof parsed.serverUrl === "string") return parsed;
    return null;
  } catch {
    return null;
  }
}

async function writeSetup(setup: { serverUrl: string }): Promise<void> {
  await writeFile(setupPath(), `${JSON.stringify(setup, null, 2)}\n`, "utf8");
}

// --- URL normalization ---
function normalizeUrl(input: string): string | null {
  const trimmed = input.trim();
  if (trimmed === "") return null;
  try {
    const url = trimmed.match(/^https?:\/\//)
      ? new URL(trimmed)
      : new URL(`http://${trimmed}`);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url.origin;
  } catch {
    return null;
  }
}

// --- Health probe ---
async function probeServer(
  url: string,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const normalized = normalizeUrl(url);
  if (normalized === null) return { ok: false, error: "Enter a valid address." };
  try {
    const response = await net.fetch(`${normalized}/rpc/health`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ json: {} }),
      cache: "no-store",
      credentials: "omit",
      redirect: "manual",
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    if (!response.ok) return { ok: false, error: `Server answered HTTP ${response.status}.` };
    const body = (await response.json()) as { ok?: boolean; version?: string };
    if (body.ok === true) return { ok: true };
    return { ok: false, error: "Not a Soothe Bridge server." };
  } catch (error) {
    const name = error instanceof Error ? error.name : "";
    if (name === "TimeoutError" || name === "AbortError")
      return { ok: false, error: "Timed out reaching that address." };
    const detail = error instanceof Error ? error.message : String(error);
    if (detail.includes("ECONNREFUSED"))
      return { ok: false, error: "Nothing is listening at that address yet." };
    return { ok: false, error: "Could not reach that address." };
  }
}

// --- Window creation ---
function createAppWindow(url: string) {
  const win = new BrowserWindow({
    width: 1000,
    height: 700,
    minWidth: 700,
    minHeight: 500,
    titleBarStyle: "hiddenInset",
    show: false,
    webPreferences: {
      preload: path.join(import.meta.dirname, "preload.cjs"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });

  win.webContents.setWindowOpenHandler(({ url: childUrl }) => {
    const external = /^https?:\/\//.test(childUrl) ? childUrl : null;
    if (external) void shell.openExternal(external);
    return { action: "deny" };
  });

  win.once("ready-to-show", () => win.show());

  win.on("close", (event) => {
    if (process.platform === "darwin") {
      event.preventDefault();
      win.hide();
    }
  });
  win.once("closed", () => {
    if (mainWindow === win) mainWindow = null;
  });

  mainWindow = win;
  void win.loadURL(url);
  return win;
}

function createSetupWindow() {
  const win = new BrowserWindow({
    width: 520,
    height: 420,
    resizable: false,
    titleBarStyle: "hiddenInset",
    show: false,
    webPreferences: {
      preload: path.join(import.meta.dirname, "setup-preload.cjs"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });

  setupWindow = win;
  win.once("ready-to-show", () => win.show());
  void win.loadFile(path.join(import.meta.dirname, "setup.html"));
  return win;
}

// --- IPC handlers ---
ipcMain.handle("desktop.platform", () => process.platform);

ipcMain.handle("desktop.window.close", (e) => {
  BrowserWindow.fromWebContents(e.sender)?.close();
});

ipcMain.handle("desktop.window.minimize", (e) => {
  BrowserWindow.fromWebContents(e.sender)?.minimize();
});

ipcMain.handle("desktop.window.toggleMaximize", (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  if (!win) return;
  win.isMaximized() ? win.unmaximize() : win.maximize();
});

ipcMain.handle("desktop.window.state", (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  if (!win) return { maximized: false };
  return { maximized: win.isMaximized() };
});

// Setup IPC
ipcMain.handle("desktop.setup.state", async () => {
  const saved = await readSetup();
  return { defaultLocalUrl: DEFAULT_BRIDGE_URL, saved };
});

ipcMain.handle("desktop.setup.test", async (_e, url: string) => {
  const result = await probeServer(url);
  if (result.ok) return { ok: true, url: normalizeUrl(url) };
  return { ok: false, error: result.error };
});

ipcMain.handle("desktop.setup.save", async (_e, setup: { serverUrl: string }) => {
  const normalized = normalizeUrl(setup.serverUrl);
  if (normalized === null) return { ok: false, error: "Invalid address." };
  const result = await probeServer(normalized);
  if (!result.ok) return result;
  await writeSetup({ serverUrl: normalized });
  if (setupWindow && !setupWindow.isDestroyed()) setupWindow.close();
  createAppWindow(normalized);
  return { ok: true };
});

ipcMain.handle("desktop.setup.quit", () => app.quit());

// --- App lifecycle ---
app.whenReady().then(async () => {
  const saved = await readSetup();
  const envUrl = process.env.SOOTHE_BRIDGE_URL?.trim();
  const targetUrl = envUrl || saved?.serverUrl;
  if (targetUrl) {
    createAppWindow(targetUrl);
  } else {
    createSetupWindow();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", async () => {
  if (mainWindow === null && setupWindow === null) {
    const saved = await readSetup();
    if (saved) createAppWindow(saved.serverUrl);
    else createSetupWindow();
  }
});

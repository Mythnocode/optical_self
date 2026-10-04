import { app, BrowserWindow, clipboard, dialog, ipcMain, protocol, shell } from "electron";
import { readFile, stat, writeFile } from "node:fs/promises";
import { mkdirSync } from "node:fs";
import { basename, extname, isAbsolute, relative, resolve } from "node:path";
import type { ApiRequest, ApiResponse } from "../bridge-contract.js";
import { serializeApiBody } from "../api-json.js";
import { BackendManager } from "./backend-manager.js";
import { recentDiagnostics, writeDiagnostic } from "./diagnostics.js";

const APP_SCHEME = "app";
const APP_HOST = "renderer";
const API_ORIGIN = "http://127.0.0.1:8000";
const requestedDevRendererUrl = process.env.OPTICAL_RENDERER_URL;
const DEV_RENDERER_URL = !app.isPackaged && isAllowedDevRendererUrl(requestedDevRendererUrl)
  ? requestedDevRendererUrl
  : undefined;
const ALLOWED_METHODS = new Set(["GET", "POST", "PUT", "PATCH", "DELETE"]);
const CONTENT_TYPES: Record<string, string> = {
  ".css": "text/css; charset=utf-8",
  ".glb": "model/gltf-binary",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};

protocol.registerSchemesAsPrivileged([
  {
    scheme: APP_SCHEME,
    privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true },
  },
]);

app.setName("Optical ML Platform");
if (process.env.OPTICAL_DESKTOP_USER_DATA_DIR) {
  const userData = resolve(process.env.OPTICAL_DESKTOP_USER_DATA_DIR);
  mkdirSync(userData, { recursive: true });
  app.setPath("userData", userData);
}

let mainWindow: BrowserWindow | null = null;
let quitting = false;
const apiControllers = new Map<string, AbortController>();
const backendManager = new BackendManager((status) => {
  writeDiagnostic("main", "backend-status", status);
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("desktop:backend-status-changed", status);
  }
});

app.whenReady().then(async () => {
  writeDiagnostic("main", "app-ready", { version: app.getVersion(), packaged: app.isPackaged });
  const rendererRoot = resolve(app.getAppPath(), "frontend_web", "dist");
  await protocol.handle(APP_SCHEME, (request) => serveRenderer(request, rendererRoot));
  registerIpcHandlers();
  createWindow();
  void backendManager.start();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("before-quit", (event) => {
  if (quitting) {
    return;
  }
  event.preventDefault();
  quitting = true;
  writeDiagnostic("main", "app-quitting");
  void backendManager.stop().finally(() => app.quit());
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

function createWindow(): void {
  mainWindow = new BrowserWindow({
    show: process.env.OPTICAL_DESKTOP_BACKGROUND !== "1",
    width: 1280,
    height: 800,
    useContentSize: true,
    minWidth: 720,
    minHeight: 560,
    backgroundColor: "#EEF1F5",
    title: "激光耦合仿真系统及智能优化平台",
    webPreferences: {
      preload: resolve(app.getAppPath(), "desktop-dist", "preload.cjs"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });
  mainWindow.removeMenu();

  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("did-finish-load", () => writeDiagnostic("renderer", "load-complete", mainWindow?.webContents.getURL()));
  mainWindow.webContents.on("did-fail-load", (_event, code, description, url) => writeDiagnostic("renderer", "load-failed", { code, description, url }));
  mainWindow.webContents.on("render-process-gone", (_event, details) => writeDiagnostic("renderer", "process-gone", details));
  mainWindow.webContents.on("console-message", (details) => {
    if (details.level === "warning" || details.level === "error") {
      writeDiagnostic("renderer", "console", { level: details.level, message: details.message, line: details.lineNumber });
    }
  });
  mainWindow.webContents.on("will-navigate", (event, targetUrl) => {
    if (!isTrustedRendererUrl(targetUrl)) {
      event.preventDefault();
    }
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  if (DEV_RENDERER_URL) {
    void mainWindow.loadURL(DEV_RENDERER_URL);
    if (!app.isPackaged) {
      mainWindow.webContents.openDevTools({ mode: "detach" });
    }
  } else {
    void mainWindow.loadURL(`${APP_SCHEME}://${APP_HOST}/index.html`);
  }
}

function isTrustedRendererUrl(targetUrl: string): boolean {
  try {
    const target = new URL(targetUrl);
    if (DEV_RENDERER_URL) {
      const devOrigin = new URL(DEV_RENDERER_URL).origin;
      return target.origin === devOrigin && target.pathname === "/";
    }
    return target.protocol === `${APP_SCHEME}:`
      && target.hostname === APP_HOST
      && target.pathname === "/index.html";
  } catch {
    return false;
  }
}

function registerIpcHandlers(): void {
  ipcMain.handle("desktop:open-project-file", async (event) => {
    assertTrustedSender(event);
    const selection = await dialog.showOpenDialog({ title: "打开光学项目", properties: ["openFile"], filters: [{ name: "光学项目 JSON", extensions: ["json"] }] });
    const path = selection.filePaths[0];
    if (selection.canceled || !path) return null;
    if ((await stat(path)).size > 64 * 1024 * 1024) throw new Error("项目文件超过 64 MiB。");
    const bytes = await readFile(path);
    if (bytes.byteLength > 64 * 1024 * 1024) throw new Error("项目文件超过 64 MiB。");
    return { name: basename(path), contents: bytes.toString("utf8") };
  });
  ipcMain.handle("desktop:backend-status", (event) => {
    assertTrustedSender(event);
    return backendManager.getStatus();
  });
  ipcMain.handle("desktop:backend-start", async (event) => {
    assertTrustedSender(event);
    return backendManager.start();
  });
  ipcMain.handle("desktop:open-backend-logs", async (event) => {
    assertTrustedSender(event);
    const result = await shell.openPath(backendManager.logsDirectory);
    if (result) {
      throw new Error(`无法打开后端日志目录：${result}`);
    }
  });
  ipcMain.handle("desktop:copy-diagnostics", (event) => {
    assertTrustedSender(event);
    clipboard.writeText(JSON.stringify({
      time: new Date().toISOString(), app_version: app.getVersion(), packaged: app.isPackaged,
      platform: process.platform, arch: process.arch, electron: process.versions.electron,
      backend: backendManager.getStatus(), logs_directory: backendManager.logsDirectory,
      recent_events: recentDiagnostics(),
    }, null, 2));
  });
  ipcMain.handle("desktop:select-tabular-dataset-file", async (event) => {
    assertTrustedSender(event);
    const selection = await dialog.showOpenDialog({
      properties: ["openFile"],
      filters: [{ name: "表格数据", extensions: ["csv", "json", "jsonl", "ndjson"] }],
    });
    const path = selection.filePaths[0];
    return selection.canceled || !path ? null : { path, name: basename(path) };
  });
  ipcMain.handle("desktop:save-text-file", async (event, request: { suggestedName?: unknown; contents?: unknown }) => {
    assertTrustedSender(event);
    if (typeof request?.contents !== "string" || Buffer.byteLength(request.contents, "utf8") > 64 * 1024 * 1024) {
      throw new Error("待保存文本无效或超过 64 MiB。");
    }
    const baseName = basename(String(request.suggestedName || "manifest.json"))
      .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")
      .replace(/\.json$/i, "") || "manifest";
    const result = await dialog.showSaveDialog({
      title: "保存 JSON 文件",
      defaultPath: `${baseName}.json`,
      filters: [{ name: "JSON 文件", extensions: ["json"] }],
    });
    if (result.canceled || !result.filePath) return { canceled: true };
    await writeFile(result.filePath, request.contents, "utf8");
    return { canceled: false, name: basename(result.filePath) };
  });
  ipcMain.handle("desktop:save-png-file", async (event, request: { suggestedName?: unknown; dataUrl?: unknown }) => {
    assertTrustedSender(event);
    if (typeof request?.dataUrl !== "string" || request.dataUrl.length > 44 * 1024 * 1024 || !/^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(request.dataUrl)) {
      throw new Error("待保存 PNG 无效或超过 32 MiB。");
    }
    const bytes = Buffer.from(request.dataUrl.slice("data:image/png;base64,".length), "base64");
    if (!bytes.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) throw new Error("PNG 文件头无效。");
    const fileName = basename(String(request.suggestedName || "analysis_result.png")).replace(/[<>:"/\\|?*\x00-\x1f]/g, "_");
    const result = await dialog.showSaveDialog({ title: "导出科研图", defaultPath: fileName, filters: [{ name: "PNG 图像", extensions: ["png"] }] });
    if (result.canceled || !result.filePath) return { canceled: true };
    await writeFile(result.filePath, bytes);
    return { canceled: false, name: basename(result.filePath) };
  });
  ipcMain.handle("desktop:select-complex-field-file", async (event) => {
    assertTrustedSender(event);
    const selection = await dialog.showOpenDialog({
      title: "选择光纤复场文件", properties: ["openFile"],
      filters: [{ name: "复场数据", extensions: ["npy", "npz", "csv"] }],
    });
    const path = selection.filePaths[0];
    return selection.canceled || !path ? null : { path, name: basename(path) };
  });
  ipcMain.handle("desktop:api-request", async (event, request: ApiRequest) => {
    assertTrustedSender(event);
    return requestLocalApi(request);
  });
  ipcMain.on("desktop:api-abort", (event, requestId: string) => {
    assertTrustedSender(event);
    if (typeof requestId === "string") {
      apiControllers.get(requestId)?.abort();
    }
  });
}

function assertTrustedSender(event: Electron.IpcMainInvokeEvent | Electron.IpcMainEvent): void {
  const frame = event.senderFrame;
  if (!frame || frame !== event.sender.mainFrame || !isTrustedRendererUrl(frame.url)) {
    throw new Error("拒绝来自非受信任 Renderer 的 IPC 请求。");
  }
  if (!DEV_RENDERER_URL) {
    if (new URL(frame.url).pathname !== "/index.html") {
      throw new Error("拒绝来自应用外部页面的 IPC 请求。");
    }
  }
}

function isAllowedDevRendererUrl(value: string | undefined): value is string {
  if (!value) {
    return false;
  }
  try {
    const url = new URL(value);
    return url.origin === "http://127.0.0.1:5173"
      && url.pathname === "/"
      && url.username === ""
      && url.password === ""
      && url.search === ""
      && url.hash === "";
  } catch {
    return false;
  }
}

async function requestLocalApi(request: ApiRequest): Promise<ApiResponse> {
  if (!request || typeof request !== "object" || typeof request.path !== "string") {
    throw new Error("API 请求格式无效。");
  }
  if (!request.path.startsWith("/api/v1/") || request.path.startsWith("//")) {
    throw new Error("仅允许访问本地 /api/v1/ 接口。");
  }

  const url = new URL(request.path, API_ORIGIN);
  if (url.origin !== API_ORIGIN || !url.pathname.startsWith("/api/v1/")) {
    throw new Error("API 请求目标不在本机后端白名单内。");
  }

  const method = String(request.method ?? "GET").toUpperCase();
  if (!ALLOWED_METHODS.has(method)) {
    throw new Error(`不允许的 API 方法：${method}`);
  }

  const requestId = validRequestId(request.requestId) ? request.requestId : crypto.randomUUID();
  const timeoutMs = Math.max(250, Math.min(Number(request.timeoutMs) || 15_000, 120_000));
  const controller = new AbortController();
  apiControllers.set(requestId, controller);
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const started = performance.now();

  try {
    const body = request.body === undefined || method === "GET"
      ? undefined
      : serializeApiBody(request.path, request.body);
    if (body && Buffer.byteLength(body, "utf8") > 5 * 1024 * 1024) {
      throw new Error("单次 API 请求的 JSON 内容不能超过 5 MiB。");
    }

    const response = await fetch(url, {
      method,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
      },
      body,
      signal: controller.signal,
    });
    const raw = await response.text();
    let payload: unknown;
    try {
      payload = raw ? JSON.parse(raw) : null;
    } catch {
      payload = { message: raw.slice(0, 1_000) };
    }

    const responseRequestId = response.headers.get("X-Request-ID") ?? requestId;
    const data = payload && typeof payload === "object" && "data" in payload ? payload.data : undefined;
    const jobId = data && typeof data === "object" && "job_id" in data && typeof data.job_id === "string" ? data.job_id : undefined;
    writeDiagnostic("main", "api-request", { request_id: responseRequestId, method, route: url.pathname,
      status: response.status, elapsed_ms: Math.round((performance.now() - started) * 1000) / 1000, job_id: jobId });
    return {
      status: response.status,
      ok: response.ok,
      requestId: responseRequestId,
      body: payload,
    };
  } catch (error) {
    writeDiagnostic("main", "api-request", { request_id: requestId, method, route: url.pathname,
      status: 0, elapsed_ms: Math.round((performance.now() - started) * 1000) / 1000,
      error_name: error instanceof Error ? error.name : "Error" });
    throw error;
  } finally {
    clearTimeout(timeout);
    apiControllers.delete(requestId);
  }
}

async function serveRenderer(request: Request, rendererRoot: string): Promise<Response> {
  const url = new URL(request.url);
  if (url.hostname !== APP_HOST || request.method !== "GET") {
    return new Response("Not found", { status: 404 });
  }

  let pathname: string;
  try {
    pathname = decodeURIComponent(url.pathname);
  } catch {
    return new Response("Bad path", { status: 400 });
  }
  const relativePath = pathname.replace(/^[/\\]+/, "") || "index.html";
  const filePath = resolve(rendererRoot, relativePath);
  const relativePathFromRoot = relative(rendererRoot, filePath);
  if (relativePathFromRoot.startsWith("..") || isAbsolute(relativePathFromRoot)) {
    return new Response("Forbidden", { status: 403 });
  }

  try {
    const bytes = await readFile(filePath);
    if (extname(filePath) === ".html") writeDiagnostic("main", "renderer-resource", { path: relativePath, status: 200 });
    return new Response(bytes, {
      headers: {
        "Cache-Control": "no-cache",
        "Content-Type": CONTENT_TYPES[extname(filePath).toLowerCase()] ?? "application/octet-stream",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    writeDiagnostic("main", "renderer-resource", { path: relativePath, status: 404 });
    return new Response("Not found", { status: 404 });
  }
}

function validRequestId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9._:-]{1,128}$/.test(value);
}

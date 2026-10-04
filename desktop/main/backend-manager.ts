import { spawn, type ChildProcess } from "node:child_process";
import { createWriteStream, existsSync, mkdirSync, type WriteStream } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { app } from "electron";
import type { BackendStatus } from "../bridge-contract.js";

const API_HEALTH_URL = "http://127.0.0.1:8000/api/v1/health";
const START_TIMEOUT_MS = 45_000;
const HEALTH_INTERVAL_MS = 400;

export class BackendManager {
  readonly logsDirectory: string;

  private child: ChildProcess | null = null;
  private currentStatus: BackendStatus = {
    state: "checking",
    message: "正在检查 Python 后端…",
    owned: false,
  };
  private startup: Promise<BackendStatus> | null = null;
  private stopping = false;
  private logStream: WriteStream | null = null;
  private recentOutput = "";
  private healthTimer: ReturnType<typeof setInterval> | null = null;
  private probingHealth = false;
  private healthFailures = 0;
  private lifecycleVersion = 0;

  constructor(private readonly onStatus: (status: BackendStatus) => void) {
    this.logsDirectory = join(app.getPath("userData"), "logs");
  }

  getStatus(): BackendStatus {
    return { ...this.currentStatus };
  }

  start(): Promise<BackendStatus> {
    if (this.stopping) return Promise.resolve(this.getStatus());
    if (this.currentStatus.state === "connected") {
      return Promise.resolve(this.getStatus());
    }
    if (this.startup) {
      return this.startup;
    }

    const version = this.lifecycleVersion;
    this.startup = this.startBackend(version).catch((error: unknown) => {
      if (!this.isCurrentStartup(version)) return this.getStatus();
      this.publish("error", `启动 Python 后端失败：${messageOf(error)}`, this.hasLiveChild());
      return this.getStatus();
    });
    void this.startup.then(() => { this.startup = null; });
    return this.startup;
  }

  async stop(): Promise<void> {
    this.lifecycleVersion += 1;
    this.stopping = true;
    if (this.healthTimer) clearInterval(this.healthTimer);
    this.healthTimer = null;
    const child = this.child;
    if (!child || child.exitCode !== null) {
      this.child = null;
      this.closeLogStream();
      this.stopping = false;
      this.publish("stopped", "本次后端连接已关闭。", false);
      return;
    }

    this.publish("stopping", "正在关闭本次启动的 Python 后端…", true);
    await this.terminateProcessTree(child);
    this.child = null;
    this.closeLogStream();
    this.stopping = false;
    this.publish("stopped", "Python 后端已关闭。", false);
  }

  private async startBackend(version: number): Promise<BackendStatus> {
    this.publish("checking", "正在检查 http://127.0.0.1:8000…", this.hasLiveChild());
    const healthy = await this.isHealthy();
    if (!this.isCurrentStartup(version)) return this.getStatus();
    if (healthy) {
      this.publish("connected", "已连接到本机 FastAPI 后端。", this.hasLiveChild());
      return this.getStatus();
    }
    // A temporarily unresponsive owned backend may still be computing. Retrying
    // must preserve that process and its jobs, rather than overwrite its handle.
    const existing = this.child;
    if (existing && this.hasLiveChild()) {
      this.publish("starting", "正在等待现有 Python 后端重新响应…", true);
      const deadline = Date.now() + START_TIMEOUT_MS;
      while (this.isCurrentStartup(version) && Date.now() < deadline && existing.exitCode === null && existing.signalCode === null) {
        const healthy = await this.isHealthy();
        if (!this.isCurrentStartup(version)) return this.getStatus();
        if (healthy) {
          this.publish("connected", "Python 后端已重新连接。", true);
          return this.getStatus();
        }
        await delay(HEALTH_INTERVAL_MS);
      }
      if (!this.isCurrentStartup(version)) return this.getStatus();
      this.publish("error", this.hasLiveChild()
        ? "后台进程仍在运行，但暂时无法连接。请稍后重新连接或查看日志。"
        : "Python 后端已退出，请重新连接或查看日志。", this.hasLiveChild());
      return this.getStatus();
    }

    const backendRoot = app.isPackaged
      ? join(process.resourcesPath, "backend")
      : app.getAppPath();
    const backendScript = resolve(backendRoot, "desktop", "backend_bootstrap.py");
    const python = app.isPackaged
      ? join(process.resourcesPath, "python", "python.exe")
      : process.env.OPTICAL_PYTHON_EXECUTABLE || (process.platform === "win32" ? "python" : "python3");
    const nativeDll = join(backendRoot, "native", "build", "optical_native.dll");
    const requiredResources = app.isPackaged ? [backendScript, python, nativeDll] : [backendScript];
    const missingResource = requiredResources.find((path) => !existsSync(path));
    if (missingResource) {
      this.publish(
        "error",
        `未找到后端运行资源：${missingResource}。请重新安装或重新构建应用。`,
        false,
      );
      return this.getStatus();
    }

    const backendEnv: NodeJS.ProcessEnv = { ...process.env, PYTHONPATH: backendRoot };
    if (app.isPackaged) {
      const dataRoot = process.env.USER_DATA_DIR || join(app.getPath("userData"), "backend");
      Object.assign(backendEnv, {
        APP_ENV: "production",
        USER_DATA_DIR: dataRoot,
        OPTICAL_NATIVE_DLL: nativeDll,
        PYTHONNOUSERSITE: "1",
        MPLCONFIGDIR: join(dataRoot, "cache", "matplotlib"),
        NUMBA_CACHE_DIR: join(dataRoot, "cache", "numba"),
        PATH: `${dirname(python)};${join(dirname(python), "DLLs")};${process.env.PATH || ""}`,
      });
      delete backendEnv.PYTHONHOME;
    }
    this.recentOutput = "";
    this.openLogStream(join(this.logsDirectory, "backend.log"));
    this.publish("starting", `正在启动 Python 后端（${python}）…`, false);

    try {
      this.child = spawn(python, app.isPackaged ? ["-I", "-B", "-X", "utf8", backendScript] : [backendScript], {
        cwd: backendRoot,
        env: backendEnv,
        windowsHide: true,
        detached: process.platform !== "win32",
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (error) {
      this.publish("error", `启动 Python 后端失败：${messageOf(error)}`, false);
      return this.getStatus();
    }

    const child = this.child;
    let spawnFailure: Error | null = null;
    child.stdout?.on("data", (chunk: Buffer) => this.writeLog("stdout", chunk));
    child.stderr?.on("data", (chunk: Buffer) => this.writeLog("stderr", chunk));
    child.once("error", (error) => {
      spawnFailure = error;
      this.recentOutput += `${error.message}\n`;
    });
    child.once("exit", (code, signal) => {
      if (this.child !== child) return;
      this.child = null;
      if (this.stopping || spawnFailure) {
        return;
      }
      const portConflict = /address already in use|10048|EADDRINUSE/i.test(this.recentOutput);
      const reason = portConflict
        ? "端口 8000 已被其他进程占用。请关闭占用进程后重试。"
        : `Python 后端意外退出（code=${String(code)}, signal=${String(signal)}）。请查看后端日志。`;
      this.publish("error", reason, false);
    });

    const deadline = Date.now() + START_TIMEOUT_MS;
    while (this.isCurrentStartup(version) && Date.now() < deadline) {
      if (spawnFailure) {
        break;
      }
      if (child.exitCode !== null || child.signalCode !== null) {
        break;
      }
      const healthy = await this.isHealthy();
      if (!this.isCurrentStartup(version)) return this.getStatus();
      if (healthy) {
        this.publish("connected", "Python 后端已就绪。", true);
        return this.getStatus();
      }
      if (spawnFailure) {
        break;
      }
      await delay(HEALTH_INTERVAL_MS);
    }
    if (!this.isCurrentStartup(version)) return this.getStatus();

    const exitedEarly = child.exitCode !== null || child.signalCode !== null;
    if (child.exitCode === null && child.signalCode === null) {
      await this.terminateProcessTree(child);
    }
    if (!this.isCurrentStartup(version)) return this.getStatus();
    this.child = null;
    this.closeLogStream();
    if (spawnFailure) {
      this.publish("error", `启动 Python 后端失败：${messageOf(spawnFailure)}`, false);
      return this.getStatus();
    }
    const portConflict = /address already in use|10048|EADDRINUSE/i.test(this.recentOutput);
    this.publish(
      "error",
      portConflict
        ? "端口 8000 已被其他进程占用。请关闭占用进程后重试。"
        : exitedEarly
          ? `Python 后端启动时退出（code=${String(child.exitCode)}, signal=${String(child.signalCode)}）。请查看后端日志。`
          : "Python 后端在 45 秒内没有通过健康检查。请查看后端日志。",
      false,
    );
    return this.getStatus();
  }

  private async isHealthy(): Promise<boolean> {
    try {
      const response = await fetch(API_HEALTH_URL, { signal: AbortSignal.timeout(1_200) });
      const payload = await response.json() as {
        code?: string;
        data?: { status?: string };
      };
      return response.ok && payload.code === "OK" && payload.data?.status === "healthy";
    } catch {
      return false;
    }
  }

  private openLogStream(logPath: string): void {
    try {
      mkdirSync(dirname(logPath), { recursive: true });
      this.logStream = createWriteStream(logPath, { flags: "a", encoding: "utf8" });
      this.logStream.on("error", () => { this.logStream = null; });
      this.logStream.write(`\n--- backend start ${new Date().toISOString()} ---\n`);
    } catch {
      this.logStream = null;
    }
  }

  private writeLog(stream: "stdout" | "stderr", chunk: Buffer): void {
    const text = chunk.toString("utf8");
    this.recentOutput = `${this.recentOutput}${text}`.slice(-16_384);
    this.logStream?.write(`[${new Date().toISOString()}] [${stream}] ${text}`);
  }

  private closeLogStream(): void {
    this.logStream?.end();
    this.logStream = null;
  }

  private async terminateProcessTree(child: ChildProcess): Promise<void> {
    if (child.pid === undefined || child.exitCode !== null) {
      return;
    }
    if (process.platform === "win32") {
      await new Promise<void>((resolveExit) => {
        const killer = spawn("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], {
          windowsHide: true,
          stdio: "ignore",
        });
        killer.once("error", () => resolveExit());
        killer.once("exit", () => resolveExit());
      });
      return;
    }

    try {
      process.kill(-child.pid, "SIGTERM");
    } catch {
      child.kill("SIGTERM");
    }
    await waitForExit(child, 3_000);
    if (child.exitCode === null) {
      try {
        process.kill(-child.pid, "SIGKILL");
      } catch {
        child.kill("SIGKILL");
      }
    }
  }

  private publish(state: BackendStatus["state"], message: string, owned: boolean): void {
    this.currentStatus = { state, message, owned };
    if (state === "connected") {
      this.healthFailures = 0;
      if (!this.healthTimer) {
        this.healthTimer = setInterval(() => void this.checkConnection(), 2_000);
        this.healthTimer.unref();
      }
    }
    this.onStatus(this.getStatus());
  }

  private hasLiveChild(): boolean {
    return !!this.child && this.child.exitCode === null && this.child.signalCode === null;
  }

  private isCurrentStartup(version: number): boolean {
    return version === this.lifecycleVersion && !this.stopping;
  }

  private async checkConnection(): Promise<void> {
    if (this.probingHealth || this.stopping || this.currentStatus.state !== "connected") return;
    this.probingHealth = true;
    try {
      const healthy = await this.isHealthy();
      if (this.stopping || this.currentStatus.state !== "connected") return;
      this.healthFailures = healthy ? 0 : this.healthFailures + 1;
      if (this.healthFailures >= 2) {
        this.publish("error", this.hasLiveChild()
          ? "暂时无法连接后端，后台进程仍在运行。请重新连接或查看日志。"
          : "后端连接已断开。请重新连接或查看日志。", this.hasLiveChild());
      }
    } finally { this.probingHealth = false; }
  }
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, ms));
}

function waitForExit(child: ChildProcess, timeoutMs: number): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve();
  }
  return new Promise((resolveExit) => {
    const timeout = setTimeout(resolveExit, timeoutMs);
    child.once("exit", () => {
      clearTimeout(timeout);
      resolveExit();
    });
  });
}

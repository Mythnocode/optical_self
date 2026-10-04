import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build as buildBundle } from "esbuild";

const projectRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const viteUrl = "http://127.0.0.1:5173/";

await buildBundle({
  entryPoints: {
    main: resolve(projectRoot, "desktop/main/main.ts"),
    preload: resolve(projectRoot, "desktop/preload/index.ts"),
  },
  outdir: resolve(projectRoot, "desktop-dist"),
  entryNames: "[name]",
  outExtension: { ".js": ".cjs" },
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node22",
  external: ["electron"],
  sourcemap: true,
});

const vite = spawn(
  process.execPath,
  [resolve(projectRoot, "node_modules/vite/bin/vite.js"), "--config", "frontend_web/vite.config.ts", "--host", "127.0.0.1"],
  { cwd: projectRoot, stdio: "inherit", windowsHide: true },
);
const electron = resolve(projectRoot, "node_modules/electron/cli.js");
let appProcess;
let stopping = false;

function stopProcess(child, signal = "SIGTERM") {
  if (!child || child.exitCode !== null || child.killed) {
    return;
  }
  child.kill(signal);
}

async function waitForRenderer() {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (vite.exitCode !== null) {
      throw new Error(`Vite exited before it became ready (code ${vite.exitCode}).`);
    }
    try {
      const response = await fetch(viteUrl, { signal: AbortSignal.timeout(1_000) });
      if (response.ok) {
        return;
      }
    } catch {
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 250));
    }
  }
  throw new Error("Vite did not become ready within 30 seconds.");
}

async function stopChildren() {
  if (stopping) {
    return;
  }
  stopping = true;
  stopProcess(appProcess);
  stopProcess(vite);
}

process.on("SIGINT", () => void stopChildren());
process.on("SIGTERM", () => void stopChildren());

try {
  await waitForRenderer();
  appProcess = spawn(process.execPath, [electron, "."], {
    cwd: projectRoot,
    stdio: "inherit",
    windowsHide: true,
    env: { ...process.env, OPTICAL_RENDERER_URL: viteUrl },
  });
  const exitCode = await new Promise((resolveExit, reject) => {
    appProcess.once("error", reject);
    appProcess.once("exit", (code, signal) => {
      if (signal && !stopping) {
        reject(new Error(`Electron stopped by ${signal}.`));
        return;
      }
      resolveExit(code ?? 0);
    });
  });
  process.exitCode = exitCode;
} finally {
  await stopChildren();
}

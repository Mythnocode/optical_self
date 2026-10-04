import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build as buildBundle } from "esbuild";

const projectRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const outputDirectory = resolve(projectRoot, "desktop-dist");

await buildBundle({
  entryPoints: {
    main: resolve(projectRoot, "desktop/main/main.ts"),
    preload: resolve(projectRoot, "desktop/preload/index.ts"),
  },
  outdir: outputDirectory,
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
  [resolve(projectRoot, "node_modules/vite/bin/vite.js"), "build", "--config", "frontend_web/vite.config.ts"],
  { cwd: projectRoot, stdio: "inherit", windowsHide: true },
);

const exitCode = await new Promise((resolveExit, reject) => {
  vite.once("error", reject);
  vite.once("exit", (code, signal) => {
    if (signal) {
      reject(new Error(`Vite build stopped by ${signal}.`));
      return;
    }
    resolveExit(code ?? 1);
  });
});

if (exitCode !== 0) {
  process.exitCode = exitCode;
}

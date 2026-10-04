import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { app } from "electron";

const recent: Array<{ time: string; channel: string; event: string; data: unknown }> = [];

export function recentDiagnostics(): typeof recent {
  return recent.slice();
}

export function writeDiagnostic(channel: "main" | "renderer", event: string, data: unknown = null): void {
  const entry = { time: new Date().toISOString(), channel, event, data };
  recent.push(entry);
  if (recent.length > 60) recent.shift();
  try {
    const directory = join(app.getPath("userData"), "logs");
    mkdirSync(directory, { recursive: true });
    appendFileSync(join(directory, `${channel}.log`), `${JSON.stringify(entry)}\n`, "utf8");
  } catch {
    // Diagnostics must not prevent the app from starting or shutting down.
  }
}

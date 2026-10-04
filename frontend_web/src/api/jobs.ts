import { apiRequest, type ApiEnvelope } from "./http.js";

export type JobTerminalState = "completed" | "failed" | "cancelled";
export type JobState = "queued" | "running" | JobTerminalState | string;

export interface JobStatus {
  job_id: string;
  job_type?: string;
  status: JobState;
  progress?: number;
  stage?: string;
  completed_items?: number;
  total_items?: number;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  result_available?: boolean;
  retry_available?: boolean;
  retry_of?: string | null;
  last_activity_at?: string | null;
  message?: string;
  result_version?: number;
  partial_result_available?: boolean;
  metrics?: Record<string, number | string | null>;
  error?: { code?: string; message?: string } | string | null;
  [key: string]: unknown;
}

export interface JobListQuery {
  limit?: number;
  offset?: number;
  status?: string;
  jobType?: string;
}

export type JobResultSummary = Record<string, unknown>;

export interface JobEvent {
  type: string;
  job_id?: string;
  status?: string;
  progress?: number;
  stage?: string;
  result_version?: number;
  metrics?: Record<string, number | string | null>;
  error?: { code?: string; message?: string } | string;
}

export async function submitSimulation(payload: unknown): Promise<string> {
  const response = await apiRequest<{ job_id: string }>("/api/v1/simulation/jobs", {
    method: "POST",
    body: payload,
  });
  if (!response.data?.job_id) {
    throw new Error("Simulation API did not return a job_id.");
  }
  return response.data.job_id;
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const response = await apiRequest<JobStatus>(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
  return response.data;
}

export async function getJobResult<T = unknown>(jobId: string): Promise<T> {
  const response = await apiRequest<T>(`/api/v1/jobs/${encodeURIComponent(jobId)}/result`);
  return response.data;
}

export async function cancelJob(jobId: string): Promise<void> {
  await apiRequest(`/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
}

export async function retryJob(jobId: string): Promise<JobStatus> {
  const response = await apiRequest<JobStatus>(`/api/v1/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
  return response.data;
}

export async function getJobResultSummary(jobId: string): Promise<JobResultSummary> {
  const response = await apiRequest<JobResultSummary>(`/api/v1/jobs/${encodeURIComponent(jobId)}/result-summary`);
  return response.data;
}

export async function listJobs(query: number | JobListQuery = 20): Promise<JobStatus[]> {
  const options = typeof query === "number" ? { limit: query } : query;
  const params = new URLSearchParams({
    limit: String(Math.max(1, Math.min(options.limit ?? 20, 200))),
    offset: String(Math.max(0, options.offset ?? 0)),
  });
  if (options.status) params.set("status", options.status);
  if (options.jobType) params.set("job_type", options.jobType);
  const response = await apiRequest<JobStatus[]>(`/api/v1/jobs?${params.toString()}`, { timeoutMs: 5_000 });
  return response.data;
}

export class JobSocket {
  private socket: WebSocket | null = null;
  private readonly jobIds = new Set<string>();
  private reconnectTimer: number | null = null;
  private attempts = 0;
  private disposed = false;

  constructor(private readonly onEvent: (event: JobEvent) => void) {}

  subscribe(jobId: string): void {
    this.jobIds.add(jobId);
    this.connect();
    this.sendSubscriptions();
  }

  unsubscribe(jobId: string): void {
    this.jobIds.delete(jobId);
    if (this.jobIds.size === 0) {
      this.socket?.close();
      this.socket = null;
      return;
    }
    this.sendSubscriptions();
  }

  dispose(): void {
    this.disposed = true;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
    }
    this.socket?.close();
    this.socket = null;
    this.jobIds.clear();
  }

  private connect(): void {
    if (this.disposed || this.socket || this.jobIds.size === 0) {
      return;
    }
    const url = import.meta.env.DEV
      ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/jobs`
      : "ws://127.0.0.1:8000/ws/jobs";
    const socket = new WebSocket(url);
    this.socket = socket;
    socket.addEventListener("open", () => {
      this.attempts = 0;
      this.sendSubscriptions();
    });
    socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(String(event.data)) as JobEvent;
        if (payload.type !== "ping" && payload.type !== "error") {
          this.onEvent(payload);
        }
      } catch {
        console.warn("Ignored an invalid job event frame.");
      }
    });
    socket.addEventListener("close", () => {
      if (this.socket === socket) {
        this.socket = null;
      }
      this.scheduleReconnect();
    });
    socket.addEventListener("error", () => socket.close());
  }

  private sendSubscriptions(): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ action: "subscribe", job_ids: [...this.jobIds] }));
    }
  }

  private scheduleReconnect(): void {
    if (this.disposed || this.jobIds.size === 0 || this.reconnectTimer !== null) {
      return;
    }
    const delayMs = Math.min(500 * 2 ** this.attempts, 15_000);
    this.attempts += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delayMs);
  }
}

export function unwrapJobStatus(response: ApiEnvelope<JobStatus>): JobStatus {
  return response.data;
}

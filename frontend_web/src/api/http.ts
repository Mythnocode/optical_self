import type { ApiMethod, ApiRequest, ApiResponse } from "../../../desktop/bridge-contract.js";
import { serializeApiBody } from "../../../desktop/api-json.js";
import { recordRequestDiagnostic } from "./diagnostics.js";

export interface ApiEnvelope<T> {
  code: string;
  message: string;
  data: T;
  error: null | { code: string; stage?: string; message: string; retryable?: boolean };
  request_id: string | null;
}

export interface ApiRequestOptions {
  method?: ApiMethod;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
  retry?: boolean;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId: string,
    readonly stage?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<ApiEnvelope<T>> {
  if (!path.startsWith("/api/v1/") || path.startsWith("//")) {
    throw new Error("API 路径必须位于 /api/v1/ 下。");
  }
  if (options.signal?.aborted) {
    throw options.signal.reason ?? new DOMException("Request cancelled.", "AbortError");
  }

  const method = options.method ?? "GET";
  const requestId = createRequestId();
  const timeoutMs = Math.max(250, Math.min(options.timeoutMs ?? 15_000, 120_000));
  const request: ApiRequest = {
    path,
    method,
    body: options.body,
    requestId,
    timeoutMs,
  };
  const maxAttempts = options.retry !== false && method === "GET" ? 2 : 1;
  let lastError: unknown;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      const response = await sendRequest(request, options.signal, timeoutMs);
      const envelope = isApiEnvelope<T>(response.body) ? response.body : null;
      if (!response.ok) {
        const error = envelope?.error;
        const hasEnvelope = envelope !== null;
        const message = error?.message
          || envelope?.message
          || (!hasEnvelope
            ? "本机 FastAPI 后端没有返回有效响应。请确认服务正在运行，并监听 127.0.0.1:8000。"
            : `本地 API 请求失败 (${response.status})`);
        const code = error?.code || envelope?.code || "BACKEND_UNAVAILABLE";
        if (attempt + 1 < maxAttempts && [502, 503, 504].includes(response.status)) {
          await delay(180);
          continue;
        }
        throw new ApiError(message, response.status, code, response.requestId, error?.stage);
      }
      if (!envelope) {
        throw new ApiError(
          "本机 API 返回了无效响应。请检查 FastAPI 的响应封套。",
          response.status,
          "INVALID_API_RESPONSE",
          response.requestId,
        );
      }
      if (import.meta.env.DEV) {
        console.debug("API response", { method, path, requestId, status: response.status });
      }
      return envelope;
    } catch (error) {
      if (options.signal?.aborted) {
        throw options.signal.reason ?? error;
      }
      lastError = isFetchFailure(error)
        ? new ApiError(
            "无法连接本机 FastAPI 后端。请确认服务正在运行，并监听 127.0.0.1:8000。",
            0,
            "BACKEND_UNAVAILABLE",
            requestId,
          )
        : error;
      if (error instanceof ApiError || attempt + 1 >= maxAttempts) {
        throw lastError;
      }
      await delay(180);
    }
  }

  throw lastError instanceof Error ? lastError : new Error("本机 API 请求失败。");
}

export async function apiRaw<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  if (!path.startsWith("/api/v1/") || path.startsWith("//")) {
    throw new Error("API 路径必须位于 /api/v1/ 下。");
  }
  if (options.signal?.aborted) {
    throw options.signal.reason ?? new DOMException("Request cancelled.", "AbortError");
  }

  const method = options.method ?? "GET";
  const requestId = createRequestId();
  const timeoutMs = Math.max(250, Math.min(options.timeoutMs ?? 15_000, 120_000));
  const request: ApiRequest = { path, method, body: options.body, requestId, timeoutMs };
  try {
    const response = await sendRequest(request, options.signal, timeoutMs);
    if (!response.ok) {
      const envelope = isApiEnvelope<unknown>(response.body) ? response.body : null;
      const error = envelope?.error;
      throw new ApiError(
        error?.message || envelope?.message || `本地 API 请求失败 (${response.status})`,
        response.status,
        error?.code || envelope?.code || "BACKEND_UNAVAILABLE",
        response.requestId,
        error?.stage,
      );
    }
    return response.body as T;
  } catch (error) {
    if (options.signal?.aborted) {
      throw options.signal.reason ?? error;
    }
    if (isFetchFailure(error)) {
      throw new ApiError(
        "无法连接本机 FastAPI 后端。请确认服务正在运行，并监听 127.0.0.1:8000。",
        0,
        "BACKEND_UNAVAILABLE",
        requestId,
      );
    }
    throw error;
  }
}

async function sendRequest(
  request: ApiRequest,
  signal: AbortSignal | undefined,
  timeoutMs: number,
): Promise<ApiResponse> {
  const started = performance.now();
  const bridge = window.opticalDesktop;
  if (bridge) {
    const abort = () => bridge.abortRequest(request.requestId ?? "");
    signal?.addEventListener("abort", abort, { once: true });
    const timeout = window.setTimeout(abort, timeoutMs);
    try {
      const response = await bridge.request(request);
      recordAttempt(request, started, response);
      return response;
    } catch (error) {
      recordAttempt(request, started, undefined, error);
      throw error;
    } finally {
      window.clearTimeout(timeout);
      signal?.removeEventListener("abort", abort);
    }
  }

  const controller = new AbortController();
  const abortFromCaller = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeout = window.setTimeout(() => controller.abort(new DOMException("Request timed out.", "TimeoutError")), timeoutMs);
  try {
    const response = await fetch(request.path, {
      method: request.method,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Request-ID": request.requestId ?? createRequestId(),
      },
      body: request.body === undefined || request.method === "GET" ? undefined : serializeApiBody(request.path, request.body),
      signal: controller.signal,
    });
    const rawBody = await response.text();
    let body: unknown = null;
    if (rawBody) {
      try {
        body = JSON.parse(rawBody) as unknown;
      } catch {
        body = { message: rawBody.slice(0, 1_000) };
      }
    }
    const result: ApiResponse = {
      status: response.status,
      ok: response.ok,
      requestId: response.headers.get("X-Request-ID") ?? request.requestId ?? "",
      body,
    };
    recordAttempt(request, started, result);
    return result;
  } catch (error) {
    recordAttempt(request, started, undefined, error);
    throw error;
  } finally {
    window.clearTimeout(timeout);
    signal?.removeEventListener("abort", abortFromCaller);
  }
}

function recordAttempt(request: ApiRequest, started: number, response?: ApiResponse, error?: unknown): void {
  const body = response?.body;
  const envelope = body && typeof body === 'object' ? body as Record<string, unknown> : undefined;
  const data = envelope?.data && typeof envelope.data === 'object' ? envelope.data as Record<string, unknown> : undefined;
  recordRequestDiagnostic({ time: new Date().toISOString(), request_id: response?.requestId ?? request.requestId ?? '',
    method: request.method ?? 'GET', route: request.path.split('?')[0]!, status: response?.status ?? 0,
    elapsed_ms: Math.round((performance.now() - started) * 1000) / 1000,
    code: typeof envelope?.code === 'string' ? envelope.code : undefined,
    job_id: typeof data?.job_id === 'string' ? data.job_id : undefined,
    error_name: error instanceof Error ? error.name : undefined });
}

function isApiEnvelope<T>(value: unknown): value is ApiEnvelope<T> {
  return value !== null
    && typeof value === "object"
    && "code" in value
    && typeof value.code === "string";
}

function isFetchFailure(error: unknown): error is TypeError {
  return error instanceof TypeError && /fetch|network|connect/i.test(error.message);
}

function createRequestId(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolveDelay) => window.setTimeout(resolveDelay, ms));
}

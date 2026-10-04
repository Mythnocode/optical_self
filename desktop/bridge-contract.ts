export type BackendState = "checking" | "starting" | "connected" | "error" | "stopping" | "stopped";

export interface BackendStatus {
  state: BackendState;
  message: string;
  owned: boolean;
}

export type ApiMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface ApiRequest {
  path: string;
  method?: ApiMethod;
  body?: unknown;
  requestId?: string;
  timeoutMs?: number;
}

export interface ApiResponse<T = unknown> {
  status: number;
  ok: boolean;
  requestId: string;
  body: T;
}

export interface LocalFileSelection {
  path: string;
  name: string;
}

export interface TextFileSaveRequest {
  suggestedName: string;
  contents: string;
}

export interface TextFileSaveResult {
  canceled: boolean;
  name?: string;
}

export interface DesktopBridge {
  getBackendStatus(): Promise<BackendStatus>;
  startBackend(): Promise<BackendStatus>;
  onBackendStatus(listener: (status: BackendStatus) => void): () => void;
  request<T = unknown>(request: ApiRequest): Promise<ApiResponse<T>>;
  abortRequest(requestId: string): void;
  selectTabularDatasetFile(): Promise<LocalFileSelection | null>;
  selectComplexFieldFile(): Promise<LocalFileSelection | null>;
  openProjectFile(): Promise<{ name: string; contents: string } | null>;
  saveTextFile(request: TextFileSaveRequest): Promise<TextFileSaveResult>;
  savePngFile(request: { suggestedName: string; dataUrl: string }): Promise<TextFileSaveResult>;
  openBackendLogs(): Promise<void>;
  copyDiagnostics(): Promise<void>;
}

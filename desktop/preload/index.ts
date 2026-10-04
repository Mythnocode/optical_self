import { contextBridge, ipcRenderer } from "electron";
import type { BackendStatus, DesktopBridge, LocalFileSelection, TextFileSaveRequest } from "../bridge-contract.js";

const bridge: DesktopBridge = {
  getBackendStatus: () => ipcRenderer.invoke("desktop:backend-status") as Promise<BackendStatus>,
  startBackend: () => ipcRenderer.invoke("desktop:backend-start") as Promise<BackendStatus>,
  onBackendStatus(listener) {
    const handler = (_event: Electron.IpcRendererEvent, status: BackendStatus) => listener(status);
    ipcRenderer.on("desktop:backend-status-changed", handler);
    return () => ipcRenderer.removeListener("desktop:backend-status-changed", handler);
  },
  request: (request) => ipcRenderer.invoke("desktop:api-request", request),
  abortRequest: (requestId) => ipcRenderer.send("desktop:api-abort", requestId),
  selectTabularDatasetFile: () => ipcRenderer.invoke("desktop:select-tabular-dataset-file") as Promise<LocalFileSelection | null>,
  selectComplexFieldFile: () => ipcRenderer.invoke("desktop:select-complex-field-file") as Promise<LocalFileSelection | null>,
  openProjectFile: () => ipcRenderer.invoke("desktop:open-project-file"),
  saveTextFile: (request: TextFileSaveRequest) => ipcRenderer.invoke("desktop:save-text-file", request),
  savePngFile: (request: { suggestedName: string; dataUrl: string }) => ipcRenderer.invoke("desktop:save-png-file", request),
  openBackendLogs: () => ipcRenderer.invoke("desktop:open-backend-logs") as Promise<void>,
  copyDiagnostics: () => ipcRenderer.invoke("desktop:copy-diagnostics") as Promise<void>,
};

contextBridge.exposeInMainWorld("opticalDesktop", bridge);

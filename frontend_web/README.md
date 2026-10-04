# Optical ML Platform Web Renderer

This is the first incremental migration slice. The existing PySide frontend and all Python calculation packages remain in place.

## Local development

Requirements: Node.js `>=22.12.0`, npm `>=10`, and the project's supported Python environment (`>=3.11,<3.14`) with its existing dependencies installed.

```powershell
npm install
npm run dev
```

`npm run dev` builds the Electron main/preload scripts, starts Vite, then opens Electron. Electron checks `http://127.0.0.1:8000/api/v1/health` and starts `run_backend.py` when a healthy backend is not already listening. Set `OPTICAL_PYTHON_EXECUTABLE` to the full path of the intended Python interpreter when `python` does not resolve to the project environment.

The browser renderer uses Vite's `/api/v1` and `/ws` development proxies. The packaged Electron renderer is served from the restricted `app://renderer` protocol and can request only local `/api/v1/` paths through preload IPC.

`npm run assets:teaching:sync` copies the currently mapped GLBs from the legacy asset directory. It externalizes embedded PNG/JPEG/WebP images into adjacent files in the public directory so Electron and browser renderers load those textures without temporary blob URLs.

## Checks

```powershell
npm run typecheck
npm test
npm run build
```

## Current migration slice

- Electron main/preload with Node integration disabled, context isolation and sandbox enabled.
- Local backend health detection, process lifecycle, process-tree cleanup, and append-only backend logs under Electron's user-data directory.
- Restricted REST IPC, API request IDs, timeout, GET-only retry, and cancellation.
- Vue 3, Router, Pinia, API health/version screen, jobs WebSocket client and status reconciliation store.
- Teaching SceneStore, revision counter, rad/deg boundary, coordinate golden tests, GLB manifest and Three.js selection/transform preview.
- Missing or invalid GLB files fall back to procedural geometry.

The current PoC does not yet call formal Teaching calculations, migrate all platform pages, implement project-file persistence, or package the Python backend for Windows installation.

# JS / Three.js migration baseline

Date: 2026-09-28  
Starting branch: `0914` at `45bcc7a`  
Implementation branch: `js`  
Baseline tag: `migration-baseline-js-20260928`  
Application version: `1.5.6` (`pyproject.toml`)

## Existing migration boundary

- FastAPI is mounted under `/api/v1`; `/api/v1/health`, `/api/v1/version`, `/api/v1/jobs`, and `/ws/jobs` already exist.
- `optical_core`, `optical_runtime`, `machine_learning`, and `teaching_runtime` remain Python-owned.
- Teaching's Python coordinate source is `frontend_pyside/features/teaching_v2/coordinates.py`.
- Render position is `(x, z, -y)`; Teaching pose angles are radians; the mirror render pose includes the existing 45 degree fold convention.
- Existing GLB assets include the Teaching laser, lens, fiber, and breadboard. The first renderer slice copies those four assets into the Vite public directory; the old PySide asset files remain unchanged.

## Python suite baseline

The baseline was captured before changing any Python source.

| Command | Result |
|---|---|
| `pytest -q` | **2 skipped, 30 collection errors** under the `D:\anacondanew` Python 3.10 environment. |
| `py -3.12 -m pytest -q --continue-on-collection-errors` | **197 passed, 6 failed, 3 collection errors** under Python 3.12.4. |

The Python 3.12 run collected the bulk of the suite, but the existing baseline is not green:

- Three collection errors come from tests importing missing names from `frontend_pyside.app.workbench_shell`: `_optimization_status_label`, `_shap_feature_key`, and `RESULT_PLOT_KEYS`.
- Six failures are existing assertions about the 780 nm high-coupling demo value, the legacy Teaching namespace, the video demo bundle ID, a SHAP XZ metric, frozen secondary navigation, and backend-status text.
- The default Python 3.10 environment also has an incompatible NumPy/SciPy combination (NumPy 1.26.4 versus a SciPy build requiring NumPy `>=2.0,<2.8`) and a PySide6 DLL load failure (`0xc0000139`).
- The working Python 3.12 executable on this machine is `D:\python\python3.12\python.exe`; it can import the FastAPI application and start the backend. The Electron launch smoke test must set `OPTICAL_PYTHON_EXECUTABLE` to this interpreter because `python` on `PATH` resolves to the broken 3.10 environment.

These findings are retained as migration baseline debt; this frontend slice does not alter Python calculations, dependencies, or legacy tests.

## Captured golden data

`tests/golden/teaching_coordinates.json` freezes three cases generated directly from the current Python coordinate module: identity-axis pose, oblique pose, and mirror 45 degree fold pose. JS unit tests compare positions and quaternions with `1e-9` tolerance.

## First JS vertical-slice smoke (2026-09-28)

- `npm run typecheck`: passed.
- `npm test`: passed, 3 tests.
- `npm run build`: passed; Vite reports the lazy Three.js route chunk is 689.15 KiB (175.62 KiB gzip).
- `npm audit`: 0 vulnerabilities.
- `npm run dev` with `OPTICAL_PYTHON_EXECUTABLE=D:\python\python3.12\python.exe`: Electron and Vite started; the managed backend returned HTTP 200 for health, version, and jobs. The same preview showed an explicit backend-offline message when port 8000 was unavailable.
- The browser renderer added a laser to the Teaching scene and visually rendered the breadboard texture. The original legacy GLB was preserved; its frontend copy now references the extracted PNG beside the GLB.
- Baseline screenshots from the initial smoke were not saved then. A later parity pass saved the 1280 × 800 legacy Home, Teaching 2D, Simulation lens-data, Model dataset, Optimization variables, and Explainability global-contribution screens under `tests/golden/ui-baseline/`; see `docs/migration/visual-parity.md` for measurements and remaining gaps.

## Phase 0 artifacts and remaining baseline work

- `openapi-baseline.json` freezes the FastAPI 1.5.6 OpenAPI document captured from the working Python 3.12 backend.
- The current coordinate golden covers identity, oblique, and 45 degree mirror-fold poses. A standard Teaching scene and formal Python result snapshot are still pending.
- `teaching-glb-inventory.md` records default-scene transformed AABBs for the complete legacy GLB library. Four of those assets are copied into the first renderer slice; the rest await kind and anchor validation.
- Direct legacy 3D capture, non-default route screenshots, and Simulation/dataset/model/optimization workflow smoke snapshots remain pending.

The Python suite must remain unchanged during the UI migration until its pre-existing failures are triaged in a separate backend/test task.

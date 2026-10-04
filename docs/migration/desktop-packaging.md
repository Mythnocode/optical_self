# Windows desktop packaging

Branch: `js`. The full migration remains in progress.

The subsequent dataset visual corrections (layout, fonts, scrollbar and six Qt
checkbox PNG assets) are in the source and current Web build. The installer
below has not been rebuilt with those corrections; its resource acceptance
describes the earlier diagnostics artifact.

## Latest artifact — diagnostics slice

The subsequent diagnostics slice adds API request timing/correlation, a recovery
dialog and backend connection monitoring. See [backend-diagnostics.md](backend-diagnostics.md).
The install/uninstall and C++ job acceptance below describe the earlier installer;
they are not new acceptance runs for a rebuilt artifact.

Current installer: `dist/desktop/Optical-ML-Platform-1.5.6-x64-Setup.exe`,
378,683,418 bytes, SHA-256
`1f9efa280977be92151fc76f9e8d12f542e966a13621490665a4975f9e68e5f0`, unsigned.
Runtime and renderer resource gates passed for this artifact. The rebuilt runtime
contains 28,073 files / 1,068,338,664 bytes and 54 packages; app.asar SHA-256 is
`e133a261077ccafc03ba317daa22ed7113529fc6542b40a08c0e5914aa7aa00a`.
Automatic approval rejected the subsequent background launch command, without a
specific reason beyond "blocked by policy". No new installed or startup acceptance
is claimed for this hash. Reports are in `tests/golden/backend-diagnostics/`.

## Build

```powershell
$env:OPTICAL_PYTHON_EXECUTABLE = 'D:/python/python3.12/python.exe'
npm run package:win
```

`npm run package:dir` produces the unpacked application for diagnosis. The build
uses Windows x64 CPython 3.12 and the exact dependency closure recorded in
`requirements/desktop-runtime.lock.txt`. It fails if the selected interpreter's
installed versions differ. This lock records the environment used for the actual
migration calculations; it does not replace the original `requirements.txt`.

The selected distributions may be installed in the build interpreter's main or
user site. Each distribution is copied from its own installed wheel record into
the bundle. At runtime, `python312._pth` and `-I -B` isolate the application from
the user's Python environment and prevent writes into installed code directories.
The launcher passes `-X utf8` explicitly: isolation ignores `PYTHONUTF8`, and this
machine otherwise uses GBK for piped Python logs. Spawn workers inherit UTF-8 mode.
Windows multiprocessing workers use the same bundled interpreter and search roots.

The existing `native/build/optical_native.dll` is required. Its SHA-256 is recorded
in the resource manifest and verified after packaging. Dataset generation still
uses the existing native trace adapter, quality gates and precision profiles.

The build copies the Microsoft x64 C++ runtime from Visual Studio's redistributable
directory. `OPTICAL_VC_RUNTIME_DIR` can select an explicit licensed redistributable
directory. DLLs are placed beside the bundled Python executable. Some wheels also
load their own packaged Microsoft DLLs; validation records all loaded copies and
rejects any Microsoft C++ runtime loaded outside the bundled Python directory.

## Contents and checks

- Electron main/preload and the built Vue renderer, in `app.asar`.
- `resources/python`: isolated interpreter, standard library and 54 locked packages.
- `resources/backend`: existing backend, optical/ML runtimes, pure presentation
  modules, resources, teaching assets and the existing native DLL/source.
- `resources/resources-manifest.json`: every runtime file's size and SHA-256,
  package versions, interpreter version and native DLL checksum.

The `afterPack` hook runs `validate-desktop-resources.py` with the actual copied
interpreter. Missing files, changed hashes, dependency mismatches, failed scientific
library imports, missing native tracing or external Microsoft C++ DLLs stop the build.
The renderer gate checks the built desktop entry points and every renderer asset
against the bytes inside `app.asar`, including the lazy chunks and teaching GLBs.
Generated resources are replaced only after staging succeeds, under the workspace's
`build` directory. Empty `.gitkeep` placeholders, Python bytecode caches and the
two unused setuptools ARM64 launcher executables are omitted from this x64 bundle.

## Runtime paths and logs

The packaged application launches `resources/python/python.exe -I -B -X utf8` with
`resources/backend/desktop/backend_bootstrap.py`. Default persistent backend data
and caches live under Electron's user data directory. `USER_DATA_DIR` and
`OPTICAL_DESKTOP_USER_DATA_DIR` allow isolated manual acceptance runs.

Three logs are written in the Electron user data `logs` directory:

- `main.log`: app startup, backend lifecycle and renderer resource failures.
- `renderer.log`: renderer load, warnings/errors and renderer process failures.
- `backend.log`: Python stdout/stderr.

`OPTICAL_DESKTOP_BACKGROUND=1` starts an invisible window for local acceptance.
Normal launches show the application window. Existing healthy local backends are
attached without ownership; only a backend launched by this application is stopped
on normal application quit.

The default 1280 × 800 dimensions now describe the renderer content, matching the
original Qt client size. Electron's default extra menu bar is removed. These window
settings are source-level corrections; the packaged native window has not received
an on-screen visual comparison in this environment.

## Acceptance evidence

See `tests/golden/desktop-packaging/` for the packaged runtime inventory and actual
dataset request/result evidence. The unpacked application started its own isolated
backend and loaded `app://renderer/index.html#/`. Its Windows multiprocessing
workers retained `-I -B`. The final bundle contains 28,073 inventoried files
(1,068,337,249 bytes), plus its manifest.

The repeated actual dataset job `job-ccb892e4ec47` produced
`dataset-e5a6836a6838`: 8 valid samples in 17 attempts, all 17 recorded
`cpp_native`. The other 9 failed the existing optical energy gate. Sample features,
targets, validity, failure messages, splits and convergence flags exactly equal the
earlier development dataset `dataset-0077c0bb0956` for the same input and seed.
Worker computation was 35.497 seconds on this run; this is runtime acceptance, not
a controlled acceleration benchmark.

The final NSIS installer was installed locally into
`build/desktop-installed acceptance` (a path containing a space), with exit code 0.
All 28,073 backend/runtime files and all 60 renderer/desktop files matched their
recorded or built contents after installation. Loaded native and Microsoft C++
DLLs came from the installation. The app and multiprocessing workers used
`-I -B -X utf8`, and the renderer loaded without recorded errors.

The installed application then completed `job-1e69eeb75777` /
`dataset-06ce4efcb92a`: 8 valid samples in 17 attempts, all 17 `cpp_native`,
9 existing energy-gate failures, worker computation 13.288 seconds. The same
sample fields again exactly matched `dataset-0077c0bb0956`. The installer hash,
installed resource checks, process commands, actual job/results and comparison
are retained under `tests/golden/desktop-packaging/installed-*` and `installer.json`.

The first local installation check found that the two unused setuptools ARM64
launchers were absent after installation; that check was not accepted. They are
now explicitly omitted when staging this x64 bundle, and the rebuilt installer
passed the complete installed-file check. Initial installer/check/uninstall records
are retained separately.

The initial packaged job `job-9afc30c91d29` is retained separately: 6 valid in
24 attempts, 14 energy failures and 4 engine errors (including explicit NumPy
allocation failures). Only 20 final samples recorded `cpp_native`; the four failed
engine calls had no backend metadata. Do not count that job as a full successful
dataset generation or assume that every attempt has a native trace record.

The acceptance application was stopped as an owned process tree after both jobs
were terminal; no packaged backend or port-8000 listener remained. This does not
verify normal window-close cleanup or recovery during an active job.

Local runtime checks do not establish clean-machine compatibility; a separate
clean Windows installation remains required by the plan. The NSIS installer is
not code signed. Full migration, all-page visual identity, high-DPI checks and
normal lifecycle regression remain incomplete.

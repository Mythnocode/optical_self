# Teaching engineering synchronization — 2026-10-01

Branch `js`; migration remains active; PySide is retained. No commit was created.

## Implementation

The live four-asphere menu now loads the original engineering default project and numerical contract. It is distinct from the isolated `SceneStore.apply_optical_scheme(4)` fixture. Both synchronization directions use extracted original Python presentation and the existing simulation DTO.

- `shared_presentation/teaching_sync.py` preserves original lens grouping, scene positions, authored surface properties, source and receiver mapping. Qt uses the same scene helper.
- `/teaching/scenes/from-simulation` returns the mapped scene and optional captured engineering request. The client resets selection/history and fits the canvas as the original shell does.
- `/teaching/scenes/publish` returns only original supported wavelength/MFD changes and the full teaching research snapshot. Publication preserves existing source spectra, receiver Y diameter and numerical options.
- Active teaching calculation contracts are invalidated after physical scene changes or simulation changes. The saved simulation source contract survives teaching edits, allowing “从仿真更新” to restore its numerical settings. Publication updates the two supported source-contract fields before reimport; reload persists both active and source contracts.
- Formal jobs capture the full engineering request. Applying a result checks both physical scene and engineering prescription/options/precision. Selection-only changes remain allowed.

## Evidence

Original Git-source Qt shell and actual browser/API captures live under `tests/golden/ui-baseline/teaching/sync/` and `tests/golden/ui-current/teaching/sync/`.

`workflow-comparison.json` records full mapped scene equality, identical published source/receiver/surfaces and teaching research profile. The actual browser publication used 1030 nm and 7.5 μm. Same-request and selection-only apply return 200; missing or changed numerical contracts return 409. The intermediate invalid precision sample returned 422 and was corrected to the valid `preview` enum before recording the accepted case.

`engineering-comparison.json` records actual spot job `job-3587933326af` and coupling job `job-6837a8eaf9cc`. Original live-menu prescription matches; both use `engineering_project` scope. RMS radius is 2.1858016463646486 μm, mode overlap is 0.9518450969477794 and total coupling is 0.9470498589270048. Physics responses match after excluding elapsed time and three cache diagnostics. Latest coupling cache hit/miss/size differ because the server worker has previous calculations; the raw comparison retains this difference. These fields are not optical results.

Actual browser reload restored the 94.7% result. Teaching edit followed by reimport restored the numerical contract; the DOM evidence is `restore-after-teaching-edit.txt`. Engineering analysis screenshots were visually inspected. Six more control rectangles have zero position/size difference and equal text; combined analysis evidence now covers 28 controls across five states. RGB differences remain; universal pixel identity is unproven.

## Remaining acceptance

Full original Workbench/Teaching lifecycle across arbitrary editor changes, ordinary nondefault projects, running jobs, retries and cancellation still needs comparison. Native independent tool windows, resizing/high DPI and broader Three appearance remain pending. Older offscreen screenshot baselines need Windows font-resolution auditing.

Original `ComputationController._on_finished` applies formal artifacts while skipping geometry; `TeachingShell._scene_changed` continues to draw the geometry rays. `previewReady` alone updates canvas rays. Preserve that separation when accepting canvas behavior; adding formal rays to the bench would change the original interaction.

Typecheck and production build passed, including source-contract persistence and fingerprint regeneration before reimport. `reimport-after-publish-reload.txt` records successful numerical-contract inheritance after actual publication and reload. No automatic test suite was added or run. The existing 600 kB Three chunk warning remains.

## Ordinary and imported project lifecycle — later 2026-10-01 checkpoint

Before Workbench's first formal submission, the original Teaching shell uses `serialize_project(project)` without form state. The API now reproduces its 0.5 mm waist, 0.12 receiver NA and authored last-thickness image distance. After submission it captures the complete numerical request immediately, independently of completion. Local reload persists that submitted request.

`capture-teaching-sync-lifecycle.py` loads the original Git-source shell for an 850 nm / 9 μm ordinary project, both before first submission and after a captured submission. Native/API complete scene and status equality are recorded in `sync/lifecycle/comparison.json`; actual browser scene exports also match components, reference, baseline and selection in `browser-comparison.json`. The two fiber X positions intentionally differ: 124.89204407257958 mm before submission and 129.8657747476572 mm with the form contract.

Original Workbench retains its last serialized source/options while ordinary editor changes invalidate the active Teaching comparison. On the next “从仿真更新”, original mapping combines the live authored lens rows with that stored source and contract. The API accepts a separate `editor_project`; the client records a persistent project context identity, retains source contracts across edits and discards them when another project is opened. A later submission replaces the old contract. `capture-teaching-sync-edited-source.py` reproduces the original behavior: live first radius 6.2 mm and editor wavelength 940 nm/grid 257, mapped wavelength 850 nm and contract grid 129. Full native/API scene equality and actual browser component equality are recorded. Actual browser reload and jobs `job-114a68160c16` / `job-7ede833a383f` reproduce original physics, excluding elapsed and three cache diagnostics.

The ordinary 129×129 browser jobs `job-449c5a97ded7` / `job-048ef1c53548` have identical original metrics and physics under those exclusions: RMS radius 3.3654331420884467 μm and total coupling 0.5734582466091375. The edited-source pair retains these metrics as the original does. These captures do not establish equality for every combination of editor change, source preset or numerical setting.

Teaching source/active contracts and pending analysis requests now store field references instead of complex matrices in localStorage. Restoring them hydrates the original field arrays from IndexedDB while preserving the captured numerical options. Imported 513×513 Simulation job `job-6dd19a4f2c56`, followed by Teaching jobs `job-55fae3ffe5f8` / `job-3a985d9f833b`, succeeded through actual page reloads. Submitted real/imaginary matrices equal the original NPZ loader, options and precision match, and complete physics matches the original Git-source gateway excluding runtime diagnostics. Total coupling is 0.5681617869124951. The imported fixture's raw project differs by the fingerprint and explicit zero/default surface editor metadata; those differences are retained in `imported-formal-comparison.json`, rather than claiming raw request identity.

IndexedDB now retains fields referenced by the editor, submitted Simulation request and live Teaching snapshots, pruning unreferenced entries on a later field import. Legacy `current` slots remain readable. Actual replacement acceptance submitted the original 513×513 field (`job-1a69a6f0d4b5`), then loaded a phase-shifted replacement through the field selector and fully refreshed the page. The editor copy identifies the replacement; Teaching inheritance and jobs `job-f6fd503287b2` / `job-f931eedfe135` restore the original captured arrays. Full real/imaginary equality and options equality pass, and original gateway physics matches under the same runtime exclusions. Numeric field digests normalize signed zero and use little-endian float64, so JSON number formatting and object-key order do not create spurious hash differences. Evidence is `field-replacement-editor-probe.json`, `field-replacement-formal-comparison.json` and `field-replacement-final-context.png`. Repeated eviction, simultaneous renderer contexts and 1025×1025 acceptance remain pending.

Native inspector captures explicitly register Windows YaHei, resolving Microsoft YaHei UI. Earlier 621×720 expanded /621×473 collapsed captures reflect toggling before the queued initial fit or explicitly refitting; they are superseded for ordinary interaction by the settled-window acceptance in `teaching-inspector.md`. Original unit widths are exported from Qt. The settled ordinary laser/lens/fiber window is 621×467, including after expansion. Imported and edited-source analysis windows add 12 exact control rectangles/text, with RGB differences about 3.56 and 3.61. Typeface rasterization, native spin/checkbox rendering, independent window frames and Three appearance remain acceptance gaps.

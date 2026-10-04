# Visual parity check — updated 2026-09-30

## Desktop packaging checkpoint — 2026-10-02

Windows x64 Electron packaging now includes an isolated Python runtime, the
existing C++ optical DLL and Microsoft C++ runtime. The actual packaged dataset
job produced 8 valid samples in 17 attempts, all `cpp_native`, with exact sample
features/targets/validity matching the development reference. See
[desktop-packaging.md](desktop-packaging.md) for installed-resource checks and
the retained initial memory failures. Full migration and all-page visual identity
remain incomplete. The older gap lists below are historical checkpoints; use the
latest module documents and handoff for the current state.

## Capture setup

- Reference app: current PySide window with `apply_application_theme()` applied.
- Reference viewport: 1280 × 800.
- New UI: Vite browser renderer at 1280 × 800, inspected from fresh screenshots and DOM bounds.
- Legacy screenshots are saved in [`tests/golden/ui-baseline`](../../tests/golden/ui-baseline/).
- The teaching reference was captured with Qt's offscreen platform, which forces the legacy teaching canvas into 2D. It is a valid 2D layout reference, not a rendered 3D comparison.

## Compared screens

| Screen | Visual baseline | Current comparison |
|---|---|---|
| Home | Main frame at `(22,72)`, `1236 × 706`; five workflow columns; AI button at `(1217,737)` | Main frame and AI placement match. Five column positions, card widths, intro heights, and scroll height are within about 2 px of the reference. |
| Teaching 2D | Board at about `(165,139)`, `948 × 632`; floating actions and quick-action bar | Board bounds match within 1 px. Floating palette is `66 × 126` and quick-action bar is `424 × 62` at the legacy positions. Toolbar button widths and status controls use measured legacy dimensions. |
| Simulation / lens data | Secondary bar, 290 px object rail, toolbar, 8-row lens table | Default structure and 95 px secondary bar visually aligned. Real shared project now drives editable rows. Re-measured the legacy card at (304,215,962,571), matched exactly; table differs by less than 1 px. The original 640 × 520 properties content was captured and basic/profile/asphere states compared. Real JS and legacy-default simulation requests produce equal checked metrics. See simulation-project.md. |
| Model / dataset | 3-tab, 95 px secondary bar; dataset rail; data and training cards | Main rail and card bounds aligned; data card starts at `(303,164)`, training card at `(303,347)`, within 1 px. Expanded RF/XGB and BiLSTM parameter groups were captured from PySide and visually compared. Joint training and sequence training submit real jobs. Generation still needs shared project state. Native sequence file selection remains unverified. |
| Model / training results | Selector `(303,164,482,42)`, summary `(303,212,964,39)`, completed progress `(303,257,964,24)`, chart workspace `(303,287,964,502)` | Replaced the generic result card with the original selector, summary, progress, and four diagnostics. Compared actual joint-training results in both frontends, including point positions, tolerance bands, quantile trend, residual inset, legend, axes, and footer. Also checked BiLSTM residual/curve and saved RF OOB curve against matching PySide captures. Reload restores the job or selected model. Task Center opens saved training charts. |
| Model / prediction | Legacy three sections: model/target, current-lens inputs, result | Added model registry list and details, explicit current-model adoption, version/model-ID display, current-lens input table, standard prediction, and BiLSTM sequence prediction. Visually checked standard and BiLSTM selection/result states at 1280 × 800 using a temporary local mock API; both API request shapes reached the result table. That earlier mock check has now been supplemented by real shared-project prediction against model-63d9d3ea55cf: all 17 declared features loaded through the Python adapter, result 0.751145 displayed, and editing the live radius cleared the old result and reloaded new features. Complete visual parity for every populated prediction state remains pending. |
| Optimization / variables | 3-tab, 81 px secondary bar; variable rail; three right-side cards | Default layout was rebuilt and compared. Variable selection and optimization submission are still presentation-only. |
| Explainability / contribution | 2-tab, 81 px secondary bar; model rail; toolbar and empty state | Default layout, control positions, and empty state were rebuilt and compared. Model selection and chart generation are still presentation-only. |
| Task Center | The migration plan calls for a jobs table; there is no dedicated legacy task-center screen in the current primary navigation. | Added a separate `/tasks` route without changing the six main tabs. Checked loading/error, running, completed, failed, progress, action, and expanded result-summary states in the browser; the latter used synthetic local API records because the project backend was not running. A small task-count badge on the existing compute action opens the route when jobs are available. |

## Remaining visual and migration gaps

- The legacy 3D view could not be captured by the offscreen Qt run, which forces the teaching canvas to 2D. The new default camera was checked against the QML reset formula (38° field of view, axis height 25 mm, empty beam range 0–80 mm, distance 204 mm); the QQuick3D window-handle capture returned a black frame, so a usable on-screen legacy 3D screenshot is still needed for direct pixel comparison.
- Non-default pages under Optimization, Explainability, and Simulation still use generic workbench content. Their screenshots and layouts have not been migrated.
- Responsive widths and interactive states have not been compared across all routes.
- Task list and opening completed training charts were checked against real persisted jobs. Retry/cancel and other result types still need real backend verification.
- Training submission/result retrieval and saved model diagnostics have been exercised against the real backend. The browser uses the Vite proxy; Electron starts/manages this backend. Native Electron CSV selection and full renderer IPC training submission still need direct UI verification because desktop-control authorization timed out.
- The shared project now drives real simulation and prediction, including Python-derived physical features. Source/receiver/environment/field and settings now synchronize real simulation requests. Dedicated result views and detector overlays are connected; dataset generation and optimization still need complete integration. Unknown model features remain unavailable.
- The current diagnostics use SVG. Font rasterization, native combo arrows, automatic tick selection across untested ranges, and scatter density hexbin for ≥140 samples remain parity gaps; these checks do not establish pixel identity for all states/resolutions.

## Training evidence — 2026-09-30

- `job-15fb81b2a95b`: real RF/XGB joint training on the packaged 90-sample dataset, completed; test R² RF `0.950675`, XGB `0.937863`. The same API result was fed into the unmodified PySide result widget and the JS renderer.
- `job-5aa026541d6f`: real BiLSTM training, 5 epochs, batch size 8, seed 42; 30 systems split 21/4/5. This uses a synthetic sequence fixture for transport/UI verification, not optical or scientific validation.
- `job-ffb4458c36b7`: another joint training completed using the backend started by Electron. RF `max_features=1.0` was checked by loading the actual saved estimator: Python type `float`, value `1.0`; RF R² `0.969900`, XGB `0.937863`.
- Saved source JSON/sequence fixture: [`tests/golden/training`](../../tests/golden/training/). Capture utility: [`scripts/capture-model-baseline.py`](../../scripts/capture-model-baseline.py).
- PySide images: `ui-baseline/model-training-chart-{0,1,2,3}.png`, `ui-baseline/bilstm/`, `ui-baseline/random-forest/`; JS images: `ui-current/model-training-*.jpg`, `model-bilstm-*.jpg`, `model-random-forest-curve.jpg`.
- Typecheck and production build passed after the final changes. The lazy Teaching chunk remains about 690 kB and produces the existing size warning.

## Desktop runtime finding

`D:/python/python3.12/python.exe` provides NumPy, sklearn, XGBoost, torch and PySide on this machine. The PATH Anaconda environment lacks XGBoost and cannot load PySide correctly. Select the full interpreter with `OPTICAL_PYTHON_EXECUTABLE`.

Optional SHAP/OpenCV import can leave `cv2` at the start of `sys.path`; Windows workers then import its `typing` package and fail. The new desktop bootstrap imports optional SHAP before starting the backend service graph and restores `sys.path` before workers start. Electron startup, health, simulation-worker readiness and complete training-worker execution were observed with this bootstrap. Computation modules are unchanged. Packaging and repeated lifecycle acceptance remain pending.


## Simulation inspector evidence

Six original inspector defaults and the 540×580 calculation-settings content were compared visually at 1280×800. Corrected navigation/tool font weights, accumulated category-row spacing, unit widths, detector select widths, material-list text position and settings scrollbar allocation. Inspected numeric/select bounds are within 1 px of the corresponding Qt bounds (see ui-current/simulation-inspectors-geometry-comparison.json). Detector unit-wrapper visibility mirrors the existing Qt behavior, including when observation is disabled or switched to fiber mode. This is a measured default-state checkpoint; native controls, rasterization and all uninspected states/resolutions still require work.

Real edited-inspector and imported-complex-field requests were compared with independently serialized original requests and run through the same engine. Both pairs produced exactly matching six checked metrics. Sampling warnings remain in the JSON evidence. The browser NPY/NPZ file picker now works; native Electron file pickers remain unverified.


## Simulation result evidence — later checkpoint

Ray layout, spot, coupling and wavefront now consume real completed jobs and the original shared Python adapters. Result metrics and frozen submission geometry were checked against the original. Both 321×321 fast heatmap RGB buffers have zero differing channels. Editing the active project shows a stale indicator while preserving the submitted result image.

The formal 3D result has an offscreen Matplotlib reference, distinct from the still-unavailable QQuick3D Teaching reference. Shared original surface/body/envelope/fiber primitives feed a lazy Three renderer. The original square orthographic viewport and camera match all 150 reference ray vertices within 1.03e-12 px at equal dimensions; actual CSS layout contributes at most 0.263 px. Initial scene, rotation and the S4 surface tooltip were manually inspected. The shared geometry, theme and camera extraction preserves Qt behavior.

Current records: tests/golden/ui-current/simulation-results/; originals: tests/golden/ui-baseline/simulation-results/. Details and unaccepted states are in simulation-results.md. GPU/Canvas font rasterization still differs from Qt; these records do not establish universal pixel identity. The red task-count badge was removed to retain the original top bar; Ctrl+Shift+J opened the real 19-job Task Center successfully.

## Material UI evidence — later checkpoint

Used-material details, the internal material library, search and three custom material editors now use the shared original Python catalog and presentation helpers. The 162 default catalog records match the Qt baseline exactly. Constant/Cauchy/Sellmeier records match at 780 and 850 nm; manual UI saves, editing, cancellation and reload restoration were exercised. NaN/infinite request validation now returns 422 instead of failing to serialize error context.

Original and current images are in ui-baseline/materials/ and ui-current/materials/. The library outer bounds and dialog content sizes match the original; initially measured custom controls differ by at most 0.40 px, followed by fixed original footer widths. Text wrapping, value-label columns, numeric truncation and scrollbars were corrected through image inspection. Native independent dialogs, resize grips, glyph rasterization and other states/resolutions remain pending. See materials.md. Whole goal remains active; branch js; no commit.

Final material measurement: fixed original footer widths removed the earlier subpixel difference. All inspected input/value/footer rectangles for three custom editors and two detail windows now match exactly in materials/geometry-comparison.json; table bounds match as well. A full reload restored all three QA records. Final typecheck/build passed. Font rasterization and native dialog framing remain pending.
# Teaching equipment checkpoint — 2026-10-01

The original Qt equipment popup and Web replacement were visually inspected in the default state, lens and no-match searches, laser/default/custom, lens, mirror, aperture, fiber, CCD and oscilloscope states. At the documented 1920×1080 Qt reference and 1280×900 browser viewport, all eleven client sizes and 274 measured control rectangles match exactly. Presets are shared with PySide. The 2D equipment drop adds a component exactly equal to the original Qt handler, including full-precision pose, with one undo entry.

Evidence: `tests/golden/ui-baseline/teaching/equipment/` and `tests/golden/ui-current/teaching/equipment/`. The latter contains matching PNGs, `comparison.json`, `domain-comparison.json`, `drop-2d-comparison.json` and full context proof. Minor glyph and border rasterization differences remain. Three picking, independent native windows, adaptive screen sizing and all other unresolved migration states are not accepted by this checkpoint.

## 公共导航 — 2026-10-02

主导航按钮、下划线、右上角24 px图标和所有模块二级选中边框已按原版实际截图校准。
1280×800与1440×900共114个导航矩形、50个图标尺寸及选中状态一致，详情见
[navigation.md](navigation.md)。原版Qt堆叠布局历史变化、字体/边框栅格及整页控件仍未
完成验收；这些导航测量不代表整页像素一致。

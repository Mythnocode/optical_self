# Teaching scenes, inspector and 2D canvas checkpoint

Updated 2026-10-01. Work remains on branch `js`. Original PySide is retained.

## Implemented

- Original model, coordinates, physics and asset catalog are shared Python modules with Qt compatibility facades. Scene normalization and edits remain authoritative in Python. Qt `SceneStore` retains QObject and its real signals.
- Teaching HTTP endpoints provide default, normalization, edits and inspection. Inspection returns the original applicability report, setup warnings, geometry preview and renderer independent 2D primitives. Geometry preview supplies no formal coupling efficiency.
- Web scene persistence uses the original schema 2, component metadata, reference, poses in radians, baseline and result fields. Full scene snapshots provide fifty undo entries; drag creates one entry. JSON open, legacy schema 1 normalization, save and copy are connected to the Teaching document.
- `TeachingInspector` reproduces the original collapsed coordinate controls, parameter expansion, enabled state, optional values, baseline actions and laser presets. Controls commit through shared scene APIs. Teaching manifests are generated with `scripts/export-teaching-domain.py`.
- `TeachingBench2D` replaces the placeholder. It renders shared body primitives, original table holes, ray segments and baseline. Selection, double click, drag, Shift snapping, wheel zoom, panning, scrollbar handling and fit are implemented. Actual acceptance below covers only the exercised states.
- Three preview lines use the shared Python geometry preview. Imported axis height updates the renderer. The toolbar Calculate action follows the original shell's preview behavior; View offers reset, top and 2D fit. Formal calculation belongs to the analysis popup and remains pending.
- Save and View menus render above the canvas. Teaching store uses Pinia's HMR adapter; a full reload was used for final browser acceptance after adding store actions.
- `TeachingEquipment` replaces the flat placeholder with the original four groups, search filtering, engineering presets, custom laser wavelength and persistent popup state. Click adds without closing. Original PySide and Web use `shared_presentation/teaching_equipment.py`; the generated manifest includes the original detector/CCD key mismatch, so CCD correctly has no preset controls. Presets apply to the original last-added target; a stale deleted target does not redirect edits to another selected object.
- Equipment pointer dragging uses the original eight-pixel Manhattan threshold. 2D drops use the existing viewport transform and original fixed 25 mm axis height; add plus pose is one Python edit and one undo entry. Three drop code follows the original pick/fallback and table clamp semantics, but its appearance and precise picking remain unaccepted.

## Evidence

Evidence resides in `tests/golden/ui-current/teaching/` and original references in `tests/golden/ui-baseline/teaching/`.

| Check | Observed result |
| --- | --- |
| Four original model presets: original/shared/Qt | Scene dictionaries exactly equal |
| HTTP presets and schema 1 pose conversion | Equal after JSON tuple/list normalization |
| Physics: four defaults plus four misaligned scenes | Original/shared/API rays, warnings and applicability reports equal; elapsed timing excluded |
| Inspector default / expanded / empty | Sizes 621×475 / 621×475 / 440×320 equal; 52 measured rectangles have zero coordinate difference |
| Original vs shared Qt body painting | 17 kinds × normal/selected/hover = 51 images; zero differing color channels |
| Four-lens 2D camera at 1280×690 | Viewport 1266×676 equal; largest matrix difference 1.11×10⁻¹⁶ |
| Browser coordinate edit | 140 → 140.25; undo 140; redo 140.25 |
| Browser optical parameter | Focal length 18 → 19.25; undo restores 18 |
| Baseline | Exported x = 140; visibility false; undo restores visibility |
| Browser 2D drag | Full pose retained in copied scene; one undo restores x=140, y=0; redo restores dragged pose |
| Browser file open | Legacy 45°/−12°/5° converts to radians; nonfinite parameter rejected without replacing scene |
| Browser wheel | One observed step changes scale by 1.15 |
| Browser View / Calculate | 2D fit action operates; Calculate completes with “光路示意已更新” |
| Equipment presets vs original Git source | All six preset mappings exactly equal |
| Equipment default / two searches / seven kinds / custom laser | 11 states; 274 measured control rectangles and all client sizes exactly equal at the documented 1080p reference |
| Equipment custom laser | Exported wavelength 1030.125 nm; other default parameters preserved |
| Equipment lens preset | Exported focal length and alias both 100 mm; diameter 25.4 mm |
| Equipment close/reopen | Custom choice and 1030.125 nm edit preserved |
| Equipment 2D drop vs Qt | Full added component exactly equal, pose difference zero; one undo restores six original components |
| Drag followed by click | Regression confirms first subsequent click adds laser; eight-component scene exported, then three undo operations restore original six-component scene |

Key records: `model-comparison.json`, `api-comparison.json`, `physics-comparison.json`, `inspector-comparison.json`, `ui-edit-evidence.json`, `ui-import-evidence.json`, `canvas/qt-primitive-comparison.json`, `canvas/camera-comparison.json`. `canvas/final-context.jpg` shows the accepted browser context.

Equipment records are in `equipment/`: `comparison.json`, `domain-comparison.json`, `custom-laser-scene.json`, `lens-preset-scene.json`, `drop-2d-comparison.json`, `drag-click-persistence-scene.json` and eleven matching PNGs. `equipment/final-context.jpg` shows the actual custom laser popup over the 2D bench. Original capture uses a configured 1920×1080, 96 DPI, DPR 1 offscreen screen: Qt's default 800×800 offscreen screen clips `adjustSize()` popups. The baseline records 420×560 default, 420×681 optical presets and 420×720 laser presets. Capture scripts preserve native Qt layout and exercise the original drop handler. Visual checks identify minor glyph/border rasterization differences; zero rectangle difference is not a pixel equality claim.

Typecheck and production build passed. No automatic test suite was added or run for this checkpoint. The existing approximately 600 kB Three chunk warning remains.

## Remaining work

This checkpoint does not establish pixel identity for every page, state or resolution. Qt and SVG font rasterization differs; independent native tool windows, framing, resizing and native file dialogs remain unaccepted. Original 3D is skipped by the offscreen shell, so its appearance still needs a usable visual reference.

Priority work:

1. Extend equipment acceptance to Three drops, drag cancellation, all preset choices and other screen sizes. The current Web equipment client matches the 1080p reference; adaptive native `adjustSize()` dimensions, independent windows and framing remain pending. Exercise remaining inspector warnings and numeric boundaries.
2. Formal job APIs and the real analysis window are implemented; see `teaching-analysis.md` for actual five-analysis equivalence, stale/cancel/failure evidence and 28 measured controls. Continue broader failure/retry/cancel UI acceptance. Original canvas retains geometry rays when formal artifacts are applied; geometry persistence is implemented.
3. Both Simulation synchronization directions and the live engineering four-asphere menu are implemented and accepted for recorded default/publication cases; see `teaching-sync.md`. Continue arbitrary editor/project lifecycle comparisons, interrupted synchronization and running-job invalidation. Keep the engineering preset separate from the isolated `SceneStore.apply_optical_scheme(4)` fixture.
4. Verify 3D asset sizing on parameter changes, mounting hardware, loaded reference scales, picking and drag, alternate cameras, missing assets, performance and cleanup. The generated catalog now uses original housing definitions, but that alone does not verify Three rendering.
5. Broaden 2D acceptance to all rotations, large scenes, Shift/cancel, scrollbar and pan behavior, viewport sizes, and disabled components. Wheel was observed; exhaustive Qt zoom/scroll equality was not established.
6. Complete Optimization, Explainability, remaining Training states, independent result windows, packaging and backend lifecycle acceptance as required by the full migration plan.

The whole migration goal remains active. No commit was created.

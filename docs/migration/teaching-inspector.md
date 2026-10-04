# Teaching Inspector fidelity — 2026-10-01

Branch `js`; the full migration remains incomplete. PySide remains the reference.

## Corrected reference behavior

The original Inspector performs its initial fit after queued Qt layout work. Clicking “更多参数” after that fit does **not** resize the window. Earlier 621×720 expanded /621×473 collapsed captures toggled details before the queued fit or explicitly fitted again. Those captures describe initialization timing, not the ordinary user interaction, and are superseded for this acceptance.

The settled original window is 621×467 for the ordinary laser, lens and fiber fixtures. The 14 other placeable kinds have an off-axis two-line warning in these fixtures and fit to 621×535. Details retain that height and scroll. The empty window is 440×320. Editing an existing object can change warning content without refitting the window; closing and reopening preserves details and scroll.

## Implementation

- Fit once after the current physical scene inspection is ready. Inspection readiness uses the physical scene signature, because imported scenes can share an ID and revision while containing different components.
- Keep the Inspector mounted while hidden. Rebuild only when scene identity, selection or parameter keys change; numeric edits retain details and height.
- Match original unit widths, numeric/text row heights, pose columns and warning layout. Ratio rows in the PBS, splitter and beam sampler two-row grids are 45 px; other captured unitless rows are 42 px. Omit the optical-parameter section when it is empty, as the original does.
- Use a visible 12 px scrollbar with the original colors, proportional thumb, keyboard paging/Home/End and pointer drag handling. The browser's underlying scrollbar retains the same layout space.

## Evidence and capture procedure

`scripts/capture-teaching-inspector-states.py` loads the original Git HEAD Inspector, explicitly registers Windows YaHei fonts, settles the queued initial fit, and then clicks details. It captures all 17 placeable kinds in collapsed/expanded/bottom states, an empty state, and four edit/disable/reopen states. Closing and reopening at scroll position 386 px preserves that position in both frontends. These fixtures cover placeable kinds, not every GLB asset variant.

Browser captures use the actual project chooser, property controls and scrollbar. Expanded top/bottom states are explicitly positioned with Home/End. The browser automation's focus/scroll-into-view can move a collapsed warning window to its 2 px scroll maximum before clicking; this is not treated as a demonstrated user-click defect. Captures move the pointer to inert status text and take a fresh rendered screenshot before saving to avoid stale hover pixels from the in-app browser compositor.

Evidence is under `tests/golden/ui-baseline/teaching/inspector-states/` and `tests/golden/ui-current/teaching/inspector-states/`. `comparison.json` records **56 states /1857 controls**, with no window-size, control-count or text mismatches. The maximum control-rectangle difference is **0.333374 px**, confined to scroll/DPI quantization; edit-warning, edit-disabled and reopen states have zero rectangle difference. Mean absolute RGB differences range from **2.05 to 6.16** on the 0–255 scale. Original and current warning, lens-bottom, oscilloscope-bottom and empty screenshots were inspected visually.

This is layout/text acceptance, not universal pixel identity. Font rasterization, native input and checkbox strokes, independent native window frames, resizing/high DPI and original on-screen Three appearance still require acceptance. Scrollbar keyboard movement is exercised by the captures; pointer drag and resize lifecycle remain pending.

`final-context.png` shows the current Simulation-derived scene with the expanded lens Inspector at 1280×900. The temporary capture viewport is reset afterward. The file named `saved-scene.json` in the current Inspector evidence directory is a Simulation request copied before this work, **not** a Teaching scene backup; do not import it as a Teaching scene.

Typecheck, production build and `git diff --check` passed. The existing 600.12 kB Three chunk warning remains. No automatic test suite or commit was created.

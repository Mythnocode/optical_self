# Material UI checkpoint

Branch: `js`. The complete migration remains in progress.

## Implementation

- Used lens materials open the original detail fields on double click or Enter. Air names, glass-prefix display, unknown materials, wavelength formatting and catalog ordering follow the original Python helpers.
- The original material library is registered internally but omitted from the default secondary navigation. The five original buttons are retained; right click on the used-material list opens the internal library route.
- Material search, built-in details, custom editing and constant/Cauchy/Sellmeier parameter pages are implemented. Numeric inputs retain their text while another field commits, round to the original six/eight decimals, and support the original default step of one.
- Original material presentation helpers now live in `shared_presentation/materials.py`. Qt uses the same helpers. POST `/api/v1/simulation/materials` uses them without importing Qt; no dispersion calculation is duplicated in JavaScript.
- Custom records are stored under `frontend_state.custom_materials`, included in local restoration and portable project export. The original shared simulation DTO has no custom-material definitions; these records retain the existing UI capability and are not passed as new engine models.
- Invalid request values return 422. Validation error context now serializes nonfinite inputs and validator exceptions safely; NaN previously caused error-response serialization to return 500.

## Evidence

Original: `tests/golden/ui-baseline/materials/`, produced by `scripts/capture-materials-baseline.py` with isolated Qt settings. Current: `tests/golden/ui-current/materials/`.

- Default catalog: all 162 records and the used-material record match the original captured data.
- Constant, Cauchy and Sellmeier queries at 780 and 850 nm match the original helpers, including case-insensitive custom lookup and the unknown-material placeholder. Zero wavelength, unsupported model, out-of-range index, NaN and infinity return 422. See `api-comparison.json`.
- Browser checks covered three model saves, Cauchy refresh restoration, same-name replacement, cancellation, numeric step keys, range rejection, Escape, and Enter on Cancel. QA values were 1.6, 1.45684 and 1.51118 at 780 nm.
- Visually inspected the library, four N-BK7 filter results, built-in detail, Cauchy detail and all three custom parameter pages at 1280×800. Corrected text wrapping, label alignment, table truncation, scrollbars and dialog controls.
- Table outer bounds match the original: `[303, 214, 964, 575]`. Detail content is 420×420; custom content is 420×462. Initially measured custom controls differed by at most 0.40 px. After fixed footer widths, all measured input, value and footer rectangles for the three editors and two detail windows match exactly. See `geometry.json` and `geometry-comparison.json`.
- Original Qt capture completed after shared-helper extraction. Typecheck and production build passed during implementation; final rerun is recorded in the handoff.

These records establish the inspected data and layout states. Browser/Qt glyph rasterization, native independent dialog windows and resize grips, other resolutions, project-file import and native export still need acceptance. No automatic test suite was added or run.

## Next work

Special surfaces and coordinate breaks, dynamic lens columns, project import/undo, remaining functional optimization/explanation screens, and native scientific-window/export behavior remain part of the active migration goal. Three QA custom records remain in the browser preview's local project; physical lens materials and Gaussian fiber defaults are restored after capture.

# Teaching formal analysis checkpoint — 2026-10-01

The migration goal remains active. Work is on branch `js`; no commit was created.

## Implementation

- `/teaching/jobs` dispatches raytrace, spot, coupling, field and wavefront through the existing Python `FormalTeachingGateway` and optical engine. Persistent job workers provide cancellation and progress. JS implements no optical solver.
- Completed and diagnostic failed results are read through `/teaching/jobs/{id}/result`. `/apply` rejects different scene IDs, revisions, references or component prescriptions. Selection and prior results do not alter the physical prescription. Same revision with different components is also rejected.
- Geometry preview results are now persisted in the full scene, as in the original controller. Formal application preserves current selection and any newer geometry result.
- The analysis window uses the original 500 × 640 client, starts spot then coupling, retains earlier valid metrics during updates, hides stale metrics after edits, and restores saved results and pending jobs after reload. A stopped or failed spot does not start coupling.
- Metric formatting and illustrative ring data come from shared Python presentation. The illustration remains the original decorative diagram, not a numerical intensity plot. Task Center labels these jobs “教学计算”.

## Authoritative evidence

`tests/golden/ui-baseline/teaching/analysis/` contains original gateway results and Qt control captures. `tests/golden/ui-current/teaching/analysis/` contains actual API results, browser captures and comparisons.

- `formal-comparison.json`: all five actual API physics responses match original Git-source gateway output, excluding elapsed time. Each has 4,851 ray segments.
- Isolated four-lens fixture: spot RMS 338.69051698901905 μm; mode overlap 0.00007001163527039372; total coupling 0.00004990216936172944. These are the independent scene fixture values, **not** the live shell's engineering four-asphere menu.
- `job-workflow.json`: same scene and selection-only application return 200; new revision and same-revision changed pose return 409 `TEACHING_RESULT_STALE`; duplicate requests use the same job ID; cancellation reaches `cancelled`; a displaced fiber produces a failed task and no displayed efficiency.
- Browser spot `job-9e814e458b8f` followed by coupling `job-7d6b310051ab` completed across a reload during the spot run. The window showed RMS 338.691 μm and total coupling 0.00499%.
- Actual browser edit L4 X=140→141 hides the summary and efficiency, shows the original update prompt; undo restores the valid saved result. Clear→calculate shows the original missing-laser message; undo restores the fixture.
- `comparison.json`: 28 control rectangles across completed, stale, blocked, updating-spot and engineering-completed states have zero position/size difference and identical text. Vision inspected original and Web completed/empty/engineering states; colors, summary spacing, caption placement and status color were corrected.
- Native offscreen capture explicitly registers installed Windows YaHei fonts. Without registration, Qt silently used Droid Sans Fallback and altered font metrics. Current analysis baseline resolves `Microsoft YaHei UI`; this is a capture correction, not a product font change. Older module captures require the same font-resolution audit before whole-application visual acceptance.
- Screenshot mean RGB differences remain about 1.8–5.9 / 255; animated progress phase, borders and glyph rasterization differ. Rectangle equality does not prove pixel identity.
- `npm run typecheck` and production build passed. The existing 600 kB Three chunk warning remains. No automatic test suite was added or run.

## Remaining acceptance

Engineering synchronization and the live four-asphere menu now use the original prescription and numerical contract; see `teaching-sync.md`. Original canvas rays remain geometry previews while formal artifacts update the analysis window. Broader canvas interaction, independent native tool windows, resizing/high DPI, native file dialogs, exhaustive analysis failure/retry/cancel interactions and broader Three rendering still need acceptance. Optimization, Explainability, remaining training states and packaging/lifecycle remain part of the unchanged full plan.

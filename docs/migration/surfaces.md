# Simulation surfaces and project files — 2026-09-30

Branch: `js`. Migration remains in progress; PySide is retained. No commit or automatic test suite was performed for this checkpoint.

## Implementation

The original eleven-type surface registry, sequential media/coordinate-break serializer and quantity parser now live in `shared_presentation`. Qt compatibility modules and the HTTP boundary use the same Python implementations. The browser contains editing state and presentation, not a second optical solver. `/simulation/surfaces/serialize` rejects invalid editor numbers before formal serialization; Python-mode model dumping preserves nonfinite numbers for validation.

The lens editor includes generated special-surface properties, original dynamic column definitions and hidden-column behavior, keyboard navigation, single-cell copy and atomic rectangular TSV paste. Invalid blocks leave the project unchanged. Surface history stores up to fifty snapshots and supports undo/redo; it currently covers surface operations only.

Project opening validates the whole request before replacement. Electron has a restricted native JSON picker; browser preview uses a file input. Portable files embed imported complex fields; local parameter copies retain cache identities. Dirty state, Ctrl+O/S/Z/Y and the Save context menu are connected. Quantity expressions are parsed by the original Python helper, including length and angular unit conversion. Merely focusing/blurring a compact numeric value preserves its full authored precision.

## Evidence

Manual browser operations, original Qt offscreen captures, direct API comparisons, type checking and production builds were used. Evidence paths are relative to the repository.

| Check | Evidence | Recorded result |
| --- | --- | --- |
| Eleven types and coordinate accumulation/reset | `tests/golden/ui-current/surfaces/api-comparison.json` | Original pre-extraction serializer, shared serializer and HTTP output exactly equal for twelve authored rows; no Qt modules loaded through the shared API path |
| Four dynamic tables | `table-comparison.json` in the same folder | Headers match and maximum column-width difference is zero |
| Forty-four property states | `geometry-comparison.json` | Matched controls differ by at most 0.667 CSS px in recorded states |
| Native reference | `tests/golden/ui-baseline/surfaces/` | 114 original captures, including focused and long numeric input |
| Project validation | `project-file-api.json` | Valid request accepted; nonfinite surface editor and malformed complex-field shape rejected with 422 |
| Undo/redo | `project-history-evidence.json`, `project-history.jpg` | Full-precision values, insert/delete and redo invalidation manually exercised |
| Portable field | `project-portable-field-evidence.json`, `project-portable-field.jpg` | Embedded 65×65 field opened and restored after refresh; original inactive 513×513 field subsequently restored |
| Units | `quantity-api.json` | Five conversions match original helper; cross-dimension and overflow inputs rejected |

Additional manual rectangular paste: two rows containing R/thickness values 7.123456789/3.25 and -8.5/14.5 applied together; one undo restored the preceding project. A block containing negative thickness was rejected without changing its valid cells. ArrowDown moved between corresponding radius cells. Entering 500 μm in the radius property produced 0.50 mm; untouched focus/blur retained the authored 5.123456789 radius.

## Remaining acceptance and work

These measured states do not establish universal pixel identity. Font rasterization, focused numeric suffix/caret behavior, native independent-window framing/resizing, additional viewport sizes and all menu/scroll interactions still need comparison. Qt applies all property control values on each change; browser edits currently apply the changed field. Full table range selection, quoted spreadsheet fields and virtualization are pending.

History does not yet include source/fiber/settings/material changes. Native Electron dialogs, verified save receipt, original legacy-file variants, multiple field-cache contexts, cache eviction and 1025×1025 fields remain unaccepted. Browser copy is compact project parameters, not a verified portable-array clipboard transfer.

Teaching scene files/history/formal computation, Optimization, Explainability, dense training plots, remaining result tools, packaging and clean-machine acceptance remain part of the active whole migration.

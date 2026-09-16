# Primary entry modules

The first-level navigation entries each have one owning package:

- `home/` — workflow home and entry widgets
- `simulation/` — simulation tabs and simulation documents
- `teaching/` — teaching canvas, equipment and analysis windows
- `model/` — dataset, training-result and prediction tabs
- `optimization/` — scan, variables, result and goal controls
- `explainability/` — global contribution, trend and current-system tabs

Within ordinary entries, `documents.py` holds shared implementations for tabs
that use the same state model, while small entry-point files fix the ownership
and constructor contract for each visible Tab.

`app/workbench_shell.py` keeps the shared workbench shell and cross-entry job
wiring. New UI should be added under its owning entry package and exposed
through one small factory or router branch.

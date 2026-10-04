# Migration golden cases

The teaching coordinate cases in `teaching_coordinates.json` were generated from the existing Python `coordinates.py` and freeze its render position and quaternion convention. Update a golden only when the corresponding Python contract changes intentionally, and record the reason in the migration baseline.

The broader project cases (formal teaching results, simulation, jobs, datasets, ML, and optimization) are not captured yet. `py -3.12 -m pytest -q --continue-on-collection-errors` collected most tests on the baseline, but returned 197 passed, 6 failed, and 3 collection errors. See `docs/migration/phase-0-baseline.md` for the pre-migration failure list. Capture the broader cases after the existing baseline defects are triaged or from a separately verified run that can produce stable formal results.

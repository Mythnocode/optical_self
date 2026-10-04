# Training visual fixtures

These files capture actual backend results used for visual comparisons on 2026-09-30.

- `joint-result.json`: completed RF/XGBoost training on the packaged 90-sample four-lens dataset; seed 42, default UI hyperparameters, RF max_features `sqrt`. RF test R² 0.950675; XGB test R² 0.937863. Used for the main four PySide baseline charts.
- `random-forest-result.json`: saved packaged RF model manifest, used to compare its 100-point OOB curve.
- `sequence-ui-fixture.csv`: synthetic 30-system long table. It checks field mapping and result transport. Its targets are artificial, so this is not an optical calculation reference.
- `bilstm-result.json`: real training output from that fixture, 5 epochs, batch size 8, seed 42; train/validation/test counts 21/4/5. Removed the machine-specific model directory from this copy.

Regenerate a PySide visual reference with an environment containing the project's existing dependencies:

```powershell
& 'D:/python/python3.12/python.exe' scripts/capture-model-baseline.py --output tests/golden/ui-baseline --result tests/golden/training/joint-result.json
```

The capture uses the original widget, theme, a 1280 × 800 offscreen window, and isolated local settings. It does not validate numerical correctness or replace the migration's full regression gates.

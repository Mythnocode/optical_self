"""Expose authored variable labels without importing Qt or calculating in JS."""
from types import SimpleNamespace
from backend.optical_ml_app.application.surface_presentation import editor_surfaces
from shared_presentation.variable_rows import variable_rows
from shared_presentation.dataset_generation import TARGETS, SAMPLING, PRECISION
from machine_learning.datasets.variable_schemes import resolve_lens_bindings

def generation_presentation(project: dict) -> dict:
    rows = variable_rows(SimpleNamespace(surfaces=editor_surfaces(project)))
    return {
        "targets": list(TARGETS), "sampling": list(SAMPLING), "precision": list(PRECISION),
        "lens_count": len(resolve_lens_bindings(project)),
        "variables": [{"path": path, "label": f"{group} / {face} / {parameter}", "selected": path.endswith((".radius_mm", ".distance_to_next_mm"))} for path, group, face, parameter in rows],
    }

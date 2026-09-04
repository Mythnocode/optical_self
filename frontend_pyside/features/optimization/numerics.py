from __future__ import annotations

from typing import Any

from frontend_pyside.features.simulation.form_state import PROPAGATION_MAP
from frontend_pyside.shared.settings import SimulationNumericsProfileStore


_PRECISION_MAP = {
    "129×129": "preview",
    "257×257": "standard",
    "513×513": "high",
    "1025×1025": "high",
    "预览": "preview",
    "标准": "standard",
    "高精度": "high",
    "研究级": "high",
}
_PRECISION_MODE_MAP = {"preview": "preview", "standard": "balanced", "high": "reference"}


def research_simulation_numerics(profile: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """Return the formal simulation numerics shared by research tasks.

    Parameter scans, automatic optimisation and tolerance analysis must evaluate the
    same physical system with the same numerical strategy as the simulation workbench.
    In automatic mode this deliberately re-applies the recommended profile instead of
    trusting stale expert values left in QSettings by an older application version.
    Expert/manual mode is preserved verbatim.
    """
    values = dict(profile if profile is not None else SimulationNumericsProfileStore().load())
    precision_text = SimulationNumericsProfileStore.normalize_precision(str(values.get("precision", "257×257")))
    if bool(values.get("automatic", True)):
        values.update(SimulationNumericsProfileStore.recommended_sampling(precision_text))

    precision = _PRECISION_MAP.get(precision_text, "standard")
    grid_size = int(values.get("grid_size", 257))
    pupil_sample_count = int(values.get("pupil_sample_count", 49))
    propagation_text = str(values.get("propagation", "缩放 Fresnel"))
    propagation_model = PROPAGATION_MAP.get(propagation_text, propagation_text or "scaled_fresnel")
    extent_mm = float(values.get("extent_mm", 0.024))
    padding = float(values.get("padding", 2.0))
    convergence = bool(values.get("sampling_convergence", True))

    options: dict[str, Any] = {
        "geometric": {
            "pupil_sample_count": pupil_sample_count,
        },
        "hybrid": {
            "pupil_sample_count": pupil_sample_count,
            "grid_size": grid_size,
            "output_grid_size": grid_size,
            "output_extent_x_mm": extent_mm,
            "output_extent_y_mm": extent_mm,
            "propagation_model": propagation_model,
            "zero_padding_factor": padding,
            "precision_mode": _PRECISION_MODE_MAP.get(precision, "balanced"),
            "convergence_enabled": convergence,
            "sampling_convergence_enabled": convergence,
            "auto_expand_output": True,
            "wavefront_fit_order": 4,
            "include_diagnostic_arrays": False,
            "result_array_policy": "field_only",
        },
    }
    return precision, options


__all__ = ["research_simulation_numerics"]

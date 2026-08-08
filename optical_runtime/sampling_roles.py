
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


_COMPLEX_FIELD_ANALYSES = {
    "coupling",
    "detector",
    "exit_pupil",
    "psf_mtf",
    "wavefront_quality",
    "fiber_alignment",
    "coupling_research",
}
_TOLERANCE_ANALYSES = {"fiber_tolerance"}


def infer_sampling_role(
    analysis_names: Iterable[str],
    options: Mapping[str, Any] | None = None,
) -> str:


    opts = dict(options or {})
    explicit_role = opts.get("sampling_role")
    if explicit_role:
        return str(explicit_role)
    if opts.get("explicit_pupil_samples") is not None:
        return "validation_probe"

    names = {str(name).strip().lower() for name in analysis_names}
    if names & _TOLERANCE_ANALYSES:
        if bool(opts.get("include_monte_carlo", False)) or int(opts.get("monte_carlo_samples", 0) or 0) > 0:
            return "monte_carlo"
        return "tolerance_fast"
    if names & _COMPLEX_FIELD_ANALYSES:
        return "complex_field_dense"
    return "geometric_analysis"

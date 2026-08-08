# 出瞳复场分析。
# 几何光线向波动光场转换的重要分析入口
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.operators.axisymmetric_reconstruction import reconstruct_axisymmetric_field
from optical_core.physics.hybrid.operators.cartesian_reconstruction import reconstruct_cartesian_field
from optical_core.physics.hybrid.reconstruction import ComplexFieldReconstructionRequest, formal_complex_field_reconstructor
from optical_core.runtime.protected_merge import merge_unique_mappings


@dataclass(frozen=True, slots=True)
class ExitPupilAnalysisOptions:
    wavelength_nm: float = 550.0
    grid_size: int = 257
    extent_scale: float = 1.04
    radial_bins: int = 64
    normalize: bool = True
    wavefront_fit_order: int = 2


@dataclass(slots=True)
class ExitPupilAnalysisResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def evaluate_exit_pupil(trace: TraceBundle, options: ExitPupilAnalysisOptions | dict[str, Any] | None = None) -> ExitPupilAnalysisResult:
    if isinstance(options, ExitPupilAnalysisOptions):
        opts = options
    else:
        raw = dict(options or {})
        opts = ExitPupilAnalysisOptions(
            wavelength_nm=float(raw.get("wavelength_nm", 550.0)),
            grid_size=int(raw.get("pupil_grid_size", raw.get("grid_size", 257))),
            extent_scale=float(raw.get("pupil_extent_scale", raw.get("extent_scale", 1.04))),
            radial_bins=int(raw.get("radial_bins", 64)),
            normalize=bool(raw.get("normalize", True)),
            wavefront_fit_order=int(raw.get("wavefront_fit_order", 2)),
        )
    formal = formal_complex_field_reconstructor().reconstruct(
        trace,
        ComplexFieldReconstructionRequest(
            wavelength_nm=opts.wavelength_nm,
            grid_size=opts.grid_size,
            extent_scale=opts.extent_scale,
            opl_fit_order=opts.wavefront_fit_order,
            normalize_power=opts.normalize,
        ),
    )
    axisymmetric = reconstruct_axisymmetric_field(formal.field, radial_bins=opts.radial_bins)
    cartesian = reconstruct_cartesian_field(formal.field, normalize_power=False)
    return ExitPupilAnalysisResult(
        metrics=merge_unique_mappings(
            formal.metrics, axisymmetric.metrics, cartesian.metrics, collection="exit_pupil.metrics"
        ),
        arrays=merge_unique_mappings(
            formal.arrays, axisymmetric.arrays, cartesian.arrays, collection="exit_pupil.arrays"
        ),
        warnings=[*formal.warnings, *axisymmetric.warnings, *cartesian.warnings],
        metadata={
            "analysis": "exit_pupil",
            **formal.metadata,
            "reconstruction_interface": "ComplexFieldReconstructor",
            "formal_reconstructor": formal_complex_field_reconstructor().name,
            "ray_deposition_used": False,
        },
    )

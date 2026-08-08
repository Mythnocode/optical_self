
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.physics.wave.solvers.advanced_propagation import (
    PropagationResult,
    SamplingDiagnostics,
    _angular_spectrum_transfer,
    _edge_power_fraction_from_intensity,
    _field_power,
    _make_field,
    _nyquist_margin_from_phase_step,
    zero_pad_field,
)
from optical_core.physics.wave.solvers.workspace import (
    PropagationWorkspacePool,
    global_propagation_workspace_pool,
)


@dataclass(frozen=True, slots=True)
class UnifiedBatchIndex:
    design: int = 0
    wavelength: int = 0
    perturbation: int = 0
    focus: int = 0

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.design, self.wavelength, self.perturbation, self.focus)


@dataclass(frozen=True, slots=True)
class UnifiedPropagationInput:


    field: ScalarField2D
    distances_mm: tuple[float, ...]
    design_index: int = 0
    wavelength_index: int = 0
    perturbation_index: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "distances_mm", tuple(float(v) for v in self.distances_mm))
        if any(v < 0.0 for v in self.distances_mm):
            raise ValueError("current forward propagation interface requires distance_mm >= 0")


@dataclass(frozen=True, slots=True)
class UnifiedPropagationRecord:
    index: UnifiedBatchIndex
    distance_mm: float
    value: Any
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UnifiedPropagationBatchResult:
    records: tuple[UnifiedPropagationRecord, ...]
    axis_sizes: tuple[int, int, int, int]
    input_field_count: int
    forward_fft_count: int
    plane_count: int
    elapsed_s: float
    retained_fields: bool
    workspace_info: Mapping[str, int]

    def by_index(self) -> dict[tuple[int, int, int, int], Any]:
        return {record.index.as_tuple(): record.value for record in self.records}


MetricReducer = Callable[
    [UnifiedBatchIndex, np.ndarray, ScalarField2D, SamplingDiagnostics, Mapping[str, Any]], Any
]


def _default_metrics_reducer(
    index: UnifiedBatchIndex,
    output: np.ndarray,
    field: ScalarField2D,
    diagnostics: SamplingDiagnostics,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    del index, output, field
    return {
        "diagnostics": dict(diagnostics.metrics),
        "warnings": tuple(diagnostics.warnings),
        "metadata": dict(metadata),
    }


def propagate_unified_batch(
    inputs: Sequence[UnifiedPropagationInput] | Iterable[UnifiedPropagationInput],
    *,
    zero_padding_factor: float = 2.0,
    band_limited: bool = False,
    transfer_model: str = "exact",
    edge_power_threshold: float = 1.0e-4,
    energy_closure_threshold: float = 5.0e-3,
    nyquist_margin_min: float = 1.0,
    retain_fields: bool = False,
    reducer: MetricReducer | None = None,
    workspace_pool: PropagationWorkspacePool | None = None,
) -> UnifiedPropagationBatchResult:


    started = time.perf_counter()
    items = tuple(inputs)
    pool = workspace_pool or global_propagation_workspace_pool()
    reduce_output = reducer or _default_metrics_reducer
    records: list[UnifiedPropagationRecord] = []
    max_design = max((item.design_index for item in items), default=-1)
    max_wavelength = max((item.wavelength_index for item in items), default=-1)
    max_perturbation = max((item.perturbation_index for item in items), default=-1)
    max_focus = -1
    plane_count = 0

    for item in items:
        working = zero_pad_field(item.field, zero_padding_factor)
        values = np.asarray(working.values, dtype=np.complex128)
        input_power = _field_power(values, working.grid.dx_mm, working.grid.dy_mm)
        with pool.acquire(values.shape) as workspace:
            workspace.fft2(values)
            for focus_index, distance_mm in enumerate(item.distances_mm):
                max_focus = max(max_focus, focus_index)
                plane_count += 1
                transfer, transfer_metrics = _angular_spectrum_transfer(
                    nx=values.shape[1], ny=values.shape[0],
                    dx_mm=working.grid.dx_mm, dy_mm=working.grid.dy_mm,
                    wavelength_nm=working.wavelength_nm,
                    refractive_index=working.refractive_index,
                    distance_mm=distance_mm,
                    band_limited=band_limited,
                    transfer_model=transfer_model,
                )
                output = workspace.propagate_spectrum(transfer)
                intensity = workspace.update_intensity(output)
                output_power = float(
                    np.sum(intensity) * abs(working.grid.dx_mm * working.grid.dy_mm)
                )
                edge_fraction = _edge_power_fraction_from_intensity(intensity)
                closure = abs(output_power - input_power) / max(abs(input_power), 1.0e-30)
                nyquist_margin = _nyquist_margin_from_phase_step(
                    transfer_metrics["max_transfer_phase_step_x_rad"],
                    transfer_metrics["max_transfer_phase_step_y_rad"],
                )
                warnings: list[str] = []
                if edge_fraction > float(edge_power_threshold):
                    warnings.append(
                        f"输出边缘功率占比 {edge_fraction:.3g} 超过阈值 {edge_power_threshold:.3g}。"
                    )
                if nyquist_margin < float(nyquist_margin_min):
                    warnings.append(
                        f"角谱传递函数 Nyquist 余量 {nyquist_margin:.3g} 小于要求 {nyquist_margin_min:.3g}。"
                    )
                if closure > float(energy_closure_threshold):
                    warnings.append(
                        f"角谱传播能量闭合误差 {closure:.3g} 超过阈值 {energy_closure_threshold:.3g}。"
                    )
                method = "band_limited_angular_spectrum" if band_limited else "angular_spectrum"
                metrics = {
                    **transfer_metrics,
                    "zero_padding_factor": float(zero_padding_factor),
                    "input_power_a.u.": float(input_power),
                    "output_power_a.u.": float(output_power),
                    "energy_closure_error": float(closure),
                    "power_capture_ratio": float(output_power / max(abs(input_power), 1.0e-30)),
                    "nyquist_margin_min": float(nyquist_margin),
                    "energy_closure_pass": bool(closure <= float(energy_closure_threshold)),
                    "nyquist_pass": bool(nyquist_margin >= float(nyquist_margin_min)),
                    "edge_power_fraction": float(edge_fraction),
                    "batch_forward_fft_reused": True,
                }
                diagnostics = SamplingDiagnostics(method=method, metrics=metrics, warnings=tuple(warnings))
                index = UnifiedBatchIndex(
                    design=int(item.design_index),
                    wavelength=int(item.wavelength_index),
                    perturbation=int(item.perturbation_index),
                    focus=int(focus_index),
                )
                record_metadata = {
                    **dict(item.metadata),
                    "method": method,
                    "transfer_model": str(transfer_model),
                    "batch_forward_fft_reused": True,
                }
                if retain_fields:
                    out_field = _make_field(
                        working, output.copy(), working.grid, working.z_mm + float(distance_mm)
                    )
                    value: Any = PropagationResult(
                        field=out_field,
                        diagnostics=diagnostics,
                        metadata=record_metadata,
                    )
                else:
                    value = reduce_output(index, output, working, diagnostics, record_metadata)
                records.append(UnifiedPropagationRecord(
                    index=index,
                    distance_mm=float(distance_mm),
                    value=value,
                    metadata=record_metadata,
                ))

    return UnifiedPropagationBatchResult(
        records=tuple(records),
        axis_sizes=(max_design + 1, max_wavelength + 1, max_perturbation + 1, max_focus + 1),
        input_field_count=len(items),
        forward_fft_count=len(items),
        plane_count=int(plane_count),
        elapsed_s=float(time.perf_counter() - started),
        retained_fields=bool(retain_fields),
        workspace_info=pool.info(),
    )


__all__ = [
    "UnifiedBatchIndex",
    "UnifiedPropagationInput",
    "UnifiedPropagationRecord",
    "UnifiedPropagationBatchResult",
    "MetricReducer",
    "propagate_unified_batch",
]

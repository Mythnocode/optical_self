
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .form_state import SimulationFormState


class DirtyScope(IntEnum):
    CLEAN = 0
    ANALYSIS_PLAN = 1
    COUPLING = 2
    WAVE_PROPAGATION = 3
    RAY_TRACE = 4
    FULL_SIMULATION = 5


@dataclass(frozen=True, slots=True)
class DirtyState:
    scope: DirtyScope = DirtyScope.CLEAN
    reason: str = "正式结果与当前参数一致"

    @property
    def is_dirty(self) -> bool:
        return self.scope != DirtyScope.CLEAN


def classify_form_change(
    previous: SimulationFormState | None,
    current: SimulationFormState,
) -> DirtyState:
    if previous is None:
        return DirtyState(DirtyScope.FULL_SIMULATION, "尚未建立正式计算基线")
    if previous == current:
        return DirtyState()

    if previous.source != current.source or previous.system != current.system:
        return DirtyState(DirtyScope.RAY_TRACE, "光源或系统参数已修改")

    if previous.receiver != current.receiver:
        return DirtyState(DirtyScope.COUPLING, "光纤或五轴参数已修改")

    old_calc = previous.calculation
    new_calc = current.calculation
    propagation_fields_changed = (
        old_calc.precision != new_calc.precision
        or old_calc.output_grid_size != new_calc.output_grid_size
        or old_calc.pupil_sample_count != new_calc.pupil_sample_count
        or old_calc.propagation_model != new_calc.propagation_model
        or old_calc.zero_padding_factor != new_calc.zero_padding_factor
        or old_calc.output_extent_mm != new_calc.output_extent_mm
        or old_calc.sampling_convergence_enabled != new_calc.sampling_convergence_enabled
        or old_calc.save_large_arrays != new_calc.save_large_arrays
    )
    if propagation_fields_changed:
        return DirtyState(DirtyScope.WAVE_PROPAGATION, "采样或传播参数已修改")

    if (
        old_calc.analyses != new_calc.analyses
        or old_calc.only_visible_results != new_calc.only_visible_results
        or old_calc.include_energy_audit != new_calc.include_energy_audit
        or previous.alignment != current.alignment
    ):
        return DirtyState(DirtyScope.ANALYSIS_PLAN, "正式分析项目已修改")

    return DirtyState(DirtyScope.FULL_SIMULATION, "正式输入已修改")


__all__ = ["DirtyScope", "DirtyState", "classify_form_change"]

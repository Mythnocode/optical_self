
from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .form_state import SimulationFormState

_LAYOUT_ANALYSES = frozenset({"raytrace"})


def state_for_analyses(
    state: SimulationFormState,
    analyses: Iterable[str],
) -> SimulationFormState:


    planned = tuple(sorted({str(item) for item in analyses if str(item)})) or ("raytrace",)
    calculation = state.calculation
    if frozenset(planned) == _LAYOUT_ANALYSES:
        calculation = replace(
            calculation,
            analyses=planned,
            pupil_sample_count=int(calculation.layout_pupil_sample_count),
            include_energy_audit=False,
            sampling_convergence_enabled=False,
            save_large_arrays=False,
        )
    else:
        calculation = replace(calculation, analyses=planned)
    return replace(state, calculation=calculation)


def is_layout_only(analyses: Iterable[str]) -> bool:
    return frozenset(str(item) for item in analyses if str(item)) == _LAYOUT_ANALYSES


__all__ = ["is_layout_only", "state_for_analyses"]

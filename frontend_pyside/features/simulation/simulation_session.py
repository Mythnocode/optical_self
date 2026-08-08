
from __future__ import annotations

from dataclasses import dataclass

from .dirty_state import DirtyScope, DirtyState, classify_form_change
from .form_state import SimulationFormState


@dataclass(slots=True)
class SimulationSession:
    clean_form_state: SimulationFormState | None = None
    dirty: DirtyState = DirtyState(DirtyScope.FULL_SIMULATION, "尚未运行正式计算")

    def mark_form(self, state: SimulationFormState) -> DirtyState:
        self.dirty = classify_form_change(self.clean_form_state, state)
        return self.dirty

    def mark_geometry(self) -> DirtyState:
        self.dirty = DirtyState(DirtyScope.FULL_SIMULATION, "光学表面或系统结构已修改")
        return self.dirty

    def accept(self, state: SimulationFormState) -> None:
        self.clean_form_state = state
        self.dirty = DirtyState()


__all__ = ["SimulationSession"]

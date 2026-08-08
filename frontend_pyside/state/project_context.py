from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from frontend_pyside.core.types import LensSurface, ProjectSnapshot
from frontend_pyside.presets.demo_780nm_four_lens import (
    DEFAULT_RECEIVER_MFD_UM,
    DEFAULT_WAVELENGTH_NM,
    FOUR_LENS_SURFACES,
    PROJECT_NAME,
    REFERENCE_COUPLING_EFFICIENCY,
    REFERENCE_GRID_SIZE,
)


def default_project() -> ProjectSnapshot:
    surfaces = [LensSurface(**dict(spec)) for spec in FOUR_LENS_SURFACES]
    return ProjectSnapshot(
        name=PROJECT_NAME,
        wavelength_nm=DEFAULT_WAVELENGTH_NM,
        receiver_mfd_um=DEFAULT_RECEIVER_MFD_UM,
        surfaces=surfaces,
        metrics={
            "reference_coupling_efficiency": REFERENCE_COUPLING_EFFICIENCY,
            "reference_grid_size": REFERENCE_GRID_SIZE,
        },
    )


class ProjectContext(QObject):


    project_changed = Signal(object)
    metrics_changed = Signal(dict)
    dirty_changed = Signal(bool)
    version_changed = Signal(str)
    formal_result_changed = Signal(object)
    selection_changed = Signal(str, str)
    research_profile_changed = Signal(dict)
    simulation_project_payload_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = default_project()
        self._dirty = False
        self._formal_result = None
        self._selected_element_id = ""
        self._selected_surface_id = ""
        self._research_profile: dict = {}
        self._simulation_project_payload: dict = {}

    @property
    def project(self) -> ProjectSnapshot:
        return self._project

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def formal_result(self):
        return self._formal_result

    @property
    def selected_element_id(self) -> str:
        return self._selected_element_id

    @property
    def selected_surface_id(self) -> str:
        return self._selected_surface_id

    @property
    def research_profile(self) -> dict:
        return deepcopy(self._research_profile)

    @property
    def simulation_project_payload(self) -> dict:

        return deepcopy(self._simulation_project_payload)

    def set_project(self, project: ProjectSnapshot, *, dirty: bool = False) -> None:
        project.ensure_stable_ids()
        self._project = project
        self._formal_result = None
        self._research_profile = {}
        self._simulation_project_payload = {}
        self._set_dirty(dirty)
        self.project_changed.emit(project)
        self.formal_result_changed.emit(None)
        self.research_profile_changed.emit({})
        self.simulation_project_payload_changed.emit({})

    def update_metrics(self, metrics: dict) -> None:
        self._project.metrics.update(dict(metrics or {}))
        snapshot = dict(self._project.metrics)
        self.metrics_changed.emit(snapshot)
        self.project_changed.emit(self._project)

    def replace_surfaces(self, surfaces: list[LensSurface], *, mark_dirty: bool = True) -> None:
        for surface in surfaces:
            surface.__post_init__()
        self._project.surfaces = list(surfaces)
        self._set_dirty(mark_dirty)
        self.project_changed.emit(self._project)

    def update_surface(self, surface_id: str, **changes) -> LensSurface | None:
        wanted = str(surface_id or "")
        for index, surface in enumerate(self._project.surfaces):
            if surface.surface_id != wanted:
                continue
            protected = {"surface_id", "element_id", "group_id"}
            values = {key: value for key, value in changes.items() if key not in protected}
            updated = replace(surface, **values)
            updated.surface_id = surface.surface_id
            updated.element_id = surface.element_id
            updated.group_id = surface.group_id
            self._project.surfaces[index] = updated
            self._set_dirty(True)
            self.project_changed.emit(self._project)
            return deepcopy(updated)
        return None

    def reverse_element(self, element_id: str) -> bool:
        wanted = str(element_id or "")
        indices = [
            index
            for index, surface in enumerate(self._project.surfaces)
            if surface.element_id == wanted
        ]
        if len(indices) < 2:
            return False
        values = [self._project.surfaces[index] for index in indices][::-1]
        for target, value in zip(indices, values):
            self._project.surfaces[target] = value
        self._set_dirty(True)
        self.project_changed.emit(self._project)
        return True

    def select(self, *, element_id: str = "", surface_id: str = "") -> None:
        element_id = str(element_id or "")
        surface_id = str(surface_id or "")
        if (
            element_id == self._selected_element_id
            and surface_id == self._selected_surface_id
        ):
            return
        self._selected_element_id = element_id
        self._selected_surface_id = surface_id
        self.selection_changed.emit(element_id, surface_id)

    def set_formal_result(self, result, *, metrics: dict | None = None) -> None:
        self._formal_result = result
        if metrics:
            self._project.metrics.update(dict(metrics))
            self.metrics_changed.emit(dict(self._project.metrics))
        self._set_dirty(False)
        self.formal_result_changed.emit(result)
        self.project_changed.emit(self._project)


    def set_simulation_project_payload(self, payload: dict | None) -> None:
        snapshot = deepcopy(dict(payload or {}))
        if snapshot == self._simulation_project_payload:
            return
        self._simulation_project_payload = snapshot
        self.simulation_project_payload_changed.emit(deepcopy(snapshot))

    def update_research_profile(self, profile: dict | None = None, **changes) -> dict:

        merged = dict(self._research_profile)
        if profile is not None:
            merged.update(dict(profile))
        merged.update(changes)
        if merged == self._research_profile:
            return deepcopy(merged)
        self._research_profile = merged
        snapshot = deepcopy(merged)
        self.research_profile_changed.emit(snapshot)
        return snapshot

    def clear_research_profile(self) -> None:
        if not self._research_profile:
            return
        self._research_profile = {}
        self.research_profile_changed.emit({})

    def mark_dirty(self) -> None:
        self._set_dirty(True)

    def save_version(self) -> str:
        try:
            number = int(str(self._project.version).lstrip("v")) + 1
        except ValueError:
            number = 2
        self._project.version = f"v{number}"
        self._set_dirty(False)
        self.version_changed.emit(self._project.version)
        self.project_changed.emit(self._project)
        return self._project.version

    def touch_version(self) -> None:
        self.save_version()

    def new_project_identity(self) -> None:
        self._project.project_id = f"project_{uuid4().hex}"
        self.project_changed.emit(self._project)

    def _set_dirty(self, dirty: bool) -> None:
        dirty = bool(dirty)
        if dirty == self._dirty:
            return
        self._dirty = dirty
        self.dirty_changed.emit(dirty)


__all__ = ["ProjectContext", "default_project"]

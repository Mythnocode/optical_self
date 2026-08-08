from __future__ import annotations


class SimulationSelectionMixin:
    def _surface_selected_from_editor(self, index: int) -> None:
        group_id = self.editor.selected_group_id()
        self.results.set_selected_surface(int(index), group_id)

    def _surface_activated_from_editor(self, index: int) -> None:
        self.editor.select_surface(int(index), open_properties=True)
        self._surface_selected_from_editor(int(index))

    def _surface_selected_from_plot(self, index: int) -> None:
        self.editor.select_surface(int(index), open_properties=False)

    def _surface_activated_from_plot(self, index: int) -> None:
        self.editor.select_surface(int(index), open_properties=True)

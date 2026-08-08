from __future__ import annotations

from frontend_pyside.shared.plotting.canvas_view import zoom_axes_at_event

class CanvasInteractionMixin:
    def _capture_view_state(self) -> None:
        if self._axis is None:
            return
        try:
            state = {"kind": self._data.get("kind"), "xlim": self._axis.get_xlim(), "ylim": self._axis.get_ylim()}
            if hasattr(self._axis, "get_zlim"):
                state.update({"zlim": self._axis.get_zlim(), "elev": self._axis.elev, "azim": self._axis.azim})
            self._view_state = state
        except Exception:
            self._view_state = {}

    def _on_button_press(self, event) -> None:
        if self._axis is None:
            return
        kind = self._data.get("kind")
        if kind in {"bar", "barh"}:
            for artist, label in list(getattr(self, "_item_artists", [])):
                try:
                    contains, _details = artist.contains(event)
                except Exception:
                    contains = False
                if contains:
                    self.itemSelected.emit(str(label))
                    return
            return
        if kind == "beeswarm":
            if event.ydata is None:
                return
            labels = list(getattr(self, "_item_labels", []))
            index = int(round(float(event.ydata)))
            if 0 <= index < len(labels) and abs(float(event.ydata) - index) <= 0.55:
                self.itemSelected.emit(str(labels[index]))
            return
        if kind not in {"raytrace", "raytrace_section"}:
            return
        if event.xdata is None:
            return
        surfaces = list(self._data.get("surfaces", []))
        if not surfaces:
            return
        x_span = abs(self._axis.get_xlim()[1] - self._axis.get_xlim()[0])
        nearest = min(surfaces, key=lambda item: abs(float(item.get("z", 0.0)) - float(event.xdata)))
        distance = abs(float(nearest.get("z", 0.0)) - float(event.xdata))
        if distance > max(0.012 * x_span, 0.05):
            return
        index = int(nearest.get("surface_index", -1))
        if index < 0:
            return
        if bool(getattr(event, "dblclick", False)):
            self.surfaceActivated.emit(index)
        else:
            self.surfaceSelected.emit(index)

    def _on_scroll(self, event) -> None:
        if self._axis is None:
            return
        if self._data.get("kind") in {"optical_scene_3d", "raytrace3d"}:
            
            factor = 0.86 if event.button == "up" else 1.16
            for getter, setter in (
                (self._axis.get_xlim, self._axis.set_xlim),
                (self._axis.get_ylim, self._axis.set_ylim),
                (self._axis.get_zlim, self._axis.set_zlim),
            ):
                low, high = getter()
                centre = 0.5 * (low + high)
                half = 0.5 * (high - low) * factor
                setter(centre - half, centre + half)
            self.draw_idle()
            self.viewChanged.emit()
        elif zoom_axes_at_event(self._axis, event):
            self.draw_idle()
            self.viewChanged.emit()

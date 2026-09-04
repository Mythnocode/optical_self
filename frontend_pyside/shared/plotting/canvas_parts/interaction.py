from __future__ import annotations

from frontend_pyside.shared.plotting.canvas_view import apply_optical_scene_3d_zoom, zoom_axes_at_event


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
        # 中键拖动用于科研图窗平移；不占用左键的器件/表面选择。
        if getattr(event, "button", None) == 2 and event.xdata is not None and event.ydata is not None:
            try:
                self._pan_start = {
                    "x": float(event.xdata), "y": float(event.ydata),
                    "xlim": tuple(self._axis.get_xlim()), "ylim": tuple(self._axis.get_ylim()),
                }
                return
            except Exception:
                self._pan_start = None

        kind = self._data.get("kind")
        if kind == "parameter_response" and getattr(event, "button", None) == 1 and event.xdata is not None and event.ydata is not None:
            try:
                import numpy as np
                x = np.asarray(self._data.get("x", []), dtype=float)
                y = np.asarray(self._data.get("y", []), dtype=float)
                count = min(len(x), len(y))
                if count:
                    xspan = max(abs(float(self._axis.get_xlim()[1] - self._axis.get_xlim()[0])), 1e-12)
                    yspan = max(abs(float(self._axis.get_ylim()[1] - self._axis.get_ylim()[0])), 1e-12)
                    distance = ((x[:count] - float(event.xdata)) / xspan) ** 2 + ((y[:count] - float(event.ydata)) / yspan) ** 2
                    index = int(np.nanargmin(distance))
                    if float(distance[index]) <= 0.03 ** 2:
                        self.pointSelected.emit(float(x[index]), float(y[index]))
                        return
            except Exception:
                pass
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

    def _on_motion(self, event) -> None:
        state = getattr(self, "_pan_start", None)
        if not state or self._axis is None or event.xdata is None or event.ydata is None:
            return
        try:
            dx = float(event.xdata) - state["x"]
            dy = float(event.ydata) - state["y"]
            x0, x1 = state["xlim"]; y0, y1 = state["ylim"]
            self._axis.set_xlim(x0 - dx, x1 - dx)
            self._axis.set_ylim(y0 - dy, y1 - dy)
            self.draw_idle()
            self.viewChanged.emit()
        except Exception:
            return

    def _on_button_release(self, event) -> None:
        if getattr(event, "button", None) == 2:
            self._pan_start = None

    def _on_scroll(self, event) -> None:
        if self._axis is None:
            return
        if self._data.get("kind") in {"optical_scene_3d", "raytrace3d"}:
            # Do not shrink x/y/z limits: that silently clips L1/L4/fiber when users
            # only intend to make the 3D train larger on screen.  Scale the 3D box.
            current = float(getattr(self, "_optical_3d_zoom", 1.0) or 1.0)
            current *= 1.08 if event.button == "up" else 0.93
            self._optical_3d_zoom = max(0.66, min(1.22, current))
            apply_optical_scene_3d_zoom(self._axis, zoom=self._optical_3d_zoom)
            self.draw_idle()
            self.viewChanged.emit()
        elif zoom_axes_at_event(self._axis, event):
            self.draw_idle()
            self.viewChanged.emit()

    def zoom_by(self, factor: float) -> None:
        if self._axis is None:
            return
        factor = max(float(factor), 1.0e-3)
        if self._data.get("kind") in {"optical_scene_3d", "raytrace3d"}:
            current = float(getattr(self, "_optical_3d_zoom", 1.0) or 1.0) / factor
            self._optical_3d_zoom = max(0.66, min(1.22, current))
            apply_optical_scene_3d_zoom(self._axis, zoom=self._optical_3d_zoom)
            self.draw_idle(); self.viewChanged.emit(); return
        try:
            for getter, setter in ((self._axis.get_xlim, self._axis.set_xlim), (self._axis.get_ylim, self._axis.set_ylim)):
                low, high = getter(); centre = 0.5 * (low + high); half = 0.5 * (high - low) * factor
                setter(centre - half, centre + half)
            if hasattr(self._axis, "get_zlim"):
                low, high = self._axis.get_zlim(); centre = 0.5 * (low + high); half = 0.5 * (high - low) * factor
                self._axis.set_zlim(centre - half, centre + half)
            self.draw_idle(); self.viewChanged.emit()
        except Exception:
            return

    def set_physical_aspect(self, enabled: bool) -> None:
        if self._axis is None or hasattr(self._axis, "get_zlim"):
            return
        try:
            kind = str(self._data.get("kind", ""))
            if enabled:
                self._axis.set_aspect("equal", adjustable="box")
            elif kind in {"raytrace", "raytrace_section"}:
                self._axis.set_aspect("auto", adjustable="box")
            else:
                self._axis.set_aspect("auto", adjustable="box")
            self.draw_idle(); self.viewChanged.emit()
        except Exception:
            return

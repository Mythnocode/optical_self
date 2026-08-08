
from __future__ import annotations

from time import monotonic


class Optical3DInteractionController:


    def __init__(self, canvas, *, on_surface_selected=None, on_surface_activated=None):
        self.canvas = canvas
        self.on_surface_selected = on_surface_selected
        self.on_surface_activated = on_surface_activated
        self.high_quality_artists: list = []
        self.ray_collections: list = []
        self.pick_artists: dict[object, int] = {}
        self.dragging = False
        self._ray_alphas: dict[int, object] = {}
        self._last_motion_draw = 0.0
        self._last_click_time = 0.0
        self._last_surface = None
        self._connections = [
            canvas.mpl_connect("button_press_event", self._press),
            canvas.mpl_connect("button_release_event", self._release),
            canvas.mpl_connect("motion_notify_event", self._motion),
            canvas.mpl_connect("pick_event", self._pick),
        ]

    def update_artists(self, *, high_quality, ray_collections, pick_artists) -> None:
        self.high_quality_artists = list(high_quality)
        self.ray_collections = list(ray_collections)
        self.pick_artists = dict(pick_artists)

    def clear(self) -> None:
        self.update_artists(high_quality=[], ray_collections=[], pick_artists={})

    def _press(self, event) -> None:
        if getattr(event, "button", None) not in (1, 2, 3):
            return
        self.dragging = True
        for artist in self.high_quality_artists:
            try:
                artist.set_visible(False)
            except Exception:
                continue
        self._ray_alphas = {}
        for collection in self.ray_collections:
            try:
                self._ray_alphas[id(collection)] = collection.get_alpha()
                collection.set_alpha(0.22)
            except Exception:
                continue
        self._last_motion_draw = monotonic()
        self.canvas.draw_idle()

    def _release(self, _event) -> None:
        if not self.dragging:
            return
        self.dragging = False
        for artist in self.high_quality_artists:
            try:
                artist.set_visible(True)
            except Exception:
                continue
        for collection in self.ray_collections:
            try:
                collection.set_alpha(self._ray_alphas.get(id(collection)))
            except Exception:
                continue
        self._ray_alphas = {}
        self.canvas.draw_idle()

    def _motion(self, _event) -> None:
        if not self.dragging:
            return
        now = monotonic()
        
        
        if now - self._last_motion_draw < 1.0 / 30.0:
            return
        self._last_motion_draw = now
        self.canvas.draw_idle()

    def _pick(self, event) -> None:
        surface_index = self.pick_artists.get(getattr(event, "artist", None))
        if surface_index is None:
            return
        now = monotonic()
        double = self._last_surface == surface_index and now - self._last_click_time <= 0.42
        self._last_surface = surface_index
        self._last_click_time = now
        if double and self.on_surface_activated:
            self.on_surface_activated(int(surface_index))
        elif self.on_surface_selected:
            self.on_surface_selected(int(surface_index))


__all__ = ["Optical3DInteractionController"]

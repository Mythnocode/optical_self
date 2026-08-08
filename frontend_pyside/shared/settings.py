
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6.QtCore import QObject, QSettings, Signal


DISPLAY_MODES = ("标准", "紧凑", "大字体")
RENDER_QUALITIES = ("性能优先", "平衡", "质量优先")


@dataclass(frozen=True, slots=True)
class RenderProfile:
    representative_rays: int
    surface_samples: int
    animation_enabled: bool
    thumbnails_expanded: bool
    max_log_rows: int
    idle_preload: bool


_RENDER_PROFILES = {
    "性能优先": RenderProfile(7, 24, False, False, 500, True),
    "平衡": RenderProfile(15, 40, True, False, 1200, True),
    "质量优先": RenderProfile(31, 72, True, True, 2500, False),
}


class UiPreferences(QObject):
    display_mode_changed = Signal(str)
    render_quality_changed = Signal(str)

    def __init__(self, settings: QSettings | None = None, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings or QSettings("Optical ML Platform", "OpticalFrontend")
        self._display_mode = self._validated(
            self.settings.value("ui/display_mode", "标准", type=str), DISPLAY_MODES, "标准"
        )
        self._render_quality = self._validated(
            self.settings.value("ui/render_quality", "平衡", type=str),
            RENDER_QUALITIES,
            "平衡",
        )

    @property
    def display_mode(self) -> str:
        return self._display_mode

    @property
    def render_quality(self) -> str:
        return self._render_quality

    @property
    def render_profile(self) -> RenderProfile:
        return _RENDER_PROFILES[self._render_quality]

    def set_display_mode(self, value: str) -> None:
        value = self._validated(value, DISPLAY_MODES, "标准")
        if value == self._display_mode:
            return
        self._display_mode = value
        self.settings.setValue("ui/display_mode", value)
        self.display_mode_changed.emit(value)

    def set_render_quality(self, value: str) -> None:
        value = self._validated(value, RENDER_QUALITIES, "平衡")
        if value == self._render_quality:
            return
        self._render_quality = value
        self.settings.setValue("ui/render_quality", value)
        self.render_quality_changed.emit(value)

    @staticmethod
    def _validated(value: str, allowed: Iterable[str], fallback: str) -> str:
        text = str(value or "")
        return text if text in set(allowed) else fallback


class WorkspaceStateStore:


    def __init__(self, namespace: str, settings: QSettings | None = None) -> None:
        self.namespace = str(namespace).strip("/")
        self.settings = settings or QSettings("Optical ML Platform", "OpticalFrontend")

    def _key(self, suffix: str) -> str:
        return f"workspace/{self.namespace}/{suffix}"

    def save_splitter(self, name: str, splitter) -> None:
        self.settings.setValue(self._key(f"splitter/{name}"), splitter.saveState())

    def restore_splitter(self, name: str, splitter, fallback_sizes: list[int]) -> None:
        value = self.settings.value(self._key(f"splitter/{name}"))
        restored = bool(value) and splitter.restoreState(value)
        if not restored:
            splitter.setSizes([int(item) for item in fallback_sizes])

    def save_tab(self, name: str, tab_widget) -> None:
        self.settings.setValue(self._key(f"tab/{name}"), int(tab_widget.currentIndex()))

    def restore_tab(self, name: str, tab_widget, fallback: int = 0) -> None:
        index = self.settings.value(self._key(f"tab/{name}"), fallback, type=int)
        if 0 <= index < tab_widget.count():
            tab_widget.setCurrentIndex(index)

    def save_drawer(self, name: str, expanded: bool) -> None:
        self.settings.setValue(self._key(f"drawer/{name}"), bool(expanded))

    def drawer(self, name: str, fallback: bool = False) -> bool:
        return self.settings.value(self._key(f"drawer/{name}"), fallback, type=bool)


    def save_geometry(self, name: str, window) -> None:
        self.settings.setValue(self._key(f"geometry/{name}"), window.saveGeometry())

    def restore_geometry(self, name: str, window) -> bool:
        value = self.settings.value(self._key(f"geometry/{name}"))
        return bool(value) and bool(window.restoreGeometry(value))

    def save_table(self, name: str, table) -> None:
        header = table.horizontalHeader()
        self.settings.setValue(self._key(f"table/{name}/header"), header.saveState())

    def restore_table(self, name: str, table) -> None:
        value = self.settings.value(self._key(f"table/{name}/header"))
        if value:
            table.horizontalHeader().restoreState(value)


__all__ = [
    "DISPLAY_MODES",
    "RENDER_QUALITIES",
    "RenderProfile",
    "UiPreferences",
    "WorkspaceStateStore",
]

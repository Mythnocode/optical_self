from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot, Qt
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .teaching_scene_model import TeachingOpticalMetrics, TeachingOpticalState


class _Teaching3DBridge(QObject):
    changed = Signal()
    focusChanged = Signal()
    viewNameChanged = Signal()
    objectActivated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._focus = "fiber"
        self._view_name = "isometric"
        self._fiber_x = 310.0
        self._fiber_y = 0.0
        self._fiber_z = 60.0
        self._input_radius = 18.0
        self._end_radius = 6.0
        self._show_envelope = True
        self._show_main_ray = True
        self._show_axis = True

    @Property(str, notify=focusChanged)
    def focusKey(self): return self._focus
    @Property(str, notify=viewNameChanged)
    def viewName(self): return self._view_name
    @Property(float, notify=changed)
    def fiberX(self): return self._fiber_x
    @Property(float, notify=changed)
    def fiberY(self): return self._fiber_y
    @Property(float, notify=changed)
    def fiberZ(self): return self._fiber_z
    @Property(float, notify=changed)
    def inputRadius(self): return self._input_radius
    @Property(float, notify=changed)
    def endRadius(self): return self._end_radius
    @Property(bool, notify=changed)
    def showEnvelope(self): return self._show_envelope
    @Property(bool, notify=changed)
    def showMainRay(self): return self._show_main_ray
    @Property(bool, notify=changed)
    def showAxis(self): return self._show_axis

    def set_state(self, state: TeachingOpticalState, metrics: TeachingOpticalMetrics | None) -> None:
        self._fiber_x = 310.0 + float(getattr(state, "offset_z_um", 0.0) or 0.0) * 0.35
        self._fiber_y = float(getattr(state, "offset_x_um", 0.0) or 0.0) * 1.6
        self._fiber_z = 60.0 + float(getattr(state, "offset_y_um", 0.0) or 0.0) * 1.6
        self._input_radius = max(7.0, min(32.0, 12.0 + float(getattr(state, "input_beam_radius_mm", 1.0) or 1.0) * 9.0))
        radius = float(getattr(metrics, "beam_radius_at_fiber_um", 3.0) or 3.0) if metrics is not None else 3.0
        self._end_radius = max(4.0, min(25.0, radius * 2.0))
        self.changed.emit()

    def set_focus(self, key: str) -> None:
        value = str(key or "")
        if value != self._focus:
            self._focus = value
            self.focusChanged.emit()

    def set_view(self, name: str) -> None:
        value = str(name or "isometric")
        if value != self._view_name:
            self._view_name = value
        self.viewNameChanged.emit()

    def set_layers(self, *, envelope=None, branches=None, axes=None, labels=None) -> None:
        if envelope is not None: self._show_envelope = bool(envelope)
        if axes is not None: self._show_axis = bool(axes)
        # Main ray is deliberately always present in teaching view; branches belong to measurement overlays.
        self._show_main_ray = True
        self.changed.emit()

    @Slot(str)
    def activateObject(self, key: str) -> None:
        self.objectActivated.emit(str(key))


class TeachingQuick3DView(QWidget):
    """True Qt Quick 3D teaching scene with GPU camera interaction and 3D beam geometry."""
    objectActivated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setMinimumHeight(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._quick = QQuickWidget(self)
        self._quick.setWindowFlags(Qt.WindowType.Widget)
        self._quick.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self._quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._quick.setClearColor("#F4F7FA")
        self._bridge = _Teaching3DBridge(self)
        self._bridge.objectActivated.connect(self.objectActivated)
        self._quick.rootContext().setContextProperty("teachingBridge", self._bridge)
        qml = Path(__file__).resolve().parents[2] / "resources" / "qml" / "teaching_optical_scene_3d.qml"
        self._quick.setSource(QUrl.fromLocalFile(str(qml)))
        layout.addWidget(self._quick)

    def set_state(self, state: TeachingOpticalState, metrics: TeachingOpticalMetrics) -> None:
        self._bridge.set_state(state, metrics)
    def set_instruments(self, instruments) -> None:
        # Measurement instruments remain 2D/overlay teaching elements for now.
        pass
    def set_focus(self, key: str) -> None:
        self._bridge.set_focus(key)
    def set_layers(self, **kwargs) -> None:
        self._bridge.set_layers(**kwargs)
    def set_view(self, name: str) -> None:
        self._bridge.set_view(name)
    def focus_selected(self) -> None:
        # Axis view is the clearest deterministic focus operation for the selected optical chain.
        self._bridge.set_view("axis")

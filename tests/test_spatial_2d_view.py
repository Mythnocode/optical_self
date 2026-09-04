from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QGraphicsSceneMouseEvent

from frontend_pyside.features.teaching.spatial_routing_upgrade import (
    FlexibleSpatialGraphicsView,
)
from frontend_pyside.features.teaching.unified_workbench import ExperimentNode


class _ViewModel:
    def __init__(self, nodes=None) -> None:
        self.nodes = dict(nodes or {})
        self.edges = {}
        self.selected_node_id = None
        self.selected_edge_id = None
        self.mode = "free"

    def scene_snapshot(self):
        metrics = SimpleNamespace(reached_node_ids=set(), path_node_ids=())
        return SimpleNamespace(
            metrics=metrics,
            current_radii={},
            ideal_radii={},
            formal_rays_mm=(),
        )


class Spatial2DViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _wheel(self, view, y=120):
        event = QWheelEvent(
            QPointF(400, 300), QPoint(400, 300), QPoint(0, y), QPoint(0, y),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        view.wheelEvent(event)

    def test_wheel_zoom_persists_across_model_refresh(self) -> None:
        model = _ViewModel()
        view = FlexibleSpatialGraphicsView()
        view.resize(900, 600)
        view.set_model(model, preserve_view=False)
        before = view.transform().m11()
        self._wheel(view)
        after = view.transform().m11()
        self.assertGreater(after, before)
        view.set_model(model, preserve_view=True)
        self.assertAlmostEqual(view.transform().m11(), after, places=4)
        view.deleteLater()

    def test_press_triggered_refresh_keeps_pressed_item_alive(self) -> None:
        model = _ViewModel({
            "n1": ExperimentNode(id="n1", kind="lens", label="透镜", x=640.0, y=310.0),
        })
        view = FlexibleSpatialGraphicsView()
        view.resize(900, 600)
        view.set_model(model, preserve_view=False)
        item = view._node_items["n1"]
        activated: list[str] = []

        def refresh_on_activate(node_id: str) -> None:
            activated.append(node_id)
            # Replicate the workbench: activating a node synchronously rebuilds
            # the view (scene refresh) while the press is still being handled.
            view.set_model(model, preserve_view=True)

        item.activated.connect(refresh_on_activate)
        press = QGraphicsSceneMouseEvent(QEvent.Type.MouseButtonPress)
        press.setScenePos(QPointF(item.pos()))
        press.setButton(Qt.MouseButton.LeftButton)
        press.setButtons(Qt.MouseButton.LeftButton)
        press.setModifiers(Qt.KeyboardModifier.NoModifier)
        item.mousePressEvent(press)
        self.assertEqual(activated, ["n1"])
        # The refresh ran inside the press handler; the pressed item must have
        # been reused rather than deleted (regression for "Internal C++ object
        # already deleted" raised by super().mousePressEvent()).
        self.assertIs(view._node_items["n1"], item)
        self.assertIs(item.scene(), view.scene_obj)
        view.deleteLater()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from frontend_pyside.features.teaching.spatial_routing_upgrade import (
    FlexibleSpatialGraphicsView,
    FlexibleSpatialExperimentModel,
)


class DragNoLiveTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_drag_move_does_not_start_live_trace_timer(self) -> None:
        model = FlexibleSpatialExperimentModel()
        view = FlexibleSpatialGraphicsView()
        view.resize(900, 600)
        view.set_model(model, preserve_view=False)
        node_id = next(iter(model.nodes))
        # 模拟拖拽中的位置变化回调
        view._on_item_position_changed(node_id)
        self.assertFalse(view._live_trace_timer.isActive())
        view.deleteLater()


if __name__ == "__main__":
    unittest.main()

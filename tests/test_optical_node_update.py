from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from frontend_pyside.features.teaching.unified_workbench import ExperimentNode, OpticalNodeItem


class OpticalNodeItemUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _item(self) -> OpticalNodeItem:
        node = ExperimentNode("n1", "lens", "L1", 100, 200, rotation_deg=0, params={"focal_mm": 50.0})
        item = OpticalNodeItem(node, True, display_layer="overlay")
        item.update_from_node(node, movable=True, display_layer="overlay", show_ports=False)
        return item

    def test_unchanged_update_does_not_repaint(self) -> None:
        item = self._item()
        node = ExperimentNode("n1", "lens", "L1", 100, 200, rotation_deg=0, params={"focal_mm": 50.0})
        calls = []
        original = item.update
        item.update = lambda *a, **k: calls.append(1)
        try:
            item.update_from_node(node, movable=True, display_layer="overlay", show_ports=False)
        finally:
            item.update = original
        self.assertEqual(calls, [])

    def test_changed_position_repaints(self) -> None:
        item = self._item()
        node = ExperimentNode("n1", "lens", "L1", 320, 240, rotation_deg=0, params={"focal_mm": 50.0})
        calls = []
        original = item.update
        item.update = lambda *a, **k: calls.append(1)
        try:
            item.update_from_node(node, movable=True, display_layer="overlay", show_ports=False)
        finally:
            item.update = original
        self.assertGreaterEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()

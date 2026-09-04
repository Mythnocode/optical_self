from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from frontend_pyside.features.teaching.quick3d_bridge import QML_PATH, TeachingQuick3DWidget


class Quick3DSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_qml_scene_loads(self) -> None:
        self.assertTrue(QML_PATH.is_file())
        widget = TeachingQuick3DWidget()
        self.assertTrue(widget.load_ok, widget.errors())
        self.assertIsNotNone(widget.rootObject())
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()

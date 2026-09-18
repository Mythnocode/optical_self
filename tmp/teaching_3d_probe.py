"""Render the teaching 3D view to a PNG for visual checks.

Runs on the real display (Quick3D needs a GPU context), so it must not be used
from the offscreen-only test suite.

Usage:  py -3 tmp/teaching_3d_probe.py <out.png> [lens_count] [selected_id] [preset]
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="optical-3d-probe-")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from frontend_pyside.features.teaching_v2.model import SceneStore
from frontend_pyside.features.teaching_v2.view3d import BenchView3D


def wait(ms: int = 250) -> None:
    QTest.qWait(ms)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tmp" / "teaching_3d.png"
    lens_count = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    selected = sys.argv[3] if len(sys.argv) > 3 else "lens-002"
    preset = sys.argv[4] if len(sys.argv) > 4 else ""

    app = QApplication.instance() or QApplication([])
    store = SceneStore()
    store.apply_optical_scheme(lens_count)
    if selected:
        store.select(selected)
    view = BenchView3D(store)
    view.resize(1400, 860)
    # The probe window sits on the real desktop: ignore the cursor so a stray
    # click cannot drag a component while the still is being rendered.
    view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    view.show()
    view._quick.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    for _ in range(20):
        wait(200)
    if preset == "top":
        view.look_top()
    else:
        view.reset_camera()
    for _ in range(8):
        wait(200)
    if preset.startswith("zoom"):
        # Pull the orbit camera in so the 13 mm gizmo is legible in a still.
        distance = float(preset[4:] or 42.0)
        for child in view._quick.rootObject().findChildren(QObject):
            if "PerspectiveCamera" in child.metaObject().className():
                child.setProperty("z", distance)
        for _ in range(6):
            wait(200)
    if preset == "close":
        from PySide6.QtGui import QVector3D

        for child in view._quick.rootObject().findChildren(QObject):
            if "PerspectiveCamera" in child.metaObject().className():
                pivot = child.parent()
                pivot.setProperty("position", QVector3D(
                    view.bridge.gizmoX, view.bridge.gizmoY, view.bridge.gizmoZ))
                pivot.setProperty("eulerRotation", QVector3D(-26.0, -36.0, 0.0))
                child.setProperty("z", 46.0)
        for _ in range(8):
            wait(200)
    print("quick3d ready:", view.is_quick3d_ready(), "components:", [
        (item.component_id, item.pose.x_mm) for item in store.components.values()
    ])
    print("gizmo:", view.bridge.gizmoVisible, (view.bridge.gizmoX, view.bridge.gizmoY, view.bridge.gizmoZ))
    print("tag text:", view.bridge.selectedLabel, "|", view.bridge.selectedPosition)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not view.grab().save(str(out)):
        raise SystemExit(f"failed to save {out}")
    print("saved", out)
    view.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

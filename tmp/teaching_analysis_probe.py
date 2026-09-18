"""Render the teaching 成像与耦合 popup with real engine numbers.

Usage:  py -3 tmp/teaching_analysis_probe.py <out.png> [lens_count]
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="optical-popup-probe-")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.workbench_shell import TeachingShell
from frontend_pyside.core.ui_theme import apply_application_theme


def wait(ms: int = 200) -> None:
    QTest.qWait(ms)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tmp" / "teaching_analysis.png"
    lens_count = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    app = QApplication.instance() or QApplication([])
    apply_application_theme(app)
    shell = TeachingShell(create_app_context())
    shell.resize(1400, 860)
    shell.show()
    for _ in range(10):
        wait(150)
    shell._apply_scheme(lens_count)
    wait(250)

    def finished() -> bool:
        status = str(shell.analysis_popup.status.text() or "") if shell.analysis_popup else ""
        return "正式计算完成" in status or "未完成" in status or "未命中" in status

    shell._toolbar_action("analysis")
    popup = shell.analysis_popup
    print("popup:", popup, "title:", popup.windowTitle())
    popup.run_button.click()
    wait(300)
    popup.grab().save(str(out.with_name(out.stem + "_busy" + out.suffix)))
    deadline = 420000
    while deadline > 0 and not finished():
        wait(300)
        deadline -= 300
    wait(400)
    popup.grab().save(str(out))
    print("status:", popup.status.text(), flush=True)
    print("imaging:", popup.imaging_summary.text(), "| available:", popup.imaging_visual.available)
    print("pills:", {k: v.text() for k, v in popup.coupling_pills.items()})
    print("detail:", popup.coupling_detail.text())
    print("notes:", popup.notes.text())
    print("saved", out)
    shell.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

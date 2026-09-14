"""Headless smoke check for TeachingShell.

Run from the project root with ``QT_QPA_PLATFORM=offscreen``.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.workbench_shell import TeachingShell


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    shell = TeachingShell(create_app_context())
    shell.resize(1280, 760)
    shell.show()
    app.processEvents()
    shell._toolbar_action("calculate")
    app.processEvents()
    shell.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Generate deterministic UI review screenshots of the live two-shell app.

Run with the Qt/PySide environment, for example:
  QT_QPA_PLATFORM=offscreen python tools/ui_visual_regression.py --out /tmp/ui-review
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="optical-ui-regression-settings-"))

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from frontend_pyside.app.bootstrap import create_main_window

SIZES = ((1366, 768), (1920, 1080))
MODULES = (
    ("home", None),
    ("simulation", "lens_data"),
    ("simulation", "coupling"),
    ("model", "dataset"),
    ("optimization", "opt_goal"),
    ("explainability", "global_contrib"),
    ("teaching", None),
)


def wait(ms: int = 220) -> None:
    QTest.qWait(ms)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def show_module(window, module: str, kind: str | None) -> str:
    if module == "teaching" or kind is None:
        window.navigate(module)
        wait(350)
        return module
    window.open_document(module, kind)
    wait(350)
    return f"{module}_{kind}"


def capture(window, out: Path, name: str) -> None:
    filename = name + ".png"
    if not window.grab().save(str(out / filename)):
        raise RuntimeError(f"failed to save {filename}")


def run_size(width: int, height: int, base_out: Path) -> None:
    out = base_out / f"{width}x{height}"
    out.mkdir(parents=True, exist_ok=True)
    window = create_main_window()
    window.resize(width, height)
    window.show()
    wait(500)
    if hasattr(window, "_pages") or getattr(window, "canvas_workspace", None) is not None:
        raise AssertionError("legacy page stack / canvas shell is still mounted")
    for module, kind in MODULES:
        name = show_module(window, module, kind)
        capture(window, out, name)
    window.close()
    wait(100)
    print(f"VISUAL_SIZE_OK {width}x{height} {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="ui_visual_regression")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    global app
    app = QApplication.instance() or QApplication([])
    for width, height in SIZES:
        run_size(width, height, out)
    print("UI_VISUAL_REGRESSION_OK")


if __name__ == "__main__":
    main()

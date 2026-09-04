"""Generate deterministic UI review screenshots and basic layout checks.

This is deliberately a visual/interaction regression helper rather than a unit test.
It renders the real PySide pages at the two screen sizes used during UI review and
checks a few rules that previously regressed: one page-owned scroll area on normal
analysis pages, stable model-training section, and no zero-sized plot workspace.

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

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.shared.components.errors import PageLoadErrorWidget

SIZES = ((1366, 768), (1920, 1080))
PAGES = ("optimization", "machine_learning", "explainability", "simulation", "tasks", "teaching")


def wait(ms: int = 220) -> None:
    QTest.qWait(ms)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def loaded_page(window, page_id: str):
    window.navigate(page_id, update_document=False)
    wait(450)
    holder = window._pages[page_id]
    page = holder.loaded_page
    if page is None:
        raise AssertionError(f"{page_id}: deferred page did not load")
    if isinstance(page, PageLoadErrorWidget):
        raise AssertionError(f"{page_id}: deferred page loaded an error widget")
    return page


def assert_analysis_scroll_policy(page_id: str, page) -> None:
    if page_id not in {"optimization", "machine_learning", "explainability"}:
        return
    visible = [item for item in page.findChildren(QScrollArea) if item.isVisible()]
    if len(visible) > 1:
        names = [item.objectName() or item.__class__.__name__ for item in visible]
        raise AssertionError(f"{page_id}: nested QScrollArea visible: {names}")


def assert_plot_slot(page_id: str, page) -> None:
    candidates = []
    for name in (
        "research_result_slot", "analysis_result", "shap_view_tabs",
        "results", "research_preview",
    ):
        widget = getattr(page, name, None)
        if widget is not None and widget.isVisible():
            candidates.append((name, widget))
    for name, widget in candidates:
        size = widget.size()
        if size.width() < 260 or size.height() < 180:
            raise AssertionError(f"{page_id}:{name} plot/result slot too small: {size.width()}x{size.height()}")


def capture(window, out: Path, page_id: str, suffix: str = "") -> None:
    name = page_id + (f"_{suffix}" if suffix else "") + ".png"
    if not window.grab().save(str(out / name)):
        raise RuntimeError(f"failed to save {name}")


def model_workflow_states(page, window, out: Path) -> None:
    buttons = list(getattr(page, "workflow_buttons", []) or [])
    stack = getattr(page, "workflow_stack", None)
    if len(buttons) != 5 or stack is None:
        raise AssertionError("machine_learning: integrated five-stage workflow missing")
    suffixes = ("overview", "data", "training", "comparison", "prediction")
    for index, suffix in enumerate(suffixes):
        buttons[index].click(); wait(140)
        if stack.currentIndex() != index:
            raise AssertionError(f"machine_learning: failed to switch to {suffix}")
        capture(window, out, "machine_learning", suffix)

def simulation_collapsed_state(page, window, out: Path) -> None:
    button = getattr(page, "parameter_toggle_button", None)
    splitter = getattr(page, "main_splitter", None)
    if button is None or splitter is None:
        return
    before = splitter.sizes()
    button.click(); wait(100)
    collapsed = splitter.sizes()
    capture(window, out, "simulation", "parameters_hidden")
    button.click(); wait(100)
    restored = splitter.sizes()
    if not collapsed or collapsed[0] > 8:
        raise AssertionError(f"simulation parameter panel did not collapse: {collapsed}")
    if not restored or restored[0] < 250:
        raise AssertionError(f"simulation parameter panel did not restore: {before} -> {restored}")


def run_size(width: int, height: int, base_out: Path) -> None:
    out = base_out / f"{width}x{height}"
    out.mkdir(parents=True, exist_ok=True)
    window = create_main_window()
    window.resize(width, height)
    window.show()
    wait(500)
    for page_id in PAGES:
        page = loaded_page(window, page_id)
        assert_analysis_scroll_policy(page_id, page)
        assert_plot_slot(page_id, page)
        capture(window, out, page_id)
        if page_id == "machine_learning":
            model_workflow_states(page, window, out)
        elif page_id == "simulation":
            simulation_collapsed_state(page, window, out)
    window.close(); wait(100)
    print(f"VISUAL_SIZE_OK {width}x{height} {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="ui_visual_regression")
    args = parser.parse_args()
    out = Path(args.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    global app
    app = QApplication.instance() or QApplication([])
    for width, height in SIZES:
        run_size(width, height, out)
    print("UI_VISUAL_REGRESSION_OK")


if __name__ == "__main__":
    main()

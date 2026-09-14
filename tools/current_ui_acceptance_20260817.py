"""Acceptance for the live two-shell workbench.

The 2026-08-17 compact-shell/page-stack checks are retired.  This script now
exercises MainWindow → WorkflowHome / WorkbenchShell / TeachingShell.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="optical-ui-accept-"))

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QLabel,
    QWidget,
)

from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.app.shell_catalog import CATEGORIES
from frontend_pyside.app.workbench_shell import PRIMARY_MODULES, TeachingShell, WorkbenchShell
from frontend_pyside.core.ui_theme import apply_application_theme


def wait(ms: int = 180) -> None:
    QTest.qWait(ms)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def fail(message: str) -> None:
    raise AssertionError(message)


def shot(widget: QWidget, out: Path, name: str) -> str:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    if not widget.grab().save(str(path)):
        fail(f"failed to save screenshot: {path}")
    return str(path)


def all_visible_text(root: QWidget) -> str:
    parts: list[str] = []
    for label in root.findChildren(QLabel):
        if label.isVisible() and label.text():
            parts.append(label.text())
    for button in root.findChildren(QAbstractButton):
        if button.isVisible() and button.text():
            parts.append(button.text())
    return "\n".join(parts)


def global_rect(widget: QWidget) -> QRect:
    return QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())


def assert_no_overlap(a: QWidget, b: QWidget, label: str) -> None:
    if not a.isVisible() or not b.isVisible():
        return
    inter = global_rect(a).intersected(global_rect(b))
    if inter.width() > 2 and inter.height() > 2:
        fail(f"{label}: overlap {inter.width()}x{inter.height()}")


def assert_two_shell_window(window) -> None:
    if hasattr(window, "_pages") or hasattr(window, "command_buttons") or hasattr(window, "open_feature_window"):
        fail("legacy page stack or command strip is still mounted")
    if not isinstance(window.workbench, WorkbenchShell) or not isinstance(window.teaching, TeachingShell):
        fail("live shells are not WorkbenchShell / TeachingShell")


def shell_and_home(window, out: Path, checks: list[str]) -> None:
    window.navigate("home")
    wait(220)
    assert_two_shell_window(window)
    if window.mode_stack.currentWidget() is not window.home:
        fail("home did not become the active shell")
    text = all_visible_text(window.home)
    if "光学研究工作流" not in text:
        fail("home does not show the workflow title")
    for forbidden in ("你现在想做什么", "当前工作", "任务记录"):
        if forbidden in text:
            fail(f"home still exposes removed landing block: {forbidden}")
    labels = [button.text() for button in window.primary.buttons.values()]
    expected = [title for _key, title in PRIMARY_MODULES]
    if labels != expected:
        fail(f"primary bar is not {expected}: {labels}")
    shot(window, out, "01_home")
    checks.append("PASS home: workflow map; primary bar is 首页/仿真/教学/模型/优化/解释")


def simulation(window, out: Path, checks: list[str]) -> None:
    window.navigate("simulation")
    wait(260)
    if window.mode_stack.currentWidget() is not window.workbench:
        fail("simulation did not open WorkbenchShell")
    window.workbench.open_document("simulation", "lens_data")
    wait(180)
    if "simulation:lens_data" not in window.workbench._tabs:
        fail("simulation lens table document did not open")
    shot(window, out, "02_simulation_lens")
    window.open_document("simulation", "coupling")
    wait(180)
    if "simulation:coupling" not in window.workbench._tabs:
        fail("simulation coupling document did not open")
    shot(window, out, "03_simulation_coupling")
    checks.append("PASS simulation: WorkbenchShell documents for lens table and coupling")


def optimization_and_model(window, out: Path, checks: list[str]) -> None:
    window.navigate("optimization")
    wait(180)
    window.workbench.open_document("optimization", "opt_goal")
    wait(160)
    if window.workbench.module != "optimization":
        fail("optimization module was not selected")
    shot(window, out, "04_optimization")
    window.navigate("model")
    wait(180)
    window.workbench.open_document("model", "dataset")
    wait(160)
    if window.workbench.module != "model":
        fail("model module was not selected")
    shot(window, out, "05_model")
    checks.append("PASS ordinary modules: optimization and model stay on WorkbenchShell")


def teaching(window, out: Path, checks: list[str]) -> None:
    window.navigate("teaching")
    wait(260)
    if window.mode_stack.currentWidget() is not window.teaching:
        fail("teaching did not open TeachingShell")
    text = all_visible_text(window.teaching)
    for required in ("器材库", "计算", "同步到仿真"):
        if required not in text:
            fail(f"teaching toolbar missing {required}")
    if "五大失配" in text:
        fail("teaching still exposes retired mismatch lessons")
    shot(window, out, "06_teaching")
    checks.append("PASS teaching: TeachingShell canvas with floating tools; no legacy page tabs")


def responsive(window, out: Path, checks: list[str]) -> None:
    sizes = [(1100, 720), (900, 650), (768, 1366)]
    for width, height in sizes:
        window.resize(width, height)
        wait(220)
        if window.width() > width + 2 or window.height() > height + 2:
            fail(f"window minimum size blocks {width}x{height}: actual {window.size()}")
        assistant = getattr(window, "assistant_button", None)
        if assistant is not None:
            assert_no_overlap(window.primary, assistant, f"primary/AI {width}x{height}")
        shot(window, out, f"07_responsive_{width}x{height}")
    window.resize(1366, 768)
    wait(160)
    checks.append("PASS responsive: 1100x720, 900x650, 768x1366 accepted")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "ui_acceptance_20260817"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    apply_application_theme(app)
    window = create_main_window()
    window.resize(1366, 768)
    window.show()
    wait(350)

    checks: list[str] = []
    status = "PASS"
    error = ""
    try:
        shell_and_home(window, out, checks)
        simulation(window, out, checks)
        optimization_and_model(window, out, checks)
        teaching(window, out, checks)
        responsive(window, out, checks)
    except Exception as exc:
        status = "FAIL"
        error = f"{type(exc).__name__}: {exc}"
    finally:
        window.close()
        wait(80)

    report = {
        "status": status,
        "checks": checks,
        "error": error,
        "product_title": "光学研究工作流",
        "primary_modules": [title for _key, title in PRIMARY_MODULES],
        "catalog_action_count": sum(len(actions) for c in CATEGORIES for _g, actions in c.groups),
        "note": "Old compact-shell / deferred-page stack has been removed.",
    }
    (out / "acceptance_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "acceptance_report.txt").write_text("\n".join([status, *checks, error]), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

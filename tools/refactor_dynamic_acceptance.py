"""Dynamic GUI acceptance for the two-shell workbench.

Checks hit testing, module switching, teaching canvas tools, and resize.
Screenshots are evidence, not decoration.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="optical-dyn-settings-"))
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractButton, QWidget

from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.app.workbench_shell import PRIMARY_MODULES, TeachingShell, WorkbenchShell


def wait(ms=180):
    QTest.qWait(ms)
    app = QApplication.instance()
    if app:
        app.processEvents()


def fail(msg):
    raise AssertionError(msg)


def current_shell(window):
    return window.mode_stack.currentWidget()


def shot(window, out: Path, name: str):
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    if not window.grab().save(str(path)):
        fail(f"failed screenshot {path}")
    return str(path)


def is_ancestor(ancestor: QWidget, widget: QWidget | None) -> bool:
    cur = widget
    while cur is not None:
        if cur is ancestor:
            return True
        cur = cur.parentWidget()
    return False


def assert_hittable(button: QAbstractButton, label: str):
    if not button.isVisible() or not button.isEnabled():
        fail(f"{label}: button not visible/enabled")
    center = button.rect().center()
    global_pos = button.mapToGlobal(center)
    hit = QApplication.widgetAt(global_pos)
    if hit is None:
        if button.width() < 16 or button.height() < 16:
            fail(f"{label}: invalid button geometry {button.size()}")
        return
    if not is_ancestor(button, hit):
        fail(f"{label}: click center covered by {hit.objectName() or hit.__class__.__name__}")


def global_rect(widget: QWidget) -> QRect:
    tl = widget.mapToGlobal(QPoint(0, 0))
    return QRect(tl, widget.size())


def assert_no_widget_overlap(a: QWidget, b: QWidget, scope: str, tolerance: int = 2):
    if not a.isVisible() or not b.isVisible():
        return
    inter = global_rect(a).intersected(global_rect(b))
    if inter.width() > tolerance and inter.height() > tolerance:
        fail(f"{scope}: overlap {inter.width()}x{inter.height()}")


def assert_no_pair_overlap(buttons, scope: str):
    rows = []
    for b in buttons:
        if not b.isVisible():
            continue
        tl = b.mapToGlobal(QPoint(0, 0))
        r = QRect(tl, b.size())
        rows.append((b, r))
    for i, (a, ra) in enumerate(rows):
        for b, rb in rows[i + 1:]:
            inter = ra.intersected(rb)
            if inter.width() > 2 and inter.height() > 2:
                fail(f"{scope}: {a.text()} overlaps {b.text()} by {inter.width()}x{inter.height()}")


def click(button, label):
    assert_hittable(button, label)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    wait(160)


def shell_checks(window, report):
    if hasattr(window, "_pages") or hasattr(window, "command_buttons"):
        fail("legacy page stack / command strip still present")
    if not isinstance(window.workbench, WorkbenchShell) or not isinstance(window.teaching, TeachingShell):
        fail("live shells are not WorkbenchShell / TeachingShell")
    buttons = list(window.primary.buttons.values())
    expected = [title for _key, title in PRIMARY_MODULES]
    actual = [b.text() for b in buttons]
    if actual != expected:
        fail(f"primary bar should be {expected}: {actual}")
    assert_no_pair_overlap(buttons, "primary bar")
    for key, button in window.primary.buttons.items():
        assert_hittable(button, f"primary:{key}")
    assistant = getattr(window, "assistant_button", None)
    if assistant is not None:
        assert_hittable(assistant, "floating assistant")
        assert_no_widget_overlap(window.primary, assistant, "primary vs AI")
    report.append("PASS two-shell primary bar is hittable; old page stack is gone")


def home_checks(window, out, report):
    window.navigate("home")
    wait(220)
    if current_shell(window) is not window.home:
        fail("home: workflow map is not active")
    title = window.home.findChild(QWidget, "HomeTitle")
    if title is None or not title.isVisible():
        fail("home: platform title missing")
    shot(window, out, "home_workflow")
    report.append("PASS homepage is the workflow map")


def simulation_checks(window, out, report):
    click(window.primary.buttons["simulation"], "primary:simulation")
    if current_shell(window) is not window.workbench:
        fail("simulation: WorkbenchShell not active")
    window.workbench.open_document("simulation", "lens_data")
    wait(180)
    shot(window, out, "simulation_lens")
    window.open_document("simulation", "coupling")
    wait(180)
    shot(window, out, "simulation_coupling")
    if "simulation:coupling" not in window.workbench._tabs:
        fail("simulation coupling document missing")
    report.append("PASS simulation stays on WorkbenchShell with document tabs")


def optimization_checks(window, out, report):
    window.navigate("optimization")
    wait(180)
    window.workbench.open_document("optimization", "opt_goal")
    wait(160)
    shot(window, out, "optimization_goal")
    if window.workbench.module != "optimization":
        fail("optimization module not selected")
    assistant = getattr(window, "assistant_button", None)
    if assistant is not None:
        assert_no_widget_overlap(assistant, window.workbench.object_rail, "AI launcher vs object rail")
    report.append("PASS optimization remains an ordinary WorkbenchShell module")


def ml_checks(window, out, report):
    window.navigate("model")
    wait(180)
    window.workbench.open_document("model", "dataset")
    wait(160)
    shot(window, out, "model_dataset")
    window.workbench.open_document("model", "predict")
    wait(160)
    shot(window, out, "model_predict")
    if window.workbench.module != "model":
        fail("model module not selected")
    report.append("PASS model module opens dataset and prediction documents")


def teaching_checks(window, out, report):
    click(window.primary.buttons["teaching"], "primary:teaching")
    if current_shell(window) is not window.teaching:
        fail("teaching: TeachingShell not active")
    if getattr(window.teaching, "store", None) is None:
        fail("teaching has no scene store")
    window.teaching._toolbar_action("equipment")
    wait(160)
    if window.teaching.equipment_popup is None or not window.teaching.equipment_popup.isVisible():
        fail("teaching equipment popup did not open")
    shot(window, out, "teaching_v2")
    report.append("PASS teaching V2 canvas opened; legacy page tabs are absent")


def responsive_checks(window, out, report):
    for w, h, name in ((1366, 768, "landscape_1366"), (1100, 720, "landscape_1100"), (768, 1366, "portrait_rotated"), (1920, 1080, "landscape_1920")):
        window.resize(w, h)
        wait(300)
        shell_checks(window, [])
        shot(window, out, f"responsive_{name}")
    report.append("PASS resize/orientation checks 1366x768, 1100x720, 768x1366, 1920x1080")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="acceptance/final_dynamic")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    report = []
    errors = []
    window = create_main_window()
    window.resize(1366, 768)
    window.show()
    wait(500)
    checks = [
        ("shell", lambda: shell_checks(window, report)),
        ("home", lambda: home_checks(window, out, report)),
        ("simulation", lambda: simulation_checks(window, out, report)),
        ("optimization", lambda: optimization_checks(window, out, report)),
        ("machine_learning", lambda: ml_checks(window, out, report)),
        ("teaching", lambda: teaching_checks(window, out, report)),
        ("responsive", lambda: responsive_checks(window, out, report)),
    ]
    for name, fn in checks:
        try:
            fn()
        except Exception as exc:
            errors.append({"check": name, "error": str(exc), "traceback": traceback.format_exc()})
    window.close()
    wait(100)
    result = {"passed": not errors, "passes": report, "errors": errors}
    (out / "dynamic_acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Dynamic GUI Acceptance", "", *(f"- {x}" for x in report)]
    if errors:
        lines += ["", "## FAILURES"] + [f"- FAIL {e['check']}: {e['error']}" for e in errors]
    else:
        lines += ["", "**OVERALL: PASS**"]
    (out / "dynamic_acceptance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

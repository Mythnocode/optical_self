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

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QLabel,
    QPushButton,
    QScrollArea,
    QWidget,
)

from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.app.compact_shell import CATEGORIES, ShellAction
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.shared.components.errors import PageLoadErrorWidget


def wait(ms: int = 180) -> None:
    QTest.qWait(ms)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def fail(message: str) -> None:
    raise AssertionError(message)


def load_page(window, key: str):
    window.navigate(key, update_document=False)
    wait(650)
    host = window._pages.get(key)
    if host is None or host.loaded_page is None:
        fail(f"{key}: page did not load")
    if isinstance(host.loaded_page, PageLoadErrorWidget):
        fail(f"{key}: page load error")
    return host.loaded_page


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


def phase_fixture() -> dict:
    x = np.linspace(-8.0, 8.0, 65)
    y = np.linspace(-8.0, 8.0, 65)
    xx, yy = np.meshgrid(x, y)
    z = 0.015 * xx + 0.007 * yy + 0.0015 * (xx**2 + yy**2)
    return {
        "kind": "heatmap",
        "title": "端面相位",
        "source": "UI 验收数据夹具（仅用于结构验收）",
        "x": x.tolist(),
        "y": y.tolist(),
        "z": z.tolist(),
        "x_label": "X / μm",
        "y_label": "Y / μm",
        "description": "验证概览与详细为两个不同信息视图；不作为物理验收数据。",
        "key_metrics": [
            {"label": "RMS 相位", "value": "0.188 rad"},
            {"label": "PV", "value": "0.512 rad"},
            {"label": "采样", "value": "65 × 65"},
        ],
        "center_offset_um": 0.42,
        "coupling_efficiency_percent": 84.7,
        "system_efficiency_percent": 91.2,
        "propagation_edge_power_fraction": 0.0018,
    }


def shell_and_home(window, out: Path, checks: list[str]) -> None:
    p = load_page(window, "home")
    text = all_visible_text(p)
    for forbidden in ("你现在想做什么", "当前工作", "任务记录"):
        if forbidden in text:
            fail(f"home still exposes removed landing block: {forbidden}")
    if "激光耦合仿真系统及智能优化平台" not in text:
        fail("home does not show corrected product title")
    if [b.text() for b in window.command_buttons.values()] != ["系统", "运行", "分析"]:
        fail("top command strip is not reduced to 系统 / 运行 / 分析")
    shot(window, out, "01_home_1366x768")

    window._toggle_toolbox(); wait(220)
    if not window.drawer.isVisible():
        fail("floating toolbox did not open")
    shot(window, out, "02_toolbox_full")
    window.drawer.search.setText("反向预测"); wait(180)
    matches = [b.text() for b in window.drawer.body.findChildren(QPushButton) if b.isVisible()]
    if "反向预测" not in matches:
        fail(f"toolbox search cannot discover ML reverse prediction: {matches}")
    shot(window, out, "03_toolbox_search_reverse")
    window._close_tool_drawer(); wait(100)
    checks.append("PASS shell/home: minimal top bar, cleaned home, searchable toolbox exposes ML reverse prediction")


def simulation(window, out: Path, checks: list[str]) -> None:
    p = load_page(window, "simulation")
    p.params.expand_section("lens"); wait(160)
    if p.editor.list.horizontalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff:
        fail("quick lens object list permits horizontal scrolling")
    shot(window, out, "04_simulation_lens_objects")

    live = p.results
    live.set_results({"相位": phase_fixture()}, replace=False)
    live.set_current_result("相位", notify=False); wait(260)
    live._set_detail_mode(False); wait(160)
    if not live.workspace.isVisible() or live.detail_report.isVisible():
        fail("analysis overview is not plot-first")
    shot(window, out, "05_analysis_phase_overview")

    live._set_detail_mode(True); wait(180)
    if live.workspace.isVisible() or not live.detail_report.isVisible():
        fail("analysis detail still shows main plot or hides data report")
    if live.detail_report.horizontalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff:
        fail("detail report has unexpected horizontal page scroll")
    text = all_visible_text(live.detail_report)
    for required in ("关键指标", "二维数据统计", "中心行数值"):
        if required not in text:
            fail(f"detail report missing professional data section: {required}")
    shot(window, out, "06_analysis_phase_detail_data_only")
    live._set_detail_mode(False)
    checks.append("PASS simulation: compact object panel; overview=plot+metrics; detail=data-only report")


def optimization_tasks(window, out: Path, checks: list[str]) -> None:
    scan = ShellAction("scan", "参数研究", "chart", "optimization", "optimization.scan")
    window._open_task_window(scan); wait(650)
    dialog = window._task_dialog; p = window._task_page
    if dialog is None or p is None or dialog.isModal():
        fail("parameter research is not a modeless major task window")
    if window._current_key != "simulation":
        fail("main simulation workspace was replaced by research task")
    named_scrolls = [s.objectName() for s in p.findChildren(QScrollArea) if s.isVisible()]
    if "optimizationResearchScroll" not in named_scrolls:
        fail(f"optimization does not expose the whole-task scroll: {named_scrolls}")
    if getattr(p, "task_header", None) is None or "参数研究" not in p.task_header.title_label.text():
        fail("parameter research title not contextual")
    shot(window, out, "07_simulation_behind_task")
    shot(dialog, out, "08_task_parameter_research")

    reverse = ShellAction("reverse", "代理模型反向预测", "workflow", "optimization", "optimization.surrogate_inverse")
    window._open_task_window(reverse); wait(300)
    if "反向预测" not in p.task_header.title_label.text():
        fail("surrogate reverse prediction did not become an explicit task")
    if "反向预测" not in p.start_research_button.text():
        fail("surrogate reverse task has no explicit primary action")
    shot(dialog, out, "09_task_ml_reverse_prediction")

    inverse = ShellAction("inverse", "物理反向设计", "workflow", "optimization", "optimization.inverse_design")
    window._open_task_window(inverse); wait(260)
    if "物理反向设计" not in p.task_header.title_label.text():
        fail("physical inverse design is not distinct from ML reverse prediction")
    shot(dialog, out, "10_task_physical_inverse_design")
    dialog.close(); wait(180)
    checks.append("PASS task windows: modeless; simulation remains usable; scan / ML reverse / physical inverse are distinct")


def machine_learning(window, out: Path, checks: list[str]) -> None:
    p = load_page(window, "machine_learning")
    p.handle_assistant_action({"target": "machine_learning.builder"}); wait(200)
    if p.page_header.title_label.text() != "模型构建":
        fail("ML builder still opens a proxy-model landing page")
    visible = [b.text() for b in p.workflow_buttons if b.isVisible()]
    if visible != ["数据准备", "模型训练", "模型比较"]:
        fail(f"model construction does not expose only its flow stages: {visible}")
    shot(window, out, "11_ml_model_builder")

    p.handle_assistant_action({"target": "machine_learning.prediction"}); wait(240)
    if p.page_header.title_label.text() != "正向预测" or p.stage_bar.isVisible():
        fail("forward prediction is not presented as a direct concrete task")
    shot(window, out, "12_ml_forward_prediction_direct")
    checks.append("PASS ML hierarchy: no landing overview; model building is a 3-step flow; forward prediction opens directly")


def teaching(window, out: Path, checks: list[str]) -> None:
    p = load_page(window, "teaching")
    text = all_visible_text(p)
    if "教学环境 · 不影响当前系统" not in text:
        fail("teaching environment still uses old formal-plan wording")
    if "自动吸附" in text or "解除吸附" in text:
        fail("teaching first screen still exposes legacy snap interaction")
    shot(window, out, "13_teaching_2d_engine_semantics")
    checks.append("PASS teaching: current-system terminology and no visible auto-snap workflow")


def responsive(window, out: Path, checks: list[str]) -> None:
    sizes = [(1100, 720), (900, 650), (768, 1366)]
    for width, height in sizes:
        window.resize(width, height); wait(260)
        if window.width() > width + 2 or window.height() > height + 2:
            fail(f"window minimum size blocks {width}x{height}: actual {window.size()}")
        assert_no_overlap(window.toolbox_button, window.assistant_button, f"floating launchers {width}x{height}")
        assert_no_overlap(window.toolbox_button, window.footer_tasks_button, f"toolbox/footer {width}x{height}")
        assert_no_overlap(window.assistant_button, window.footer_tasks_button, f"AI/footer {width}x{height}")
        shot(window, out, f"14_responsive_{width}x{height}")
    window.resize(1366, 768); wait(160)
    checks.append("PASS responsive: 1100x720, 900x650, 768x1366 accepted without launcher/footer overlap")


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
    window.show(); wait(350)

    checks: list[str] = []
    status = "PASS"
    error = ""
    try:
        shell_and_home(window, out, checks)
        simulation(window, out, checks)
        optimization_tasks(window, out, checks)
        machine_learning(window, out, checks)
        teaching(window, out, checks)
        responsive(window, out, checks)
    except Exception as exc:
        status = "FAIL"
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if getattr(window, "_task_dialog", None) is not None:
            window._task_dialog.close()
        window.close(); wait(80)

    report = {
        "status": status,
        "checks": checks,
        "error": error,
        "product_title": "激光耦合仿真系统及智能优化平台",
        "top_commands": ["系统", "运行", "分析"],
        "toolbox_action_count": sum(len(actions) for c in CATEGORIES for _g, actions in c.groups),
        "quick3d_real_gpu": "NOT_TESTED_BY_THIS_SCRIPT",
        "note": "Professional-analysis phase data is a deterministic UI-only fixture; it is not a physical accuracy result.",
    }
    (out / "acceptance_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "acceptance_report.txt").write_text("\n".join([status, *checks, error]), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

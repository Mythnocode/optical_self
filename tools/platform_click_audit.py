"""Headless Qt click audit for the current compact-shell UI (2026-08).

Simulates real mouse clicks on top-level navigation and key workflows,
collecting PASS/FAIL with actionable detail. Runs offscreen; no backend required
for most checks (formal compute is not submitted).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="optical-audit-settings-"))

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractButton, QWidget

from frontend_pyside.app.bootstrap import create_app_context, create_main_window
from frontend_pyside.shared.components.errors import PageLoadErrorWidget


@dataclass
class AuditRow:
    area: str
    action: str
    status: str
    detail: str = ""


@dataclass
class AuditReport:
    rows: list[AuditRow] = field(default_factory=list)

    def record(self, area: str, action: str, ok: bool, detail: str = "") -> None:
        self.rows.append(AuditRow(area, action, "PASS" if ok else "FAIL", detail))

    def fail_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "FAIL")


def wait(ms: int = 180) -> None:
    QTest.qWait(ms)
    app = QApplication.instance()
    if app:
        app.processEvents()


def click(widget: QWidget | None, label: str) -> None:
    if widget is None:
        raise AssertionError(f"{label}: widget missing")
    if not widget.isVisible():
        raise AssertionError(f"{label}: not visible")
    if hasattr(widget, "isEnabled") and not widget.isEnabled():
        raise AssertionError(f"{label}: disabled")
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    wait()


def load_page(window, key: str) -> QWidget:
    window.navigate(key, update_document=False)
    wait(400)
    host = window._pages.get(key)
    if host is None or host.loaded_page is None:
        raise AssertionError(f"{key}: page host not loaded")
    page = host.loaded_page
    if isinstance(page, PageLoadErrorWidget):
        raise AssertionError(f"{key}: page load error widget shown")
    return page


def safe_case(report: AuditReport, area: str, action: str, fn) -> None:
    try:
        detail = str(fn() or "ok")
        report.record(area, action, True, detail)
    except Exception as exc:
        report.record(area, action, False, f"{type(exc).__name__}: {exc}")


def audit_shell(window, report: AuditReport) -> None:
    expected = {"simulation", "optimization", "surrogate", "machine_learning", "explainability", "teaching"}
    buttons = getattr(window, "command_buttons", {})
    missing = expected - set(buttons)
    if missing:
        report.record("顶栏", "命令按钮齐全", False, f"缺少: {sorted(missing)}")
    else:
        report.record("顶栏", "命令按钮齐全", True, ", ".join(sorted(buttons)))

    toolbox = getattr(window, "toolbox_button", None)
    if toolbox is None:
        report.record("工具箱", "悬浮入口存在", False, "toolbox_button missing")
        return
    click(toolbox, "打开工具箱")
    drawer = getattr(window, "drawer", None)
    if drawer is None or not drawer.isVisible():
        report.record("工具箱", "抽屉可打开", False, "drawer not visible after click")
        return
    report.record("工具箱", "抽屉可打开", True, "visible")
    if hasattr(drawer, "search"):
        drawer.search.setText("参数研究")
        wait(120)
        hits = [b for b in drawer.findChildren(QAbstractButton) if b.isVisible() and "参数研究" in b.text()]
        report.record("工具箱", "搜索参数研究", bool(hits), f"hits={len(hits)}")
    close = getattr(window, "_close_tool_drawer", None)
    if callable(close):
        close()
        wait(80)


def audit_home(window, report: AuditReport) -> None:
    page = load_page(window, "home")
    title = page.findChild(QWidget, "homePlatformTitle")
    report.record("首页", "平台标题可见", title is not None and title.isVisible(), repr(getattr(title, "text", lambda: "")()))


def audit_simulation(window, report: AuditReport) -> None:
    page = load_page(window, "simulation")
    toggle = getattr(page, "parameter_toggle_button", None)
    splitter = getattr(page, "main_splitter", None)
    if toggle is None or splitter is None:
        report.record("仿真", "参数区控件", False, "toggle/splitter missing")
        return
    before = splitter.sizes()
    click(toggle, "收起参数")
    hidden = splitter.sizes()
    click(toggle, "显示参数")
    restored = splitter.sizes()
    ok = hidden[0] <= 10 and restored[0] >= max(180, before[0] - 80)
    report.record("仿真", "收起/显示参数", ok, f"{before}->{hidden}->{restored}")

    formal = getattr(page, "formal_button", None)
    report.record(
        "仿真",
        "开始计算按钮",
        formal is not None and formal.isVisible() and formal.isEnabled(),
        getattr(formal, "text", lambda: "")() if formal else "missing",
    )

    for name, btn_name in (("参数研究", "parameter_research_button"), ("容差分析", "tolerance_analysis_button")):
        btn = getattr(page, btn_name, None)
        if btn is None:
            report.record("仿真", name, False, "button missing")
            continue
        click(btn, name)
        task = getattr(window, "_optimization_task_window", None)
        ok = task is not None and task.isVisible()
        report.record("仿真", f"打开{name}任务窗", ok, getattr(task, "target", "") if task else "no window")
        if task is not None:
            task.hide()
            wait(80)

    results = getattr(page, "results", None)
    if results is not None and hasattr(results, "set_current_result"):
        for view in ("光路", "模场匹配"):
            try:
                results.set_current_result(view)
                wait(120)
                report.record("仿真", f"切换结果视图·{view}", True, "set_current_result ok")
            except Exception as exc:
                report.record("仿真", f"切换结果视图·{view}", False, str(exc))


def audit_optimization(window, report: AuditReport) -> None:
    page = load_page(window, "optimization")
    start = getattr(page, "start_research_button", None)
    report.record(
        "优化",
        "开始研究/优化按钮可见",
        start is not None and start.isVisible(),
        getattr(start, "text", lambda: "")() if start else "missing",
    )
    main_result = getattr(page, "main_result", None)
    if main_result is not None:
        report.record(
            "优化",
            "结果区尺寸合理",
            main_result.width() >= 400 and main_result.height() >= 200,
            f"{main_result.width()}x{main_result.height()}",
        )


def audit_ml(window, report: AuditReport) -> None:
    page = load_page(window, "machine_learning")
    buttons = list(getattr(page, "workflow_buttons", []) or [])
    report.record("代理模型", "流程按钮数量", len(buttons) >= 4, f"count={len(buttons)}")
    names = ("数据准备", "模型训练", "模型比较", "预测")
    for idx, name in enumerate(names):
        if idx >= len(buttons):
            report.record("代理模型", f"点击{name}", False, "button missing")
            continue
        click(buttons[idx], name)
        stack = getattr(page, "workflow_stack", None)
        expected = idx + 1
        ok = stack is not None and stack.currentIndex() == expected
        report.record("代理模型", f"切换到{name}", ok, f"stack={getattr(stack, 'currentIndex', lambda: '?')()}")


def audit_explainability(window, report: AuditReport) -> None:
    page = load_page(window, "explainability")
    report.record("模型解释", "页面加载", page is not None, page.__class__.__name__)


def audit_teaching(window, report: AuditReport) -> None:
    page = load_page(window, "teaching")
    wb = getattr(page, "workbench", None)
    if wb is None:
        report.record("教学", "工作台加载", False, "workbench missing")
        return
    report.record("教学", "工作台加载", True, wb.__class__.__name__)

    combo = wb.findChild(QWidget, "teachingMismatchCombo")
    report.record("教学", "研究变量下拉存在", combo is not None, "teachingMismatchCombo")

    # QML category buttons are bridged through toolCategoryRequested; simulate via Python hook.
    handler = getattr(wb, "_on_tool_category_requested", None)
    if callable(handler):
        handler("搭建")
        wait(200)
        drawer = getattr(wb, "left_drawer", None)
        visible = drawer is not None and drawer.isVisible()
        report.record("教学", "点搭建打开抽屉", visible, getattr(wb, "_left_drawer_key", ""))
        if visible and hasattr(wb, "_populate_free_experiment_tools"):
            body_text = " ".join(
                str(w.text())
                for w in drawer.findChildren(QWidget)
                if hasattr(w, "text") and w.isVisible()
            )
            has_tools = "反射镜" in body_text or "光源" in body_text or "自由实验" in body_text
            report.record("教学", "搭建抽屉含元件", has_tools, body_text[:120])
            # Add mirror without jumping back to experiment preset list.
            add = getattr(wb, "_add_component", None)
            if callable(add):
                before = body_text
                add("mirror")
                wait(120)
                if drawer.isVisible():
                    after = " ".join(
                        str(w.text())
                        for w in drawer.findChildren(QWidget)
                        if hasattr(w, "text") and w.isVisible()
                    )
                    jumped = "选择实验" in after and "选择实验" not in before
                    report.record("教学", "放反射镜后不跳实验库首页", not jumped, after[:120])
                else:
                    report.record("教学", "放反射镜后不跳实验库首页", True, "drawer stayed closed")
            if drawer.isVisible():
                drawer.hide()
    else:
        report.record("教学", "搭建入口", False, "_on_tool_category_requested missing")

    view3d = getattr(wb, "view_3d_button", None)
    if view3d is not None and view3d.isVisible():
        click(view3d, "3D")
        report.record("教学", "3D视图状态", getattr(wb, "_view_kind", "") == "3d", str(getattr(wb, "_view_kind", "")))
    else:
        report.record("教学", "3D按钮可见", False, "view_3d_button hidden (may be expected in compact header)")


def audit_assistant(window, report: AuditReport) -> None:
    btn = getattr(window, "assistant_button", None)
    if btn is None:
        report.record("AI助手", "悬浮按钮", False, "missing")
        return
    click(btn, "打开AI")
    dialog = getattr(window, "_assistant_dialog", None)
    visible = dialog is not None and dialog.isVisible()
    report.record("AI助手", "对话框打开", visible, dialog.__class__.__name__ if dialog else "none")
    if visible and hasattr(dialog, "close"):
        dialog.close()
        wait(80)


def run_audit() -> AuditReport:
    app = QApplication.instance() or QApplication([])
    report = AuditReport()
    window = create_main_window()
    window.resize(1366, 768)
    window.show()
    wait(500)

    for area, fn in (
        ("shell", lambda: audit_shell(window, report)),
        ("home", lambda: audit_home(window, report)),
        ("simulation", lambda: audit_simulation(window, report)),
        ("optimization", lambda: audit_optimization(window, report)),
        ("ml", lambda: audit_ml(window, report)),
        ("explainability", lambda: audit_explainability(window, report)),
        ("teaching", lambda: audit_teaching(window, report)),
        ("assistant", lambda: audit_assistant(window, report)),
    ):
        safe_case(report, area, "workflow", fn)

    window.close()
    wait(100)
    return report


def main() -> int:
    out = Path("acceptance/platform_click_audit.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = run_audit()
    except Exception:
        traceback.print_exc()
        return 2
    payload = {
        "failures": report.fail_count(),
        "total": len(report.rows),
        "rows": [row.__dict__ for row in report.rows],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if report.fail_count() else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The live app no longer has a canvas ribbon; keep the capability catalogue."""

from __future__ import annotations

import importlib.util
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.shell_catalog import CATEGORIES
from frontend_pyside.app.workbench_shell import PRIMARY_MODULES, SECONDARY_ITEMS, WorkbenchShell
from frontend_pyside.features.canvas.registry import spec


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _catalog_titles() -> list[str]:
    return [action.title for category in CATEGORIES for _group, actions in category.groups for action in actions]


def test_old_canvas_and_page_shells_are_gone() -> None:
    for name in (
        "frontend_pyside.app.canvas_shell",
        "frontend_pyside.app.compact_shell",
        "frontend_pyside.app.page_registry",
        "frontend_pyside.app.deferred_page",
        "frontend_pyside.features.home",
        "frontend_pyside.features.help",
        "frontend_pyside.features.about",
        "frontend_pyside.features.tasks",
        "frontend_pyside.features.simulation.page",
        "frontend_pyside.features.optimization.page",
        "frontend_pyside.features.machine_learning.page",
        "frontend_pyside.features.explainability.page",
        "frontend_pyside.features.teaching_v2.page",
        "frontend_pyside.views",
    ):
        assert importlib.util.find_spec(name) is None, name


def test_capability_catalog_still_lists_live_actions() -> None:
    titles = _catalog_titles()
    for title in (
        "系统建模",
        "完整镜头编辑器",
        "参数研究",
        "容差分析",
        "自动优化",
        "物理反向设计",
        "随机森林",
        "XGBoost物理残差",
        "BiLSTM",
        "正向预测",
        "反向预测",
        "模型解释",
        "教学实验台",
    ):
        assert title in titles
    assert spec("lens_editor") is not None
    assert spec("scan") is not None
    assert spec("optimize") is not None


def test_workbench_primary_bar_replaces_canvas_ribbon() -> None:
    app = _app()
    shell = WorkbenchShell(create_app_context())
    shell.show()
    try:
        assert [key for key, _title in PRIMARY_MODULES] == [
            "home",
            "simulation",
            "teaching",
            "model",
            "optimization",
            "explainability",
        ]
        assert "analysis" not in SECONDARY_ITEMS
        assert [key for key, _title, _hint in SECONDARY_ITEMS["model"]] == [
            "dataset",
            "train_result",
            "predict_eval",
        ]
        assert [key for key, _title, _hint in SECONDARY_ITEMS["optimization"]] == [
            "scan",
            "opt_vars",
            "opt_result",
        ]
        shell.set_module("simulation")
        assert list(shell.secondary.buttons) == [
            key for key, _title, _hint in SECONDARY_ITEMS["simulation"]
        ]
    finally:
        shell.close()
        app.processEvents()

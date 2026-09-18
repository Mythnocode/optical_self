from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QApplication = pytest.importorskip("PySide6.QtWidgets").QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.workbench_shell import WorkbenchShell


def test_model_display_names_use_type_and_sequential_number() -> None:
    app = QApplication.instance() or QApplication([])
    shell = WorkbenchShell(create_app_context())
    try:
        shell._trained_models = [
            {"id": "rf-old", "model_type": "随机森林", "title": "随机森林 · old"},
            {"id": "rf-two", "model_type": "随机森林", "title": "随机森林2"},
        ]
        assert shell._next_model_name("随机森林") == ("随机森林3", 3)

        shell._on_registry_models_changed(
            [
                {"model_id": "xgb-old", "model_type": "xgboost_physics_residual", "title": "XGBoost物理残差 · old"},
                {"model_id": "rf-old", "model_type": "random_forest", "title": "随机森林 · old"},
            ]
        )
        assert [item["title"] for item in shell._trained_models] == [
            "XGBoost物理残差1",
            "随机森林1",
        ]
    finally:
        shell.close()
        app.processEvents()

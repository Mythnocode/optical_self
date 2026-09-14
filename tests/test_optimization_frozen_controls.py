from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.workbench_shell import (
    WorkbenchShell,
    _shap_feature_key,
    _variable_rows,
    _variable_shap_scores,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_shap_feature_maps_only_onto_design_variables():
    keys = [
        "surfaces[0].radius_mm",
        "surfaces[0].distance_to_next_mm",
        "receiver.offset_x_um",
        "receiver.offset_y_um",
        "receiver.axial_offset_z_um",
    ]
    assert _shap_feature_key("surfaces[0].radius_mm", keys) == "surfaces[0].radius_mm"
    assert _shap_feature_key("surfaces[0].thickness_mm", keys) == "surfaces[0].distance_to_next_mm"
    assert _shap_feature_key("receiver.offset_x_um", keys) == "receiver.offset_x_um"
    assert _shap_feature_key("轴向偏移", keys) == "receiver.axial_offset_z_um"
    assert _shap_feature_key("size_ratio", keys) is None
    scores = _variable_shap_scores(
        [
            {"feature": "surfaces[0].radius_mm", "mean_abs_shap": 0.4},
            {"feature": "size_ratio", "mean_abs_shap": 9.0},
            {"feature": "receiver.offset_x_um", "mean_abs_shap": 1.2},
        ],
        keys,
    )
    assert scores["receiver.offset_x_um"] == 1.2
    assert "size_ratio" not in scores


def test_optimization_shap_sorts_without_changing_checks():
    app = _app()
    shell = WorkbenchShell(create_app_context())
    shell.show()
    try:
        shell.set_module("optimization")
        rail = shell.object_rail
        assert rail.shap_button.isVisible()
        assert not rail.shap_button.isEnabled()
        rows = _variable_rows(shell.context.project.project)
        fiber = "receiver.offset_x_um"
        assert any(key == fiber for key, *_rest in rows)
        first_key = rail.list.item(0).data(Qt.ItemDataRole.UserRole)
        fiber_item = next(
            rail.list.item(index)
            for index in range(rail.list.count())
            if rail.list.item(index).data(Qt.ItemDataRole.UserRole) == fiber
        )
        fiber_item.setCheckState(Qt.CheckState.Checked)
        rail.set_shap_scores({fiber: 8.0, str(first_key): 0.1})
        assert rail.shap_button.isEnabled()
        rail.shap_button.setChecked(True)
        assert rail.list.item(0).data(Qt.ItemDataRole.UserRole) == fiber
        assert rail.list.item(0).checkState() == Qt.CheckState.Checked
        rail.shap_button.setChecked(False)
        assert rail.list.item(0).data(Qt.ItemDataRole.UserRole) == first_key
        still_checked = next(
            rail.list.item(index)
            for index in range(rail.list.count())
            if rail.list.item(index).data(Qt.ItemDataRole.UserRole) == fiber
        )
        assert still_checked.checkState() == Qt.CheckState.Checked
    finally:
        shell.close()
        app.processEvents()

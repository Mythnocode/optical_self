from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDoubleSpinBox

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.features.optimization.page import OptimizationPage
from frontend_pyside.features.optimization.tolerance_analysis import tolerance_scale_limits
from frontend_pyside.shared.display_names import parameter_label


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _page() -> OptimizationPage:
    app = _app()
    page = OptimizationPage(create_app_context())
    page.resize(1366, 768)
    page.show()
    app.processEvents()
    return page


def test_tolerance_scale_limits_for_alignment_paths():
    min_x, max_x = tolerance_scale_limits("receiver.offset_x_mm", 0.0)
    assert min_x > 0
    assert max_x == 0.05
    min_tilt, max_tilt = tolerance_scale_limits("receiver.tilt_x_deg", 0.0)
    assert max_tilt == 2.0


def test_tolerance_run_button_disabled_when_lhs_samples_too_few():
    page = _page()
    try:
        page._set_workspace_mode(0)
        page.tolerance_candidate.setCurrentText("当前系统")
        paths = [f"surfaces[{i}].radius_mm" for i in range(8)]
        paths += [f"surfaces[{i}].distance_to_next_mm" for i in range(8)]
        paths.append("receiver.offset_x_mm")
        page.tolerance_table.setRowCount(0)
        for index, path in enumerate(paths[:17]):
            page._tolerance_append_row(
                parameter_label(path),
                path,
                20.0,
                "mm",
                0.05,
                "正态",
            )
        page.tolerance_method.setCurrentText("LHS")
        page.tolerance_samples.setValue(16)
        page._tolerance_refresh_input_state()
        assert not page.tolerance_run_button.isEnabled()
        assert "样本数" in page.tolerance_validation_hint.text()
        page.tolerance_samples.setValue(68)
        page._tolerance_refresh_input_state()
        assert page.tolerance_run_button.isEnabled()
    finally:
        page.close()


def test_tolerance_table_uses_bounded_spinboxes():
    page = _page()
    try:
        page.tolerance_template.setCurrentText("常用装调")
        page._tolerance_apply_template()
        scale_spin = page.tolerance_table.cellWidget(0, 4)
        assert isinstance(scale_spin, QDoubleSpinBox)
        assert scale_spin.minimum() > 0
        assert scale_spin.maximum() > scale_spin.minimum()
    finally:
        page.close()

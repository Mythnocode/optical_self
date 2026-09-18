"""Layout guards for the explainability physical-chain page.

The chain view hides the plot workspace, so nothing in that view owns the page
height by default: the previous layout let the top action row swallow the
leftover space (two large blank bands) and cut the SHAP ranking list off after
four rows.  These checks pin the corrected layout.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.workbench_shell import WorkbenchShell

SHAP_FEATURES = (
    ("surfaces[6].thickness_mm", 4.822e-10),
    ("surfaces[6].radius_mm", 4.169e-10),
    ("surfaces[4].thickness_mm", 1.702e-10),
    ("surfaces[2].radius_mm", 1.527e-10),
    ("surfaces[8].conic", 9.3e-11),
    ("receiver.offset_x_um", 7.1e-11),
    ("source.waist_x_um", 5.2e-11),
    ("surfaces[3].thickness_mm", 3.4e-11),
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait(ms: int = 200) -> None:
    QTest.qWait(ms)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def _shap_payload() -> dict:
    return {
        "status": "ok",
        "target_name": "coupling_loss_db",
        "target_unit": "dB",
        "top_features": [
            {"feature": feature, "mean_abs_shap": value, "mean_shap": value}
            for feature, value in SHAP_FEATURES
        ],
    }


def _open_chain_document(shell: WorkbenchShell):
    shell.set_module("explainability")
    shell._secondary_clicked("param_trend")
    document = shell._widgets["explainability:param_trend"]
    document.set_trained_models([{
        "id": "model-chain-1",
        "title": "XGBoost物理残差1",
        "family": "xgboost",
        "target": "coupling_loss_db",
    }])
    document._render_shap(_shap_payload())
    document.param_view_buttons[1].click()
    _wait()
    return document


def test_chain_view_keeps_ranking_and_formulas_readable():
    _app()
    shell = WorkbenchShell(create_app_context())
    shell.resize(1600, 1000)
    shell.show()
    try:
        document = _open_chain_document(shell)
        action_row = document.layout().itemAt(0).widget()

        # The chain view must scroll rather than run past the window.
        assert isinstance(document.chain_view, QScrollArea)
        assert document.chain_view.isVisible()
        assert document.workspace.isHidden()

        # The action row hugs its content instead of absorbing page slack, and
        # the cards start right below it with no blank band in between.
        assert action_row.height() <= action_row.sizeHint().height()
        assert document.chain_view.y() - action_row.geometry().bottom() < 20

        # Regression probe: with nothing owning the page height at all the row
        # used to take it all, which is what pushed the cards apart.
        document.chain_view.hide()
        _wait(150)
        assert action_row.height() <= action_row.sizeHint().height()
        document.chain_view.show()
        _wait(150)

        # Every ranked parameter is laid out without an inner scrollbar: the
        # picker takes its height from the row count instead of a fixed cap.
        picker = document.feature_picker
        assert picker.count() == len(SHAP_FEATURES)
        row_height = picker.sizeHintForRow(0)
        assert picker.height() == picker.count() * row_height + 2 * picker.frameWidth() + 4
        assert picker.verticalScrollBar().maximum() == 0
    finally:
        shell.close()
        _wait(60)


def test_chain_view_scrolls_on_a_short_window():
    _app()
    shell = WorkbenchShell(create_app_context())
    shell.resize(1600, 1000)
    shell.show()
    try:
        document = _open_chain_document(shell)
        assert document.chain_view.verticalScrollBar().maximum() == 0

        shell.resize(1000, 520)
        _wait(300)
        # Never taller than the document, and the rest stays reachable instead
        # of being clipped outside the window.
        assert document.chain_view.height() <= document.height()
        scroll_bar = document.chain_view.verticalScrollBar()
        assert scroll_bar.maximum() > 0
        assert document.chain_view.widget().height() > document.chain_view.viewport().height()
    finally:
        shell.close()
        _wait(60)


def test_plot_view_still_fills_the_page():
    _app()
    shell = WorkbenchShell(create_app_context())
    shell.resize(1600, 1000)
    shell.show()
    try:
        document = _open_chain_document(shell)
        document.param_view_buttons[0].click()
        _wait()
        assert document.workspace.isVisible()
        assert document.chain_view.isHidden()
        assert document.workspace.height() > shell.height() // 2
    finally:
        shell.close()
        _wait(60)

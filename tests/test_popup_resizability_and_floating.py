from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QDialog

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.main_window import MainWindow
from frontend_pyside.features.assistant.dialog import AiAssistantDialog
from frontend_pyside.features.machine_learning.task_window import MachineLearningPredictionTaskWindow
from frontend_pyside.features.optimization.task_window import OptimizationTaskWindow
from frontend_pyside.features.simulation.windows.lens_editor import LensEditorWindow
from frontend_pyside.shared.components.data_dialogs import ReportContentDialog, TablePreviewDialog
from frontend_pyside.shared.dialogs.result_viewers import ScientificPlotWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(count: int = 10) -> None:
    app = _app()
    for _ in range(count):
        app.processEvents()


def _assert_resizable(widget, *, grow=(64, 48)) -> None:
    widget.show()
    _pump()
    before = widget.size()
    widget.resize(before.width() + grow[0], before.height() + grow[1])
    _pump()
    assert widget.width() == before.width() + grow[0]
    assert widget.height() == before.height() + grow[1]


def test_representative_popup_windows_are_resizable() -> None:
    app = _app()
    context = create_app_context()
    dialogs = [
        TablePreviewDialog("表格", ["A"], [[1]]),
        ReportContentDialog(),
        OptimizationTaskWindow(context),
        MachineLearningPredictionTaskWindow(context),
        AiAssistantDialog(context),
        ScientificPlotWindow("测试图", {"kind": "empty", "message": "暂无结果"}),
    ]
    try:
        for dialog in dialogs:
            _assert_resizable(dialog)
            if isinstance(dialog, QDialog):
                assert dialog.isSizeGripEnabled() is True
    finally:
        for dialog in dialogs:
            dialog.close()
        app.processEvents()


def test_surface_property_popup_is_resizable() -> None:
    app = _app()
    context = create_app_context()
    editor = LensEditorWindow(context.project)
    editor.show()
    try:
        _pump()
        editor._open_surface_properties(0)
        _pump()
        assert editor.property_dialog.isSizeGripEnabled() is True
        _assert_resizable(editor.property_dialog, grow=(80, 40))
    finally:
        editor.close()
        app.processEvents()


def test_all_direct_qdialogs_opt_in_to_resize_grip_and_no_fixed_dialog_hint() -> None:
    """Static guard for modal helper dialogs that cannot be opened in a nonblocking test."""

    root = Path(__file__).resolve().parents[1] / "frontend_pyside"
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "QDialog(" not in text and "(QDialog)" not in text:
            continue
        if "MSWindowsFixedSizeDialogHint" in text:
            offenders.append(f"{path.relative_to(root)}: fixed-size dialog hint")
        # Every file that directly declares/constructs a QDialog must explicitly
        # opt into the shared resize affordance.  This catches newly added modal
        # helper dialogs before they regress to a fixed-size popup.
        if "setSizeGripEnabled(True)" not in text:
            offenders.append(f"{path.relative_to(root)}: missing setSizeGripEnabled(True)")
    assert offenders == []


def test_toolbox_and_ai_floating_buttons_keep_user_positions_inside_workbench() -> None:
    app = _app()
    window = MainWindow(create_app_context())
    window.resize(1100, 700)
    window.show()
    try:
        _pump(20)
        window.toolbox_button.move(180, 430)
        window.toolbox_button._user_moved = True
        window.assistant_button.move(780, 260)
        window.assistant_button._user_moved = True
        window._position_floating_tools()
        window._position_assistant_button()
        _pump()
        assert window.toolbox_button.pos() == QPoint(180, 430)
        assert window.assistant_button.pos() == QPoint(780, 260)

        # Shrinking the host must clamp both controls back into the visible area
        # without snapping them to their default corners.
        window.resize(900, 650)
        _pump(20)
        root = window.central_root.rect()
        for button in (window.toolbox_button, window.assistant_button):
            assert root.contains(button.geometry().topLeft())
            assert root.contains(button.geometry().bottomRight())
            assert button._user_moved is True
    finally:
        window.close()
        app.processEvents()


def test_idle_optimization_status_does_not_push_toolbox_over_result_header() -> None:
    app = _app()
    window = MainWindow(create_app_context())
    window.resize(1100, 720)
    window.show()
    try:
        window.navigate("optimization", update_document=False)
        _pump(30)
        page = window._pages["optimization"].loaded_page
        assert page is not None
        assert page.research_progress.isVisible() is False

        window.toolbox_button._user_moved = False
        window._position_floating_tools()
        _pump()

        result_tab = page.result_view_buttons[0]
        tab_top_left = result_tab.mapTo(window.central_root, result_tab.rect().topLeft())
        tab_rect = result_tab.rect().translated(tab_top_left)
        assert not window.toolbox_button.geometry().intersects(tab_rect)
        # The compact status row must spend its width on the status itself rather
        # than a report-sized key column, so ordinary idle text stays legible.
        assert page.guided_status.key_label.maximumWidth() <= 56
    finally:
        window.close()
        app.processEvents()


def test_ai_assistant_compact_layout_does_not_clip_composer_or_history_actions() -> None:
    """Regression guard for the 720x520 / minimum-size assistant overlap found in screenshot QA."""

    app = _app()
    context = create_app_context()
    dialog = AiAssistantDialog(context)
    dialog.show()
    try:
        dialog.resize(720, 520)
        _pump(20)
        composer_rect = dialog.composer_frame.rect()
        send_rect = dialog.send_button.geometry()
        assert composer_rect.contains(send_rect.topLeft())
        assert composer_rect.contains(send_rect.bottomRight())
        assert dialog.input.height() == 48
        assert dialog.task_why.isVisible() is False
        assert dialog.task_effect.isVisible() is False
        assert dialog.context_hint.isVisible() is False

        dialog.resize(dialog.minimumSize())
        _pump(20)
        assert dialog.size().width() == 460
        assert dialog.size().height() == 480
        # The primary state remains visible when history is closed and must have
        # enough height for its wrapped text.
        if dialog.task_state.isVisible() and dialog.task_state.text().strip():
            flags = int(dialog.task_state.alignment()) | int(Qt.TextFlag.TextWordWrap)
            need = dialog.task_state.fontMetrics().boundingRect(
                dialog.task_state.rect(), flags, dialog.task_state.text()
            ).height()
            assert dialog.task_state.height() + 2 >= need

        dialog._toggle_history()
        _pump(20)
        assert dialog.history_panel.isVisible() is True
        assert dialog.task_state.isVisible() is False
        # At minimum width the three history actions are reflowed rather than
        # being squeezed into one clipped horizontal row.
        ys = {button.y() for button in dialog.history_action_buttons}
        assert len(ys) >= 2
    finally:
        dialog.hide()
        app.processEvents()

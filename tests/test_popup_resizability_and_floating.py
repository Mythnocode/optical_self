from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QDialog

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.main_window import MainWindow
from frontend_pyside.features.assistant.dialog import AiAssistantDialog
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
        if "setSizeGripEnabled(True)" not in text:
            offenders.append(f"{path.relative_to(root)}: missing setSizeGripEnabled(True)")
    assert offenders == []


def test_ai_floating_button_keeps_user_position_inside_workbench() -> None:
    app = _app()
    window = MainWindow(create_app_context())
    window.resize(1100, 700)
    window.show()
    try:
        _pump(20)
        window.assistant_button.move(780, 260)
        window.assistant_button._user_moved = True
        window._position_floating_tools()
        window._position_assistant_button()
        _pump()
        assert window.assistant_button.pos() == QPoint(780, 260)

        window.resize(900, 650)
        _pump(20)
        root = window.central_root.rect()
        button = window.assistant_button
        assert root.contains(button.geometry().topLeft())
        assert root.contains(button.geometry().bottomRight())
        assert button._user_moved is True
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
        ys = {button.y() for button in dialog.history_action_buttons}
        assert len(ys) >= 2
    finally:
        dialog.hide()
        app.processEvents()

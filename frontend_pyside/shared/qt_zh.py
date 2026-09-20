"""Install Chinese Qt translations and localize standard dialog buttons."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

# Keep strong references so translators are not garbage-collected.
_INSTALLED: list[QTranslator] = []
_LOADED_NAMES: set[str] = set()

_BUTTON_LABELS: dict[QDialogButtonBox.StandardButton, str] = {
    QDialogButtonBox.StandardButton.Ok: "确定",
    QDialogButtonBox.StandardButton.Cancel: "取消",
    QDialogButtonBox.StandardButton.Close: "关闭",
    QDialogButtonBox.StandardButton.Yes: "是",
    QDialogButtonBox.StandardButton.No: "否",
    QDialogButtonBox.StandardButton.Apply: "应用",
    QDialogButtonBox.StandardButton.Reset: "重置",
    QDialogButtonBox.StandardButton.Abort: "中止",
    QDialogButtonBox.StandardButton.Retry: "重试",
    QDialogButtonBox.StandardButton.Ignore: "忽略",
    QDialogButtonBox.StandardButton.Save: "保存",
    QDialogButtonBox.StandardButton.Open: "打开",
    QDialogButtonBox.StandardButton.Discard: "不保存",
    QDialogButtonBox.StandardButton.Help: "帮助",
}

_MESSAGE_BUTTON_LABELS: dict[QMessageBox.StandardButton, str] = {
    QMessageBox.StandardButton.Ok: "确定",
    QMessageBox.StandardButton.Cancel: "取消",
    QMessageBox.StandardButton.Close: "关闭",
    QMessageBox.StandardButton.Yes: "是",
    QMessageBox.StandardButton.No: "否",
    QMessageBox.StandardButton.Apply: "应用",
    QMessageBox.StandardButton.Reset: "重置",
    QMessageBox.StandardButton.Abort: "中止",
    QMessageBox.StandardButton.Retry: "重试",
    QMessageBox.StandardButton.Ignore: "忽略",
    QMessageBox.StandardButton.Save: "保存",
    QMessageBox.StandardButton.Open: "打开",
    QMessageBox.StandardButton.Discard: "不保存",
    QMessageBox.StandardButton.Help: "帮助",
}


def install_chinese_translators(app: QApplication | None = None) -> list[str]:
    """Load qt/qtbase zh_CN translators. Returns names of successfully loaded files."""
    app = app or QApplication.instance()
    if app is None:
        return []

    QLocale.setDefault(QLocale(QLocale.Language.Chinese, QLocale.Country.China))
    translations = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    loaded: list[str] = []
    for name in ("qtbase_zh_CN", "qt_zh_CN", "qtdeclarative_zh_CN"):
        if name in _LOADED_NAMES:
            continue
        translator = QTranslator(app)
        if translator.load(name, str(translations)):
            app.installTranslator(translator)
            _INSTALLED.append(translator)
            _LOADED_NAMES.add(name)
            loaded.append(name)
    return loaded


def localize_dialog_buttons(buttons: QDialogButtonBox) -> QDialogButtonBox:
    """Set Chinese labels on standard QDialogButtonBox buttons."""
    for role, text in _BUTTON_LABELS.items():
        button = buttons.button(role)
        if button is not None:
            button.setText(text)
    return buttons


def localize_message_box(box: QMessageBox) -> QMessageBox:
    """Set Chinese labels on standard QMessageBox buttons."""
    for role, text in _MESSAGE_BUTTON_LABELS.items():
        button = box.button(role)
        if button is not None:
            button.setText(text)
    return box


def ask_yes_no(
    parent,
    title: str,
    text: str,
    *,
    default_yes: bool = True,
) -> bool:
    """Show a Yes/No question with Chinese button labels. Returns True if Yes."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(
        QMessageBox.StandardButton.Yes if default_yes else QMessageBox.StandardButton.No
    )
    localize_message_box(box)
    return box.exec() == QMessageBox.StandardButton.Yes


__all__ = [
    "ask_yes_no",
    "install_chinese_translators",
    "localize_dialog_buttons",
    "localize_message_box",
]


from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import traceback

from frontend_pyside.core.constants import APP_NAME


def configure_process_environment() -> None:

    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("MPLBACKEND", "QtAgg")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def startup_log_path() -> Path:
    path = repository_root() / "logs" / "frontend_startup.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_startup_log(title: str, details: str) -> Path:
    path = startup_log_path()
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[{timestamp}] {title}\n{details.rstrip()}\n")
    return path


def format_exception(exc_type, exc_value, exc_traceback) -> str:
    return "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))


def install_exception_hook() -> None:
    previous = sys.excepthook

    def _hook(exc_type, exc_value, exc_traceback):
        details = format_exception(exc_type, exc_value, exc_traceback)
        append_startup_log("UNHANDLED FRONTEND EXCEPTION", details)
        previous(exc_type, exc_value, exc_traceback)

    sys.excepthook = _hook


def ensure_window_visible(window) -> None:

    try:
        from PySide6.QtGui import QGuiApplication

        geometry = window.frameGeometry()
        screens = QGuiApplication.screens()
        visible = any(screen.availableGeometry().intersects(geometry) for screen in screens)
        if visible:
            return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(max(window.width(), 1080), max(1080, available.width()))
        height = min(max(window.height(), 700), max(700, available.height()))
        window.resize(width, height)
        frame = window.frameGeometry()
        frame.moveCenter(available.center())
        window.move(frame.topLeft())
    except Exception:
        append_startup_log("WINDOW VISIBILITY RECOVERY FAILED", traceback.format_exc())


def restore_window_state_safely(window) -> None:
    try:
        window.restore_saved_window_state()
    except Exception:
        append_startup_log("WINDOW STATE RESTORE FAILED", traceback.format_exc())
    ensure_window_visible(window)


def show_fatal_startup_error(app, title: str, details: str) -> None:
    path = append_startup_log(title, details)
    try:
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(f"{APP_NAME}启动失败")
        box.setText("前端初始化失败，错误详情已写入日志。")
        box.setInformativeText(str(path))
        box.setDetailedText(details)
        box.exec()
    except Exception:
        print(details, file=sys.stderr)
        print(f"Startup log: {path}", file=sys.stderr)


__all__ = [
    "append_startup_log",
    "configure_process_environment",
    "ensure_window_visible",
    "install_exception_hook",
    "restore_window_state_safely",
    "show_fatal_startup_error",
    "startup_log_path",
]

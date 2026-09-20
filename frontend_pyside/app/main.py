from __future__ import annotations

import os
import sys
import traceback

for _name in (
    "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS",
):
    os.environ.setdefault(_name, os.environ.get("FRONTEND_NATIVE_THREAD_LIMIT", "1"))

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QThreadPool, QTimer
from PySide6.QtWidgets import QApplication

from frontend_pyside.core.shiboken_guard import harden_shiboken_signature_hook

harden_shiboken_signature_hook()

from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.app.startup import (
    install_exception_hook,
    restore_window_state_safely,
    show_fatal_startup_error,
)
from frontend_pyside.core.constants import APP_NAME, APP_VERSION
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.shared.performance import record_perf
from frontend_pyside.shared.font_fallback import configure_qt_font
from frontend_pyside.infrastructure.workers.worker import FunctionWorker
from frontend_pyside.shared.plotting.fast_heatmap import prewarm_fast_heatmap
from frontend_pyside.shared.components.safe_inputs import install_wheel_safety
from frontend_pyside.shared.qt_zh import install_chinese_translators


def main() -> int:
    startup_timer = QElapsedTimer()
    startup_timer.start()
    QCoreApplication.setOrganizationName("OpticalMLWorkspace")
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(APP_VERSION)

    app = QApplication.instance() or QApplication(sys.argv)
    install_chinese_translators(app)
    install_wheel_safety(app)
    install_exception_hook()
    try:
        apply_application_theme(app)
        configure_qt_font(app, point_size=13.5)
        window = create_main_window()
        
        
        app.aboutToQuit.connect(window.app_context.services.usage.close)
        window.resize(1280, 800)
        restore_window_state_safely(window)
        window.show()
        QTimer.singleShot(0, lambda: record_perf("startup_to_first_event", startup_timer.elapsed()))
        
        
        QTimer.singleShot(0, window.raise_)
        QTimer.singleShot(0, window.activateWindow)

        def start_result_path_prewarm() -> None:
            
            
            QThreadPool.globalInstance().start(FunctionWorker(prewarm_fast_heatmap))

        QTimer.singleShot(700, start_result_path_prewarm)
    except Exception:
        show_fatal_startup_error(app, "前端启动失败", traceback.format_exc())
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

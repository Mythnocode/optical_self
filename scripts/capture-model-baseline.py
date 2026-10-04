"""Capture the unmodified PySide model pages for JS visual comparison.

Run with a Python environment that already includes this project's dependencies.
Uses Qt's offscreen platform and isolated settings/usage/recovery directories.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "tests/golden/ui-baseline")
    parser.add_argument("--result", type=Path, help="Actual training result JSON for matching completed-state captures")
    args = parser.parse_args()
    isolation = Path(tempfile.mkdtemp(prefix="optical-model-baseline-"))
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["APPDATA"] = str(isolation / "appdata")
    os.environ["LOCALAPPDATA"] = str(isolation / "localappdata")
    os.environ["OPTICAL_USAGE_DIR"] = str(isolation / "usage")

    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QApplication
    from frontend_pyside.core.ui_theme import apply_application_theme
    from frontend_pyside.app.bootstrap import create_main_window

    app = QApplication([])
    app.setOrganizationName("OpticalMigrationVisualCapture")
    app.setApplicationName("ModelBaseline")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(isolation / "settings"))
    apply_application_theme(app)
    window = create_main_window()
    window.resize(1280, 800)
    window.show()
    args.output.mkdir(parents=True, exist_ok=True)
    geometry = {}

    def capture(name: str, document) -> None:
        # Visibility/layout changes can post another layout request while Qt is
        # processing the first one (notably nested dataset scroll containers).
        for _ in range(4):
            app.processEvents()
        window.grab().save(str(args.output / f"{name}.png"))
        widgets = {}
        for attr in ("chart", "train_summary", "train_progress_host", "workspace", "training_parameters_host", "training_more_button", "train_button"):
            widget = getattr(document, attr, None)
            if widget is not None and widget.isVisible():
                position = widget.mapTo(window, widget.rect().topLeft())
                widgets[attr] = [position.x(), position.y(), widget.width(), widget.height()]
        geometry[name] = widgets

    def captures() -> None:
        try:
            window.open_document("model", "dataset")
            dataset = next(widget for widget in window.workbench._widgets.values() if getattr(widget, "kind", "") == "dataset")
            dataset.training_more_button.setChecked(True)
            capture("model-training-options", dataset)
            dataset.data_kind.setCurrentIndex(dataset.data_kind.findData("sequence"))
            dataset.training_more_button.setChecked(True)
            capture("model-sequence-options", dataset)
            window.open_document("model", "train_result")
            result_page = next(widget for widget in window.workbench._widgets.values() if getattr(widget, "kind", "") == "train_result")
            capture("model-training-empty", result_page)
            if args.result:
                result = json.loads(args.result.read_text(encoding="utf-8"))
                result = result.get("data", result)
                result = result.get("result", result)
                if "random_forest" in result:
                    result_page.mark_joint_trained(result)
                else:
                    result_page.mark_trained(result)
                for index, chart in enumerate(("残差图", "实测值与预测值对照", "残差分布", "验证误差曲线")):
                    result_page.show_train_chart(chart)
                    capture(f"model-training-chart-{index}", result_page)
            (args.output / "model-training-geometry.json").write_text(json.dumps(geometry, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(geometry, ensure_ascii=False))
        finally:
            window.context.services.usage.close()
            app.quit()

    QTimer.singleShot(500, captures)
    app.exec()


if __name__ == "__main__":
    main()

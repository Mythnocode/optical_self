
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QWidget,
)

from frontend_pyside.shared.plotting.canvas import PlotCanvas


class PlotTools(QWidget):
    def __init__(self, canvas: PlotCanvas, parent=None, *, prepare=None, pixmap_provider=None):
        super().__init__(parent)
        self.canvas = canvas
        self.prepare = prepare
        self.pixmap_provider = pixmap_provider
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.reset_button = self._button("恢复视图", self.canvas.reset_view)
        self.copy_button = self._button("复制图片", self.copy_image)
        self.save_button = self._button("保存图片", self.save_image)
        self.export_button = self._button("导出数据", self.export_data)
        for button in (
            self.reset_button,
            self.copy_button,
            self.save_button,
            self.export_button,
        ):
            layout.addWidget(button)

    def _button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setFlat(True)
        button.setProperty("kind", "plotTool")
        button.clicked.connect(slot)
        return button

    def copy_image(self) -> None:
        pixmap = self.pixmap_provider() if callable(self.pixmap_provider) else self.canvas.grab()
        QApplication.clipboard().setPixmap(pixmap)

    def save_image(self) -> None:
        default = f"optical-result-{datetime.now():%Y%m%d-%H%M%S}.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存结果图",
            default,
            "PNG 图片 (*.png);;SVG 矢量图 (*.svg);;PDF 文档 (*.pdf)",
        )
        if not path:
            return
        try:
            if callable(self.prepare):
                self.prepare()
            self.canvas.save_figure(path)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))

    def export_data(self) -> None:
        default = f"optical-result-data-{datetime.now():%Y%m%d-%H%M%S}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出绘图数据",
            default,
            "CSV 数据 (*.csv);;NumPy 压缩数据 (*.npz)",
        )
        if not path:
            return
        try:
            if callable(self.prepare):
                self.prepare()
            self.canvas.export_data(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))


__all__ = ["PlotTools"]

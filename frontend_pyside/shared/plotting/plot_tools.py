"""绘图导出、格式化和小型通用工具。

这些函数服务于图片/数据导出、标签格式化和绘图安全处理，不决定某个页面的
图表类型。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QToolButton,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.icons import icon
from frontend_pyside.shared.plotting.canvas import PlotCanvas


class PlotTools(QWidget):
    """统一科研图表工具栏。

    高频动作保持轻量：恢复视图使用统一线性图标；复制、保存、导出和图表
    信息统一收进“更多 ▾”。页面不再为四个低频按钮永久占用一整行。
    """

    def __init__(self, canvas: PlotCanvas, parent=None, *, prepare=None, pixmap_provider=None):
        super().__init__(parent)
        self.canvas = canvas
        self.prepare = prepare
        self.pixmap_provider = pixmap_provider
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.reset_button = QToolButton(self)
        self.reset_button.setObjectName("plotIconTool")
        self.reset_button.setIcon(icon("reset", theme.TEXT_SECONDARY, 17))
        self.reset_button.setIconSize(QSize(17, 17))
        self.reset_button.setToolTip("恢复视图")
        self.reset_button.clicked.connect(self.canvas.reset_view)
        layout.addWidget(self.reset_button)

        self.more_button = QToolButton(self)
        self.more_button.setObjectName("plotMoreTool")
        self.more_button.setText("更多 ▾")
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.more_button)
        menu.addAction(icon("copy", theme.TEXT_SECONDARY, 16), "复制图片", self.copy_image)
        menu.addAction(icon("download", theme.TEXT_SECONDARY, 16), "保存图片", self.save_image)
        menu.addAction(icon("download", theme.TEXT_SECONDARY, 16), "导出数据", self.export_data)
        menu.addSeparator()
        menu.addAction(icon("info", theme.TEXT_SECONDARY, 16), "图表信息", self.show_info)
        self.more_button.setMenu(menu)
        layout.addWidget(self.more_button)

        # 兼容旧调用方属性；这些动作不再以独立大按钮显示。
        self.copy_button = self.save_button = self.export_button = self.more_button

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

    def show_info(self) -> None:
        data = dict(getattr(self.canvas, "data", {}) or {})
        kind = str(data.get("kind", "empty") or "empty")
        source = str(data.get("source", "—") or "—")
        summary = str(data.get("summary", data.get("description", "")) or "").strip()
        detail = f"类型：{kind}\n数据来源：{source}"
        if summary:
            detail += f"\n\n{summary}"
        QMessageBox.information(self, "图表信息", detail)


__all__ = ["PlotTools"]

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import Badge, PrimaryButton, SecondaryButton
from frontend_pyside.shared.plotting.canvas import PlotCanvas


class ImageViewerWindow(QMainWindow):


    def __init__(self, title: str, data: dict, parent=None) -> None:
        super().__init__(parent)
        self._result_title = title
        self._data = dict(data or {})
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(f"图像查看器 · {title}")
        self.resize(1180, 760)
        self.setMinimumSize(760, 520)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(7)

        toolbar = QFrame()
        toolbar.setObjectName("viewerToolbar")
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(9, 5, 9, 5)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        tools.addWidget(heading)
        source = str(self._data.get("source", "结果"))
        tools.addWidget(Badge(source, "success" if "正式" in source else "info"))
        tools.addStretch(1)
        reset = SecondaryButton("复位视图")
        reset.clicked.connect(self._reset)
        tools.addWidget(reset)
        save = PrimaryButton("导出图片")
        save.clicked.connect(self._save)
        tools.addWidget(save)
        root.addWidget(toolbar)

        body = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = PlotCanvas()
        self.canvas.set_plot(self._data)
        body.addWidget(self.canvas)

        info = QFrame()
        info.setObjectName("viewerInfoPanel")
        info.setMinimumWidth(220)
        info.setMaximumWidth(320)
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(12, 10, 12, 10)
        info_layout.setSpacing(7)
        info_layout.addWidget(QLabel("图像信息"))
        for label, value in [
            ("类型", str(self._data.get("kind", "—"))),
            ("来源", source),
            ("横轴", str(self._data.get("x_label", "—"))),
            ("纵轴", str(self._data.get("y_label", "—"))),
            ("说明", str(self._data.get("description", "—"))),
        ]:
            row = QLabel(f"{label}：{value}")
            row.setWordWrap(True)
            row.setObjectName("helperText" if label == "说明" else "viewerInfoText")
            info_layout.addWidget(row)
        info_layout.addStretch(1)
        body.addWidget(info)
        body.setSizes([900, 260])
        root.addWidget(body, 1)
        self.setCentralWidget(central)

    def _reset(self) -> None:
        self.canvas.reset_view()

    def _save(self) -> None:
        path, selected = QFileDialog.getSaveFileName(
            self,
            "导出结果图",
            f"{self._result_title}.png",
            "PNG 图片 (*.png);;SVG 矢量图 (*.svg);;PDF 文档 (*.pdf)",
        )
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if not suffix:
            suffix = ".png" if "PNG" in selected else ".svg" if "SVG" in selected else ".pdf"
            path += suffix
        try:
            self.canvas.figure.savefig(path, dpi=180, bbox_inches="tight")
        except Exception as exc:  
            QMessageBox.warning(self, "导出失败", str(exc))


class ResultCompareWindow(QMainWindow):


    def __init__(self, results: dict[str, dict], current: str = "", parent=None) -> None:
        super().__init__(parent)
        self.results = {str(k): dict(v or {}) for k, v in results.items()}
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("结果对比")
        self.resize(1360, 780)
        self.setMinimumSize(900, 560)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(7)

        toolbar = QFrame()
        toolbar.setObjectName("viewerToolbar")
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(9, 5, 9, 5)
        tools.addWidget(QLabel("左侧结果"))
        self.left_selector = QComboBox()
        self.left_selector.addItems(self.results)
        tools.addWidget(self.left_selector)
        tools.addWidget(QLabel("右侧结果"))
        self.right_selector = QComboBox()
        self.right_selector.addItems(self.results)
        tools.addWidget(self.right_selector)
        tools.addStretch(1)
        self.sync_label = Badge("独立坐标", "info")
        self.sync_label.setToolTip("当前绘图后端暂不强制同步坐标；对比窗口仍使用相同可用面积。")
        tools.addWidget(self.sync_label)
        root.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.left_canvas = PlotCanvas()
        self.right_canvas = PlotCanvas()
        splitter.addWidget(self.left_canvas)
        splitter.addWidget(self.right_canvas)
        splitter.setSizes([650, 650])
        root.addWidget(splitter, 1)

        keys = list(self.results)
        if current in keys:
            self.left_selector.setCurrentText(current)
        if len(keys) > 1:
            right = keys[1] if keys[0] == self.left_selector.currentText() else keys[0]
            self.right_selector.setCurrentText(right)
        self.left_selector.currentTextChanged.connect(self._render)
        self.right_selector.currentTextChanged.connect(self._render)
        self._render()
        self.setCentralWidget(central)

    def _render(self) -> None:
        left = self.left_selector.currentText()
        right = self.right_selector.currentText()
        self.left_canvas.set_plot(self.results.get(left, {"kind": "empty", "message": "无结果"}))
        self.right_canvas.set_plot(self.results.get(right, {"kind": "empty", "message": "无结果"}))

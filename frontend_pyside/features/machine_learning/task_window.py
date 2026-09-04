from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from frontend_pyside.features.machine_learning.page import MachineLearningPage
from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.icons import icon


class MachineLearningPredictionTaskWindow(QDialog):
    """Modeless forward-prediction task beside the persistent simulation workbench."""

    navigateRequested = Signal(str)
    openInWorkspaceRequested = Signal()

    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mlPredictionTaskWindow")
        self.setModal(False)
        self.setSizeGripEnabled(True)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(820, 560)
        self.setMinimumSize(680, 460)
        self.setWindowTitle("正向预测")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget(self)
        header.setObjectName("optimizationTaskHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 9, 10, 9)
        row.setSpacing(10)
        text_box = QWidget(header)
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        title = QLabel("正向预测", text_box)
        title.setObjectName("optimizationTaskTitle")
        subtitle = QLabel("当前系统 → 代理模型预测；主仿真工作台保持可操作并用于正式验证。", text_box)
        subtitle.setObjectName("optimizationTaskSubtitle")
        subtitle.setWordWrap(True)
        text_layout.addWidget(title)
        text_layout.addWidget(subtitle)
        row.addWidget(text_box, 1)
        keep = QLabel("非模态任务窗", header)
        keep.setObjectName("mutedText")
        # The subtitle already states that the main simulation workbench remains
        # usable. Repeating the same fact here steals valuable header width in
        # the 680 px compact window, so keep only the explicit container switch.
        keep.hide()
        self.workspace_button = QToolButton(header)
        self.workspace_button.setText("完整页面")
        self.workspace_button.setObjectName("compactTextTool")
        self.workspace_button.setMinimumWidth(96)
        self.workspace_button.setToolTip("在主工作区打开同一正向预测任务")
        self.workspace_button.clicked.connect(self.openInWorkspaceRequested.emit)
        row.addWidget(self.workspace_button)
        close = QToolButton(header)
        close.setObjectName("drawerCloseButton")
        close.setIcon(icon("close", theme.TEXT_SECONDARY, 17))
        close.setToolTip("关闭任务窗")
        close.clicked.connect(self.hide)
        row.addWidget(close)
        root.addWidget(header)

        self.page = MachineLearningPage(context, self)
        self.page.navigateRequested.connect(self.navigateRequested)
        self.page.prepare_prediction_task_window()
        root.addWidget(self.page, 1)

    def bring_to_front(self) -> None:
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()


__all__ = ["MachineLearningPredictionTaskWindow"]

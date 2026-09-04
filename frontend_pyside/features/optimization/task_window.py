from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from frontend_pyside.features.optimization.page import OptimizationPage
from frontend_pyside.shared.icons import icon
from frontend_pyside.resources import theme_tokens as theme


_TASK_COPY = {
    "optimization.scan": ("参数研究", "研究参数规律；结果点可以临时预览到主仿真工作台。"),
    "optimization.tolerance": ("容差分析", "设置制造/装调容差并查看统计结果。"),
    "optimization.variables": ("自动优化", "搜索更优参数；候选可以在主仿真工作台预览后再写回。"),
    "optimization.inverse_design": ("物理反向设计", "按目标性能进行物理搜索，并由正式仿真验证候选。"),
    "optimization.ml_inverse_prediction": ("代理模型反向预测", "代理模型快速产生候选，再交给真实光学仿真验证。"),
    "optimization.validation": ("实验验证", "把实验/文献结果与平台正式仿真进行定量比较。"),
}


class OptimizationTaskWindow(QDialog):
    """One modeless research task beside the persistent simulation workbench.

    This is deliberately a real top-level modeless window rather than a modal
    dialog.  The main simulation canvas remains interactive while the task runs.
    """

    navigateRequested = Signal(str)
    previewRequested = Signal(dict, str)
    previewCleared = Signal()
    openInWorkspaceRequested = Signal(str, object)

    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("optimizationTaskWindow")
        self.setModal(False)
        self.setSizeGripEnabled(True)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(1120, 740)
        self.setMinimumSize(880, 600)
        self._target = "optimization.scan"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget(self)
        header.setObjectName("optimizationTaskHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 8, 10, 8)
        header_layout.setSpacing(8)
        text_box = QWidget(header)
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        self.title_label = QLabel("参数研究", text_box)
        self.title_label.setObjectName("optimizationTaskTitle")
        self.subtitle_label = QLabel("", text_box)
        self.subtitle_label.setObjectName("optimizationTaskSubtitle")
        self.subtitle_label.setWordWrap(True)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)
        header_layout.addWidget(text_box, 1)

        self.keep_visible_label = QLabel("主仿真可操作", header)
        self.keep_visible_label.setToolTip("任务窗为非模态窗口；主仿真工作台仍可切换 2D/3D/模场/相位等结果")
        self.keep_visible_label.setObjectName("mutedText")
        self.keep_visible_label.setMinimumWidth(112)
        header_layout.addWidget(self.keep_visible_label)
        self.workspace_button = QToolButton(header)
        self.workspace_button.setText("完整页面")
        self.workspace_button.setObjectName("compactTextTool")
        self.workspace_button.setToolTip("在主工作区打开同一任务的完整页面；高级设置和完整数据不会丢失")
        self.workspace_button.setMinimumWidth(96)
        self.workspace_button.clicked.connect(lambda: self.openInWorkspaceRequested.emit(self._target, self.page.export_task_state()))
        header_layout.addWidget(self.workspace_button)
        close = QToolButton(header)
        close.setObjectName("drawerCloseButton")
        close.setIcon(icon("close", theme.TEXT_SECONDARY, 17))
        close.setToolTip("关闭任务窗")
        close.clicked.connect(self.hide)
        header_layout.addWidget(close)
        root.addWidget(header)

        self.page = OptimizationPage(context, self)
        self.page.navigateRequested.connect(self.navigateRequested)
        self.page.previewRequested.connect(self.previewRequested)
        self.page.previewCleared.connect(self.previewCleared)
        root.addWidget(self.page, 1)

    @property
    def target(self) -> str:
        return self._target

    def set_target(self, target: str, payload: dict | None = None) -> None:
        self._target = str(target or "optimization.scan")
        title, subtitle = _TASK_COPY.get(self._target, ("研究任务", ""))
        self.setWindowTitle(title)
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        self.page.prepare_task_window(self._target)
        if payload:
            action = {"target": self._target, "level": "prepare"}
            action.update(dict(payload))
            self.page.handle_assistant_action(action)

    def bring_to_front(self) -> None:
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()


__all__ = ["OptimizationTaskWindow"]

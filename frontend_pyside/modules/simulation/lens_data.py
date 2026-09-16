"""仿真“镜头数据”和光源/光纤示意图页面。

本模块负责三类页面组件：

* :class:`LensDataDocument`：承载唯一的顺序表面编辑器；
* :class:`ObjectSchematicView`：只绘制光源或光纤对象的轻量示意图；
* :class:`SchematicDocument`：把示意图和当前工程摘要组合成文档页面。

镜头编辑逻辑仍由 ``features.simulation.components`` 提供，本模块只负责
页面装配、选择联动和展示层刷新。
"""

from __future__ import annotations

from frontend_pyside.modules import shared as _shared
from frontend_pyside.modules.page_spec import PageSpec

globals().update(
    {
        name: value
        for name, value in vars(_shared).items()
        if not name.startswith("__")
    }
)

# 镜头数据是仿真一级入口下的默认二级页面。
PAGE = PageSpec(
    "simulation", "lens_data", "lens_data",
    "镜头数据", "镜头数据表格",
    "镜头数据", "中央顺序表面编辑器",
)

class EmptyDocument(QWidget):
    """在暂无具体数据时显示的通用占位文档。"""

    def __init__(self, title: str, subtitle: str, message: str = "当前页签等待数据", parent=None) -> None:
        """创建占位页；subtitle 和 message 保留用于兼容旧页面调用。"""
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("DocumentTitle")
        root.addWidget(heading)
        # 使用伸展空间把标题固定在页面上方，避免空页面显得拥挤。
        root.addStretch(2)


class LensDataDocument(QWidget):
    """仿真工程的顺序表面镜头数据编辑页。"""

    settingsRequested = Signal(str)

    def __init__(self, context, parent=None) -> None:
        """创建编辑器，并把它作为当前页面唯一的核心表格。"""
        super().__init__(parent)
        self.context = context
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(5)
        self.editor = OpticalSystemEditor(context.project, self)
        # 这是唯一的核心编辑器。侧边栏从不打开另一个完整的编辑器窗口；
        # 它只负责选中并滚动这个表格。
        button = getattr(self.editor, "full_editor_button", None)
        if button is not None:
            button.hide()
        root.addWidget(self.editor, 1)

    def select_surface(self, row: int) -> None:
        """选中指定表面行，并将表格滚动到该行。"""
        table = getattr(self.editor, "table", None)
        if table is None:
            # 编辑器在某些降级或初始化阶段可能暂时没有表格，此时忽略请求。
            return
        if 0 <= int(row) < table.rowCount():
            # 同时选行和滚动，保证从对象侧栏跳转时用户能看到目标表面。
            table.selectRow(int(row))
            table.scrollToItem(table.item(int(row), 0))


class ObjectSchematicView(QWidget):
    """绘制只包含光源或光纤的示意图，不绘制镜头组。"""

    def __init__(self, kind: str, parent=None) -> None:
        """创建示意图画布；kind 决定后续绘制光源还是光纤。"""
        super().__init__(parent)
        self.kind = kind
        self.mode = "gaussian"
        self.setObjectName("SchematicCanvas")
        self.setMinimumHeight(220)

    def set_mode(self, mode: str) -> None:
        """切换示意图模式，并请求 Qt 重绘画布。"""
        self.mode = str(mode or "gaussian")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制背景、光轴和当前对象的专属示意图。"""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#F7F9FC"))
        width = max(self.width(), 1)
        height = max(self.height(), 1)
        mid_y = height / 2
        painter.setPen(QPen(QColor("#8AA0B8"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(20, int(mid_y), width - 20, int(mid_y))
        if self.kind == "source_schematic":
            # 光源页展示光束类型；镜头组由正式光路图负责，不在这里重复绘制。
            self._paint_source(painter, width, height, mid_y)
        else:
            # 光纤页展示端面、模场和接收模式。
            self._paint_fiber(painter, width, height, mid_y)

    def _paint_source(self, painter: QPainter, width: float, height: float, mid_y: float) -> None:
        """按高斯光、点光源或均匀/平行光绘制光源出射示意。"""
        painter.setPen(QPen(QColor("#1F4E79"), 2))
        painter.setBrush(QColor("#D6E6F5"))
        painter.drawRect(28, int(mid_y - 28), 36, 56)
        painter.setPen(QColor("#1F4E79"))
        painter.drawText(24, int(mid_y + 48), "光源")
        start_x = 78
        end_x = width - 40
        color = QColor("#C45C26")
        painter.setPen(QPen(color, 2))
        if self.mode == "pupil":
            # 用多条平行线表达填充入瞳的均匀光/视场光。
            for offset in (-18, -6, 6, 18):
                painter.drawLine(int(start_x), int(mid_y + offset), int(end_x), int(mid_y + offset))
            painter.drawText(int(width / 2 - 40), 28, "均匀/平行光 · 视场")
        elif self.mode == "point":
            # 点光源用一个小圆点和发散光线表示，并标注 NA。
            painter.drawEllipse(int(start_x), int(mid_y - 4), 8, 8)
            for offset in (-40, -20, 0, 20, 40):
                painter.drawLine(int(start_x + 8), int(mid_y), int(end_x), int(mid_y + offset))
            painter.drawText(int(width / 2 - 30), 28, "点光源 · NA")
        else:
            # 默认使用两条边界线和一条中心线表示高斯束腰。
            painter.drawLine(int(start_x), int(mid_y - 22), int(end_x), int(mid_y - 8))
            painter.drawLine(int(start_x), int(mid_y + 22), int(end_x), int(mid_y + 8))
            painter.drawLine(int(start_x), int(mid_y), int(end_x), int(mid_y))
            painter.drawText(int(width / 2 - 40), 28, "高斯光束 · 束腰")

    def _paint_fiber(self, painter: QPainter, width: float, height: float, mid_y: float) -> None:
        """绘制光纤端面、模场区域和横向偏移方向。"""
        cx = int(width * 0.62)
        cy = int(mid_y)
        painter.setPen(QPen(QColor("#1F4E79"), 2))
        painter.setBrush(QColor("#E8EEF5"))
        painter.drawEllipse(cx - 54, cy - 54, 108, 108)
        painter.setBrush(QColor("#F4D7C5"))
        painter.drawEllipse(cx - 22, cy - 22, 44, 44)
        painter.setPen(QColor("#1F4E79"))
        painter.drawText(cx - 24, cy + 76, "端面")
        painter.drawText(cx - 20, cy + 4, "MFD")
        painter.setPen(QPen(QColor("#C45C26"), 2))
        painter.drawLine(cx, cy, cx + 48, cy - 28)
        if self.mode == "multimode":
            # 多模模式与单模模式使用相同几何图，仅改变说明文字。
            painter.drawText(40, height - 24, "多模")
        elif self.mode in {"import", "imported", "user_mode"}:
            # 导入复场是外部场分布，不再假设为理想单模高斯场。
            painter.drawText(40, height - 24, "导入复场")
        else:
            painter.drawText(40, height - 24, "单模")


class SchematicDocument(QWidget):
    """将对象示意图和当前工程的关键参数摘要组合为一个文档页。"""

    def __init__(self, context, kind: str, parent=None) -> None:
        """创建示意图，并监听工程变化以刷新摘要。"""
        super().__init__(parent)
        self.context = context
        self.kind = kind
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)
        self.canvas = ObjectSchematicView(kind)
        root.addWidget(self.canvas, 1)
        summary = QLabel()
        summary.setObjectName("DocumentMetric")
        summary.setWordWrap(True)
        root.addWidget(summary)
        self.summary = summary
        self.refresh()
        # 工程参数变化时只刷新摘要，不重建整个页面。
        context.project.project_changed.connect(lambda _project: self.refresh())

    def set_mode(self, mode: str) -> None:
        """更新示意图模式并同步刷新页面摘要。"""
        self.canvas.set_mode(mode)
        self.refresh()

    def refresh(self) -> None:
        """从当前工程读取波长或模场直径并更新页面摘要。"""
        project = self.context.project.project
        if self.kind == "source_schematic":
            self.summary.setText(f"波长：{float(project.wavelength_nm):.2f} nm")
        else:
            self.summary.setText(f"模场直径：{float(project.receiver_mfd_um):.2f} μm")

__all__ = ["EmptyDocument","LensDataDocument","ObjectSchematicView","SchematicDocument"]

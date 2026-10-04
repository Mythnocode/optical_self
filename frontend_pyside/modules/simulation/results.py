"""仿真正式结果文档。

本模块把工程上下文中的正式计算结果转换为可显示的结果工作区，并负责：

* 根据页面 ``kind`` 选择指标和绘图数据；
* 在工程修改后标记旧结果，避免用户误把过期结果当成当前结果；
* 对光路图追加用户探测器示意对象；
* 提供文字查看、独立窗口放大和 PNG 导出操作。

具体的光学计算和结果适配仍由 ``features.simulation`` 完成，本模块不重新
计算物理量，只做 Qt 页面生命周期和展示层适配。
"""

from __future__ import annotations

from shared_presentation.simulation.result_metrics import ResultMetrics

import numpy as np

from frontend_pyside.modules import shared as _shared
from frontend_pyside.shared.plotting.optical_scene_geometry import (
    build_beam_envelope,
    focus_from_envelope,
)

globals().update(
    {
        name: value
        for name, value in vars(_shared).items()
        if not name.startswith("__")
    }
)

# 每种结果类型按照优先级列出可接受的绘图键；前面的键优先使用。
RESULT_PLOT_KEYS: dict[str, tuple[str, ...]] = {
    "ray_layout": ("光路",),
    "layout_3d": ("3D光路",),
    "spot": ("点列图",),
    "coupling": ("端面匹配", "模式重叠", "耦合图", "能量分解"),
    "wavefront": ("波前", "PSF"),
}

# 供工作台或结果查看器使用的正式结果视图名称集合。
FORMAL_RESULT_VIEWS: tuple[str, ...] = (
    "光路", "3D光路", "点列图", "PSF", "波前", "端面匹配"
)

class ResultDocument(QWidget):
    """一个正式分析结果文档，外层工作台不再重复创建结果工具栏。"""

    relatedRequested = Signal(str)

    def __init__(self, context, kind: str, parent=None) -> None:
        """创建结果页，并订阅正式结果和指标变化信号。"""
        super().__init__(parent)
        self.context = context
        self.kind = kind
        self._result_revision = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)
        # 页眉只显示结果来源和必要的关联视图入口。
        header = QHBoxLayout()
        # 三个效率标签放在左侧，正式结果到达后由指标信号实时刷新。
        self.sys_coup = QLabel("系统效率：—")
        self.sys_coup.setObjectName("coup")
        self.rec_coup = QLabel("端面接收效率：—")
        self.rec_coup.setObjectName("coup")
        self.tot_coup = QLabel("总耦合效率：—")
        self.tot_coup.setObjectName("coup")
        for label in (self.sys_coup, self.rec_coup, self.tot_coup):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.addWidget(label)

        source = QLabel("光学仿真结果未生成")
        source.setObjectName("ResultSource")
        # 让三个效率标签和右侧“已计算”状态标签保持相同高度。
        status_height = source.sizeHint().height()
        source.setFixedHeight(status_height)
        for label in (self.sys_coup, self.rec_coup, self.tot_coup):
            label.setFixedHeight(status_height)
        header.addStretch(1)
        header.addWidget(source)
        if kind == "ray_layout":
            # 3D 光路与 2D 光路共用同一份正式结果，因此只作为关联视图打开。
            view3d = QToolButton()
            view3d.setText("3D 视图")
            view3d.setToolTip("系统三维光路；仿真示意图不画镜头")
            view3d.clicked.connect(lambda: self.relatedRequested.emit("layout_3d"))
            header.addWidget(view3d)
        root.addLayout(header)
        # 隐藏通用工作区的多余工具栏，把页面控制权收敛到本模块底部按钮。
        self.workspace = LazyResultWorkspace(self)
        self.workspace.set_single_view_only(True)
        self.workspace.set_toolbar_visible(False)
        self.workspace.set_pane_header_visible(False)
        self.workspace.set_pane_source_visible(False)
        self.workspace.set_plot_tools_visible(False)
        self.workspace.set_maximize_controls_visible(False)
        self.workspace.set_footer_visible(False)
        root.addWidget(self.workspace, 1)
        action_row = QHBoxLayout()
        self.text_button = QPushButton("文字")
        self.zoom_button = QPushButton("放大")
        self.export_button = QPushButton("导出")
        action_row.addStretch(1)
        action_row.addWidget(self.text_button)
        action_row.addWidget(self.zoom_button)
        action_row.addWidget(self.export_button)
        root.addLayout(action_row)
        self._text = QLabel("")
        self._text.setWordWrap(True)
        self._text.setObjectName("DocumentText")
        self._text.hide()
        root.addWidget(self._text)
        self.text_button.clicked.connect(lambda: self._text.setVisible(not self._text.isVisible()))
        self.zoom_button.clicked.connect(self._open_plot_window)
        self.export_button.clicked.connect(self._export_plot)
        # 保存最近一次绘图载荷，供放大窗口和导出操作复用。
        self._last_plot: dict[str, Any] = {"kind": "empty", "message": ""}
        self._sync_export_enabled()
        # 正式结果到达时刷新图表；工程指标变化时刷新页内摘要。
        context.project.formal_result_changed.connect(self._result_changed)
        context.project.metrics_changed.connect(lambda _metrics: self._refresh_metrics())
        self._refresh_metrics()
        existing = getattr(context.project, "formal_result", None)
        if isinstance(existing, dict) and existing:
            self._result_changed(existing)
        else:
            self._show_placeholder()

    def _show_placeholder(self) -> None:
        """在尚未生成正式结果时显示占位信息。"""
        self._set_source("等待计算结果")
        self._update_header_metrics({})
        self._last_plot = {"kind": "empty", "message": "提交计算后，这里显示对应结果。"}
        self.workspace.set_result(0, "等待结果", self._last_plot)
        self._sync_export_enabled()

    def _result_changed(self, result: object) -> None:
        """接收新的正式结果，并更新指标、图表和文字详情。"""
        if not isinstance(result, dict) or not result:
            # 空结果代表计算被清空或尚未完成，回到统一占位状态。
            self._show_placeholder()
            return
        metrics = dict(result.get("metrics") or {})
        arrays = dict(result.get("arrays") or {})
        self._result_revision = int(getattr(self.context.project, "design_revision", 0) or 0)
        self._set_source("已计算")
        self._update_header_metrics(metrics, arrays=arrays)
        # 先把后端结果转换为绘图载荷，再交给懒加载工作区渲染。
        data = self._result_plot(result)
        self._last_plot = data
        self.workspace.set_result(0, _kind_titles("simulation", self.kind)[0], data)
        self._text.setText(self._detail_text(result))
        self._sync_export_enabled()

    def refresh(self) -> None:
        """刷新指标，并在工程修改后标记正式结果过期。"""
        self._refresh_metrics()
        current_revision = int(getattr(self.context.project, "design_revision", 0) or 0)
        if self._result_revision and current_revision != self._result_revision:
            self.mark_stale()

    def mark_stale(self) -> None:
        """当结果对应的设计版本落后于当前工程时更新过期提示。"""
        current_revision = int(getattr(self.context.project, "design_revision", 0) or 0)
        if not self._result_revision or current_revision == self._result_revision:
            return
        self._set_source("当前系统已修改 · 需重新计算")

    def _set_source(self, text: str) -> None:
        """更新页眉中的结果来源，并刷新其过期状态样式。"""
        source = self.findChild(QLabel, "ResultSource")
        if source is not None:
            source.setText(text)
            source.setProperty("stale", str(text).startswith("当前系统已修改"))
            source.style().unpolish(source)
            source.style().polish(source)

    def _refresh_metrics(self) -> None:
        """从项目上下文读取当前指标并更新指标标签。"""
        formal_result = getattr(self.context.project, "formal_result", None)
        if isinstance(formal_result, dict) and formal_result:
            metrics = dict(formal_result.get("metrics") or {})
            arrays = dict(formal_result.get("arrays") or {})
            self._update_header_metrics(metrics, arrays=arrays)
            return
        metrics = dict(getattr(self.context.project.project, "metrics", {}) or {})
        self._update_header_metrics(metrics)

    def _result_plot(self, result: dict[str, Any]) -> dict[str, Any]:
        """根据页面 kind 选择并生成第一个可用的绘图载荷。"""
        keys = RESULT_PLOT_KEYS.get(self.kind, ())
        try:
            project = serialize_project(self.context.project.project)
        except Exception:
            project = {}
        # The active calculation settings are stored in the submitted project
        # snapshot.  Merge them back here because the result document is opened
        # after submission and otherwise serialize_project() has no form state.
        stored_payload = getattr(self.context.project, "simulation_project_payload", {})
        if callable(stored_payload):
            stored_payload = stored_payload()
        if isinstance(stored_payload, dict):
            stored_settings = stored_payload.get("analysis_settings")
            if isinstance(stored_settings, dict):
                project["analysis_settings"] = {
                    **dict(project.get("analysis_settings") or {}),
                    **stored_settings,
                }
        # 结果适配器负责处理后端格式差异，本页面只指定需要的绘图类别。
        plots = formal_result_to_plots(result, project, requested_keys=set(keys))
        for key in keys:
            payload = plots.get(key)
            if isinstance(payload, dict) and str(payload.get("kind", "empty")) != "empty":
                # 只使用当前页面的第一份有效图表，保持工作区单视图模式。
                return self._apply_detector_overlay(payload)
        message = "正式结果已返回，但当前页暂未找到可绘制的数据。"
        diagnostics = formal_result_diagnostics(result)
        if diagnostics:
            message = f"{message}\n{diagnostics}"
        return {"kind": "empty", "message": message}

    def _apply_detector_overlay(self, payload: dict[str, Any]) -> dict[str, Any]:
        """为光路类结果追加用户探测器示意对象，不修改原始载荷。"""
        if self.kind not in {"ray_layout", "layout_3d"}:
            return payload
        overlay = _user_detector_object(self, payload)
        # 复制字典和对象列表，避免污染缓存中的后端结果。
        copied = dict(payload)
        objects = [
            dict(item)
            for item in payload.get("objects") or []
            if isinstance(item, dict) and not dict(item.get("metadata") or {}).get("user_detector")
        ]
        if overlay is not None:
            # 用户探测器只作为显示覆盖层，不参与已经完成的正式计算。
            objects.append(overlay)
        copied["objects"] = objects
        return copied

    def _detail_text(self, result: dict[str, Any]) -> str:
        """组织结果来源、状态和诊断信息，供“文字”按钮查看。"""
        lines = [
            f"结果来源：{result.get('source', '正式计算')}",
            f"状态：{result.get('status', '—')}",
            formal_result_diagnostics(result),
        ]
        return "\n".join(item for item in lines if item)

    def _open_plot_window(self) -> None:
        """在独立窗口中打开当前图表，便于放大查看。"""
        window = QWidget(self, Qt.WindowType.Window)
        window.setWindowTitle(f"{_kind_titles('simulation', self.kind)[0]} · 独立窗口")
        window.resize(900, 620)
        layout = QVBoxLayout(window)
        # 独立窗口只读取当前缓存载荷，不重新触发计算或后端请求。
        view = LazyResultWorkspace(window)
        view.set_single_view_only(True)
        view.set_result(0, _kind_titles("simulation", self.kind)[0], self._last_plot)
        layout.addWidget(view, 1)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.show()
        self._plot_window = window

    def _sync_export_enabled(self) -> None:
        """仅在存在有效绘图载荷时启用导出按钮。"""
        plot = dict(getattr(self, "_last_plot", {}) or {})
        self.export_button.setEnabled(str(plot.get("kind") or "empty") != "empty")

    def _export_plot(self) -> None:
        """将当前工作区图表导出为用户选择路径下的 PNG 文件。"""
        figure = getattr(self.workspace, "figure", None)
        if figure is None or str((self._last_plot or {}).get("kind") or "empty") == "empty":
            # 没有有效结果时禁止导出，避免生成空白文件或抛出绘图库异常。
            self.export_button.setEnabled(False)
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出结果", "analysis_result.png", "PNG 图像 (*.png)")
        if not path:
            # 用户取消保存对话框时不改变当前页面状态。
            return
        figure.savefig(path, dpi=220, bbox_inches="tight")
    _format_efficiency = staticmethod(ResultMetrics._format_efficiency)

    _format_number = staticmethod(ResultMetrics._format_number)

    _metric_value = staticmethod(ResultMetrics._metric_value)

    _numeric_array = staticmethod(ResultMetrics._numeric_array)

    _peak_position_text = classmethod(ResultMetrics._peak_position_text.__func__)

    _focus_position_text = classmethod(ResultMetrics._focus_position_text.__func__)

    def _update_header_metrics(self, metrics: dict[str, Any], *, arrays: dict[str, Any] | None = None) -> None:
        values = ResultMetrics(self.kind).labels(metrics, arrays=arrays)
        for index, label in enumerate((self.sys_coup, self.rec_coup, self.tot_coup)):
            if index >= len(values):
                label.hide()
            else:
                label.setText(values[index])
                label.show()


__all__ = ["ResultDocument"]

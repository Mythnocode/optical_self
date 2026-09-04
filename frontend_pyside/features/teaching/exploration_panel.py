from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import CollapsiblePanel, PrimaryButton, SecondaryButton
from frontend_pyside.shared.icons import icon
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace

from .mismatch_lab import LESSONS, LESSON_BY_KEY, MismatchVisualWidget, TrendWidget, lesson_efficiency
from .phenomenon_lab import PHENOMENA
from .applicability import evaluate_scene_applicability


_CONCEPTS: dict[str, dict[str, str]] = {
    "gaussian_q": {
        "title": "高斯光束与 q 参数：尺寸相同，状态也可能不同",
        "observe": "拖动传播位置，光斑半径与波前曲率会同时变化；束腰处曲率趋于无穷大。",
        "why": "q 参数把光斑尺寸和波前曲率放在同一个复参数中，所以单看焦点或光斑直径不足以描述耦合状态。",
        "boundary": "教学曲线使用理想 Gaussian 关系；明显像差、高数值孔径或非高斯光场应回正式复场。",
        "verify": "在正式仿真中同时查看接收面强度与相位，并扫描接收面位置。",
    },
    "model_boundary": {
        "title": "快速近似什么时候开始不够",
        "observe": "随着系统逐渐偏离近轴条件，解析趋势与高保真趋势开始分开。",
        "why": "ABCD 方法只传播近轴高斯光束的一阶状态；像差、截光和高角度成分不会被完整描述。",
        "boundary": "差异出现并不自动说明正式模型正确，正式模型仍需要采样、窗口和能量收敛检查。",
        "verify": "改变 F/# 或有效口径，比较解析结果、正式复场与数值收敛结果。",
    },
    "ccd_phase": {
        "title": "为什么 CCD 看起来正常，耦合仍可能很低",
        "observe": "强度曲线可以保持不变，而相位坡度或波前曲率已经明显变化。",
        "why": "CCD 主要测量强度；单模耦合依赖复场相干重叠，因此相位错误可以在强度图中被隐藏。",
        "boundary": "真实相机还会受背景、像元积分、饱和与噪声影响。",
        "verify": "用轴向/角度扫描和正式复场相位诊断形成第二条证据。",
    },
    "spot_definitions": {
        "title": "RMS / FWHM / D4σ 不是同一个光斑尺寸",
        "observe": "同一个分布用不同定义会得到不同的数值；加入背景或裁剪后偏差也不同。",
        "why": "这些指标来自不同的统计或阈值定义，不能直接把一个软件的 RMS 与另一个软件的 FWHM 比较。",
        "boundary": "非高斯、饱和或感兴趣区域截断时，理想高斯换算关系会失效。",
        "verify": "统一图像预处理、像元尺寸、ROI 和尺寸定义后，再做平台—实验—Zemax比较。",
    },
    "aperture_clipping": {
        "title": "孔径截断：光线命中也不等于能量完整通过",
        "observe": "减小有效口径后，边缘功率先损失，光斑旁瓣与峰值也随之变化。",
        "why": "有限口径截断振幅分布，既降低系统透过率，也改变接收面的衍射结构。",
        "boundary": "仅看主光线是否穿过孔径无法判断截光；必须检查全光束包络或复场边缘功率。",
        "verify": "扫描有效口径并检查能量审计、边缘功率和接收面复场收敛。",
    },
    "path_miss": {
        "title": "光路未命中：连接关系不能冒充物理光线",
        "observe": "器件仍可在拓扑上相连，但正式追迹没有到达下游接收面。",
        "why": "三维位置、口径、倾角或器件顺序使真实光线与有效面不相交。",
        "boundary": "灰色拓扑线只说明设计意图；只有带版本号的正式追迹可以显示为红色物理光线。",
        "verify": "查看未命中表面、偏离量和方向，修正后重新提交当前版本追迹。",
    },
    "polarization": {
        "title": "偏振失配：强度相同，偏振重叠仍可能不同",
        "observe": "旋转偏振轴时几何光路和总强度近似不变，但通过 PBS 或保偏接收的功率变化。",
        "why": "偏振器件和保偏光纤对 Jones/Stokes 状态及轴向夹角敏感。",
        "boundary": "标量高斯与普通几何追迹不能给出完整偏振耦合结论。",
        "verify": "使用偏振追迹并扫描偏振轴角，比较两正交分量与正式偏振重叠。",
    },
    "sampling": {
        "title": "采样不足：数值误差不是一种物理失配",
        "observe": "改变网格、窗口或光瞳采样时结果仍明显漂移。",
        "why": "离散网格没有解析足够的相位、旁瓣或孔径边缘，导致积分结果依赖数值设置。",
        "boundary": "采样不足不能通过调镜片补偿；它会让优化器追逐数值伪峰。",
        "verify": "完成网格、窗口、零填充和光瞳点数的逐级收敛检查。",
    },
    "compound_mismatch": {
        "title": "复合失配：不要强迫系统只有一个“主因”",
        "observe": "横向、角度、尺寸、曲率或截光可同时存在，单参数扫描会出现偏峰或不对称。",
        "why": "多个自由度在复场重叠中共同作用，局部等效关系会让不同机制产生相似效率损失。",
        "boundary": "SHAP 排名是代理模型内的候选因素，不是复合系统的唯一物理因果证明。",
        "verify": "列出多个候选及证据，采用互补扫描、正式复场与实验观测逐项排除。",
    },
    "reality": {
        "title": "真实实验为什么没有理论曲线那么漂亮",
        "observe": "打开背景、噪声、饱和或回程间隙后，同一理想响应会出现偏置、削顶和迟滞。",
        "why": "测量链和机械链也会改变观测结果；实验曲线不是纯光学模型的直接输出。",
        "boundary": "这些开关只是教学示意，不是具体相机或机械平台的标定模型。",
        "verify": "真实实验应使用暗场、饱和检查、机械回程测试和输入功率监测。",
    },
}



class _CurrentPageStack(QStackedWidget):
    """Size only for the visible teaching page.

    Qt's default QStackedWidget minimum-size hint considers every hidden page.
    That made the six-column multi-mismatch editor silently force the single
    mismatch page to ~850 px wide on portrait screens.
    """

    def sizeHint(self) -> QSize:
        widget = self.currentWidget()
        return widget.sizeHint() if widget is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        widget = self.currentWidget()
        if widget is None:
            return super().minimumSizeHint()
        hint = widget.minimumSizeHint()
        # The inspector itself owns the useful minimum width. Hidden teaching
        # modes must never increase it.
        return QSize(min(hint.width(), 430), hint.height())

_ENGINEERING: dict[str, dict[str, str]] = {
    "convergence": {
        "title": "点数更多不是为了画得更漂亮：数值结果必须收敛",
        "observe": "网格逐渐加密时，结果应趋于稳定；窗口太小时边缘功率会提醒你结果仍受截断影响。",
        "why": "正式复场是离散计算，网格、光瞳采样和窗口都会成为数值误差来源。",
        "boundary": "不同光路不能机械照搬同一个 513/1025 网格标准，应针对当前系统重新检查。",
        "verify": "固定物理输入，只改变网格、光瞳采样和窗口，记录结果变化与边缘功率。",
    },
    "robustness": {
        "title": "最高效率不一定是工程上最好的设计",
        "observe": "名义峰值更高的设计如果容差很窄，加入装调误差后平均效率和良率可能更差。",
        "why": "工程设计关心误差分布下的表现，而不是只关心一个理想参数点。",
        "boundary": "良率结论依赖你给出的真实误差分布；错误的分布会得到错误的工程判断。",
        "verify": "对候选结果使用同一组误差分布做 Monte Carlo，并比较 P5/P50/P95 与目标良率。",
    },
    "ml_boundary": {
        "title": "参数扫描、Sobol、SHAP 回答的是不同问题",
        "observe": "改变输入范围或训练数据后，Sobol/SHAP 排名可能变化，但正式单参数响应并不会因此变成另一条物理规律。",
        "why": "参数扫描是正式模型正向响应；Sobol 是指定分布下的方差分解；SHAP 是代理模型预测解释。",
        "boundary": "三者都不能脱离各自的输入范围、数据和模型质量被解释成普遍物理常数。",
        "verify": "高价值 SHAP 结论回到正式参数扫描；代理优化候选回到正式复场复算。",
    },
    "false_peak": {
        "title": "代理模型为什么会产生假峰值",
        "observe": "训练样本稀疏的区域可能出现代理模型高峰，而正式物理面并没有对应高效率。",
        "why": "优化器只会寻找代理模型给出的高值，不知道那个高值是插值可信区还是外推误差。",
        "boundary": "测试集误差不能保证未来所有候选都处于同样误差范围。",
        "verify": "检查候选与训练域距离，用正式复场复算并把新真实结果回填训练集。",
    },
}


class TeachingExplorationPanel(QFrame):
    closeRequested = Signal()
    returnRequested = Signal(object)

    SECTION_MISMATCH = 0
    SECTION_DIAGNOSIS = 1
    SECTION_CONCEPTS = 2
    SECTION_ENGINEERING = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("teachingExplorationPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(430, 500)
        self.setMaximumWidth(520)
        self._section_buttons: list[QPushButton] = []
        self._scene_model = None
        self._scene_snapshot = None
        self._build_ui()
        self.open_section("mismatch", "lateral")

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("教学提示")
        title.setObjectName("pageTitle")
        top.addWidget(title)
        subtitle = QLabel("当前实验的参数、现象与验证")
        subtitle.setObjectName("helperText")
        top.addWidget(subtitle)
        top.addStretch(1)
        close = QToolButton()
        close.setIcon(icon("close", "#344054", 18))
        close.setToolTip("关闭探索面板")
        close.clicked.connect(self.closeRequested.emit)
        top.addWidget(close)
        root.addLayout(top)

        self.nav_layout = QGridLayout()
        self.nav_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_layout.setHorizontalSpacing(7)
        self.nav_layout.setVerticalSpacing(6)
        self.section_group = QButtonGroup(self)
        self.section_group.setExclusive(True)
        for index, (label, icon_name) in enumerate([
            ("失配探索", "inspect"),
            ("曲线诊断", "phenomenon"),
            ("模型与测量", "intensity"),
            ("数值与工程", "chart"),
        ]):
            button = SecondaryButton(label)
            button.setIcon(icon(icon_name, "#344054", 17))
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self._set_section(i))
            self.section_group.addButton(button, index)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._section_buttons.append(button)
            self.nav_layout.addWidget(button, 0, index)
        root.addLayout(self.nav_layout)

        self.stack = _CurrentPageStack()
        self.stack.addWidget(self._build_mismatch_page())
        self.stack.addWidget(self._build_diagnosis_page())
        self.stack.addWidget(self._build_concepts_page())
        self.stack.addWidget(self._build_engineering_page())
        root.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        note = QLabel("教学图用于建立物理直觉；正式科研结论仍需回当前系统的正式仿真、扫描或实验验证。")
        note.setObjectName("helperText")
        note.setWordWrap(True)
        footer.addWidget(note, 1)
        self.return_button = PrimaryButton("带着这个问题回正式研究")
        self.return_button.setIcon(icon("next", "#FFFFFF", 17))
        self.return_button.clicked.connect(self._return_to_research)
        footer.addWidget(self.return_button)
        root.addLayout(footer)

        self.setStyleSheet(
            "QFrame#teachingExplorationPanel { background:#FFFFFF; border:1px solid #98A2B3; border-radius:10px; }"
        )

    def _clear_grid_positions(self, layout: QGridLayout, widgets: list[QWidget]) -> None:
        for widget in widgets:
            layout.removeWidget(widget)

    def _apply_compact_layout(self) -> None:
        compact = self.width() < 900
        very_compact = self.width() < 560

        # Section navigation: 4-across when there is room, 2x2 in the docked inspector.
        self._clear_grid_positions(self.nav_layout, list(self._section_buttons))
        nav_cols = 2 if very_compact else 4
        for index, button in enumerate(self._section_buttons):
            self.nav_layout.addWidget(button, index // nav_cols, index % nav_cols)

        # Never let a long mismatch name force the disturbance editor beyond the viewport.
        for widget in (self.mismatch_type_label, self.mismatch_selector, self.mismatch_value_label, self.mismatch_value):
            self.primary_grid.removeWidget(widget)
        if compact:
            self.primary_grid.addWidget(self.mismatch_type_label, 0, 0)
            self.primary_grid.addWidget(self.mismatch_selector, 0, 1, 1, 3)
            self.primary_grid.addWidget(self.mismatch_value_label, 1, 0)
            self.primary_grid.addWidget(self.mismatch_value, 1, 1)
            self.primary_grid.setColumnStretch(1, 1)
            self.primary_grid.setColumnStretch(2, 1)
            self.primary_grid.setColumnStretch(3, 1)
        else:
            self.primary_grid.addWidget(self.mismatch_type_label, 0, 0)
            self.primary_grid.addWidget(self.mismatch_selector, 0, 1)
            self.primary_grid.addWidget(self.mismatch_value_label, 0, 2)
            self.primary_grid.addWidget(self.mismatch_value, 0, 3)
            self.primary_grid.setColumnStretch(1, 1)

        # Observation / correction are semantic peers, but in a narrow panel they
        # must stack rather than truncate each other's explanatory text.
        self.quick_grid.removeWidget(self.mismatch_observe)
        self.quick_grid.removeWidget(self.mismatch_adjustment)
        if compact:
            self.quick_grid.setColumnStretch(0, 1)
            self.quick_grid.setColumnStretch(1, 0)
            self.quick_grid.addWidget(self.mismatch_observe, 0, 0)
            self.quick_grid.addWidget(self.mismatch_adjustment, 1, 0)
        else:
            self.quick_grid.setColumnStretch(0, 1)
            self.quick_grid.setColumnStretch(1, 1)
            self.quick_grid.addWidget(self.mismatch_observe, 0, 0)
            self.quick_grid.addWidget(self.mismatch_adjustment, 0, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_compact_layout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_compact_layout()

    def _set_section(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        button = self.section_group.button(index)
        if button is not None:
            button.setChecked(True)

    # ------------------------------------------------------------------ mismatch
    def _build_mismatch_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.mode_controls = QGridLayout()
        self.mode_controls.setContentsMargins(0, 0, 0, 0)
        self.mode_controls.setHorizontalSpacing(8)
        self.mode_controls.setVerticalSpacing(5)
        self.mismatch_mode_label = QLabel("实验方式")
        self.mode_controls.addWidget(self.mismatch_mode_label, 0, 0)
        self.mismatch_mode = QComboBox()
        self.mismatch_mode.addItem("单因素自由探索", "single")
        self.mismatch_mode.addItem("两种失配并排对比", "compare")
        self.mismatch_mode.addItem("复合失配", "multi")
        self.mismatch_mode.currentIndexChanged.connect(self._mismatch_mode_changed)
        self.mismatch_mode.setMinimumWidth(0)
        self.mismatch_mode.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.mode_controls.addWidget(self.mismatch_mode, 0, 1)
        self.mode_controls.setColumnStretch(1, 1)
        root.addLayout(self.mode_controls)

        self.mismatch_stack = _CurrentPageStack()
        self.mismatch_stack.addWidget(self._build_single_mismatch())
        self.mismatch_stack.addWidget(self._build_compare_mismatch())
        self.mismatch_stack.addWidget(self._build_multi_mismatch())
        root.addWidget(self.mismatch_stack, 1)
        return page

    def _build_single_mismatch(self) -> QWidget:
        host = QWidget()
        root = QVBoxLayout(host)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)

        self.primary_grid = QGridLayout()
        self.primary_grid.setContentsMargins(0, 0, 0, 0)
        self.primary_grid.setHorizontalSpacing(8)
        self.primary_grid.setVerticalSpacing(5)
        self.mismatch_type_label = QLabel("失配类型")
        self.primary_grid.addWidget(self.mismatch_type_label, 0, 0)
        self.mismatch_selector = QComboBox()
        for lesson in LESSONS:
            self.mismatch_selector.addItem(lesson.title, lesson.key)
        self.mismatch_selector.currentIndexChanged.connect(self._single_mismatch_changed)
        self.mismatch_selector.setMinimumWidth(0)
        self.mismatch_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.primary_grid.addWidget(self.mismatch_selector, 0, 1)
        self.mismatch_value_label = QLabel("当前扰动")
        self.primary_grid.addWidget(self.mismatch_value_label, 0, 2)
        self.mismatch_value = QDoubleSpinBox()
        self.mismatch_value.setMinimumWidth(0)
        self.mismatch_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.mismatch_value.valueChanged.connect(self._update_single_mismatch)
        self.primary_grid.addWidget(self.mismatch_value, 0, 3)
        self.primary_grid.setColumnStretch(1, 1)
        root.addLayout(self.primary_grid)

        current = CollapsiblePanel("当前系统证据", expanded=True)
        self.current_scene_rows = {
            "feasibility": self._explain_label("几何与波段"),
            "ray": self._explain_label("正式光线"),
            "efficiency": self._explain_label("效率来源"),
            "receiver": self._explain_label("接收面测量"),
        }
        for widget in self.current_scene_rows.values():
            current.content_layout.addWidget(widget)
        root.addWidget(current)

        self.display_layout = QGridLayout()
        self.display_layout.setContentsMargins(0, 0, 0, 0)
        self.display_layout.setHorizontalSpacing(7)
        self.display_layout.setVerticalSpacing(5)
        self.display_group = QButtonGroup(self)
        self.display_group.setExclusive(True)
        for i, (text, value, icon_name) in enumerate([
            ("强度", "intensity", "intensity"), ("相位", "phase", "phase"), ("叠加", "overlay", "compare")
        ]):
            btn = SecondaryButton(text)
            btn.setIcon(icon(icon_name, "#344054", 16))
            btn.setCheckable(True)
            btn.setProperty("displayMode", value)
            btn.clicked.connect(lambda checked=False, mode=value: self._set_mismatch_display(mode))
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.display_group.addButton(btn, i)
            self.display_layout.addWidget(btn, 0, i)
            if value == "overlay":
                btn.setChecked(True)
        root.addLayout(self.display_layout)

        # At the 1366-wide application layout the explorer receives about
        # 600 px.  A side-by-side 420 px optical visual + explanation column
        # necessarily clipped controls/text.  Stack visual evidence above the
        # explanation grid so every control remains usable at the supported
        # minimum size while still using width efficiently on larger screens.
        self.mismatch_visual = MismatchVisualWidget()
        self.mismatch_trend = TrendWidget()
        visual_host = QWidget()
        visual_layout = QVBoxLayout(visual_host)
        visual_layout.setContentsMargins(0, 0, 0, 0)
        visual_layout.setSpacing(4)
        visual_layout.addWidget(self.mismatch_visual, 1)
        visual_layout.addWidget(self.mismatch_trend)
        root.addWidget(visual_host, 1)

        self.mismatch_eta = QLabel()
        self.mismatch_eta.setObjectName("panelBigMetric")
        root.addWidget(self.mismatch_eta)

        # 右侧只是教学检查器：首屏只保留“看到什么/怎么修”，
        # 原理、边界和验证按需展开，避免再次形成第二个教材页面。
        self.mismatch_observe = self._explain_label("观察")
        self.mismatch_adjustment = self._explain_label("修正")
        self.quick_grid = QGridLayout()
        self.quick_grid.setContentsMargins(0, 0, 0, 0)
        self.quick_grid.setHorizontalSpacing(10)
        self.quick_grid.setVerticalSpacing(6)
        self.quick_grid.addWidget(self.mismatch_observe, 0, 0)
        self.quick_grid.addWidget(self.mismatch_adjustment, 0, 1)
        self.quick_grid.setColumnStretch(0, 1)
        self.quick_grid.setColumnStretch(1, 1)
        root.addLayout(self.quick_grid)

        details = CollapsiblePanel("原理与验证", expanded=False)
        self.mismatch_why = self._explain_label("物理原因")
        self.mismatch_boundary = self._explain_label("适用边界")
        self.mismatch_verify = self._explain_label("实验判断")
        for widget in (self.mismatch_why, self.mismatch_boundary, self.mismatch_verify):
            details.content_layout.addWidget(widget)
        root.addWidget(details)
        self._single_mismatch_changed()
        return host

    def _build_compare_mismatch(self) -> QWidget:
        host = QWidget()
        root = QVBoxLayout(host); root.setContentsMargins(0,0,0,0)
        row = QGridLayout()
        row.setHorizontalSpacing(8); row.setVerticalSpacing(5)
        self.compare_a = QComboBox(); self.compare_b = QComboBox()
        for lesson in LESSONS:
            self.compare_a.addItem(lesson.title, lesson.key); self.compare_b.addItem(lesson.title, lesson.key)
        self.compare_b.setCurrentIndex(min(3, self.compare_b.count()-1))
        self.compare_level = QSlider(Qt.Orientation.Horizontal); self.compare_level.setRange(0,100); self.compare_level.setValue(55)
        for widget in (self.compare_a, self.compare_b):
            widget.setMinimumWidth(0); widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            widget.currentIndexChanged.connect(self._update_compare)
        self.compare_level.setMinimumWidth(0); self.compare_level.valueChanged.connect(self._update_compare)
        row.addWidget(QLabel("A"),0,0); row.addWidget(self.compare_a,0,1)
        row.addWidget(QLabel("B"),1,0); row.addWidget(self.compare_b,1,1)
        row.addWidget(QLabel("相对扰动"),2,0); row.addWidget(self.compare_level,2,1)
        row.setColumnStretch(1,1)
        root.addLayout(row)
        visuals = QHBoxLayout()
        self.compare_visual_a = MismatchVisualWidget(); self.compare_visual_b = MismatchVisualWidget()
        visuals.addWidget(self.compare_visual_a, 1); visuals.addWidget(self.compare_visual_b, 1)
        root.addLayout(visuals, 1)
        self.compare_summary = QLabel(); self.compare_summary.setWordWrap(True); self.compare_summary.setObjectName("teachingConclusion")
        root.addWidget(self.compare_summary)
        self._update_compare()
        return host

    def _build_multi_mismatch(self) -> QWidget:
        host = QWidget(); root = QVBoxLayout(host); root.setContentsMargins(0,0,0,0)
        note = QLabel("同时改变多个失配量，观察单因素解释何时开始变得不充分。这里使用可解释的教学近似乘积，不替代正式复场。")
        note.setWordWrap(True); note.setObjectName("helperText"); root.addWidget(note)
        grid = QGridLayout(); self.multi_controls: dict[str, QDoubleSpinBox] = {}
        specs = [
            ("lateral", "横向", 0, 8, 0.2, " μm"), ("defocus", "轴向", -150, 150, 5, " μm"),
            ("angle", "角度", 0, 60, 1, " mrad"), ("size", "尺寸比", 0.5, 1.5, 0.02, "×"),
            ("curvature", "曲率相位", 0, 1.5, 0.05, " waves"),
        ]
        for i,(key,label,lo,hi,step,suffix) in enumerate(specs):
            spin=QDoubleSpinBox(); spin.setRange(lo,hi); spin.setSingleStep(step); spin.setSuffix(suffix); spin.setDecimals(2)
            spin.setValue(1.0 if key=="size" else 0.0); spin.valueChanged.connect(self._update_multi)
            self.multi_controls[key]=spin; spin.setMinimumWidth(0); spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            grid.addWidget(QLabel(label), i//2, (i%2)*2); grid.addWidget(spin, i//2, (i%2)*2+1)
        grid.setColumnStretch(1, 1); grid.setColumnStretch(3, 1)
        root.addLayout(grid)
        self.multi_bar=QProgressBar(); self.multi_bar.setRange(0,1000); root.addWidget(self.multi_bar)
        self.multi_summary=QLabel(); self.multi_summary.setWordWrap(True); self.multi_summary.setObjectName("teachingConclusion"); root.addWidget(self.multi_summary)
        self.multi_plot=ResultWorkspace(); self.multi_plot.set_single_view_only(True); self.multi_plot.set_toolbar_visible(False); self.multi_plot.set_maximize_controls_visible(False); self.multi_plot.set_pane_title_visible(False); self.multi_plot.set_pane_source_visible(False); root.addWidget(self.multi_plot,1)
        self._update_multi()
        return host

    def _mismatch_mode_changed(self) -> None:
        self.mismatch_stack.setCurrentIndex(max(0, self.mismatch_mode.currentIndex()))

    def _single_mismatch_changed(self) -> None:
        lesson = LESSON_BY_KEY.get(str(self.mismatch_selector.currentData() or "lateral"), LESSONS[0])
        self.mismatch_value.blockSignals(True)
        self.mismatch_value.setRange(lesson.minimum, lesson.maximum); self.mismatch_value.setSingleStep(lesson.step); self.mismatch_value.setDecimals(2)
        self.mismatch_value.setSuffix((" " + lesson.unit) if lesson.unit else "")
        self.mismatch_value.setValue(lesson.default)
        self.mismatch_value.blockSignals(False)
        self._update_single_mismatch()

    def _set_mismatch_display(self, mode: str) -> None:
        self.mismatch_visual.set_display_mode(mode)

    def _update_single_mismatch(self) -> None:
        lesson=LESSON_BY_KEY.get(str(self.mismatch_selector.currentData() or "lateral"),LESSONS[0]); value=float(self.mismatch_value.value())
        eta=lesson_efficiency(lesson,value,780.0); self.mismatch_visual.set_state(lesson,value,eta); self.mismatch_trend.set_state(lesson,780.0,value)
        self.mismatch_eta.setText(f"教学近似耦合  {eta*100:.1f}%")
        self.mismatch_observe.value_label.setText(lesson.phenomenon)
        self.mismatch_adjustment.value_label.setText(lesson.adjustment)
        self.mismatch_why.value_label.setText(lesson.reason)
        self.mismatch_boundary.value_label.setText("只在近高斯、其它自由度基本匹配的单因素条件下使用；出现明显非对称、双峰或高阶像差时应回正式复场。")
        self.mismatch_verify.value_label.setText(lesson.adjustment + "；再用互补扫描、相位/质心或正式复场形成第二条证据。")

    def bind_scene(self, model: Any, snapshot: Any | None = None) -> None:
        """Bind the principle inspector to the one live experiment state."""
        self._scene_model = model
        self._scene_snapshot = snapshot or (model.scene_snapshot() if model is not None else None)
        if model is None or not hasattr(self, "current_scene_rows"):
            return
        report = evaluate_scene_applicability(model)
        scene_snapshot = self._scene_snapshot
        metrics = getattr(scene_snapshot, "metrics", None)
        validation = tuple(getattr(scene_snapshot, "validation_messages", ()) or ())
        feasibility = "可提交正式追迹" if report.allowed else "已阻止正式追迹"
        if validation:
            feasibility += "；" + str(validation[0])
        else:
            feasibility += f"；{report.coupling_mode}；{report.prescription_source}"
        self.current_scene_rows["feasibility"].value_label.setText(feasibility)
        ray_status = str(getattr(scene_snapshot, "physics_status", "pending") or "pending")
        ray_source = str(getattr(scene_snapshot, "physics_source", "等待正式计算") or "等待正式计算")
        ray_count = len(tuple(getattr(scene_snapshot, "formal_rays_mm", ()) or ()))
        self.current_scene_rows["ray"].value_label.setText(f"{ray_source} · {ray_status} · {ray_count} 条有效路径")
        efficiency_source = str(getattr(scene_snapshot, "efficiency_source", "教学快速估算") or "教学快速估算")
        total = float(getattr(metrics, "total_efficiency", 0.0) or 0.0) if metrics is not None else 0.0
        self.current_scene_rows["efficiency"].value_label.setText(f"{efficiency_source} · 当前 {total * 100:.2f}%")

        scene_nodes = list(dict(getattr(model, "nodes", {}) or {}).values())
        lens_x = max(
            (float(getattr(node, "x", 0.0)) for node in scene_nodes if str(getattr(node, "kind", "")) == "lens"),
            default=-math.inf,
        )
        receiver = next(
            (
                node for node in sorted(scene_nodes, key=lambda item: float(getattr(item, "x", 0.0)))
                if str(getattr(node, "kind", "")) in {"fiber", "imaging_camera", "focus_scan_module", "beam_analyzer"}
                and float(getattr(node, "x", 0.0)) > lens_x
            ),
            None,
        )
        reading = model.instrument_reading(receiver.id) if receiver is not None and hasattr(model, "instrument_reading") else {}
        if reading.get("valid") and "radius_x_um" in reading:
            rx = float(reading.get("rms_x_um", 0.0) or 0.0)
            ry = float(reading.get("rms_y_um", 0.0) or 0.0)
            radial = float(reading.get("radial_rms_um", 0.0) or 0.0)
            self.current_scene_rows["receiver"].value_label.setText(
                f"教学测量预览：RMSx {rx:.2f} µm · RMSy {ry:.2f} µm · 径向 RMS {radial:.2f} µm · 椭圆率 {float(reading.get('ellipticity', 1.0)):.3f}"
            )
        else:
            self.current_scene_rows["receiver"].value_label.setText("当前接收面没有有效测量；未命中时不生成伪光斑。")

    def _update_compare(self) -> None:
        if not hasattr(self,"compare_a"): return
        a=LESSON_BY_KEY[str(self.compare_a.currentData())]; b=LESSON_BY_KEY[str(self.compare_b.currentData())]; f=self.compare_level.value()/100.0
        va=a.minimum+(a.maximum-a.minimum)*f; vb=b.minimum+(b.maximum-b.minimum)*f
        if a.key=="size": va=1.0+(a.maximum-1.0)*f
        if b.key=="size": vb=1.0+(b.maximum-1.0)*f
        ea=lesson_efficiency(a,va,780); eb=lesson_efficiency(b,vb,780)
        self.compare_visual_a.set_state(a,va,ea); self.compare_visual_b.set_state(b,vb,eb)
        self.compare_summary.setText(f"A：{a.title} → {ea*100:.1f}%；B：{b.title} → {eb*100:.1f}%。即使最后效率接近，强度、相位和最有区分力的扫描也可能完全不同。")

    def _update_multi(self) -> None:
        if not hasattr(self,"multi_controls"): return
        factors=[]; total=1.0
        for key,spin in self.multi_controls.items():
            lesson=LESSON_BY_KEY[key]; eta=lesson_efficiency(lesson,float(spin.value()),780); total*=eta
            if eta < 0.97: factors.append((lesson.title,eta))
        self.multi_bar.setValue(int(max(0,min(1,total))*1000))
        factors.sort(key=lambda x:x[1])
        dominant="、".join(name for name,_ in factors[:3]) or "没有明显失配"
        self.multi_summary.setText(f"组合教学近似效率 {total*100:.1f}% · 当前主要损失来自：{dominant}。多因素同时存在时，不应再把一条扫描曲线当作唯一因果证据。")
        xs=[-3+i*0.06 for i in range(101)]; width=max(0.35,1.0-0.35*(1-total)); shift=float(self.multi_controls['lateral'].value())/8*1.4
        ys=[total*math.exp(-((x-shift)/width)**2) for x in xs]
        self.multi_plot.set_result(0,"复合响应示意",{"kind":"line","x":xs,"y":ys,"x_label":"归一化扫描参数","y_label":"教学响应","source":"教学近似","description":"复合失配时曲线形状可能不再对应单一闭式公式。"})

    # ------------------------------------------------------------------ diagnosis
    def _build_diagnosis_page(self) -> QWidget:
        host=QWidget(); root=QVBoxLayout(host); root.setContentsMargins(0,0,0,0)
        row=QHBoxLayout(); row.addWidget(QLabel("我看到的现象")); self.diagnosis_selector=QComboBox()
        for key,item in PHENOMENA.items(): self.diagnosis_selector.addItem(item["title"],key)
        self.diagnosis_selector.currentIndexChanged.connect(self._update_diagnosis); row.addWidget(self.diagnosis_selector,1)
        row.addWidget(QLabel("变化程度")); self.diagnosis_strength=QSlider(Qt.Orientation.Horizontal); self.diagnosis_strength.setRange(0,100); self.diagnosis_strength.setValue(65); self.diagnosis_strength.valueChanged.connect(self._update_diagnosis); row.addWidget(self.diagnosis_strength)
        root.addLayout(row)
        body=QHBoxLayout(); self.diagnosis_plot=ResultWorkspace(); self.diagnosis_plot.set_single_view_only(True); self.diagnosis_plot.set_toolbar_visible(False); self.diagnosis_plot.set_maximize_controls_visible(False); self.diagnosis_plot.set_pane_title_visible(False); self.diagnosis_plot.set_pane_source_visible(False); body.addWidget(self.diagnosis_plot,6)
        text=QVBoxLayout(); self.diag_observe=self._explain_label("先描述证据"); self.diag_suspect=self._explain_label("优先怀疑"); self.diag_alternative=self._explain_label("还不能排除"); self.diag_verify=self._explain_label("最有区分力的下一项实验")
        for w in (self.diag_observe,self.diag_suspect,self.diag_alternative,self.diag_verify): text.addWidget(w)
        text.addStretch(1); body.addLayout(text,5); root.addLayout(body,1); self._update_diagnosis(); return host

    def _update_diagnosis(self) -> None:
        if not hasattr(self,"diagnosis_selector"): return
        key=str(self.diagnosis_selector.currentData() or "curve_features"); item=PHENOMENA[key]; level=self.diagnosis_strength.value()/100.0; xs=[-3+i*0.06 for i in range(101)]
        ref=[math.exp(-(x**2)) for x in xs]
        if key in {"peak_shift","peak_boundary"}: second=[math.exp(-((x-(1.1 if key=='peak_shift' else 2.7)*level)**2)) for x in xs]
        elif key=="narrow_width": second=[math.exp(-((x/max(.28,1.05-.7*level))**2)) for x in xs]
        elif key=="broad_width": second=[math.exp(-((x/(1+.9*level))**2)) for x in xs]
        elif key=="asymmetry": second=[math.exp(-(x**2))*(1 if x<=0 else math.exp(-.9*level*x)) for x in xs]
        else: second=[max(0,min(1,math.exp(-((x-.45*level)/(1+.25*level))**2))) for x in xs]
        self.diagnosis_plot.set_result(0,"扫描指纹",{"kind":"line_multi","x":xs,"series":[{"label":"参考","y":ref},{"label":"当前现象","y":second}],"x_label":"扫描参数（归一化）","y_label":"响应","source":"教学趋势示意","description":"先看峰位、峰高、3 dB 宽度和对称性，再提出假设。"})
        self.diag_observe.value_label.setText(item["observe"]); self.diag_suspect.value_label.setText(item["suspect"])
        self.diag_alternative.value_label.setText(item["distinguish"]); self.diag_verify.value_label.setText(item["verify"])

    # ------------------------------------------------------------------ concepts
    def _build_concepts_page(self) -> QWidget:
        host=QWidget(); root=QVBoxLayout(host); root.setContentsMargins(0,0,0,0)
        row=QHBoxLayout(); row.addWidget(QLabel("主题")); self.concept_selector=QComboBox()
        for key,item in _CONCEPTS.items(): self.concept_selector.addItem(item["title"],key)
        self.concept_selector.currentIndexChanged.connect(self._update_concept); row.addWidget(self.concept_selector,1)
        row.addWidget(QLabel("变化程度")); self.concept_level=QSlider(Qt.Orientation.Horizontal); self.concept_level.setRange(0,100); self.concept_level.setValue(50); self.concept_level.valueChanged.connect(self._update_concept); row.addWidget(self.concept_level)
        root.addLayout(row)
        self.reality_options=QWidget(); ro=QHBoxLayout(self.reality_options); ro.setContentsMargins(0,0,0,0); self.reality_checks={}
        for key,label in [("background","背景"),("noise","噪声"),("saturation","饱和"),("backlash","回程间隙")]:
            cb=QCheckBox(label); cb.toggled.connect(self._update_concept); ro.addWidget(cb); self.reality_checks[key]=cb
        ro.addStretch(1); self.reality_options.hide(); root.addWidget(self.reality_options)
        body=QHBoxLayout(); self.concept_plot=ResultWorkspace(); self.concept_plot.set_single_view_only(True); self.concept_plot.set_toolbar_visible(False); self.concept_plot.set_maximize_controls_visible(False); self.concept_plot.set_pane_title_visible(False); self.concept_plot.set_pane_source_visible(False); body.addWidget(self.concept_plot,6)
        text=QVBoxLayout(); self.concept_observe=self._explain_label("看什么"); self.concept_why=self._explain_label("为什么"); self.concept_boundary=self._explain_label("适用/失效边界"); self.concept_verify=self._explain_label("怎样验证")
        for w in (self.concept_observe,self.concept_why,self.concept_boundary,self.concept_verify): text.addWidget(w)
        text.addStretch(1); body.addLayout(text,5); root.addLayout(body,1); self._update_concept(); return host

    def _update_concept(self) -> None:
        if not hasattr(self,"concept_selector"): return
        key=str(self.concept_selector.currentData() or "gaussian_q"); item=_CONCEPTS[key]; level=self.concept_level.value()/100.0; xs=[-3+i*.06 for i in range(101)]
        self.reality_options.setVisible(key=="reality")
        if key=="gaussian_q":
            w0=.55+.25*level; ys=[w0*math.sqrt(1+(x/(.9+1.1*level))**2) for x in xs]; curve=[(1e6 if abs(x)<.03 else x*(1+1/(x*x+.2))) for x in xs]
            data={"kind":"line_multi","x":xs,"series":[{"label":"光斑半径 w(z)","y":ys},{"label":"曲率示意(缩放)","y":[max(-3,min(3,v/3)) for v in curve]}],"x_label":"传播位置 z","y_label":"归一化量","source":"理想高斯教学关系"}
        elif key=="model_boundary":
            analytic=[.98-.18*(abs(x)/3)**2 for x in xs]; formal=[a-(.03+.20*level)*max(0,(abs(x)-1.1)/1.9)**2 for x,a in zip(xs,analytic)]
            data={"kind":"line_multi","x":xs,"series":[{"label":"快速近似","y":analytic},{"label":"正式复场趋势示意","y":formal}],"x_label":"离轴/高NA程度","y_label":"归一化表现","source":"教学示意"}
        elif key=="ccd_phase":
            intensity=[math.exp(-(x**2)) for x in xs]; phase=[level*x for x in xs]
            data={"kind":"line_multi","x":xs,"series":[{"label":"CCD强度（几乎不变）","y":intensity},{"label":"相位坡度（缩放）","y":phase}],"x_label":"端面位置","y_label":"强度 / 相位示意","source":"教学示意"}
        elif key=="spot_definitions":
            base=[math.exp(-(x**2)) for x in xs]; bg=.04*level; observed=[min(1,bg+y) for y in base]
            data={"kind":"line_multi","x":xs,"series":[{"label":"理想光斑截面","y":base},{"label":"加入背景后","y":observed}],"x_label":"位置","y_label":"强度","source":"教学示意"}
        elif key=="aperture_clipping":
            unclipped=[math.exp(-(x**2)) for x in xs]; limit=max(.45,2.5-1.8*level); clipped=[y if abs(x)<=limit else 0.0 for x,y in zip(xs,unclipped)]
            data={"kind":"line_multi","x":xs,"series":[{"label":"入射场","y":unclipped},{"label":"孔径后场","y":clipped}],"x_label":"孔径坐标","y_label":"归一化振幅","source":"教学截光示意"}
        elif key=="path_miss":
            labels=["拓扑连接","正式命中","接收面有效"]; values=[1.0,max(0.0,1.0-1.4*level),max(0.0,1.0-1.8*level)]
            data={"kind":"barh","labels":labels,"values":values,"show_values":True,"source":"状态分层示意","description":"拓扑连接不是正式光线，未命中时接收结果无效。"}
        elif key=="polarization":
            angles=[-90+i*2 for i in range(91)]; aligned=[math.cos(math.radians(v))**2 for v in angles]
            data={"kind":"line","x":angles,"y":aligned,"x_label":"偏振轴夹角 / °","y_label":"偏振重叠","source":"Jones 标量分量教学关系"}
        elif key=="sampling":
            grids=[65,129,257,513,1025]; error=[(.12+.18*level)/(g/65)**1.1 for g in grids]
            data={"kind":"line","x":grids,"y":error,"x_label":"接收面网格","y_label":"相对变化","source":"数值收敛教学示意"}
        elif key=="compound_mismatch":
            single=[math.exp(-(x**2)) for x in xs]; compound=[(.94-.18*level)*math.exp(-((x-.55*level)/(1-.25*level))**2) for x in xs]
            data={"kind":"line_multi","x":xs,"series":[{"label":"单因素响应","y":single},{"label":"复合失配响应","y":compound}],"x_label":"扫描参数","y_label":"响应","source":"复合趋势教学示意"}
        else:
            ideal=[math.exp(-(x**2)) for x in xs]; observed=list(ideal)
            if self.reality_checks.get('background') and self.reality_checks['background'].isChecked(): observed=[min(1,y+.08) for y in observed]
            if self.reality_checks.get('noise') and self.reality_checks['noise'].isChecked(): observed=[max(0,min(1,y+.035*math.sin(i*2.37))) for i,y in enumerate(observed)]
            if self.reality_checks.get('saturation') and self.reality_checks['saturation'].isChecked(): observed=[min(.72,y) for y in observed]
            if self.reality_checks.get('backlash') and self.reality_checks['backlash'].isChecked(): observed=observed[3:]+observed[-3:]
            data={"kind":"line_multi","x":xs,"series":[{"label":"理想响应","y":ideal},{"label":"实验观测示意","y":observed}],"x_label":"扫描位置","y_label":"归一化观测","source":"教学示意"}
        self.concept_plot.set_result(0,"概念探索",data)
        self.concept_observe.value_label.setText(item['observe']); self.concept_why.value_label.setText(item['why']); self.concept_boundary.value_label.setText(item['boundary']); self.concept_verify.value_label.setText(item['verify'])

    # ------------------------------------------------------------------ engineering
    def _build_engineering_page(self) -> QWidget:
        host=QWidget(); root=QVBoxLayout(host); root.setContentsMargins(0,0,0,0)
        row=QHBoxLayout(); row.addWidget(QLabel("主题")); self.eng_selector=QComboBox()
        for key,item in _ENGINEERING.items(): self.eng_selector.addItem(item['title'],key)
        self.eng_selector.currentIndexChanged.connect(self._update_engineering); row.addWidget(self.eng_selector,1)
        row.addWidget(QLabel("条件")); self.eng_level=QSlider(Qt.Orientation.Horizontal); self.eng_level.setRange(0,100); self.eng_level.setValue(55); self.eng_level.valueChanged.connect(self._update_engineering); row.addWidget(self.eng_level); root.addLayout(row)
        body=QHBoxLayout(); self.eng_plot=ResultWorkspace(); self.eng_plot.set_single_view_only(True); self.eng_plot.set_toolbar_visible(False); self.eng_plot.set_maximize_controls_visible(False); self.eng_plot.set_pane_title_visible(False); self.eng_plot.set_pane_source_visible(False); body.addWidget(self.eng_plot,6)
        text=QVBoxLayout(); self.eng_observe=self._explain_label('看什么'); self.eng_why=self._explain_label('为什么'); self.eng_boundary=self._explain_label('不要误解'); self.eng_verify=self._explain_label('正式验证')
        for w in (self.eng_observe,self.eng_why,self.eng_boundary,self.eng_verify): text.addWidget(w)
        text.addStretch(1); body.addLayout(text,5); root.addLayout(body,1); self._update_engineering(); return host

    def _update_engineering(self) -> None:
        if not hasattr(self,'eng_selector'): return
        key=str(self.eng_selector.currentData() or 'convergence'); item=_ENGINEERING[key]; level=self.eng_level.value()/100.0
        if key=='convergence':
            xs=[65,129,257,513,1025]; asym=.015+.05*level; ys=[.974-asym/(x/65) for x in xs]; edge=[.025/(x/65)**.8 for x in xs]
            data={'kind':'line_multi','x':xs,'series':[{'label':'耦合结果','y':ys},{'label':'边缘功率(示意)','y':edge}], 'x_label':'接收面网格','y_label':'结果 / 边缘功率','source':'教学收敛示意'}
        elif key=='robustness':
            xs=list(range(-50,51,2)); sigma_a=9+10*level; sigma_b=22+8*level; a=[.98*math.exp(-(x/sigma_a)**2) for x in xs]; b=[.95*math.exp(-(x/sigma_b)**2) for x in xs]
            data={'kind':'line_multi','x':xs,'series':[{'label':'设计A：峰值高/容差窄','y':a},{'label':'设计B：峰值略低/容差宽','y':b}], 'x_label':'装调误差','y_label':'效率','source':'教学鲁棒性示意'}
        elif key=='ml_boundary':
            labels=['参数扫描','Sobol','SHAP']; values=[.80,.35+.45*level,.70-.40*level]
            data={'kind':'barh','labels':labels,'values':values,'show_values':True,'source':'教学示意','description':'三者数值不可直接横向当作同一种“重要性”。'}
        else:
            xs=[-2+i*.05 for i in range(81)]; truth=[.82+.12*math.exp(-((x-.15)/.7)**2) for x in xs]; proxy=[y+.16*level*math.exp(-((x-1.65)/.2)**2) for x,y in zip(xs,truth)]
            data={'kind':'line_multi','x':xs,'series':[{'label':'正式物理面','y':truth},{'label':'代理模型','y':proxy}], 'x_label':'候选参数','y_label':'预测/真实效率','source':'教学假峰值示意'}
        self.eng_plot.set_result(0,'工程可信度',data)
        self.eng_observe.value_label.setText(item['observe']); self.eng_why.value_label.setText(item['why']); self.eng_boundary.value_label.setText(item['boundary']); self.eng_verify.value_label.setText(item['verify'])

    @staticmethod
    def _explain_label(title: str) -> QFrame:
        frame=QFrame(); layout=QVBoxLayout(frame); layout.setContentsMargins(0,3,0,3); layout.setSpacing(1)
        heading=QLabel(title); heading.setObjectName('cardTitle'); body=QLabel('—'); body.setObjectName('mutedText'); body.setWordWrap(True)
        layout.addWidget(heading); layout.addWidget(body); frame.value_label=body  # type: ignore[attr-defined]
        return frame

    def open_section(self, section: str, key: str = '') -> None:
        section=str(section or 'mismatch')
        mapping={'mismatch':self.SECTION_MISMATCH,'diagnosis':self.SECTION_DIAGNOSIS,'concept':self.SECTION_CONCEPTS,'engineering':self.SECTION_ENGINEERING}
        index=mapping.get(section,self.SECTION_MISMATCH); self._set_section(index)
        if index==self.SECTION_MISMATCH and key:
            i=self.mismatch_selector.findData(key)
            if i>=0: self.mismatch_selector.setCurrentIndex(i)
        elif index==self.SECTION_DIAGNOSIS and key:
            i=self.diagnosis_selector.findData(key)
            if i>=0: self.diagnosis_selector.setCurrentIndex(i)
        elif index==self.SECTION_CONCEPTS and key:
            i=self.concept_selector.findData(key)
            if i>=0: self.concept_selector.setCurrentIndex(i)
        elif index==self.SECTION_ENGINEERING and key:
            i=self.eng_selector.findData(key)
            if i>=0: self.eng_selector.setCurrentIndex(i)

    def assistant_target_widget(self, action: dict[str, Any]):
        target=str(action.get('target',''))
        if target=='teaching.mismatch': return self.mismatch_selector
        if target in {'teaching.diagnosis','teaching.phenomenon'}: return self.diagnosis_selector
        if target=='teaching.concept': return self.concept_selector
        if target=='teaching.explore': return self.section_group.button(self.SECTION_MISMATCH)
        return self

    def _return_to_research(self) -> None:
        if self.stack.currentIndex()==self.SECTION_DIAGNOSIS:
            item=PHENOMENA[str(self.diagnosis_selector.currentData() or 'curve_features')]
            parameter=item.get('parameter','当前扫描参数')
        else:
            parameter='当前教学参数'
        self.returnRequested.emit({'label':'带着这个问题回正式研究','target':'optimization.scan','level':'prepare','prefill_parameter':parameter,'from_teaching':True})


__all__ = ['TeachingExplorationPanel']

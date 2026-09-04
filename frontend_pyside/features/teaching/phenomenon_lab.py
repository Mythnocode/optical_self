from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import PrimaryButton, SecondaryButton
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace


PHENOMENA: dict[str, dict] = {
    "peak_shift": {
        "title": "为什么曲线整体向左 / 右移动？",
        "observe": "先看峰位是否移动，再看峰高和 3 dB 宽度有没有一起明显变化。",
        "suspect": "如果主要是峰位平移，优先检查横向零点、固定位置偏差或参考面定义。",
        "distinguish": "不要只凭一条曲线定因。再看光斑质心，或在相同条件下做另一个方向扫描。",
        "verify": "回到参数研究做对应位置扫描；必要时同时记录端面质心。",
        "parameter": "光纤横向位置",
        "check": ("先检查什么？", ["机械/参考零点", "直接认定模场直径错误", "直接换透镜"], 0),
    },
    "peak_boundary": {
        "title": "为什么最佳点落在扫描边界？",
        "observe": "当前只看到了单侧趋势，真正峰值可能还在现有扫描范围之外。",
        "suspect": "首先怀疑扫描范围不足，而不是立即把边界值当成最佳参数。",
        "distinguish": "先扩大范围；如果扩大后仍持续单调，再检查参数定义、约束和模型/实验参考零点。",
        "verify": "扩大扫描范围重新计算，确认峰值确实落在范围内部。",
        "parameter": "当前扫描参数",
        "check": ("现在最先做什么？", ["扩大扫描范围", "直接采用边界点", "先跑 SHAP"], 0),
    },
    "narrow_width": {
        "title": "为什么曲线很窄？",
        "observe": "3 dB 宽度较小，代表这一自由度稍有偏差，结果就会明显下降。",
        "suspect": "这首先说明容差紧，而不是自动等同于某一种机械故障。",
        "distinguish": "把横向与角度、X 与 Y 等互补自由度一起比较；一宽一窄时对模场尺寸更有诊断价值。",
        "verify": "做互补自由度扫描，并在候选结果确定后进入容差分析。",
        "parameter": "当前扫描参数",
        "check": ("曲线窄首先说明什么？", ["容差偏紧", "一定是机械零点错", "模型一定失效"], 0),
    },
    "broad_width": {
        "title": "为什么曲线变宽？",
        "observe": "3 dB 宽度增加，说明当前自由度允许更大的偏差而不会立刻掉出高效率区。",
        "suspect": "宽度变化常与有效模场尺寸、聚焦状态或参数耦合有关，但不能由一条曲线唯一反推。",
        "distinguish": "横向与角度容差具有互补信息：横向变宽、角度变窄时尤其值得检查模场尺寸。",
        "verify": "增加角度扫描或端面光斑/模场测量，寻找第二条独立证据。",
        "parameter": "光纤横向位置",
        "check": ("怎样提高诊断价值？", ["增加互补扫描", "只看峰高", "直接相信 SHAP"], 0),
    },
    "asymmetry": {
        "title": "为什么 z 曲线或参数曲线不对称？",
        "observe": "比较峰值左右两侧下降速度；明显不对称说明单一对称失配模型可能不够。",
        "suspect": "优先检查离焦与其他参数耦合、像差、截断、扫描范围或多个失配同时存在。",
        "distinguish": "二维扫描出现长脊线时说明参数可能退化，现有数据不能唯一确定一个原因。",
        "verify": "增加第二个参数做二维扫描，并回到正式复场检查端面振幅与相位。",
        "parameter": "光纤轴向位置",
        "check": ("明显不对称时更合理的做法？", ["增加第二个独立变量验证", "直接用峰值定因", "只增加 SHAP 样本"], 0),
    },
    "curve_features": {
        "title": "一条扫描曲线应该先看什么？",
        "observe": "按固定顺序看：峰位、峰高、3 dB 宽度、左右对称性。",
        "suspect": "这些特征只能给出优先检查方向，不能直接变成实验因果结论。",
        "distinguish": "若多个因素能产生相似曲线，就需要第二个扫描、质心、光斑或波前信息来打破退化。",
        "verify": "先做最有区分度的第二项研究，再用正式复场确认。",
        "parameter": "当前扫描参数",
        "check": ("正确的诊断顺序？", ["先描述曲线，再提出怀疑，再验证", "看到 SHAP 就下结论", "只比较最高点"], 0),
    },
    "xy_difference": {
        "title": "为什么 X 和 Y 的曲线不一样？",
        "observe": "分别比较 X/Y 的峰位、宽度和峰高，不要只看最高效率。",
        "suspect": "可能来自椭圆光斑、像散、柱面整形不完全、X/Y 零点不同或方向相关像差。",
        "distinguish": "如果 X/Y 束腰位置也不同，像散证据更强；只有峰位不同则先检查零点。",
        "verify": "同时测 X/Y 光斑尺寸和束腰位置，再做对应扫描。",
        "parameter": "光纤横向位置",
        "check": ("X/Y 不同首先要比较什么？", ["峰位、宽度和峰高", "只看总效率", "只看模型特征重要性"], 0),
    },
    "phase_mismatch": {
        "title": "为什么光斑大小看起来正确，效率还是低？",
        "observe": "强度图接近只能说明振幅尺寸可能匹配，复场耦合还取决于相位和波前曲率。",
        "suspect": "优先检查离焦、波前曲率、倾角造成的相位坡度，以及像差。",
        "distinguish": "比较端面相位/曲率与光纤模式；不要只用 CCD 光斑尺寸证明模场完全匹配。",
        "verify": "做轴向扫描并查看正式复场的相位或曲率诊断。",
        "parameter": "光纤轴向位置",
        "check": ("光斑尺寸接近但效率低，还应检查？", ["相位/波前曲率", "只重新测功率", "只增加训练轮数"], 0),
    },
    "f_number": {
        "title": "为什么 F/# 很小时焦斑反而变差？",
        "observe": "理想衍射趋势并不代表真实透镜在更大数值孔径下仍保持低像差。",
        "suspect": "球差、截断、非理想面形和有效孔径利用可能开始主导。",
        "distinguish": "比较几何/波动结果与正式波前、PSF，不能只根据理想 Airy 尺寸判断。",
        "verify": "改变有效孔径或 F/#，同时比较峰值效率、PSF/波前和焦点位置。",
        "parameter": "有效孔径",
        "check": ("F/# 变小后焦斑变差，应同时检查？", ["像差与有效孔径", "只看理想衍射公式", "只改光纤 MFD"], 0),
    },
    "spacing_focus": {
        "title": "为什么改透镜间距后最佳焦点也跟着变？",
        "observe": "透镜间距改变了系统等效传播和中间束腰，因此最佳接收面位置通常会联动。",
        "suspect": "空气间隔和光纤轴向位置可能存在参数耦合，单变量结果不一定能唯一确定原因。",
        "distinguish": "二维扫描若形成长脊线，说明两者可以部分互相补偿。",
        "verify": "做“空气间隔 × 光纤轴向位置”二维扫描，再正式复场确认候选点。",
        "parameter": "空气间隔",
        "check": ("看到长脊线通常意味着？", ["参数存在退化/补偿", "只有一个参数有效", "SHAP 已证明因果"], 0),
    },
}


class PhenomenonLearningPanel(QFrame):
    closeRequested = Signal()
    returnRequested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("phenomenonLearningPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(720, 500)
        self._key = "curve_features"

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)
        top = QHBoxLayout()
        title = QLabel("现象怎么理解")
        title.setObjectName("pageTitle")
        top.addWidget(title)
        top.addStretch(1)
        close = QToolButton()
        close.setText("关闭")
        close.clicked.connect(self.closeRequested.emit)
        top.addWidget(close)
        root.addLayout(top)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("我看到的现象"))
        self.selector = QComboBox()
        for key, item in PHENOMENA.items():
            self.selector.addItem(item["title"], key)
        self.selector.currentIndexChanged.connect(self._selection_changed)
        selector_row.addWidget(self.selector, 1)
        selector_row.addWidget(QLabel("变化程度"))
        self.strength = QSlider(Qt.Orientation.Horizontal)
        self.strength.setRange(0, 100)
        self.strength.setValue(65)
        self.strength.setMaximumWidth(180)
        self.strength.valueChanged.connect(self._update_plot)
        selector_row.addWidget(self.strength)
        root.addLayout(selector_row)

        middle = QHBoxLayout()
        text_host = QWidget()
        text = QVBoxLayout(text_host)
        text.setContentsMargins(0, 0, 0, 0)
        self.observe = self._row("先看什么")
        self.suspect = self._row("优先检查")
        self.distinguish = self._row("怎样区分")
        self.verify = self._row("怎样验证")
        for row in (self.observe, self.suspect, self.distinguish, self.verify):
            text.addWidget(row)
        self.question = QLabel("")
        self.question.setObjectName("cardTitle")
        self.question.setWordWrap(True)
        text.addWidget(self.question)
        self.choice_row = QHBoxLayout()
        self.choice_buttons: list[QPushButton] = []
        for index in range(3):
            button = SecondaryButton("—")
            button.clicked.connect(lambda checked=False, i=index: self._answer(i))
            self.choice_buttons.append(button)
            self.choice_row.addWidget(button)
        text.addLayout(self.choice_row)
        self.feedback = QLabel("")
        self.feedback.setObjectName("helperText")
        self.feedback.setWordWrap(True)
        text.addWidget(self.feedback)
        middle.addWidget(text_host, 5)

        self.plot = ResultWorkspace()
        self.plot.set_single_view_only(True)
        self.plot.set_toolbar_visible(False)
        self.plot.set_maximize_controls_visible(False)
        self.plot.set_pane_title_visible(False)
        self.plot.set_pane_source_visible(False)
        self.plot.setMinimumSize(360, 300)
        middle.addWidget(self.plot, 6)
        root.addLayout(middle, 1)

        footer = QHBoxLayout()
        note = QLabel("教学图用于理解趋势，不替代当前系统的正式参数扫描和复场计算。")
        note.setObjectName("helperText")
        note.setWordWrap(True)
        footer.addWidget(note, 1)
        self.return_button = PrimaryButton("检查我的当前系统")
        self.return_button.clicked.connect(self._return_to_research)
        footer.addWidget(self.return_button)
        root.addLayout(footer)

        self.setStyleSheet(
            "QFrame#phenomenonLearningPanel { background:#FFFFFF; border:1px solid #98A2B3; border-radius:10px; }"
        )
        self.set_phenomenon("curve_features")

    @staticmethod
    def _row(title: str) -> QFrame:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        body = QLabel("—")
        body.setObjectName("mutedText")
        body.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(body)
        frame.value_label = body  # type: ignore[attr-defined]
        return frame

    def set_phenomenon(self, key: str) -> None:
        key = key if key in PHENOMENA else "curve_features"
        self._key = key
        index = self.selector.findData(key)
        if index >= 0 and index != self.selector.currentIndex():
            self.selector.blockSignals(True)
            self.selector.setCurrentIndex(index)
            self.selector.blockSignals(False)
        item = PHENOMENA[key]
        self.observe.value_label.setText(item["observe"])
        self.suspect.value_label.setText(item["suspect"])
        self.distinguish.value_label.setText(item["distinguish"])
        self.verify.value_label.setText(item["verify"])
        question, choices, _correct = item["check"]
        self.question.setText("自检 · " + question)
        for button, choice in zip(self.choice_buttons, choices):
            button.setText(choice)
            button.setProperty("answerState", "")
            button.style().unpolish(button); button.style().polish(button)
        self.feedback.setText("")
        self._update_plot()

    def _selection_changed(self) -> None:
        self.set_phenomenon(str(self.selector.currentData() or "curve_features"))

    @staticmethod
    def _gaussian(x: float, center: float, sigma: float) -> float:
        return math.exp(-((x - center) / max(sigma, 1e-6)) ** 2)

    def _update_plot(self) -> None:
        key = self._key
        level = self.strength.value() / 100.0
        xs = [-3.0 + i * 0.06 for i in range(101)]
        ref = [self._gaussian(x, 0.0, 1.0) for x in xs]
        second: list[float]
        second_label = "变化后"
        x_label = "归一化参数"
        y_label = "归一化耦合效率"
        if key in {"peak_shift", "peak_boundary"}:
            shift = (1.1 if key == "peak_shift" else 2.7) * level
            second = [self._gaussian(x, shift, 1.0) for x in xs]
            second_label = "零点/位置改变后"
        elif key == "narrow_width":
            second = [self._gaussian(x, 0.0, max(0.28, 1.05 - 0.7 * level)) for x in xs]
            second_label = "容差变紧"
        elif key == "broad_width":
            second = [self._gaussian(x, 0.0, 1.0 + 0.9 * level) for x in xs]
            second_label = "横向容差变宽"
        elif key == "asymmetry":
            second = [self._gaussian(x, 0.0, 1.0) * (1.0 if x <= 0 else math.exp(-0.9 * level * x)) for x in xs]
            second_label = "耦合/像差后"
        elif key == "xy_difference":
            ref = [self._gaussian(x, -0.25 * level, 1.0 + 0.25 * level) for x in xs]
            second = [self._gaussian(x, 0.35 * level, max(0.5, 1.0 - 0.35 * level)) for x in xs]
            second_label = "Y 方向"
        elif key == "phase_mismatch":
            second = [0.95 * self._gaussian(x, 0.0, 1.0) * max(0.12, 1.0 - 0.75 * level) for x in xs]
            second_label = "尺寸相近但相位失配"
        elif key == "f_number":
            ref = [max(0.0, min(1.0, 0.45 + 0.12 * (x + 3))) for x in xs]
            second = [max(0.0, min(1.0, r - level * 0.38 * self._gaussian(x, 2.0, 0.75))) for x, r in zip(xs, ref)]
            x_label = "F/# 变化方向"
            second_label = "含像差后的实际趋势"
        elif key == "spacing_focus":
            ref = [0.52 + 0.06 * x for x in xs]
            second = [0.52 - 0.10 * level + (0.06 + 0.07 * level) * x for x in xs]
            x_label = "空气间隔变化"
            y_label = "最佳焦点位置（示意）"
            second_label = "间隔改变后"
        else:
            second = [self._gaussian(x, 0.45 * level, 1.0 + 0.25 * level) for x in xs]
        self.plot.set_result(0, "现象对照", {
            "kind": "line_multi",
            "x": xs,
            "series": [
                {"label": "参考状态" if key != "xy_difference" else "X 方向", "y": ref},
                {"label": second_label, "y": second},
            ],
            "x_label": x_label,
            "y_label": y_label,
            "source": "教学趋势示意",
            "description": "只观察曲线特征；真实结论要回当前系统正式扫描确认。",
        })

    def _answer(self, index: int) -> None:
        correct = int(PHENOMENA[self._key]["check"][2])
        self.feedback.setText("✓ 这个判断更稳妥：先描述现象，再增加独立证据。" if index == correct else "这个选项下结论太快。先回到曲线特征和‘怎样验证’，再选一次。")

    def _return_to_research(self) -> None:
        item = PHENOMENA[self._key]
        self.returnRequested.emit({
            "label": "检查我的当前系统",
            "target": "optimization.scan",
            "level": "prepare",
            "prefill_parameter": item.get("parameter", "当前扫描参数"),
            "from_teaching": self._key,
        })


__all__ = ["PhenomenonLearningPanel", "PHENOMENA"]

"""节点内嵌参数表单：声明式 schema → QFormLayout 面板。

- scan / tolerance / optimize / compute_settings 共用；
- 字段值实时写入 `values` 字典；「✓ 确认」时 apply_to(config) 校验并写回；
- 按钮风格与画布语言一致（黑白灰 + 主按钮深色）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from frontend_pyside.features.canvas.parameter_catalog import (
    CALC_PRECISION_CHOICES,
    LAYOUT_PUPIL_CHOICES,
    OPTIMIZATION_ALGORITHM_CHOICES,
    OPTIMIZATION_OBJECTIVE_CHOICES,
    OUTPUT_GRID_CHOICES,
    PROPAGATION_CHOICES,
    SCAN_MODE_CHOICES,
    SCAN_RESPONSE_CHOICES,
    SCAN_SCALE_CHOICES,
    TOLERANCE_CANDIDATE_CHOICES,
    TOLERANCE_DISTRIBUTION_CHOICES,
    TOLERANCE_SAMPLING_CHOICES,
    TOLERANCE_TEMPLATE_CHOICES,
    VARIABLE_FILTER_CHOICES,
    VARIABLE_SCALE_CHOICES,
    VALIDATION_METRIC_CHOICES,
    VALIDATION_REFERENCE_CHOICES,
)


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str  # "float" / "int" / "text" / "choice"
    default: Any = None
    minimum: float = float("-inf")
    maximum: float = float("inf")
    decimals: int = 3
    suffix: str = ""
    choices: tuple[str, ...] = ()
    hint: str = ""


FIELD_SCHEMA: dict[str, tuple[Field, ...]] = {
    "scan": (
        Field("scan_mode", "扫描模式", "choice", "一维扫描", choices=SCAN_MODE_CHOICES),
        Field("param_path", "主变量路径", "choice", "surfaces[0].radius_mm"),
        Field("param_path2", "第二变量路径", "choice", "", choices=("不启用",)),
        Field("param_label", "扫描参数", "text"),
        Field("param_label2", "第二扫描参数", "text"),
        Field("start", "起始值", "float", 4.6, -50.0, 50.0, 3, " mm"),
        Field("stop", "终止值", "float", 5.6, -50.0, 50.0, 3, " mm"),
        Field("points", "采样点数", "int", 81, 2, 501),
        Field("start2", "第二起始值", "float", -2.0, -50.0, 50.0, 3, " mm"),
        Field("stop2", "第二终止值", "float", 2.0, -50.0, 50.0, 3, " mm"),
        Field("points2", "第二采样点数", "int", 41, 2, 501),
        Field("response", "响应指标", "choice", "耦合效率", choices=SCAN_RESPONSE_CHOICES),
        Field("scale", "采样方式", "choice", "线性采样", choices=SCAN_SCALE_CHOICES),
        Field("include_baseline", "标记当前系统", "bool", True),
        Field("local_refine", "识别高效区域", "bool", True),
    ),
    "tolerance": (
        Field("sample_count", "样本数", "int", 256, 16, 200000),
        Field("candidate", "分析对象", "choice", "当前系统", choices=TOLERANCE_CANDIDATE_CHOICES),
        Field("template", "参数模板", "choice", "优化参数 + 常用装调", choices=TOLERANCE_TEMPLATE_CHOICES),
        Field("sampling", "采样方法", "choice", "LHS", choices=TOLERANCE_SAMPLING_CHOICES),
        Field("distribution", "参数分布", "choice", "正态", choices=TOLERANCE_DISTRIBUTION_CHOICES),
        Field("threshold_efficiency", "良率阈值 η ≥", "float", 0.8, 0.0, 1.0, 3),
        Field("include_deterministic_sensitivity", "一阶灵敏度估计", "bool", True),
    ),
    "optimize": (
        Field("param_path", "变量路径", "choice", "surfaces[0].radius_mm"),
        Field("param_label", "优化变量", "text"),
        Field("objective", "目标函数", "choice", "最大化耦合效率", choices=OPTIMIZATION_OBJECTIVE_CHOICES),
        Field("variable_filter", "变量筛选", "choice", "全部参数", choices=VARIABLE_FILTER_CHOICES),
        Field("variable_scale", "变量尺度", "choice", "线性", choices=VARIABLE_SCALE_CHOICES),
        Field("collimation_surface", "准直评价面", "choice", ""),
        Field("collimation_enabled", "启用准直硬约束", "bool", False),
        Field("collimation_span", "评价段长度", "float", 10.0, 0.1, 1000.0, 3, " mm"),
        Field("collimation_radius_change", "最大半径变化", "float", 2.0, 0.01, 100.0, 3, " %"),
        Field("collimation_curvature", "最大归一化曲率", "float", 0.05, 0.00001, 10.0, 5),
        Field("collimation_centroid_drift", "最大质心漂移", "float", 1.0, 0.001, 100.0, 3, " % 光斑半径"),
        Field("collimation_axis_tilt", "最大光轴倾角", "float", 1.0, 0.001, 1000.0, 3, " mrad"),
        Field("lower", "变量下界", "float", 4.0, -100.0, 100.0, 3, " mm"),
        Field("upper", "变量上界", "float", 6.5, -100.0, 100.0, 3, " mm"),
        Field("initial", "初始值", "float", 5.11, -100.0, 100.0, 3, " mm"),
        Field("algorithm", "算法", "choice", "智能全局搜索", choices=OPTIMIZATION_ALGORITHM_CHOICES),
        Field("starts", "多起点", "int", 8, 1, 100),
        Field("max_iterations", "最大迭代", "int", 300, 10, 5000),
        Field("convergence_tolerance", "收敛阈值", "float", 1e-6, 1e-10, 1e-2, 8),
        Field("validation_metric", "验证指标", "choice", "E003 耦合效率", choices=VALIDATION_METRIC_CHOICES),
        Field("validation_reference", "验证参考", "choice", "实验数据", choices=VALIDATION_REFERENCE_CHOICES),
    ),
    "physical_inverse": (
        Field("param_label", "设计变量", "text"),
        Field("lower", "变量下界", "float", 4.0, -100.0, 100.0, 3, " mm"),
        Field("upper", "变量上界", "float", 6.5, -100.0, 100.0, 3, " mm"),
        Field("initial", "初始值", "float", 5.11, -100.0, 100.0, 3, " mm"),
        Field("target_efficiency", "目标耦合效率", "float", 0.95, 0.0, 1.0, 3),
        Field("max_iterations", "最大迭代", "int", 20, 1, 500),
    ),
    "ml_inverse": (
        Field("surrogate_model_id", "代理模型 ID", "text"),
        Field("param_label", "反向变量", "text"),
        Field("lower", "变量下界", "float", 4.0, -100.0, 100.0, 3, " mm"),
        Field("upper", "变量上界", "float", 6.5, -100.0, 100.0, 3, " mm"),
        Field("initial", "初始值", "float", 5.11, -100.0, 100.0, 3, " mm"),
        Field("target_efficiency", "目标耦合效率", "float", 0.95, 0.0, 1.0, 3),
        Field("max_iterations", "最大迭代", "int", 20, 1, 500),
    ),
    "compute_settings": (
        Field("calc_precision", "主网格", "choice", "257×257", choices=CALC_PRECISION_CHOICES),
        Field("grid_size", "接收面网格", "choice", "513 × 513", choices=OUTPUT_GRID_CHOICES),
        Field("layout_pupil", "光路采样", "choice", "9 × 9", choices=LAYOUT_PUPIL_CHOICES),
        Field("pupil", "分析光瞳", "choice", "49 × 49", choices=("17 × 17", "33 × 33", "49 × 49", "65 × 65")),
        Field("algorithm", "传播算法", "choice", "缩放 Fresnel", choices=PROPAGATION_CHOICES),
        Field("wavelength_nm", "工作波长", "float", 780.0, 200.0, 30000.0, 1, " nm"),
        Field("sample_count", "采样点数", "int", 128, 16, 4096),
    ),
}


class TaskConfigForm(QWidget):
    """参数表单面板：schema 驱动，值实时收集到 values。"""

    valuesChanged = Signal()

    def __init__(self, task_kind: str, config: dict | None = None, parent=None):
        super().__init__(parent)
        self.task_kind = str(task_kind)
        self.schema = FIELD_SCHEMA.get(self.task_kind, ())
        self._config = dict(config or {})
        self.values: dict[str, Any] = {}
        self._editors: dict[str, Any] = {}

        form = QFormLayout(self)
        form.setContentsMargins(10, 8, 10, 8)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for field in self.schema:
            editor = self._build_editor(field)
            self._editors[field.key] = editor
            label = QLabel(field.label, self)
            label.setToolTip(field.hint or field.label)
            form.addRow(label, editor)
        self._collect()

    def _build_editor(self, field: Field) -> QWidget:
        current = self._config.get(field.key, field.default)
        if field.kind == "bool":
            editor = QCheckBox(self)
            editor.setChecked(bool(current))
            editor.toggled.connect(lambda _value, k=field.key: self._collect())
            return editor
        if field.kind == "choice":
            editor = QComboBox(self)
            editor.addItems(list(field.choices))
            if current is not None:
                index = editor.findText(str(current))
                editor.setCurrentIndex(max(0, index))
            editor.currentTextChanged.connect(lambda _t, k=field.key: self._collect())
            return editor
        if field.kind == "text":
            editor = QLineEdit(str(current if current is not None else ""), self)
            editor.setPlaceholderText("—")
            editor.textChanged.connect(lambda _t, k=field.key: self._collect())
            return editor
        if field.kind == "int":
            from PySide6.QtWidgets import QSpinBox

            editor = QSpinBox(self)
            editor.setRange(int(field.minimum), int(field.maximum))
            editor.setValue(int(current if current is not None else field.default or 0))
            editor.valueChanged.connect(lambda _v, k=field.key: self._collect())
            return editor
        editor = QDoubleSpinBox(self)
        editor.setDecimals(field.decimals)
        editor.setRange(field.minimum, field.maximum)
        editor.setStepType(QDoubleSpinBox.StepType.AdaptiveDecimalStepType)
        editor.setValue(float(current) if isinstance(current, (int, float)) else float(field.default or 0.0))
        if field.suffix:
            editor.setSuffix(field.suffix)
        editor.valueChanged.connect(lambda _v, k=field.key: self._collect())
        return editor

    def _collect(self) -> None:
        for field in self.schema:
            editor = self._editors.get(field.key)
            if isinstance(editor, QComboBox):
                self.values[field.key] = editor.currentText()
            elif isinstance(editor, QCheckBox):
                self.values[field.key] = bool(editor.isChecked())
            elif isinstance(editor, QLineEdit):
                self.values[field.key] = editor.text().strip()
            else:
                value = editor.value()
                self.values[field.key] = int(value) if field.kind == "int" else float(value)
        self.valuesChanged.emit()

    def apply_to(self, config: dict) -> tuple[bool, str]:
        """✓ 确认：校验并写回 config。返回 (是否成功, 错误信息)。"""
        self._collect()
        if self.task_kind in {"scan", "optimize"}:
            low, high = (
                float(self.values.get("start", 0.0)),
                float(self.values.get("stop", 0.0)),
            ) if self.task_kind == "scan" else (
                float(self.values.get("lower", 0.0)),
                float(self.values.get("upper", 0.0)),
            )
            if low >= high:
                return False, "范围无效：起始/下界必须小于终止/上界"
            if self.task_kind == "optimize" and not str(self.values.get("param_label", "")).strip():
                return False, "优化变量名不能为空"
        if self.task_kind == "scan" and not str(self.values.get("param_label", "")).strip():
            return False, "扫描参数名不能为空"
        config.update(dict(self.values))
        return True, ""


_FORM_QSS = """
QWidget#taskConfigForm { background: #F7F8FA; border: 1px solid #E1E4E8; border-radius: 8px; }
QLabel { color: #5A6169; font-size: 12px; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    background: #FFFFFF; border: 1px solid #C8CCD2; border-radius: 5px;
    padding: 2px 6px; font-size: 12px; color: #1F2328;
    selection-background-color: #1F2328;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus { border-color: #1F2328; }
"""


def build_config_form(task_kind: str, config: dict | None = None, parent=None) -> TaskConfigForm:
    form = TaskConfigForm(task_kind, config, parent)
    form.setObjectName("taskConfigForm")
    form.setStyleSheet(_FORM_QSS)
    return form


__all__ = ["FIELD_SCHEMA", "Field", "TaskConfigForm", "build_config_form"]

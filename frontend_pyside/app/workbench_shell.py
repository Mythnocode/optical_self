"""The refactored optical workbench shells.

This module contains shell-level widgets, the object rail and document
workspace orchestration.  Concrete document tabs live under
``frontend_pyside.modules``; existing optical controls are reused as leaf widgets
where they already have a stable contract.

There are two mutually exclusive shells:

* :class:`WorkbenchShell` for simulation, model, optimisation and
  explanation.  Result plots (layout, spot, coupling, wavefront) are
  simulation documents, not a separate primary module.
* :class:`TeachingShell` for the teaching bench.  It owns a large canvas and
  uses floating windows; it never creates document tabs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from math import radians
from typing import Any, Callable
from uuid import uuid4

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QIcon, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QSplitter,
    QTabBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.features.simulation.components.optical_system_editor import OpticalSystemEditor
from frontend_pyside.features.simulation.form_state import (
    AlignmentFormState,
    CalculationFormState,
    PRECISION_MAP,
    PROPAGATION_MAP,
    RECEIVER_TYPE_MAP,
    ReceiverFormState,
    SimulationFormState,
    SourceFormState,
    SystemFormState,
    parse_grid_size,
)
from frontend_pyside.features.simulation.imported_field import ImportedFieldSelector
from frontend_pyside.presets.demo_780nm_four_lens import (
    DEFAULT_CALCULATION_PRECISION_TEXT,
    DEFAULT_IMAGE_DISTANCE_MM,
    DEFAULT_OBJECT_DISTANCE_MM,
    DEFAULT_OUTPUT_GRID_SIZE,
    DEFAULT_PROPAGATION_TEXT,
    DEFAULT_PUPIL_SAMPLE_COUNT,
    DEFAULT_LAYOUT_PUPIL_SAMPLE_COUNT,
)
from frontend_pyside.app.workbench_catalog import (
    DATASET_PRECISION_CHOICES,
    DATASET_SAMPLING_CHOICES,
    DATASET_TARGET_CHOICES,
    OPTIMIZATION_OBJECTIVE_CHOICES,
    SCAN_MODE_CHOICES,
    SCAN_RESPONSE_CHOICES,
    SCAN_SCALE_CHOICES,
    SEQUENCE_DATASET_CHOICES,
    SEQUENCE_MODEL_CHOICES,
    TABULAR_DATASET_CHOICES,
    TABULAR_MODEL_CHOICES,
)
from frontend_pyside.shared.plotting.lazy_workspace import LazyResultWorkspace
from frontend_pyside.shared.components.unit_spinbox import UnitAwareDoubleSpinBox
from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.simulation.payloads import build_simulation_payload, restrict_payload
from frontend_pyside.features.simulation.result_adapter import formal_result_diagnostics, formal_result_to_plots
from frontend_pyside.features.simulation.simulation_session import SimulationSession
from frontend_pyside.features.simulation.workflow import SimulationPreviewWorkflow
from frontend_pyside.features.simulation.controller import SimulationController
from frontend_pyside.features.simulation.material_library import MaterialLibraryDocument, UsedMaterialInspector
from frontend_pyside.features.machine_learning.dataset_configuration import build_dataset_parameters
from frontend_pyside.app.workbench_payloads import _augment_payload, explain_job_failure
from frontend_pyside.features.explainability.actions import explain_shap_failure
from shared_contracts.metrics import analyses_for_metrics
from frontend_pyside.app.workbench_jobs import (
    WorkbenchJobController,
    current_lens_features,
    model_features,
    model_prediction_status,
    model_backend_kind,
    opt_chart_payload,
    sampling_backend_name,
    scan_curve_payload,
    sequence_prediction_payload,
    shap_dependence_item,
    shap_supported,
    target_backend_name,
    train_chart_payload,
    train_chart_unavailable_message,
)
from frontend_pyside.features.machine_learning.feature_adapter import FeaturePathError
from frontend_pyside.shared.feature_labels import display_feature_name
from frontend_pyside.features.teaching_v2.canvas import BenchScene, BenchView
from frontend_pyside.features.teaching_v2.inspector import Inspector
from frontend_pyside.features.teaching_v2.model import PLACEABLE_KINDS, Pose, SceneStore, TEACHING_KIND_MIME
from frontend_pyside.features.teaching_v2.physics import FormalTeachingGateway
from frontend_pyside.features.teaching_v2.tasks import ComputationController
from frontend_pyside.features.teaching_v2.view3d import BenchView3D
from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.icons import icon, icon_pixmaps


# ---------------------------------------------------------------------------
# Shell UI and shared tab helpers
# ---------------------------------------------------------------------------

# Shared UI helpers and page metadata are explicit dependencies of the shell.
from frontend_pyside.modules.shared import (
    TabSpec,
    _apply_float,
    _button,
    _coerce_feature_units,
    _coupling_efficiency_from_result,
    _display_variable,
    _field_group,
    _formal_target_value,
    _icon_action_button,
    _job_title,
    _labeled_field,
    _parse_auxiliary_wavelengths,
    _payload_float,
    _payload_length_um,
    _payload_tilt_urad,
    _rail_form,
    _ranked_variable_rows,
    _section_payload,
    _set_combo_data,
    _set_form_row_visible,
    _slider_line,
    _spin,
    _spin_unit_row,
    _unit_row,
    _variable_rows,
    _variable_shap_scores,
)
from frontend_pyside.modules.navigation import (
    FORMAL_RESULT_VIEWS,
    KIND_TO_SECONDARY,
    KIND_TITLES,
    PRIMARY_MODULES,
    RESULT_DOCUMENT_KINDS,
    SECONDARY_DEFAULT_KIND,
    SECONDARY_ICON_FALLBACK,
    SECONDARY_ICONS,
    SECONDARY_ITEMS,
    kind_titles as _kind_titles,
)


class PrimaryBar(QFrame):
    moduleRequested = Signal(str)
    actionRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PrimaryBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(3)
        self.buttons: dict[str, QToolButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, label in PRIMARY_MODULES:
            button = _button(label, checkable=True)
            button.setObjectName("PrimaryModuleButton")
            button.setProperty("module", key)
            button.clicked.connect(lambda _checked=False, value=key: self.moduleRequested.emit(value))
            group.addButton(button)
            self.buttons[key] = button
            layout.addWidget(button)
        layout.addStretch(1)
        for key, tooltip, glyph, color in (
            ("save", "保存", "save", "#344054"),
            ("compute", "开始计算", "play", "#155EEF"),
            ("settings", "设置", "settings", "#344054"),
        ):
            button = _icon_action_button(glyph, tooltip, color=color)
            button.clicked.connect(lambda _checked=False, value=key: self.actionRequested.emit(value))
            layout.addWidget(button)

    def set_module(self, module: str) -> None:
        for key, button in self.buttons.items():
            button.setChecked(key == str(module))


# 二级功能栏「上图下字」的图标参数。
# 尺寸决定按钮最小高度；两个颜色分别对应未选中 / 已选中。
# 图标尺寸。sim_/ml_/opt_/explain_*.png 那些是细线条的矢量风格位图
# （源图 1254×1254），22px 时细节会糊掉、认不出画的是什么，26px 起才清晰，
# 30px 更好但二级栏会更高。内嵌 SVG 那几张在这个尺寸下同样清晰，所以统一用 50。
SECONDARY_ICON_SIZE = 50
# 这两个色号要和 light.qss 里 QToolButton#SecondaryFunctionButton 的
# color / :checked color 保持一致，否则选中时图标和文字会是两种蓝。
SECONDARY_ICON_OFF_COLOR = "#344054"   # = 未选中时的文字色
SECONDARY_ICON_ON_COLOR = "#073A89"    # = 选中时的文字色


def _secondary_icon(key: str) -> QIcon:
    """二级栏按钮的图标：未选中/已选中两套颜色。

    图标名查 :data:`modules.navigation.SECONDARY_ICONS`，查不到就用兜底图标，
    保证每个按钮都还是「上图下字」，不会有的有图、有的没图导致高度参差。

    Qt 的 QIcon 自带 (Mode, State) 两维：对可勾选的 QToolButton 来说，
    ``Mode.Normal + State.Off`` 是未选中，``Mode.Normal + State.On`` 是选中。
    两个都塞进同一个 QIcon，按钮勾选时 Qt 会自动换图，不需要手动 setIcon。

    注意：位图图标若关掉了重新着色（``shared/icons.py`` 的
    ``TINT_PNG_ICONS = False``，当前设置），两态拿到的是同一张原图，
    选中与否只体现在按钮底色和文字颜色上。要恢复图标随选中变色，
    把那个开关打开，并把下面两个颜色对齐 QSS 里的配色即可。
    """
    name = SECONDARY_ICONS.get(str(key)) or SECONDARY_ICON_FALLBACK
    result = QIcon()
    for state, color in (
        (QIcon.State.Off, SECONDARY_ICON_OFF_COLOR),
        (QIcon.State.On, SECONDARY_ICON_ON_COLOR),
    ):
        # icon_pixmaps 已经把常见显示缩放比各烘了一张并标好 devicePixelRatio，
        # 直接整组塞进去，Qt 会挑尺寸最合适的那张，不会放大绘制。
        for pixmap in icon_pixmaps(name, color, SECONDARY_ICON_SIZE):
            result.addPixmap(pixmap, QIcon.Mode.Normal, state)
    return result


class SecondaryBar(QFrame):
    itemRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SecondaryBar")
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 2, 10, 2)
        self.layout.setSpacing(4)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}

    def set_module(self, module: str) -> None:
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # deleteLater() 只是「稍后删除」：在事件循环真正处理它之前，
                # 旧按钮仍然是本栏的子控件，仍然会被绘制，于是和新按钮叠成重影。
                # 先 setParent(None) 立刻把它从父控件摘掉，再排队删除。
                widget.setParent(None)
                widget.deleteLater()
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons.clear()
        for key, title, hint in SECONDARY_ITEMS.get(str(module), ()):
            button = _button(title, checkable=True)
            button.setObjectName("SecondaryFunctionButton")
            button.setProperty("secondaryKey", key)
            button.setToolTip(hint)
            # 使用“上图下字”布局，保证二级功能按钮的图标和标题垂直排列。
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setIcon(_secondary_icon(key))
            button.setIconSize(QSize(SECONDARY_ICON_SIZE, SECONDARY_ICON_SIZE))
            button.clicked.connect(lambda _checked=False, value=key: self.itemRequested.emit(value))
            self.group.addButton(button)
            self.buttons[key] = button
            self.layout.addWidget(button)
        self.layout.addStretch(1)

    def activate(self, key: str) -> None:
        button = self.buttons.get(str(key))
        if button is not None:
            button.setChecked(True)


class SourceInspector(QFrame):
    changed = Signal()
    schematicRequested = Signal()
 
    _MODES = (
        ("gaussian", "高斯光束"),
        ("parallel_pupil", "均匀光瞳"),
        ("object_space_na", "点光源"),
    )

    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("ObjectInspector")
        self._ready = False
        defaults = SourceFormState()
        payload = _section_payload(context, "source")
        waist_x = _payload_length_um(payload, "waist_x_um", "waist_x_mm", defaults.waist_x_um)
        waist_y = _payload_length_um(payload, "waist_y_um", "waist_y_mm", defaults.waist_y_um)
        m2_x = _payload_float(payload, "beam_quality_m2_x", default=defaults.beam_quality_m2_x)
        m2_y = _payload_float(payload, "beam_quality_m2_y", default=defaults.beam_quality_m2_y)
        na_x = _payload_float(payload, "object_na_x", default=defaults.object_na_x)
        na_y = _payload_float(payload, "object_na_y", default=defaults.object_na_y)
        field_x = _payload_float(payload, "field_x_deg", default=defaults.field_x_deg)
        field_y = _payload_float(payload, "field_y_deg", default=defaults.field_y_deg)
        split = abs(waist_x - waist_y) > 1e-9 or abs(m2_x - m2_y) > 1e-9
        split_na = abs(na_x - na_y) > 1e-9
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 4)
        root.setSpacing(6)
        identity, identity_layout = _field_group("基本参数")
        form = _rail_form()
        self.mode = QComboBox()
        for key, label in self._MODES:
            self.mode.addItem(label, key)
        wavelength = _payload_float(payload, "wavelength_nm", default=float(context.project.project.wavelength_nm))
        self.wavelength = _spin(100, 30000, 1, " nm", wavelength)
        self.power = _spin(0, 1e9, 4, "", _payload_float(payload, "power_value", default=defaults.power_value))
        self.power_unit = QComboBox()
        self.power_unit.addItems(["mW", "W", "μW"])
        unit = str(payload.get("power_unit") or defaults.power_unit)
        if self.power_unit.findText(unit) >= 0:
            self.power_unit.setCurrentText(unit)
        form.addRow("光源类型", self.mode)
        form.addRow("波长", _spin_unit_row(self.wavelength))
        form.addRow("总功率", _unit_row(self.power, self.power_unit))
        identity_layout.addLayout(form)
        root.addWidget(identity)
        self.mode_stack = QStackedWidget()
        pupil = QWidget()
        pupil_form = _rail_form()
        pupil.setLayout(pupil_form)
        self.field_x = _spin(-90, 90, 3, " °", field_x)
        self.field_y = _spin(-90, 90, 3, " °", field_y)
        self.field_x.hide()
        self.field_y.hide()
        gaussian = QWidget()
        gaussian_form = _rail_form()
        gaussian.setLayout(gaussian_form)
        self.waist = _spin(0.01, 1e6, 3, " μm", waist_x)
        waist_position = _payload_float(payload, "waist_position_mm", "waist_position_x_mm", default=defaults.waist_position_mm)
        waist_position_x = _payload_float(payload, "waist_position_x_mm", "waist_position_mm", default=waist_position)
        waist_position_y = _payload_float(payload, "waist_position_y_mm", "waist_position_mm", default=waist_position)
        self.waist_pos = _spin(-1e6, 1e6, 3, " mm", waist_position)
        self.m2 = _spin(1.0, 100.0, 3, "", m2_x)
        self.split_axes = QCheckBox("分轴（椭圆光斑）")
        self.split_axes.setChecked(split)
        self.waist_x = _spin(0.01, 1e6, 3, " μm", waist_x)
        self.waist_y = _spin(0.01, 1e6, 3, " μm", waist_y)
        self.waist_pos_x = _spin(-1e6, 1e6, 3, " mm", waist_position_x)
        self.waist_pos_y = _spin(-1e6, 1e6, 3, " mm", waist_position_y)
        self.m2_x = _spin(1.0, 100.0, 3, "", m2_x)
        self.m2_y = _spin(1.0, 100.0, 3, "", m2_y)
        gaussian_form.addRow("束腰半径 ω₀", _spin_unit_row(self.waist))
        gaussian_form.addRow("束腰位置", _spin_unit_row(self.waist_pos))
        gaussian_form.addRow("光束质量 M²", _spin_unit_row(self.m2))
        gaussian_form.addRow(self.split_axes)
        gaussian_form.addRow("束腰半径 ωₓ", _spin_unit_row(self.waist_x))
        gaussian_form.addRow("束腰位置 zₓ", _spin_unit_row(self.waist_pos_x))
        gaussian_form.addRow("束腰半径 ωᵧ", _spin_unit_row(self.waist_y))
        gaussian_form.addRow("束腰位置 zᵧ", _spin_unit_row(self.waist_pos_y))
        gaussian_form.addRow("M²ₓ", _spin_unit_row(self.m2_x))
        gaussian_form.addRow("M²ᵧ", _spin_unit_row(self.m2_y))
        self._gaussian_form = gaussian_form
        point = QWidget()
        point_form = _rail_form()
        point.setLayout(point_form)
        self.source_na = _spin(0, 1, 5, "", na_x)
        self.split_na = QCheckBox("分轴")
        self.split_na.setChecked(split_na)
        self.source_na_y = _spin(0, 1, 5, "", na_y)
        point_form.addRow("数值孔径 NA", _spin_unit_row(self.source_na))
        point_form.addRow(self.split_na)
        point_form.addRow("NAᵧ", _spin_unit_row(self.source_na_y))
        self._point_form = point_form
        self.mode_stack.addWidget(gaussian)
        self.mode_stack.addWidget(pupil)
        self.mode_stack.addWidget(point)
        beam, beam_layout = _field_group("光束参数")
        beam_layout.addWidget(self.mode_stack)
        root.addWidget(beam)
        more = QToolButton()
        more.setText("更多参数")
        more.setCheckable(True)
        more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        root.addWidget(more)
        self.more_host = QWidget()
        more_form = _rail_form()
        self.more_host.setLayout(more_form)
        self.auxiliary = QLineEdit()
        self.auxiliary.setPlaceholderText("例如 850, 1310")
        auxiliaries = payload.get("spectral_wavelengths_nm") or payload.get("auxiliary_wavelengths_nm") or ()
        extra: list[str] = []
        for value in auxiliaries:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if abs(number - wavelength) > 1e-9:
                extra.append(f"{number:.2f}")
        self.auxiliary.setText(", ".join(extra))
        more_form.addRow("辅助波长", self.auxiliary)
        self.more_host.setVisible(False)
        more.toggled.connect(self.more_host.setVisible)
        root.addWidget(self.more_host)
        _set_combo_data(self.mode, str(payload.get("source_type") or "gaussian"))
        self._mode_changed()
        self._split_changed(self.split_axes.isChecked())
        self._na_split_changed(self.split_na.isChecked())
        self._ready = True
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.split_axes.toggled.connect(self._split_changed)
        self.split_na.toggled.connect(self._na_split_changed)
        self.wavelength.valueChanged.connect(self._wavelength_changed)
        self.power.valueChanged.connect(lambda value: self._apply("source.power_value", value, "总功率"))
        self.waist.valueChanged.connect(self._waist_changed)
        self.waist_pos.valueChanged.connect(lambda value: self._apply("source.waist_position_mm", value, "束腰位置"))
        self.m2.valueChanged.connect(self._m2_changed)
        self.waist_x.valueChanged.connect(lambda value: self._apply("source.waist_x_um", value, "束腰半径 ωₓ"))
        self.waist_y.valueChanged.connect(lambda value: self._apply("source.waist_y_um", value, "束腰半径 ωᵧ"))
        self.waist_pos_x.valueChanged.connect(lambda value: self._apply("source.waist_position_x_mm", value, "X方向束腰位置"))
        self.waist_pos_y.valueChanged.connect(lambda value: self._apply("source.waist_position_y_mm", value, "Y方向束腰位置"))
        self.m2_x.valueChanged.connect(lambda value: self._apply("source.beam_quality_m2_x", value, "M²ₓ"))
        self.m2_y.valueChanged.connect(lambda value: self._apply("source.beam_quality_m2_y", value, "M²ᵧ"))
        self.field_x.valueChanged.connect(lambda value: self._apply("source.field_x_deg", value, "视场角 X"))
        self.field_y.valueChanged.connect(lambda value: self._apply("source.field_y_deg", value, "视场角 Y"))
        self.source_na.valueChanged.connect(self._na_changed)
        self.source_na_y.valueChanged.connect(lambda value: self._apply("source.object_na_y", value, "NAᵧ"))

    def _apply(self, path: str, value: float, reason: str) -> None:
        if not self._ready:
            return
        _apply_float(self.context, path, float(value), reason)

    def _mode_changed(self, _index: int = 0) -> None:
        key = str(self.mode.currentData() or "gaussian")
        self.mode_stack.setCurrentIndex({"gaussian": 0, "parallel_pupil": 1, "object_space_na": 2}.get(key, 0))
        self.schematicRequested.emit()
        self.changed.emit()

    def _split_changed(self, checked: bool) -> None:
        for widget in (self.waist_x, self.waist_pos_x, self.waist_y, self.waist_pos_y, self.m2_x, self.m2_y):
            _set_form_row_visible(self._gaussian_form, widget, checked)
        self.waist.setEnabled(not checked)
        self.waist_pos.setEnabled(not checked)
        self.m2.setEnabled(not checked)
        if not checked:
            self._waist_changed(self.waist.value())
            self._m2_changed(self.m2.value())

    def _na_split_changed(self, checked: bool) -> None:
        _set_form_row_visible(self._point_form, self.source_na_y, checked)
        self.source_na.setEnabled(True)
        if not checked:
            self._na_changed(self.source_na.value())

    def _wavelength_changed(self, value: float) -> None:
        self._apply("source.wavelength_nm", float(value), "波长")
        self.changed.emit()

    def _waist_changed(self, value: float) -> None:
        if self.split_axes.isChecked() or not self._ready:
            return
        self._apply("source.waist_x_um", float(value), "束腰半径")
        self._apply("source.waist_y_um", float(value), "束腰半径")

    def _m2_changed(self, value: float) -> None:
        if self.split_axes.isChecked() or not self._ready:
            return
        self._apply("source.beam_quality_m2_x", float(value), "M²")
        self._apply("source.beam_quality_m2_y", float(value), "M²")

    def _na_changed(self, value: float) -> None:
        if not self._ready:
            return
        self._apply("source.object_na_x", float(value), "数值孔径")
        if not self.split_na.isChecked():
            blocked = self.source_na_y.blockSignals(True)
            self.source_na_y.setValue(float(value))
            self.source_na_y.blockSignals(blocked)
            self._apply("source.object_na_y", float(value), "数值孔径")

    def current_mode(self) -> str:
        return str(self.mode.currentData() or "gaussian")

    def schematic_mode(self) -> str:
        return {
            "parallel_pupil": "pupil",
            "object_space_na": "point",
            "gaussian": "gaussian",
        }.get(self.current_mode(), "gaussian")

    def set_field_angles(self, field_x_deg: float, field_y_deg: float) -> None:
        for widget, value in ((self.field_x, field_x_deg), (self.field_y, field_y_deg)):
            blocked = widget.blockSignals(True)
            widget.setValue(float(value))
            widget.blockSignals(blocked)

    def form_state(self) -> SourceFormState:
        split = self.split_axes.isChecked()
        split_na = self.split_na.isChecked()
        waist_x = float(self.waist_x.value() if split else self.waist.value())
        waist_y = float(self.waist_y.value() if split else self.waist.value())
        m2_x = float(self.m2_x.value() if split else self.m2.value())
        m2_y = float(self.m2_y.value() if split else self.m2.value())
        na_x = float(self.source_na.value())
        na_y = float(self.source_na_y.value() if split_na else self.source_na.value())
        wavelength = float(self.wavelength.value())
        return SourceFormState(
            source_type=self.current_mode(),
            wavelength_nm=wavelength,
            waist_x_um=waist_x,
            waist_y_um=waist_y,
            waist_position_mm=float(self.waist_pos.value()),
            waist_position_x_mm=float(self.waist_pos_x.value() if split else self.waist_pos.value()),
            waist_position_y_mm=float(self.waist_pos_y.value() if split else self.waist_pos.value()),
            beam_quality_m2_x=m2_x,
            beam_quality_m2_y=m2_y,
            object_na_x=na_x,
            object_na_y=na_y,
            field_x_deg=float(self.field_x.value()),
            field_y_deg=float(self.field_y.value()),
            power_value=float(self.power.value()),
            power_unit=str(self.power_unit.currentText() or "mW"),
            auxiliary_wavelengths_nm=_parse_auxiliary_wavelengths(self.auxiliary.text(), wavelength),
        )

    def refresh(self) -> None:
        value = float(self.context.project.project.wavelength_nm)
        blocked = self.wavelength.blockSignals(True)
        self.wavelength.setValue(value)
        self.wavelength.blockSignals(blocked)


class FiberInspector(QFrame):
    changed = Signal()
    schematicRequested = Signal()

    _KINDS = (
        ("single_mode_fiber", "单模光纤"),
        ("multimode_fiber", "多模光纤"),
        ("user_mode", "用户模式"),
    )
    _MODELS = (
        ("gaussian", "高斯近似"),
        ("lp01", "LP01"),
        ("he11", "HE11"),
        ("imported", "导入复场"),
    )

    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("ObjectInspector")
        self._ready = False
        defaults = ReceiverFormState()
        payload = _section_payload(context, "receiver")
        mfd_x = _payload_float(payload, "mode_field_diameter_x_um", default=float(context.project.project.receiver_mfd_um))
        mfd_y = _payload_float(payload, "mode_field_diameter_y_um", default=mfd_x)
        na_x = _payload_float(payload, "na_x", default=defaults.na_x)
        na_y = _payload_float(payload, "na_y", default=defaults.na_y)
        core = _payload_float(payload, "core_diameter_um", default=defaults.core_diameter_um)
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 4)
        root.setSpacing(6)
        identity, identity_layout = _field_group("规格")
        form = _rail_form()
        self.kind = QComboBox()
        for key, label in self._KINDS:
            self.kind.addItem(label, key)
        self.model = QComboBox()
        for key, label in self._MODELS:
            self.model.addItem(label, key)
        self.wavelength_view = QLabel(f"{float(context.project.project.wavelength_nm):.2f} nm")
        form.addRow("光纤类型", self.kind)
        form.addRow("模式", self.model)
        form.addRow("工作波长", self.wavelength_view)
        identity_layout.addLayout(form)
        root.addWidget(identity)
        self.model_stack = QStackedWidget()
        gaussian = QWidget()
        gaussian_form = _rail_form()
        gaussian.setLayout(gaussian_form)
        self.mfd = _spin(0.01, 10000, 3, " μm", mfd_x)
        self.split_mfd = QCheckBox("分轴（椭圆模场）")
        self.split_mfd.setChecked(abs(mfd_x - mfd_y) > 1e-9)
        self.mfd_y = _spin(0.01, 10000, 3, " μm", mfd_y)
        gaussian_form.addRow("模场直径 MFD", _spin_unit_row(self.mfd))
        gaussian_form.addRow(self.split_mfd)
        gaussian_form.addRow("MFDᵧ", _spin_unit_row(self.mfd_y))
        self._gaussian_form = gaussian_form
        guided = QWidget()
        guided_form = _rail_form()
        guided.setLayout(guided_form)
        self.core = _spin(0.1, 1000, 3, " μm", core)
        self.n_core = _spin(1.0, 5.0, 6, "", _payload_float(payload, "core_refractive_index", default=defaults.core_refractive_index))
        self.n_clad = _spin(1.0, 5.0, 6, "", _payload_float(payload, "cladding_refractive_index", default=defaults.cladding_refractive_index))
        guided_form.addRow("芯径", _spin_unit_row(self.core))
        guided_form.addRow("纤芯折射率 n_core", _spin_unit_row(self.n_core))
        guided_form.addRow("包层折射率 n_clad", _spin_unit_row(self.n_clad))
        multimode = QWidget()
        mm_form = _rail_form()
        multimode.setLayout(mm_form)
        self.mm_core = _spin(0.1, 1000, 3, " μm", core if core >= 10 else 50.0)
        self.na = _spin(0.001, 1, 5, "", na_x)
        self.split_na = QCheckBox("分轴")
        self.split_na.setChecked(abs(na_x - na_y) > 1e-9)
        self.na_y = _spin(0.001, 1, 5, "", na_y)
        mm_form.addRow("芯径", _spin_unit_row(self.mm_core))
        mm_form.addRow("数值孔径 NA", _spin_unit_row(self.na))
        mm_form.addRow(self.split_na)
        mm_form.addRow("NAᵧ", _spin_unit_row(self.na_y))
        self._mm_form = mm_form
        imported = QWidget()
        imported_layout = QVBoxLayout(imported)
        imported_layout.setContentsMargins(0, 0, 0, 0)
        self.field_selector = ImportedFieldSelector(self._expected_grid_size)
        imported_layout.addWidget(self.field_selector)
        self.model_stack.addWidget(gaussian)
        self.model_stack.addWidget(guided)
        self.model_stack.addWidget(multimode)
        self.model_stack.addWidget(imported)
        mode_box, mode_layout = _field_group("模场")
        mode_layout.addWidget(self.model_stack)
        root.addWidget(mode_box)
        pose_box, pose_layout = _field_group("装调")
        pose = _rail_form()
        self.offset_x = _spin(-1e6, 1e6, 3, " μm", _payload_length_um(payload, "offset_x_um", "offset_x_mm", 0.0))
        self.offset_y = _spin(-1e6, 1e6, 3, " μm", _payload_length_um(payload, "offset_y_um", "offset_y_mm", 0.0))
        self.axial = _spin(-1e6, 1e6, 3, " μm", _payload_length_um(payload, "axial_offset_z_um", "axial_offset_z_mm", 0.0))
        self.tilt_x = _spin(-1e6, 1e6, 1, " μrad", _payload_tilt_urad(payload, "tilt_x_urad", "tilt_x_deg"))
        self.tilt_y = _spin(-1e6, 1e6, 1, " μrad", _payload_tilt_urad(payload, "tilt_y_urad", "tilt_y_deg"))
        pose.addRow("X 方向偏移", _spin_unit_row(self.offset_x))
        pose.addRow("Y 方向偏移", _spin_unit_row(self.offset_y))
        pose.addRow("轴向偏移 Δz", _spin_unit_row(self.axial))
        pose.addRow("X 方向倾角", _spin_unit_row(self.tilt_x))
        pose.addRow("Y 方向倾角", _spin_unit_row(self.tilt_y))
        pose_layout.addLayout(pose)
        root.addWidget(pose_box)
        more = QToolButton()
        more.setText("传输参数")
        more.setCheckable(True)
        more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        root.addWidget(more)
        self.more_host = QWidget()
        more_form = _rail_form()
        self.more_host.setLayout(more_form)
        self.outside = _spin(0.1, 5, 6, "", _payload_float(payload, "outside_refractive_index", default=defaults.outside_refractive_index))
        self.endface = _spin(0, 1, 5, "", _payload_float(payload, "endface_transmission", default=defaults.endface_transmission))
        self.length = _spin(0, 1e6, 3, " m", _payload_float(payload, "fiber_length_m", default=defaults.fiber_length_m))
        self.attenuation = _spin(0, 1e6, 3, " dB/km", _payload_float(payload, "attenuation_db_per_km", default=defaults.attenuation_db_per_km))
        self.connector = _spin(0, 1e6, 3, " dB", _payload_float(payload, "connector_loss_db", default=defaults.connector_loss_db))
        more_form.addRow("外部折射率 n_out", _spin_unit_row(self.outside))
        more_form.addRow("端面透射率", _spin_unit_row(self.endface))
        more_form.addRow("光纤长度", _spin_unit_row(self.length))
        more_form.addRow("衰减", _spin_unit_row(self.attenuation))
        more_form.addRow("连接器损耗", _spin_unit_row(self.connector))
        self.more_host.setVisible(False)
        more.toggled.connect(self.more_host.setVisible)
        root.addWidget(self.more_host)
        receiver_type = str(payload.get("receiver_type") or "single_mode_fiber")
        mode_model = str(payload.get("mode_model") or "gaussian")
        if mode_model == "imported":
            receiver_type = "user_mode"
        _set_combo_data(self.kind, receiver_type)
        _set_combo_data(self.model, mode_model)
        self._kind_changed()
        self._split_changed(self.split_mfd.isChecked())
        self._na_split_changed(self.split_na.isChecked())
        self._ready = True
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.model.currentIndexChanged.connect(self._model_changed)
        self.split_mfd.toggled.connect(self._split_changed)
        self.split_na.toggled.connect(self._na_split_changed)
        self.mfd.valueChanged.connect(self._mfd_changed)
        self.mfd_y.valueChanged.connect(lambda value: self._apply("receiver.mode_field_diameter_y_um", value, "MFDᵧ"))
        self.core.valueChanged.connect(lambda value: self._apply("receiver.core_diameter_um", value, "芯径"))
        self.n_core.valueChanged.connect(lambda value: self._apply("receiver.core_refractive_index", value, "纤芯折射率"))
        self.n_clad.valueChanged.connect(lambda value: self._apply("receiver.cladding_refractive_index", value, "包层折射率"))
        self.mm_core.valueChanged.connect(lambda value: self._apply("receiver.core_diameter_um", value, "芯径"))
        self.na.valueChanged.connect(self._na_changed)
        self.na_y.valueChanged.connect(lambda value: self._apply("receiver.na_y", value, "NAᵧ"))
        self.offset_x.valueChanged.connect(lambda value: self._pose("receiver.offset_x_um", value, "X 方向偏移"))
        self.offset_y.valueChanged.connect(lambda value: self._pose("receiver.offset_y_um", value, "Y 方向偏移"))
        self.axial.valueChanged.connect(lambda value: self._pose("receiver.axial_offset_z_um", value, "轴向偏移"))
        self.tilt_x.valueChanged.connect(lambda value: self._pose("receiver.tilt_x_urad", value, "X 方向倾角"))
        self.tilt_y.valueChanged.connect(lambda value: self._pose("receiver.tilt_y_urad", value, "Y 方向倾角"))
        self.outside.valueChanged.connect(lambda value: self._apply("receiver.outside_refractive_index", value, "外部折射率"))
        self.endface.valueChanged.connect(lambda value: self._apply("receiver.endface_transmission", value, "端面透射率"))
        self.length.valueChanged.connect(lambda value: self._apply("receiver.fiber_length_m", value, "光纤长度"))
        self.attenuation.valueChanged.connect(lambda value: self._apply("receiver.attenuation_db_per_km", value, "衰减"))
        self.connector.valueChanged.connect(lambda value: self._apply("receiver.connector_loss_db", value, "连接器损耗"))
        self.field_selector.fieldChanged.connect(self.changed)

    def _expected_grid_size(self) -> int:
        parent = self.parent()
        while parent is not None:
            calc = getattr(parent, "_calculation_state", None)
            if calc is not None:
                return int(getattr(calc, "output_grid_size", 257) or 257)
            parent = parent.parent()
        return 257

    def _apply(self, path: str, value: float, reason: str) -> None:
        if not self._ready:
            return
        _apply_float(self.context, path, float(value), reason)

    def _receiver_type(self) -> str:
        return str(self.kind.currentData() or "single_mode_fiber")

    def _kind_changed(self, _index: int = 0) -> None:
        kind = self._receiver_type()
        self.model.setEnabled(kind == "single_mode_fiber")
        if kind == "user_mode":
            _set_combo_data(self.model, "imported")
        if kind == "multimode_fiber":
            self.model_stack.setCurrentIndex(2)
        elif kind == "user_mode":
            self.model_stack.setCurrentIndex(3)
        else:
            self._model_changed()
        self.schematicRequested.emit()
        self.changed.emit()

    def _model_changed(self, _index: int = 0) -> None:
        kind = self._receiver_type()
        if kind == "multimode_fiber":
            self.model_stack.setCurrentIndex(2)
            return
        if kind == "user_mode":
            self.model_stack.setCurrentIndex(3)
            return
        key = str(self.model.currentData() or "gaussian")
        self.model_stack.setCurrentIndex({"gaussian": 0, "lp01": 1, "he11": 1, "imported": 3}.get(key, 0))
        self.schematicRequested.emit()
        self.changed.emit()

    def _split_changed(self, checked: bool) -> None:
        _set_form_row_visible(self._gaussian_form, self.mfd_y, checked)
        if not self._ready:
            return
        if not checked:
            blocked = self.mfd_y.blockSignals(True)
            self.mfd_y.setValue(self.mfd.value())
            self.mfd_y.blockSignals(blocked)
            self._apply("receiver.mode_field_diameter_y_um", float(self.mfd.value()), "模场直径")

    def _na_split_changed(self, checked: bool) -> None:
        _set_form_row_visible(self._mm_form, self.na_y, checked)
        if not checked:
            self._na_changed(self.na.value())

    def _na_changed(self, value: float) -> None:
        self._apply("receiver.na_x", float(value), "数值孔径")
        if not self.split_na.isChecked():
            blocked = self.na_y.blockSignals(True)
            self.na_y.setValue(float(value))
            self.na_y.blockSignals(blocked)
            self._apply("receiver.na_y", float(value), "数值孔径")

    def _mfd_changed(self, value: float) -> None:
        self._apply("receiver.mode_field_diameter_x_um", float(value), "模场直径")
        if not self.split_mfd.isChecked():
            blocked = self.mfd_y.blockSignals(True)
            self.mfd_y.setValue(float(value))
            self.mfd_y.blockSignals(blocked)
            self._apply("receiver.mode_field_diameter_y_um", float(value), "模场直径")
        self.changed.emit()

    def _pose(self, path: str, value: float, reason: str) -> None:
        self._apply(path, float(value), reason)
        self.changed.emit()

    def current_model(self) -> str:
        kind = self._receiver_type()
        if kind == "multimode_fiber":
            return "multimode"
        if kind == "user_mode":
            return "imported"
        return str(self.model.currentData() or "gaussian")

    def form_state(self) -> ReceiverFormState:
        kind = self._receiver_type()
        model = "gaussian" if kind == "multimode_fiber" else str(self.model.currentData() or "gaussian")
        if kind == "user_mode":
            model = "imported"
        imported = self.field_selector.data if model == "imported" else None
        if model == "imported" and imported is None:
            raise ValueError("选择「导入复场」后，请先选择并通过校验的复场文件。")
        core = float(self.mm_core.value() if kind == "multimode_fiber" else self.core.value())
        mfd_x = float(self.mfd.value())
        mfd_y = float(self.mfd_y.value() if self.split_mfd.isChecked() else self.mfd.value())
        na_x = float(self.na.value())
        na_y = float(self.na_y.value() if self.split_na.isChecked() else self.na.value())
        receiver_type = kind if kind in {"single_mode_fiber", "multimode_fiber", "user_mode"} else RECEIVER_TYPE_MAP.get(self.kind.currentText(), "single_mode_fiber")
        if model == "imported":
            receiver_type = "user_mode"
        return ReceiverFormState(
            receiver_type=receiver_type,
            mode_model=model,
            mode_field_diameter_x_um=mfd_x,
            mode_field_diameter_y_um=mfd_y,
            core_diameter_um=core,
            na_x=na_x,
            na_y=na_y,
            core_refractive_index=float(self.n_core.value()),
            cladding_refractive_index=float(self.n_clad.value()),
            outside_refractive_index=float(self.outside.value()),
            offset_x_um=float(self.offset_x.value()),
            offset_y_um=float(self.offset_y.value()),
            axial_offset_z_um=float(self.axial.value()),
            tilt_x_urad=float(self.tilt_x.value()),
            tilt_y_urad=float(self.tilt_y.value()),
            endface_transmission=float(self.endface.value()),
            fiber_length_m=float(self.length.value()),
            attenuation_db_per_km=float(self.attenuation.value()),
            connector_loss_db=float(self.connector.value()),
            imported_mode_real=(imported.real if imported is not None else None),
            imported_mode_imag=(imported.imag if imported is not None else None),
            imported_mode_source=(imported.path if imported is not None else ""),
        )

    def refresh(self) -> None:
        project = self.context.project.project
        blocked = self.mfd.blockSignals(True)
        self.mfd.setValue(float(project.receiver_mfd_um))
        self.mfd.blockSignals(blocked)
        self.wavelength_view.setText(f"{float(project.wavelength_nm):.2f} nm")


class EnvironmentInspector(QFrame):
    changed = Signal()

    def __init__(self, context, system: SystemFormState, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("ObjectInspector")
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 4)
        root.setSpacing(6)
        air, air_layout = _field_group("大气")
        air_form = _rail_form()
        self.temperature = _spin(-273, 1000, 3, " ℃", float(system.environment_temperature_c))
        self.pressure = _spin(0, 10000, 3, " kPa", float(system.environment_pressure_kpa))
        self.thermal = QCheckBox("温度补偿")
        self.thermal.setChecked(bool(system.thermal_compensation))
        air_form.addRow("环境温度", _spin_unit_row(self.temperature))
        air_form.addRow("大气压", _spin_unit_row(self.pressure))
        air_form.addRow(self.thermal)
        air_layout.addLayout(air_form)
        conjugate, conjugate_layout = _field_group("物像共轭")
        conjugate_form = _rail_form()
        self.object_distance = _spin(0.1, 1e9, 4, " mm", float(system.object_distance_mm))
        self.image_distance = _spin(-1e6, 1e6, 4, " mm", float(system.image_distance_mm))
        self.auto_focus = QCheckBox("最佳焦面搜索")
        self.auto_focus.setChecked(bool(system.auto_best_focus))
        conjugate_form.addRow("物距", _spin_unit_row(self.object_distance))
        conjugate_form.addRow("像面位置", _spin_unit_row(self.image_distance))
        conjugate_form.addRow(self.auto_focus)
        conjugate_layout.addLayout(conjugate_form)
        root.addWidget(air)
        root.addWidget(conjugate)
        for widget in (self.temperature, self.pressure, self.object_distance, self.image_distance):
            widget.valueChanged.connect(lambda *_args: self.changed.emit())
        self.thermal.toggled.connect(lambda *_args: self.changed.emit())
        self.auto_focus.toggled.connect(lambda *_args: self.changed.emit())

    def system_patch(self) -> dict[str, Any]:
        return {
            "environment_temperature_c": float(self.temperature.value()),
            "environment_pressure_kpa": float(self.pressure.value()),
            "thermal_compensation": self.thermal.isChecked(),
            "object_distance_mm": float(self.object_distance.value()),
            "image_distance_mm": float(self.image_distance.value()),
            "auto_best_focus": self.auto_focus.isChecked(),
        }


class FieldInspector(QFrame):
    changed = Signal()

    def __init__(self, context, system: SystemFormState, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("ObjectInspector")
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 4)
        root.setSpacing(6)
        box, layout = _field_group("入瞳与视场")
        form = _rail_form()
        self.pupil = _spin(0.01, 10000, 3, " mm", float(context.project.project.pupil_radius_mm))
        self.field_x = _spin(-90, 90, 3, " °", float(system.field_x_deg))
        self.field_y = _spin(-90, 90, 3, " °", float(system.field_y_deg))
        form.addRow("入瞳半径", _spin_unit_row(self.pupil))
        form.addRow("视场角 X", _spin_unit_row(self.field_x))
        form.addRow("视场角 Y", _spin_unit_row(self.field_y))
        layout.addLayout(form)
        root.addWidget(box)
        self.pupil.valueChanged.connect(lambda value: context.project.update_pupil_radius(float(value)))
        self.field_x.valueChanged.connect(lambda *_args: self.changed.emit())
        self.field_y.valueChanged.connect(lambda *_args: self.changed.emit())
        self.pupil.valueChanged.connect(lambda *_args: self.changed.emit())

    def field_angles(self) -> tuple[float, float]:
        return float(self.field_x.value()), float(self.field_y.value())

    def set_field_angles(self, field_x_deg: float, field_y_deg: float) -> None:
        for widget, value in ((self.field_x, field_x_deg), (self.field_y, field_y_deg)):
            blocked = widget.blockSignals(True)
            widget.setValue(float(value))
            widget.blockSignals(blocked)


class DetectorInspector(QFrame):
    changed = Signal()

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("ObjectInspector")
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 4)
        root.setSpacing(6)
        box, layout = _field_group("观察")
        form = _rail_form()
        self.enabled = QCheckBox("启用探测器")
        self.enabled.setChecked(True)
        self.placement = QComboBox()
        self.placement.addItem("光学面", "surface")
        self.placement.addItem("光纤模场", "fiber")
        self.placement.addItem("自定义位置", "custom")
        self.surface = QComboBox()
        self.offset = _spin(-1e6, 1e6, 3, " mm", 0.0)
        self.pitch = _spin(0.001, 1e6, 3, " μm", 5.0)
        self.pixels_x = _spin(1, 1e6, 0, "", 1024)
        self.pixels_y = _spin(1, 1e6, 0, "", 1024)
        form.addRow(self.enabled)
        form.addRow("观察方式", self.placement)
        form.addRow("光学面", self.surface)
        form.addRow("相对最后一面", _spin_unit_row(self.offset))
        form.addRow("像元尺寸", _spin_unit_row(self.pitch))
        form.addRow("X 像元数", self.pixels_x)
        form.addRow("Y 像元数", self.pixels_y)
        self._form = form
        layout.addLayout(form)
        root.addWidget(box)
        self.enabled.toggled.connect(self._visibility)
        self.placement.currentIndexChanged.connect(self._visibility)
        self.surface.currentIndexChanged.connect(lambda *_args: self.changed.emit())
        self.offset.valueChanged.connect(lambda *_args: self.changed.emit())
        self.pitch.valueChanged.connect(lambda *_args: self.changed.emit())
        self.pixels_x.valueChanged.connect(lambda *_args: self.changed.emit())
        self.pixels_y.valueChanged.connect(lambda *_args: self.changed.emit())
        self.refresh()
        self._visibility()

    def refresh(self) -> None:
        current = self.surface.currentData()
        self.surface.blockSignals(True)
        self.surface.clear()
        surfaces = list(getattr(self.context.project.project, "surfaces", ()) or ())
        for index, surface in enumerate(surfaces):
            name = str(getattr(surface, "name", "") or f"面{index}")
            self.surface.addItem(f"{name}（面 {index}）", index)
        found = 0
        if current is not None:
            try:
                found = max(0, self.surface.findData(int(current)))
            except (TypeError, ValueError):
                found = 0
        if self.surface.count():
            self.surface.setCurrentIndex(found)
        self.surface.blockSignals(False)

    def observation(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled.isChecked(),
            "mode": str(self.placement.currentData() or "surface"),
            "surface_index": int(self.surface.currentData() if self.surface.currentData() is not None else 0),
            "offset_mm": float(self.offset.value()),
            "pitch_um": float(self.pitch.value()),
            "pixels_x": int(self.pixels_x.value()),
            "pixels_y": int(self.pixels_y.value()),
        }

    def _visibility(self, *_args) -> None:
        mode = str(self.placement.currentData() or "surface")
        enabled = self.enabled.isChecked()
        _set_form_row_visible(self._form, self.placement, enabled)
        _set_form_row_visible(self._form, self.surface, enabled and mode == "surface")
        _set_form_row_visible(self._form, self.offset, enabled and mode == "custom")
        pixels = enabled and mode != "fiber"
        for widget in (self.pitch, self.pixels_x, self.pixels_y):
            _set_form_row_visible(self._form, widget, pixels)
        self.changed.emit()


class LensSliderPanel(QFrame):
    surfaceSelected = Signal(int)

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self._index = 0
        self._radius0 = 50.0
        self._thickness0 = 1.0
        self._ready = False
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 4)
        root.setSpacing(6)
        self.list = QListWidget()
        self.list.setObjectName("ObjectList")
        self.list.setMinimumHeight(220)
        self.list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.list.itemClicked.connect(self._clicked)
        root.addWidget(self.list, 1)
        self.radius = QSlider(Qt.Orientation.Horizontal)
        self.thickness = QSlider(Qt.Orientation.Horizontal)
        self.radius.setRange(0, 200)
        self.thickness.setRange(0, 200)
        self.radius_label = QLabel("—")
        self.thickness_label = QLabel("—")
        sliders, slider_layout = _field_group("相对当前面 ±20%")
        slider_layout.addWidget(_slider_line("曲率半径", self.radius, self.radius_label))
        slider_layout.addWidget(_slider_line("厚度", self.thickness, self.thickness_label))
        root.addWidget(sliders)
        self.radius.valueChanged.connect(self._radius_changed)
        self.thickness.valueChanged.connect(self._thickness_changed)
        self.refresh()
        self._ready = True

    def refresh(self) -> None:
        self.list.clear()
        surfaces = list(getattr(self.context.project.project, "surfaces", ()) or ())
        for index, surface in enumerate(surfaces):
            name = str(getattr(surface, "name", "") or f"面{index}")
            kind = str(getattr(surface, "surface_type", "") or "")
            item = QListWidgetItem(f"{index}  {name}  {kind}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.list.addItem(item)
        if surfaces:
            self.set_surface(min(self._index, len(surfaces) - 1))

    def set_surface(self, index: int) -> None:
        surfaces = list(getattr(self.context.project.project, "surfaces", ()) or ())
        if not surfaces:
            return
        self._index = max(0, min(int(index), len(surfaces) - 1))
        surface = surfaces[self._index]
        self._radius0 = float(getattr(surface, "radius_mm", 0.0) or 0.0)
        self._thickness0 = float(getattr(surface, "thickness_mm", getattr(surface, "distance_to_next_mm", 1.0)) or 0.0)
        self._ready = False
        self.radius.setValue(100)
        self.thickness.setValue(100)
        self.radius.setEnabled(abs(self._radius0) > 1e-9)
        self._update_labels(self._radius0, self._thickness0)
        if 0 <= self._index < self.list.count():
            self.list.setCurrentRow(self._index)
        self._ready = True

    def _clicked(self, item: QListWidgetItem) -> None:
        index = int(item.data(Qt.ItemDataRole.UserRole) or 0)
        self.set_surface(index)
        self.surfaceSelected.emit(index)

    def _mapped(self, slider: QSlider, center: float) -> float:
        return float(center) * (0.8 + 0.4 * (slider.value() / 200.0))

    def _update_labels(self, radius: float, thickness: float) -> None:
        self.radius_label.setText(f"{radius:.2f} mm")
        self.thickness_label.setText(f"{thickness:.2f} mm")

    def _radius_changed(self, _value: int) -> None:
        if not self._ready:
            return
        radius = self._mapped(self.radius, self._radius0)
        self._update_labels(radius, self._mapped(self.thickness, self._thickness0))
        _apply_float(self.context, f"surfaces[{self._index}].radius_mm", radius, "曲率半径")

    def _thickness_changed(self, _value: int) -> None:
        if not self._ready:
            return
        thickness = self._mapped(self.thickness, self._thickness0)
        self._update_labels(self._mapped(self.radius, self._radius0), thickness)
        _apply_float(self.context, f"surfaces[{self._index}].distance_to_next_mm", thickness, "厚度")




class AccordionSection(QFrame):
    toggled = Signal(str, bool)

    def __init__(self, key: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("AccordionSection")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = QToolButton()
        self.header.setObjectName("AccordionHeader")
        self.header.setCheckable(True)
        self.header.setChecked(False)
        self.header.setText(title)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.ArrowType.RightArrow)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.body = QWidget()
        self.body.setVisible(False)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(6, 4, 4, 8)
        self.body_layout.setSpacing(4)
        layout.addWidget(self.header)
        layout.addWidget(self.body)
        self.header.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self.header.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.body.setVisible(checked)
        self.toggled.emit(self.key, checked)

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(expanded)

    def set_body_widget(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)


class DatasetRailItem(QWidget):
    """Compact dataset row used by the left rail.

    Dataset generation is a long-running job, so its progress belongs to the
    dataset item itself rather than to a separate full-width table in the
    document.  The right-hand check is deliberately part of the row so the
    selected training source remains visible while the document is scrolled.
    """

    activated = Signal()
    cancelRequested = Signal()

    def __init__(
        self,
        title: str,
        *,
        selected: bool = False,
        progress: float | None = None,
        status: str = "",
        state: str = "",
        cancellable: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("DatasetRailItem")
        self._state = str(state or "")
        root = QVBoxLayout(self)
        root.setContentsMargins(5, 3, 5, 3)
        root.setSpacing(2)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)
        self.title_label = QLabel(str(title or "数据集"))
        self.title_label.setObjectName("datasetRailTitle")
        self.title_label.setToolTip(str(title or "数据集"))
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top.addWidget(self.title_label, 1)
        self.check_label = QLabel()
        self.check_label.setObjectName("datasetSelectionCheck")
        self.check_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.check_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.check_label.setFixedWidth(20)
        self._set_state_indicator(bool(selected))
        top.addWidget(self.check_label)
        self.cancel_button: QToolButton | None = None
        if cancellable:
            self.cancel_button = QToolButton()
            self.cancel_button.setObjectName("datasetCancelButton")
            self.cancel_button.setText("取消")
            self.cancel_button.setToolTip("取消数据集生成")
            self.cancel_button.setAccessibleName("取消数据集生成")
            self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.cancel_button.clicked.connect(self.cancelRequested.emit)
            top.addWidget(self.cancel_button)
        root.addLayout(top)

        self.progress_bar: QProgressBar | None = None
        self.progress_label: QLabel | None = None
        if progress is not None:
            value = max(0.0, min(1.0, float(progress)))
            status_text = str(status or "生成中")
            progress_row = QHBoxLayout()
            progress_row.setContentsMargins(0, 0, 0, 0)
            progress_row.setSpacing(5)
            self.progress_label = QLabel(f"{status_text} {value:.0%}")
            self.progress_label.setObjectName("datasetProgressText")
            self.progress_label.setMinimumWidth(72)
            self.progress_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.progress_bar = QProgressBar()
            self.progress_bar.setObjectName("datasetProgressBar")
            self.progress_bar.setProperty("datasetState", self._state)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(round(value * 100))
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            progress_row.addWidget(self.progress_label)
            progress_row.addWidget(self.progress_bar, 1)
            root.addLayout(progress_row)
            self.setMinimumHeight(47)
        else:
            self.setMinimumHeight(32)

    def set_progress(self, progress: float, status: str = "生成中") -> bool:
        """Update a pending row without destroying and recreating its widgets."""
        if self.progress_bar is None or self.progress_label is None:
            return False
        value = max(0.0, min(1.0, float(progress)))
        self.progress_label.setText(f"{str(status or '生成中')} {value:.0%}")
        self.progress_bar.setValue(round(value * 100))
        return True

    def set_cancelling(self, cancelling: bool) -> None:
        if self.cancel_button is None:
            return
        self.cancel_button.setEnabled(not cancelling)
        self.cancel_button.setText("取消中" if cancelling else "取消")

    def _set_state_indicator(self, selected: bool) -> None:
        if self._state == "generated_failed":
            self.check_label.setObjectName("datasetFailureMark")
            self.check_label.setPixmap(icon("close", "#DC2626", 16).pixmap(QSize(16, 16)))
            self.check_label.setToolTip("数据集生成失败")
            self.check_label.setAccessibleName("数据集生成失败")
            self.check_label.setVisible(True)
            return
        if self._state == "generated_cancelled":
            self.check_label.setObjectName("datasetCancelledMark")
            self.check_label.setPixmap(icon("close", "#667085", 16).pixmap(QSize(16, 16)))
            self.check_label.setToolTip("数据集生成已取消")
            self.check_label.setAccessibleName("数据集生成已取消")
            self.check_label.setVisible(True)
            return
        self.check_label.setObjectName("datasetSelectionCheck")
        self.check_label.setPixmap(icon("check", "#16A34A", 16).pixmap(QSize(16, 16)))
        self.check_label.setToolTip("已选中的数据集")
        self.check_label.setAccessibleName("已选中的数据集")
        self.check_label.setVisible(bool(selected))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
        event.ignore()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(0, 47 if self.progress_bar is not None else 32)


class ObjectRail(QFrame):
    objectRequested = Signal(str)
    optimizationSelectionChanged = Signal(str, bool)
    datasetCancelRequested = Signal(str)

    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("ObjectRail")
        self.setMinimumWidth(250)
        self.setMaximumWidth(360)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 8, 8)
        root.setSpacing(6)
        self._rail_layout = root
        self.heading = QLabel("对象")
        self.heading.setObjectName("RailTitle")
        root.addWidget(self.heading)
        self._optimization_view = "variables"
        self.optimization_view_switcher = QWidget()
        self.optimization_view_switcher.setObjectName("OptimizationRailTabs")
        optimization_view_layout = QHBoxLayout(self.optimization_view_switcher)
        optimization_view_layout.setContentsMargins(0, 0, 0, 0)
        optimization_view_layout.setSpacing(4)
        self.optimization_view_group = QButtonGroup(self)
        self.optimization_view_group.setExclusive(True)
        self.optimization_variables_button = QToolButton()
        self.optimization_variables_button.setObjectName("OptimizationRailTab")
        self.optimization_variables_button.setText("优化变量")
        self.optimization_variables_button.setCheckable(True)
        self.optimization_more_button = QToolButton()
        self.optimization_more_button.setObjectName("OptimizationRailTab")
        self.optimization_more_button.setText("更多参数")
        self.optimization_more_button.setCheckable(True)
        for key, button in (
            ("variables", self.optimization_variables_button),
            ("more", self.optimization_more_button),
        ):
            self.optimization_view_group.addButton(button)
            button.clicked.connect(
                lambda _checked=False, value=key: self._set_optimization_view(value)
            )
            optimization_view_layout.addWidget(button, 1)
        self.optimization_variables_button.setChecked(True)
        self.optimization_view_switcher.setVisible(False)
        root.addWidget(self.optimization_view_switcher)
        # self.optimization_hint = QLabel("先勾选需要调整的参数。")
        # self.optimization_hint.setObjectName("OptimizationRailHint")
        # self.optimization_hint.setWordWrap(True)
        # self.optimization_hint.setVisible(False)
        # root.addWidget(self.optimization_hint)
        self.search = QLineEdit()
        self.search.setPlaceholderText("筛选…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.filter_row = QWidget()
        filter_layout = QGridLayout(self.filter_row)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(4)
        self._group_filter = "all"
        self._group_buttons: dict[str, QToolButton] = {}
        for button_index, (key, label) in enumerate(
            (("all", "全部"), ("L1", "L1"), ("L2", "L2"), ("L3", "L3"), ("L4", "L4"), ("fiber", "光纤"))
        ):
            button = QToolButton()
            button.setObjectName("RailCategoryButton")
            button.setText(label)
            button.setCheckable(True)
            button.setChecked(key == "all")
            button.clicked.connect(lambda _checked=False, value=key: self._set_group_filter(value))
            filter_layout.addWidget(button, button_index // 3, button_index % 3)
            self._group_buttons[key] = button
        self.shap_button = QToolButton()
        self.shap_button.setObjectName("RailCategoryButton")
        self.shap_button.setText("SHAP")
        self.shap_button.setCheckable(True)
        self.shap_button.setVisible(False)
        self.shap_button.setEnabled(False)
        self.shap_button.setToolTip("请先训练并对着同一目标看过贡献排序")
        self.shap_button.toggled.connect(self._set_shap_sort)
        filter_layout.addWidget(self.shap_button, 2, 0, 1, 3)
        for column in range(3):
            filter_layout.setColumnStretch(column, 1)
        self.accordion = QScrollArea()
        self.accordion.setWidgetResizable(True)
        self.accordion.setFrameShape(QFrame.Shape.NoFrame)
        self.accordion.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.accordion_host = QWidget()
        self.accordion_layout = QVBoxLayout(self.accordion_host)
        # 右侧留 4px：滚动条出现时，展开态的实心高亮不会直接顶到滚动条上
        # （不留白的话看起来像被滚动条盖住了右半边）。
        self.accordion_layout.setContentsMargins(0, 0, 4, 0)
        self.accordion_layout.setSpacing(4)
        self.accordion_layout.addStretch(1)
        self.accordion.setWidget(self.accordion_host)
        self.list = QListWidget()
        self.list.setObjectName("ObjectList")
        self.list.itemClicked.connect(self._clicked)
        self.list.itemChanged.connect(self._item_changed)
        self.optimization_variable_host = QWidget()
        variable_layout = QVBoxLayout(self.optimization_variable_host)
        variable_layout.setContentsMargins(0, 0, 0, 0)
        variable_layout.setSpacing(6)
        variable_layout.addWidget(self.search)
        variable_layout.addWidget(self.filter_row)
        variable_layout.addWidget(self.list, 1)
        root.addWidget(self.optimization_variable_host, 1)

        self.optimization_more_scroll = QScrollArea()
        self.optimization_more_scroll.setObjectName("OptimizationMoreScroll")
        self.optimization_more_scroll.setWidgetResizable(True)
        self.optimization_more_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.optimization_more_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.optimization_more_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.optimization_more_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.optimization_more_host = QWidget()
        self.optimization_more_host.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.optimization_more_layout = QVBoxLayout(self.optimization_more_host)
        self.optimization_more_layout.setContentsMargins(0, 0, 4, 0)
        self.optimization_more_layout.setSpacing(6)
        self.optimization_more_placeholder = QLabel("打开优化页面后可配置更多参数。")
        self.optimization_more_placeholder.setObjectName("OptimizationRailHint")
        self.optimization_more_placeholder.setWordWrap(True)
        self.optimization_more_layout.addWidget(self.optimization_more_placeholder)
        self.optimization_more_layout.addStretch(1)
        self.optimization_more_scroll.setWidget(self.optimization_more_host)
        self.optimization_more_scroll.setVisible(False)
        root.addWidget(self.optimization_more_scroll, 1)
        root.addWidget(self.accordion, 1)
        self._module = ""
        self._sections: dict[str, AccordionSection] = {}
        self._checked_keys: set[str] = set()
        self.source_inspector: SourceInspector | None = None
        self.fiber_inspector: FiberInspector | None = None
        self.environment_inspector: EnvironmentInspector | None = None
        self.field_inspector: FieldInspector | None = None
        self.detector_inspector: DetectorInspector | None = None
        self.lens_sliders: LensSliderPanel | None = None
        self.materials_inspector: UsedMaterialInspector | None = None
        self.goal_inspector: OptimizationGoalInspector | None = None
        self.max_evaluations: QWidget | None = None
        self.max_evaluations_group: QFrame | None = None
        self.lens_list: QListWidget | None = None
        self._document_kind = ""
        self._datasets: list[dict[str, Any]] = []
        self._models: list[dict[str, Any]] = []
        self._dataset_family = "tabular"
        self._selected_dataset_id = ""
        self._selected_model_id = str(
            getattr(getattr(context, "registry", None), "current_model_id", "") or ""
        )
        self._shap_sort = False
        self._shap_scores: dict[str, float] = {}
        context.project.project_changed.connect(lambda _project: self._refresh_contents())

    def set_catalogs(self, datasets: list[dict[str, Any]], models: list[dict[str, Any]]) -> None:
        self._datasets = list(datasets)
        self._models = list(models)
        if self._module in {"model", "explainability"}:
            self._populate()

    def set_dataset_family(self, family: str) -> None:
        self._dataset_family = str(family or "tabular")
        if self._module == "model":
            self._populate()

    def set_selected_dataset(self, dataset_id: str) -> None:
        self._selected_dataset_id = str(dataset_id or "")
        if self._module == "model" and (self._document_kind or "dataset") == "dataset":
            self._populate()

    def set_selected_model(self, model_id: str) -> None:
        self._selected_model_id = str(model_id or "")
        if self._module == "model" and (self._document_kind or "dataset") != "dataset":
            self._populate()

    def selected_dataset_id(self) -> str:
        return self._selected_dataset_id

    def update_dataset_progress(
        self,
        dataset_id: str,
        progress: float,
        status: str = "生成中",
    ) -> bool:
        """Update one visible dataset row in place.

        Rebuilding the QListWidget for every progress event briefly exposed an
        orphaned child widget as a tiny top-level window on Windows.  Keeping
        the existing row also avoids needless allocations during long jobs.
        """
        key = f"dataset:{str(dataset_id or '').strip()}"
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item is None or item.data(Qt.ItemDataRole.UserRole) != key:
                continue
            row = self.list.itemWidget(item)
            if not isinstance(row, DatasetRailItem):
                return False
            item.setToolTip(str(status or "生成中"))
            return row.set_progress(progress, status)
        return False

    def set_dataset_cancelling(self, dataset_id: str, cancelling: bool) -> bool:
        key = f"dataset:{str(dataset_id or '').strip()}"
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item is None or item.data(Qt.ItemDataRole.UserRole) != key:
                continue
            row = self.list.itemWidget(item)
            if not isinstance(row, DatasetRailItem):
                return False
            row.set_cancelling(cancelling)
            return True
        return False

    def set_document_kind(self, kind: str) -> None:
        self._document_kind = str(kind or "")
        if self._module in {"model", "explainability"}:
            self._populate()

    def set_module(self, module: str) -> None:
        self._module = str(module)
        self.heading.setText({
            "simulation": "对象",
            "analysis": "当前系统",
            "model": "数据集",
            "optimization": "优化",
            "explainability": "参数",
        }.get(self._module, "对象"))
        simulation = self._module == "simulation"
        optimization = self._module == "optimization"
        filtered = self._module in {"optimization", "explainability"}
        self.search.setVisible(self._module in {"optimization", "explainability"})
        self.filter_row.setVisible(filtered)
        # self.optimization_hint.setVisible(self._module == "optimization")
        # SHAP belongs to the explanation workflow. Keep optimization focused
        # on choosing variables and bounds.
        self.shap_button.setVisible(False)
        self.accordion.setVisible(simulation)
        self.list.setVisible(not simulation)
        self._rail_layout.setStretch(
            self._rail_layout.indexOf(self.optimization_variable_host),
            0 if simulation else 1,
        )
        self._rail_layout.setStretch(
            self._rail_layout.indexOf(self.optimization_more_scroll),
            1 if optimization else 0,
        )
        self._rail_layout.setStretch(
            self._rail_layout.indexOf(self.accordion),
            1 if simulation else 0,
        )
        if optimization:
            self.ensure_optimization_controls()
        self._set_optimization_view(self._optimization_view)
        if simulation:
            if "environment" not in self._sections:
                self._build_simulation()
            else:
                self._refresh_contents()
        elif self._module == "optimization":
            self._clear_accordion()
            self._populate()
        else:
            self._clear_accordion()
            self._populate()

    def ensure_optimization_controls(self) -> None:
        if self.goal_inspector is not None and self.max_evaluations is not None:
            return
        self.optimization_more_layout.removeWidget(self.optimization_more_placeholder)
        self.optimization_more_placeholder.deleteLater()
        self.goal_inspector = OptimizationGoalInspector(self.context, compact=True)
        self.goal_inspector.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        self.goal_inspector.collimation.toggled.connect(
            self._reveal_optimization_collimation
        )
        self.max_evaluations = _spin(10, 100000, 0, "", 300)
        self.max_evaluations.setMinimumWidth(0)
        self.max_evaluations.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.max_evaluations_group, max_evaluations_layout = _field_group("")
        max_evaluations_row = _labeled_field("最大评价次数", self.max_evaluations)
        max_evaluations_row.setMinimumWidth(0)
        max_evaluations_layout.addWidget(max_evaluations_row)
        self.optimization_more_layout.insertWidget(0, self.goal_inspector)
        self.optimization_more_layout.insertWidget(1, self.max_evaluations_group)

    def _reveal_optimization_collimation(self, enabled: bool) -> None:
        """Keep newly expanded collimation fields inside the rail viewport."""
        if not enabled or self.goal_inspector is None:
            return
        target = self.goal_inspector.collimation_tilt
        QTimer.singleShot(
            0,
            lambda: self.optimization_more_scroll.ensureWidgetVisible(target, 0, 12),
        )

    def _set_optimization_view(self, view: str) -> None:
        self._optimization_view = "more" if str(view) == "more" else "variables"
        self.optimization_variables_button.setChecked(self._optimization_view == "variables")
        self.optimization_more_button.setChecked(self._optimization_view == "more")
        optimization = self._module == "optimization"
        simulation = self._module == "simulation"
        self.optimization_view_switcher.setVisible(optimization)
        self.optimization_variable_host.setVisible(not simulation and not (optimization and self._optimization_view == "more"))
        self.optimization_more_scroll.setVisible(optimization and self._optimization_view == "more")
        if optimization and self._optimization_view == "more":
            self.ensure_optimization_controls()

    def _clear_accordion(self) -> None:
        while self.accordion_layout.count() > 1:
            item = self.accordion_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # 同上：必须先摘父再排队删除，否则旧折叠段会和新段叠着重影。
                widget.setParent(None)
                widget.deleteLater()
        self._sections.clear()
        self.source_inspector = None
        self.fiber_inspector = None
        self.environment_inspector = None
        self.field_inspector = None
        self.detector_inspector = None
        self.lens_sliders = None
        self.lens_list = None
        self.materials_inspector = None

    def _build_simulation(self) -> None:
        self._clear_accordion()
        system = SystemFormState(pupil_radius_mm=float(self.context.project.project.pupil_radius_mm))
        self.environment_inspector = EnvironmentInspector(self.context, system)
        self.field_inspector = FieldInspector(self.context, system)
        self.source_inspector = SourceInspector(self.context)
        self.fiber_inspector = FiberInspector(self.context)
        self.detector_inspector = DetectorInspector(self.context)
        self.lens_sliders = LensSliderPanel(self.context)
        self.lens_list = self.lens_sliders.list
        self.materials_inspector = UsedMaterialInspector(self.context)
        self.source_inspector.schematicRequested.connect(lambda: self.objectRequested.emit("source"))
        self.fiber_inspector.schematicRequested.connect(lambda: self.objectRequested.emit("fiber"))
        self.lens_sliders.surfaceSelected.connect(lambda index: self.objectRequested.emit(f"lens:{index}"))
        environment = AccordionSection("environment", "环境")
        environment.set_body_widget(self.environment_inspector)
        field = AccordionSection("field", "视场")
        field.set_body_widget(self.field_inspector)
        source = AccordionSection("source", "光源")
        source.set_body_widget(self.source_inspector)
        materials = AccordionSection("materials", "材料")
        materials.set_body_widget(self.materials_inspector)
        fiber = AccordionSection("fiber", "光纤")
        fiber.set_body_widget(self.fiber_inspector)
        detector = AccordionSection("detector", "探测器")
        detector.set_body_widget(self.detector_inspector)
        # 左侧对象栏的显示顺序 = 这个元组的顺序，跟上面各 Inspector 的创建顺序无关。
        # 自下而上逐段插到末尾的 stretch 之前，所以这里先写的排在上面。
        # 环境、视场是低频项，放在最后；常改的光源/材料/光纤/探测器排前面。
        # 「镜头组」不在这里：镜头数据改由二级栏的「镜头数据」和首页的「搭建系统」进入。
        for section in (source, materials, fiber, detector, environment, field):
            section.toggled.connect(self._section_toggled)
            self.accordion_layout.insertWidget(self.accordion_layout.count() - 1, section)
            self._sections[section.key] = section
        self._refresh_contents()

    def _refresh_lens_list(self) -> None:
        if self.lens_sliders is not None:
            self.lens_sliders.refresh()
        if self.detector_inspector is not None:
            self.detector_inspector.refresh()

    def _refresh_contents(self) -> None:
        if self.source_inspector is not None:
            self.source_inspector.refresh()
        if self.fiber_inspector is not None:
            self.fiber_inspector.refresh()
        if self.lens_sliders is not None:
            self.lens_sliders.refresh()
        if self.detector_inspector is not None:
            self.detector_inspector.refresh()
        if self.materials_inspector is not None:
            self.materials_inspector.refresh()
        if self._module == "simulation":
            self._refresh_lens_list()
        elif self._module in {"optimization", "explainability"}:
            self._populate()

    def _section_toggled(self, key: str, expanded: bool) -> None:
        if expanded:
            self.objectRequested.emit(key)

    def _lens_clicked(self, item: QListWidgetItem) -> None:
        self.objectRequested.emit(f"lens:{int(item.data(Qt.ItemDataRole.UserRole) or 0)}")

    def _populate(self) -> None:
        self.list.blockSignals(True)
        # A visible item widget must be hidden before QListWidget releases it.
        # Otherwise Qt can briefly promote it to a native top-level window on
        # Windows, producing a small blank window flash during rapid refreshes.
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item is None:
                continue
            widget = self.list.itemWidget(item)
            if widget is not None:
                widget.hide()
        self.list.clear()
        module = self._module
        if module == "analysis":
            self._add_item("system_summary", "当前系统", "只读工程摘要")
            for key, title in (("show_rays", "显示光线"), ("show_axis", "显示光轴"), ("show_marks", "显示标记")):
                item = QListWidgetItem(title)
                item.setData(Qt.ItemDataRole.UserRole, key)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if key != "show_marks" else Qt.CheckState.Unchecked)
                self.list.addItem(item)
        elif module == "model":
            kind = self._document_kind or "dataset"
            if kind == "dataset":
                self.heading.setText("数据集")
                family = self._dataset_family
                for item in self._datasets:
                    if str(item.get("family") or "tabular") != family:
                        continue
                    dataset_id = str(item.get("id") or "")
                    kind = str(item.get("kind") or "")
                    self._add_item(
                        f"dataset:{dataset_id}",
                        str(item.get("title") or dataset_id or "数据集"),
                        str(item.get("status") or ""),
                        dataset=True,
                        selected=dataset_id == self._selected_dataset_id,
                        progress=(
                            float(item.get("progress") or 0.0)
                            if kind in {
                                "generated_pending",
                                "generated_failed",
                                "generated_cancelled",
                            } else None
                        ),
                        dataset_state=kind,
                        dataset_error=str(item.get("error") or ""),
                        cancellable=(
                            kind == "generated_pending"
                            and str(item.get("status") or "") != "正在取消"
                        ),
                    )
            else:
                self.heading.setText("训练结果" if kind == "train_result" else "模型")
                for item in self._models:
                    model_id = str(item.get("id") or "")
                    self._add_item(
                        f"model:{model_id}",
                        str(item.get("title") or model_id or "模型"),
                        "已训练",
                        selected=model_id == self._selected_model_id,
                        catalog=True,
                    )
        elif module == "explainability":
            kind = self._document_kind or "global_contrib"
            if kind in {"global_contrib", "current_system"}:
                self.heading.setText("模型")
                self.search.setVisible(False)
                self.filter_row.setVisible(False)
                for item in self._models:
                    model_id = str(item.get("id") or "")
                    self._add_item(
                        f"model:{model_id}",
                        str(item.get("title") or model_id or "模型"),
                        "已训练",
                        selected=model_id == self._selected_model_id,
                        catalog=True,
                    )
            else:
                self.heading.setText("参数")
                self.search.setVisible(True)
                self.filter_row.setVisible(True)
                for row in _variable_rows(self.context.project.project):
                    key, group, _face, _parameter = row
                    item = QListWidgetItem(_display_variable(row))
                    item.setData(Qt.ItemDataRole.UserRole, key)
                    item.setData(Qt.ItemDataRole.UserRole + 1, group)
                    item.setToolTip(key)
                    self.list.addItem(item)
                self._filter(self.search.text())
        elif module == "optimization":
            self.search.setVisible(True)
            self.filter_row.setVisible(True)
            self.shap_button.setVisible(False)
            rows = list(_variable_rows(self.context.project.project))
            for row in rows:
                key, group, _face, _parameter = row
                item = QListWidgetItem(_display_variable(row))
                item.setData(Qt.ItemDataRole.UserRole, key)
                item.setData(Qt.ItemDataRole.UserRole + 1, group)
                item.setToolTip(key)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if key in self._checked_keys else Qt.CheckState.Unchecked)
                self.list.addItem(item)
            self._filter(self.search.text())
        self.list.blockSignals(False)

    def _add_item(
        self,
        key: str,
        title: str,
        hint: str,
        *,
        dataset: bool = False,
        catalog: bool = False,
        selected: bool = False,
        progress: float | None = None,
        dataset_state: str = "",
        dataset_error: str = "",
        cancellable: bool = False,
    ) -> None:
        # Dataset rows are rendered by DatasetRailItem.  Leaving the title on
        # QListWidgetItem as well makes Qt paint the same text underneath the
        # custom widget, which is especially visible at Windows display
        # scaling values above 100%.
        rich_row = dataset or catalog
        item = QListWidgetItem("" if rich_row else title)
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setData(Qt.ItemDataRole.UserRole + 2, title)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, title)
        item.setToolTip(dataset_error or hint)
        self.list.addItem(item)
        if rich_row:
            row = DatasetRailItem(
                title,
                selected=selected,
                progress=progress,
                status=hint,
                state=dataset_state,
                cancellable=cancellable,
            )
            self.list.setItemWidget(item, row)
            item.setSizeHint(row.sizeHint())
            row.activated.connect(lambda item_key=key: self._activate_item(item_key))
            if dataset and cancellable:
                row.cancelRequested.connect(
                    lambda dataset_key=key: self.datasetCancelRequested.emit(
                        dataset_key.split(":", 1)[1]
                    )
                )

    def set_shap_scores(self, scores: dict[str, float]) -> None:
        self._shap_scores = {str(key): float(value) for key, value in dict(scores or {}).items()}
        has = bool(self._shap_scores)
        self.shap_button.setEnabled(has)
        self.shap_button.setToolTip(
            "按贡献排序从高到低排列变量" if has else "请先训练并对着同一目标看过贡献排序"
        )
        if not has and self.shap_button.isChecked():
            blocked = self.shap_button.blockSignals(True)
            self.shap_button.setChecked(False)
            self.shap_button.blockSignals(blocked)
            self._shap_sort = False
        if self._module == "optimization":
            self._populate()

    def _set_shap_sort(self, checked: bool) -> None:
        self._shap_sort = bool(checked) and bool(self._shap_scores)
        if checked and not self._shap_scores:
            blocked = self.shap_button.blockSignals(True)
            self.shap_button.setChecked(False)
            self.shap_button.blockSignals(blocked)
            self._shap_sort = False
            return
        if self._module == "optimization":
            self._populate()

    def _set_group_filter(self, key: str) -> None:
        self._group_filter = key
        for name, button in self._group_buttons.items():
            button.setChecked(name == key)
        self._filter(self.search.text())

    def _clicked(self, item: QListWidgetItem) -> None:
        key = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._activate_item(key)

    def _activate_item(self, key: str) -> None:
        if self._module == "optimization":
            return
        if self._module == "model" and key.startswith("dataset:"):
            self.set_selected_dataset(key.split(":", 1)[1])
        elif self._module == "model" and key.startswith("model:"):
            self.set_selected_model(key.split(":", 1)[1])
        self.objectRequested.emit(key)

    def _item_changed(self, item: QListWidgetItem) -> None:
        key = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if self._module == "optimization" and key:
            enabled = item.checkState() == Qt.CheckState.Checked
            if enabled:
                self._checked_keys.add(key)
            else:
                self._checked_keys.discard(key)
            self.optimizationSelectionChanged.emit(key, enabled)

    def _filter(self, text: str) -> None:
        query = str(text or "").strip().lower()
        group = self._group_filter
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item is None:
                continue
            label = str(item.data(Qt.ItemDataRole.UserRole + 2) or item.text()).lower()
            item_group = str(item.data(Qt.ItemDataRole.UserRole + 1) or "")
            hidden = bool(query) and query not in label
            if group == "fiber":
                hidden = hidden or item_group != "光纤"
            elif group != "all":
                hidden = hidden or not item_group.startswith(group)
            item.setHidden(hidden)












class DocumentPane(QTabWidget):
    tabActivated = Signal(str)
    tabClosed = Signal(str)
    pinChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DocumentPane")
        self.setDocumentMode(True)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setUsesScrollButtons(True)
        # 页面由二级功能栏切换，不再显示顶部的文档标签行。
        self.tabBar().hide()
        self.tabCloseRequested.connect(self._close)
        self.currentChanged.connect(self._changed)
        self._specs: dict[str, TabSpec] = {}
        self._pinned: set[str] = set()

    def open(self, spec: TabSpec, widget: QWidget) -> None:
        if spec.id in self._specs:
            self.setCurrentIndex(self.indexOf(self._widget_for(spec.id)))
            return
        index = self.addTab(widget, spec.title)
        self._specs[spec.id] = spec
        self.setTabToolTip(index, f"{spec.title}\n{spec.subtitle}")
        self._install_pin(index, spec.id)
        self.setCurrentIndex(index)

    def is_current_pinned(self) -> bool:
        spec = self.spec_for_index(self.currentIndex())
        return spec is not None and spec.id in self._pinned

    def _install_pin(self, index: int, key: str) -> None:
        pin = QToolButton(self)
        pin.setObjectName("DocumentPinButton")
        pin.setCheckable(True)
        pin.setAutoRaise(True)
        pin.setIconSize(QSize(14, 14))
        pin.setChecked(key in self._pinned)
        self._sync_pin_button(pin, key in self._pinned)
        pin.toggled.connect(lambda checked, value=key, button=pin: self._set_pinned(value, checked, button))
        self.tabBar().setTabButton(index, QTabBar.ButtonPosition.LeftSide, pin)

    def _sync_pin_button(self, button: QToolButton, checked: bool) -> None:
        button.setIcon(icon("pin-filled" if checked else "pin", "#0A327A" if checked else "#344054", 14))
        button.setToolTip("取消固定" if checked else "固定此页")

    def _set_pinned(self, key: str, checked: bool, button: QToolButton | None = None) -> None:
        if checked:
            self._pinned.add(key)
        else:
            self._pinned.discard(key)
        if button is not None:
            self._sync_pin_button(button, checked)
        widget = self._widget_for(key)
        index = self.indexOf(widget) if widget is not None else -1
        if index >= 0:
            self.tabBar().setTabTextColor(index, QColor("#0A327A" if checked else "#344054"))
        self.pinChanged.emit()

    def _widget_for(self, key: str) -> QWidget | None:
        for index in range(self.count()):
            widget = self.widget(index)
            if widget is not None and str(widget.property("documentId") or "") == key:
                return widget
        return None

    def spec_for_index(self, index: int) -> TabSpec | None:
        widget = self.widget(index)
        key = str(widget.property("documentId") or "") if widget is not None else ""
        return self._specs.get(key)

    def _changed(self, index: int) -> None:
        spec = self.spec_for_index(index)
        if spec is not None:
            self.tabActivated.emit(spec.id)

    def _close(self, index: int) -> None:
        spec = self.spec_for_index(index)
        if spec is None or not spec.closable:
            return
        widget = self.widget(index)
        self.removeTab(index)
        self._specs.pop(spec.id, None)
        self._pinned.discard(spec.id)
        if widget is not None:
            widget.deleteLater()
        self.tabClosed.emit(spec.id)

    def add_document(self, spec: TabSpec, widget: QWidget) -> None:
        widget.setProperty("documentId", spec.id)
        self.open(spec, widget)


class DocumentWorkspace(QFrame):
    documentActivated = Signal(str)
    documentClosed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DocumentWorkspace")
        self._h = QSplitter(Qt.Orientation.Horizontal, self)
        self._h.setChildrenCollapsible(False)
        self._h.setHandleWidth(5)
        self._left = QSplitter(Qt.Orientation.Vertical, self._h)
        self._right = QSplitter(Qt.Orientation.Vertical, self._h)
        self._left.setChildrenCollapsible(False)
        self._right.setChildrenCollapsible(False)
        self._h.addWidget(self._left)
        self._h.addWidget(self._right)
        self._right.hide()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(self._h, 1)
        self._panes: list[DocumentPane] = []
        self._active_pane: DocumentPane | None = None
        self._add_pane()

    def _add_pane(self) -> DocumentPane:
        pane = DocumentPane(self)
        pane.tabActivated.connect(lambda key, value=pane: self._set_active_pane(value, key))
        pane.tabClosed.connect(lambda key, value=pane: self._pane_document_closed(value, key))
        self._panes.append(pane)
        if self._active_pane is None:
            self._active_pane = pane
        self._relayout_panes()
        return pane

    def _pane_document_closed(self, pane: DocumentPane, key: str) -> None:
        self.documentClosed.emit(key)
        self._collapse_empty_panes()

    def _collapse_empty_panes(self) -> None:
        if len(self._panes) <= 1:
            return
        for pane in list(self._panes)[::-1]:
            if len(self._panes) <= 1:
                break
            if pane.count() != 0:
                continue
            if self._active_pane is pane:
                self._active_pane = next(
                    (candidate for candidate in self._panes if candidate is not pane and candidate.count() > 0),
                    next((candidate for candidate in self._panes if candidate is not pane), None),
                )
            self._panes.remove(pane)
            pane.setParent(None)
            pane.deleteLater()
        self._relayout_panes()

    def _relayout_panes(self) -> None:
        for pane in self._panes:
            pane.setParent(None)
        count = len(self._panes)
        self._right.setVisible(count >= 2)
        if count == 0:
            return
        if count == 1:
            self._left.addWidget(self._panes[0])
        elif count == 2:
            self._left.addWidget(self._panes[0])
            self._right.addWidget(self._panes[1])
            self._h.setSizes([1, 1])
        elif count == 3:
            self._left.addWidget(self._panes[0])
            self._right.addWidget(self._panes[1])
            self._right.addWidget(self._panes[2])
            self._h.setSizes([1, 1])
            self._right.setSizes([1, 1])
        else:
            self._left.addWidget(self._panes[0])
            self._left.addWidget(self._panes[1])
            self._right.addWidget(self._panes[2])
            self._right.addWidget(self._panes[3])
            self._h.setSizes([1, 1])
            self._left.setSizes([1, 1])
            self._right.setSizes([1, 1])

    def _set_active_pane(self, pane: DocumentPane, key: str) -> None:
        self._active_pane = pane
        self.documentActivated.emit(key)

    @property
    def panes(self) -> tuple[DocumentPane, ...]:
        return tuple(self._panes)

    def has_documents(self) -> bool:
        return any(pane.count() > 0 for pane in self._panes)

    def open_document(self, spec: TabSpec, widget_factory: Callable[[], QWidget], *, split: bool = False) -> None:
        for pane in self._panes:
            if spec.id in pane._specs:
                self._active_pane = pane
                pane.open(spec, pane._widget_for(spec.id) or widget_factory())
                return
        pane = self._active_pane or self._panes[-1]
        should_split = bool(split or pane.is_current_pinned())
        if should_split and len(self._panes) < 4:
            pane = self._add_pane()
            self._active_pane = pane
        elif should_split:
            pane = next((item for item in self._panes if not item.is_current_pinned()), pane)
            self._active_pane = pane
        pane.add_document(spec, widget_factory())

    def split_next(self) -> None:
        if len(self._panes) < 4:
            self._add_pane()

    def clear(self) -> None:
        for pane in self._panes:
            pane.clear()
            pane._specs.clear()
            pane._pinned.clear()
        self._collapse_empty_panes()


class WorkbenchShell(QWidget):
    """Common shell for all ordinary modules."""

    secondaryRequested = Signal(str)
    navigateRequested = Signal(str)
    taskRequested = Signal(str)

    # 左侧对象栏的宽度 = 二级栏里某个按钮「文字右端」的 x 坐标。
    # 这样栏的右边缘会和上方那排二级按钮的文字对齐，视觉上是一条竖线。
    # 换对齐目标就改这里的 key（取值见 modules/navigation.py 的 SECONDARY_ITEMS）。
    RAIL_ALIGN_SECONDARY_KEY = "image_quality"   # 「光斑图」
    # 对齐后再往右多留的像素；0 = 严格贴在文字右端。
    RAIL_ALIGN_PADDING = 0
    # 二级栏里找不到对齐目标时的兜底宽度（本栏宽度是全局固定的，
    # 切到模型/优化/解释时不会跟着变）。
    RAIL_DEFAULT_WIDTH = 280

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("WorkbenchShell")
        self.module = "simulation"
        self._rail_width = self.RAIL_DEFAULT_WIDTH
        project = context.project.project
        self._system_state = SystemFormState(
            object_distance_mm=float(DEFAULT_OBJECT_DISTANCE_MM),
            pupil_radius_mm=float(project.pupil_radius_mm),
            image_distance_mm=float(DEFAULT_IMAGE_DISTANCE_MM),
        )
        self._calculation_state = CalculationFormState(analyses=("raytrace", "spot", "coupling", "psf"))
        self._alignment_state = AlignmentFormState()
        self.object_rail = ObjectRail(context, self)
        self._workspace_stack = QStackedWidget(self)
        self._workspaces: dict[str, DocumentWorkspace] = {}
        self.workspace: DocumentWorkspace
        for module in ("simulation", "model", "optimization", "explainability"):
            workspace = DocumentWorkspace(self._workspace_stack)
            workspace.documentActivated.connect(
                lambda key, value=module: self._document_activated(value, key)
            )
            workspace.documentClosed.connect(
                lambda key, value=module: self._document_closed(value, key)
            )
            self._workspace_stack.addWidget(workspace)
            self._workspaces[module] = workspace
        self.workspace = self._workspaces["simulation"]
        self.secondary = SecondaryBar(self)
        self._tabs: dict[str, TabSpec] = {}
        self._widgets: dict[str, QWidget] = {}
        self._selected_optimization: set[str] = set()
        self._selected_explain = ""
        self._datasets = [
            {"id": "dataset-880bdde6c292", "title": "内置演示·780 nm 四透镜八变量", "kind": "builtin", "family": "tabular"},
        ]
        self._trained_models: list[dict[str, Any]] = []
        self._normalizing_model_names = False
        self._shap_scores: dict[str, float] = {}
        self._last_dataset_id = ""
        self._pending_generated_dataset_id = ""
        self._pending_generated_dataset_name = ""
        self._pending_import_dataset_name = ""
        self._explain_dataset: dict[str, dict[str, Any]] = {}
        self._explain_current: dict[str, dict[str, Any]] = {}
        self._pending_candidate_validation: dict[str, Any] | None = None
        self._predict_token = ""
        self.object_rail.set_catalogs(self._datasets, self._trained_models)
        registry = getattr(self.context, "registry", None)
        if registry is not None:
            registry.models_changed.connect(self._on_registry_models_changed)
            self._on_registry_models_changed(getattr(registry, "models", []) or [])
            QTimer.singleShot(0, self._load_registered_models)
        self._lens_document: LensDataDocument | None = None
        self._connected_field = None
        self._connected_source = None
        self._connected_env = None
        self._connected_goal = None
        self._connected_detector = None
        self._simulation_controller = SimulationController(context, SimulationPreviewWorkflow(context.project), self)
        self._simulation_controller.formalResultReady.connect(self._formal_result_ready)
        self._simulation_controller.formalFailed.connect(self._formal_failed)
        self._simulation_controller.stateChanged.connect(self._formal_status)
        self._jobs = WorkbenchJobController(context, self)
        self._jobs.submitted.connect(self._on_workbench_job_submitted)
        self._jobs.progress.connect(self._on_workbench_job_progress)
        self._jobs.finished.connect(self._on_workbench_job_finished)
        self._jobs.failed.connect(self._on_workbench_job_failed)
        self._jobs.cancelled.connect(self._on_workbench_job_cancelled)
        self._jobs.cancellationFailed.connect(self._on_workbench_job_cancellation_failed)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.secondary)
        # 用普通 QHBoxLayout 而不是 QSplitter：左侧对象栏的宽度是定死的
        # （见 _sync_rail_width），不需要拖拽手柄。用 QSplitter 反而会多出
        # 一条可拖的缝，还能把栏拖没。
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.object_rail, 0)
        body.addWidget(self._workspace_stack, 1)
        root.addLayout(body, 1)
        self.secondary.itemRequested.connect(self._secondary_clicked)
        self.object_rail.objectRequested.connect(self._object_clicked)
        self.object_rail.optimizationSelectionChanged.connect(self._optimization_selected)
        self.object_rail.datasetCancelRequested.connect(self._cancel_dataset_generation)
        self.context.project.project_changed.connect(self._project_state_changed)
        self.set_module("simulation")

    def _sync_rail_width(self) -> None:
        """把左侧对象栏的宽度锁定到二级栏某个按钮的文字右端。

        为什么不用窗口宽度的百分比：二级按钮是定宽、左对齐的，窗口变宽时它们
        原地不动。所以百分比只在某一个窗口宽度上对得齐，一缩放就错位。
        这里改成直接读按钮的真实几何，任何窗口尺寸下都对齐。
        """
        button = self.secondary.buttons.get(self.RAIL_ALIGN_SECONDARY_KEY)
        # 布局尚未跑过时按钮宽度为 0，此时不改宽度，等下一次调用。
        if button is not None and button.width() > 0:
            text_width = button.fontMetrics().horizontalAdvance(button.text())
            # QToolButton 的文字是水平居中的，所以：
            #   文字右端 = 按钮左端 + (按钮宽 + 文字宽) / 2
            text_right = button.geometry().x() + (button.width() + text_width) // 2
            self._rail_width = text_right + self.RAIL_ALIGN_PADDING
        # setFixedWidth 会把 min/max 同时钉死，因此这条栏既不可拖也不会被挤动。
        self.object_rail.setFixedWidth(self._rail_width)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        # 首次显示时窗口尺寸才确定，按钮几何此时才有效。
        super().showEvent(event)
        self._sync_rail_width()

    def set_module(self, module: str) -> None:
        if str(module) == "analysis":
            module = "simulation"
        self.module = str(module)
        self.secondary.set_module(self.module)
        # 二级栏刚重建完按钮，几何要等本轮布局跑完才有效，所以延到事件循环下一拍。
        QTimer.singleShot(0, self._sync_rail_width)
        self.object_rail.setVisible(self.module != "home")
        self.object_rail.set_module(self.module)
        workspace = self._workspaces.get(self.module)
        if workspace is not None:
            self.workspace = workspace
            self._workspace_stack.setCurrentWidget(workspace)
        self._workspace_stack.setVisible(self.module != "home")
        self._connect_rail_editors()
        self._sync_rail_document()
        # 上面 secondary.set_module() 把按钮全重建成了未选中态，这里要把它恢复
        # 到「本模块当前正在看的那个文档」对应的按钮上。否则从别的模块切回来时
        # 二级栏一个都不亮，看不出现在停在哪一页。
        #
        # 首次进入本模块时 _current_document_kind() 还是空串，这里不做任何事，
        # 由随后的 open_document() → _activate_secondary() 点亮默认文档；
        # 重入时已有文档、不会再走 open_document()，就靠这里补上。两处互补。
        self._activate_secondary(self.module, self._current_document_kind())

    def _connect_rail_editors(self) -> None:
        field = self.object_rail.field_inspector
        source = self.object_rail.source_inspector
        env = self.object_rail.environment_inspector
        goal = self.object_rail.goal_inspector
        detector = self.object_rail.detector_inspector
        if field is not None and field is not self._connected_field:
            field.changed.connect(self._sync_field)
            self._connected_field = field
        if source is not None and source is not self._connected_source:
            source.field_x.valueChanged.connect(self._sync_field_from_source)
            source.field_y.valueChanged.connect(self._sync_field_from_source)
            self._connected_source = source
        if env is not None and env is not self._connected_env:
            env.changed.connect(self._sync_environment)
            self._connected_env = env
        if goal is not None and goal is not self._connected_goal:
            goal.startRequested.connect(self.start_optimization)
            self._connected_goal = goal
        if detector is not None and detector is not self._connected_detector:
            detector.changed.connect(self._detector_overlay_changed)
            self._connected_detector = detector

    def _sync_field(self) -> None:
        field = self.object_rail.field_inspector
        source = self.object_rail.source_inspector
        if field is None or source is None:
            return
        field_x, field_y = field.field_angles()
        source.set_field_angles(field_x, field_y)
        self._system_state = replace(self._system_state, field_x_deg=field_x, field_y_deg=field_y)

    def _sync_field_from_source(self, *_args) -> None:
        field = self.object_rail.field_inspector
        source = self.object_rail.source_inspector
        if field is None or source is None:
            return
        field.set_field_angles(float(source.field_x.value()), float(source.field_y.value()))
        self._system_state = replace(
            self._system_state,
            field_x_deg=float(source.field_x.value()),
            field_y_deg=float(source.field_y.value()),
        )

    def _sync_environment(self) -> None:
        env = self.object_rail.environment_inspector
        if env is None:
            return
        self._system_state = replace(self._system_state, **env.system_patch())

    def has_documents(self, module: str | None = None) -> bool:
        workspace = self._workspaces.get(str(module or self.module))
        return bool(workspace is not None and workspace.has_documents())

    def assistant_context(self) -> dict:
        labels = {
            "simulation": "仿真系统",
            "model": "模型",
            "optimization": "优化",
            "explainability": "解释",
        }
        open_tabs = [spec.kind for spec in self._tabs.values() if spec.module == self.module]
        formal = getattr(self.context.project, "formal_result", None)
        return {
            "page": labels.get(self.module, self.module),
            "current_view": self.module,
            "open_tabs": open_tabs,
            "has_formal_result": bool(formal),
            "project_metrics": dict(getattr(self.context.project.project, "metrics", {}) or {}),
        }

    def _secondary_clicked(self, key: str) -> None:
        self.secondaryRequested.emit(key)
        if self.module == "teaching":
            return
        kind = SECONDARY_DEFAULT_KIND.get((self.module, key), key)
        self.open_document(self.module, kind)

    def _object_clicked(self, key: str) -> None:
        if self.module == "explainability":
            if str(key).startswith("model:"):
                ident = key.split(":", 1)[1]
                self.object_rail.set_selected_model(ident)
                record = next((item for item in self._trained_models if item.get("id") == ident), None)
                title = str((record or {}).get("title") or ident)
                widget = self._widgets.get(f"explainability:{self._current_document_kind()}")
                setter = getattr(widget, "set_model", None)
                if callable(setter):
                    setter(title)
                registry = getattr(self.context, "registry", None)
                if registry is not None and ident:
                    registry.set_current_model(ident)
                return
            if str(key).startswith("dataset:"):
                return
            self._selected_explain = key
            for widget in self._widgets.values():
                setter = getattr(widget, "set_selected", None)
                if callable(setter) and getattr(widget, "kind", "") == "param_trend":
                    setter(key)
            return
        if self.module == "model":
            self._model_object_clicked(key)
            return
        if self.module != "simulation":
            return
        if key in {"environment", "field", "detector", "source", "fiber", "materials"}:
            return
        if key == "lens_group":
            self.open_document("simulation", "lens_data")
        elif key.startswith("lens:"):
            index = int(key.split(":", 1)[1])
            self.open_document("simulation", "lens_data")
            document = self._lens_document
            if document is not None:
                document.select_surface(index)
            sliders = self.object_rail.lens_sliders
            if sliders is not None:
                sliders.set_surface(index)

    def _model_object_clicked(self, key: str) -> None:
        if key.startswith("dataset:"):
            ident = key.split(":", 1)[1]
            record = next(
                (item for item in self._datasets if str(item.get("id") or "") == ident),
                None,
            )
            if record is None:
                return
            self.object_rail.set_selected_dataset(ident)
            if str(record.get("kind") or "") in {
                "generated_pending",
                "generated_failed",
                "generated_cancelled",
            }:
                self.object_rail.set_selected_dataset("")
                return
            title = str(record.get("title") or ident)
            widget = self._widgets.get("model:dataset")
            if widget is not None:
                family = str(record.get("family") or "tabular")
                setter = getattr(widget, "_set_family", None)
                if callable(setter):
                    setter(family)
                mode_index = widget.source_mode.findData("import")
                if mode_index >= 0 and widget.source_mode.currentIndex() != mode_index:
                    widget.source_mode.setCurrentIndex(mode_index)
                widget.select_dataset(title)
                source = {
                    "builtin": "builtin",
                    "file": "file",
                    "generated": "generated",
                }.get(str(record.get("kind") or ""))
                if source:
                    widget.set_active_dataset(ident, source)
                    if family == "sequence" and source == "generated":
                        widget.register_generated_sequence_dataset(ident, record)
            return
        if not key.startswith("model:"):
            return
        ident = key.split(":", 1)[1]
        title = next((item["title"] for item in self._trained_models if item["id"] == ident), ident)
        kind = self._current_document_kind()
        self.object_rail.set_selected_model(ident)
        registry = getattr(self.context, "registry", None)
        if registry is not None and ident:
            registry.set_current_model(ident)
        if kind == "train_result":
            widget = self._widgets.get("model:train_result")
            if widget is not None:
                record = next(
                    (item for item in self._trained_models if str(item.get("id") or "") == ident),
                    None,
                )
                marker = getattr(widget, "mark_trained", None)
                if isinstance(record, dict) and callable(marker):
                    marker(record)
                widget.show_train_chart(widget.chart.currentText())
            return
        widget = self._widgets.get("model:predict") or self._widgets.get("model:predict_eval")
        if widget is not None:
            widget.select_predict_model(title)

    def _sync_schematic_mode(self, kind: str) -> None:
        widget = self._widgets.get(f"simulation:{kind}")
        setter = getattr(widget, "set_mode", None)
        if not callable(setter):
            return
        if kind == "source_schematic" and self.object_rail.source_inspector is not None:
            setter(self.object_rail.source_inspector.schematic_mode())
        elif kind == "fiber_schematic" and self.object_rail.fiber_inspector is not None:
            setter(self.object_rail.fiber_inspector.current_model())

    def _optimization_selected(self, key: str, enabled: bool) -> None:
        if enabled:
            self._selected_optimization.add(key)
        else:
            self._selected_optimization.discard(key)
        widget = self._widgets.get("optimization:opt_vars")
        setter = getattr(widget, "set_selected", None)
        if callable(setter):
            setter(self._selected_optimization)
        scan = self._widgets.get("optimization:scan")
        scan_setter = getattr(scan, "set_selected", None)
        if callable(scan_setter):
            scan_setter(self._selected_optimization)

    def _activate_secondary(self, module: str, kind: str) -> None:
        if module != self.module:
            return
        self.secondary.activate(KIND_TO_SECONDARY.get((module, kind), kind))

    def _make_spec(self, module: str, kind: str, *, id_suffix: str = "") -> TabSpec:
        title, subtitle = _kind_titles(module, kind)
        identifier = f"{module}:{kind}{(':' + id_suffix) if id_suffix else ''}"
        return TabSpec(identifier, module, kind, title, subtitle)

    def open_document(self, module: str, kind: str, *, id_suffix: str = "", split: bool = False) -> None:
        module = "simulation" if str(module) == "analysis" else str(module)
        kind = {"train": "train_result", "opt_goal": "opt_vars", "evaluate": "train_result"}.get(str(kind), str(kind))
        if module == "teaching":
            return
        spec = self._make_spec(module, kind, id_suffix=id_suffix)
        if spec.id in self._tabs:
            self._activate_existing(spec.id)
            self._activate_secondary(module, spec.kind)
            self._sync_rail_document()
            return
        widget = self._create_document(spec)
        widget.setProperty("documentId", spec.id)
        self._tabs[spec.id] = spec
        self._widgets[spec.id] = widget
        workspace = self._workspaces.get(module, self.workspace)
        workspace.open_document(spec, lambda value=widget: value, split=split)
        self._activate_secondary(module, kind)
        self._sync_rail_document()

    def _activate_existing(self, identifier: str) -> None:
        for workspace in self._workspaces.values():
            for pane in workspace.panes:
                for index in range(pane.count()):
                    spec = pane.spec_for_index(index)
                    if spec is not None and spec.id == identifier:
                        workspace._active_pane = pane
                        pane.setCurrentIndex(index)
                        return

    def _document_activated(self, module: str, identifier: str) -> None:
        if str(module) != self.module:
            return
        spec = self._tabs.get(str(identifier))
        if spec is not None:
            self._activate_secondary(str(module), spec.kind)
            self._sync_rail_document()

    def _document_closed(self, module: str, identifier: str) -> None:
        self._tabs.pop(str(identifier), None)
        widget = self._widgets.pop(str(identifier), None)
        if widget is self._lens_document:
            self._lens_document = None

    def _create_document(self, spec: TabSpec) -> QWidget:
        if spec.module == "simulation":
            if spec.kind == "lens_data":
                if self._lens_document is None:
                    self._lens_document = LensDataDocument(self.context)
                    self._lens_document.settingsRequested.connect(self._open_engineering)
                return self._lens_document
            if spec.kind == "material_library":
                return MaterialsTab(self.context)
            if spec.kind in {"source_schematic", "fiber_schematic"}:
                document = SchematicDocument(self.context, spec.kind)
                self._sync_widget_mode(document)
                return document
            if spec.kind in RESULT_DOCUMENT_KINDS:
                result_factory = {
                    "ray_layout": LayoutTab,
                    "spot": ImageQualityTab,
                    "coupling": FiberCouplingTab,
                    "wavefront": WaveDiffractionTab,
                }.get(spec.kind)
                document = (
                    result_factory(self.context)
                    if result_factory is not None
                    else ResultDocument(self.context, spec.kind)
                )
                document.relatedRequested.connect(lambda kind: self.open_document("simulation", kind))
                return document
        if spec.module == "model":
            document_factory = {
                "dataset": DatasetTab,
                "train_result": TrainingResultTab,
                "predict": PredictionTab,
            }.get(spec.kind)
            if document_factory is None:
                return EmptyDocument(spec.title, spec.subtitle)
            document = document_factory(self.context)
            document.trainRequested.connect(self._start_model_training)
            generate = getattr(document, "generateRequested", None)
            if generate is not None:
                generate.connect(self._start_dataset_generation)
            predict = getattr(document, "predictRequested", None)
            if predict is not None:
                predict.connect(self._start_model_predict)
            generated = getattr(document, "datasetGenerated", None)
            if generated is not None:
                generated.connect(self._register_generated_dataset)
            importer = getattr(document, "fileImportRequested", None)
            if importer is not None:
                importer.connect(self._import_dataset_file)
            kind_changed = getattr(document, "dataKindChanged", None)
            if kind_changed is not None:
                kind_changed.connect(self._set_dataset_family)
            selection_changed = getattr(document, "datasetSelectionChanged", None)
            if selection_changed is not None:
                selection_changed.connect(self._dataset_selection_changed)
            setter = getattr(document, "set_trained_models", None)
            if callable(setter):
                setter(self._trained_models)
            return document
        if spec.module == "optimization":
            document_factory = {
                "scan": ScanTab,
                "opt_vars": VariablesTab,
                "opt_result": OptimizationResultTab,
            }.get(spec.kind)
            if document_factory is None:
                return EmptyDocument(spec.title, spec.subtitle)
            if spec.kind == "opt_vars":
                self.object_rail.ensure_optimization_controls()
                document = document_factory(
                    self.context,
                    self._selected_optimization,
                    goal=self.object_rail.goal_inspector,
                    max_evaluations=self.object_rail.max_evaluations,
                )
            else:
                document = document_factory(self.context, self._selected_optimization)
            document.startRequested.connect(self.start_optimization)
            scan = getattr(document, "scanRequested", None)
            if scan is not None:
                scan.connect(self._start_scan)
            apply_and_verify = getattr(document, "applyAndVerifyRequested", None)
            if apply_and_verify is not None:
                apply_and_verify.connect(self._verify_applied_candidate)
            setter = getattr(document, "set_trained_models", None)
            if callable(setter):
                setter(self._trained_models)
            return document
        if spec.module == "explainability":
            document_factory = {
                "global_contrib": GlobalContributionTab,
                "param_trend": ParameterTrendTab,
                "current_system": CurrentSystemTab,
            }.get(spec.kind)
            if document_factory is None:
                return EmptyDocument(spec.title, spec.subtitle)
            document = document_factory(self._selected_explain, self.context)
            setter = getattr(document, "set_trained_models", None)
            if callable(setter):
                setter(self._trained_models)
            cache = getattr(document, "set_explain_cache", None)
            if callable(cache):
                cache(self._explain_dataset, self._explain_current)
            ranks = getattr(document, "shapRanksReady", None)
            if ranks is not None:
                ranks.connect(self._set_shap_ranks)
            return document
        return EmptyDocument(spec.title, spec.subtitle)

    def _sync_widget_mode(self, document: SchematicDocument) -> None:
        if document.kind == "source_schematic" and self.object_rail.source_inspector is not None:
            document.set_mode(self.object_rail.source_inspector.schematic_mode())
        elif document.kind == "fiber_schematic" and self.object_rail.fiber_inspector is not None:
            document.set_mode(self.object_rail.fiber_inspector.current_model())

    def _open_engineering(self, kind: str) -> None:
        system = self._system_state
        source = self.object_rail.source_inspector
        if source is not None:
            source_state = source.form_state()
            system = replace(
                system,
                field_x_deg=source_state.field_x_deg,
                field_y_deg=source_state.field_y_deg,
                pupil_radius_mm=float(self.context.project.project.pupil_radius_mm),
            )
        dialog = EngineeringDialog(
            kind,
            self.context,
            self,
            system=system,
            calculation=self._calculation_state,
            alignment=self._alignment_state,
        )
        if kind == "compute":
            dialog.runRequested.connect(lambda: self._apply_engineering(dialog, run=True))
        if dialog.exec():
            self._apply_engineering(dialog, run=False)

    def _apply_engineering(self, dialog: EngineeringDialog, *, run: bool) -> None:
        if dialog.kind in {"environment", "aperture"}:
            self._system_state = dialog.system_state()
            source = self.object_rail.source_inspector
            if dialog.kind == "aperture" and source is not None:
                source.set_field_angles(self._system_state.field_x_deg, self._system_state.field_y_deg)
        if dialog.kind == "compute":
            self._calculation_state = dialog.calculation_state()
            self._alignment_state = dialog.alignment_state()
            if self._alignment_state.enabled and "fiber_alignment" not in self._calculation_state.analyses:
                self._calculation_state = replace(
                    self._calculation_state,
                    analyses=tuple(self._calculation_state.analyses) + ("fiber_alignment",),
                )
            if not run:
                # Display-only coupling preferences should also update an
                # already completed result; they do not require a new solve.
                stored = getattr(self.context.project, "simulation_project_payload", {})
                if callable(stored):
                    stored = stored()
                if isinstance(stored, dict) and isinstance(stored.get("analysis_settings"), dict):
                    updated = dict(stored)
                    settings = dict(updated.get("analysis_settings") or {})
                    settings["incident_intensity_only"] = bool(self._calculation_state.incident_intensity_only)
                    updated["analysis_settings"] = settings
                    self.context.project.set_simulation_project_payload(updated)
                formal_result = getattr(self.context.project, "formal_result", None)
                coupling = self._widgets.get("simulation:coupling")
                if coupling is not None and isinstance(formal_result, dict) and formal_result:
                    callback = getattr(coupling, "_result_changed", None)
                    if callable(callback):
                        callback(formal_result)
            if run:
                self.run_formal_calculation()
                closer = dialog
                parent = dialog.parentWidget()
                if parent is not None and parent.objectName() == "CombinedSettingsDialog":
                    closer = parent
                closer.accept()

    def _start_model_training(self) -> None:
        dataset = self._widgets.get("model:dataset")
        if dataset is None:
            self.taskRequested.emit("请先打开数据集页。")
            return
        family = dataset.current_family()
        source = dataset.current_dataset_source()
        kind = "bilstm" if family == "sequence" else "train"
        if family == "sequence":
            generated = dataset.generated_sequence_config() if source == "generated" else {}
            path = str(
                generated.get("sequence_dataset_path")
                if generated else dataset.file_path.text() or ""
            ).strip()
            if source not in {"file", "generated"} or not path:
                self.open_document("model", "train_result")
                widget = self._widgets.get("model:train_result")
                status = getattr(widget, "show_train_status", None)
                if callable(status):
                    status("请先选择文件并点击“导入”。")
                return
            payload = {
                "dataset_path": path,
                "system_id_column": str(generated.get("system_id_column") or dataset.system_id_column.text() or "system_id"),
                "order_column": str(generated.get("order_column") or dataset.order_column.text() or "element_index"),
                "element_type_column": str(generated.get("element_type_column") or dataset.element_type_column.text() or "element_type"),
                "numeric_feature_columns": list(generated.get("numeric_feature_columns") or [item.strip() for item in str(dataset.numeric_columns.text() or "").split(",") if item.strip()]),
                "target_columns": list(generated.get("target_columns") or [item.strip() for item in str(dataset.sequence_target.text() or "coupling_efficiency").split(",") if item.strip()]),
                "config": dataset.train_hyperparameters(),
            }
        else:
            selected_dataset_id = dataset.selected_dataset_id()
            if not selected_dataset_id:
                self.open_document("model", "train_result")
                widget = self._widgets.get("model:train_result")
                status = getattr(widget, "show_train_status", None)
                if callable(status):
                    status(
                        "请选择“内置”，或在“生成”模式完成生成；"
                        "导入文件后请点击“导入”。"
                    )
                return
            payload = {
                "dataset_id": selected_dataset_id,
                "random_seed": int(dataset.seed.value()),
                "random_forest_hyperparameters": dataset.random_forest_hyperparameters(),
                "xgboost_hyperparameters": dataset.xgboost_hyperparameters(),
            }
        self.open_document("model", "train_result")
        widget = self._widgets.get("model:train_result")
        status = getattr(widget, "show_train_status", None)
        if callable(status):
            status("正在提交训练…")
        dataset.set_job_busy(True)
        error = self._jobs.submit("joint_train" if family == "tabular" else kind, payload)
        if error:
            handler = getattr(widget, "show_train_failed", None)
            if callable(handler):
                handler(error)
            dataset.set_job_busy(False)
            if callable(status):
                status(error)
            self.taskRequested.emit(error)

    def _import_dataset_file(self, path: str) -> None:
        """Import the selected local table before allowing tabular training."""
        dataset = self._widgets.get("model:dataset")
        if dataset is None:
            return
        source_path = str(path or "").strip()
        if not source_path:
            return
        if dataset.current_family() == "sequence":
            dataset.mark_file_imported()
            dataset.show_generate_status(
                "文件已导入",
                [("—", source_path.replace("\\", "/").rsplit("/", 1)[-1], "—", "可训练")],
            )
            return
        api = getattr(self.context, "api_client", None)
        if api is None:
            dataset.set_import_busy(False)
            return
        self._pending_import_dataset_name = source_path.replace("\\", "/").rsplit("/", 1)[-1]
        self._dataset_import_token = f"workbench.dataset.import.{uuid4().hex[:8]}"
        if not getattr(self, "_dataset_import_bound", False):
            api.completed.connect(self._on_dataset_import_completed)
            api.failed.connect(self._on_dataset_import_failed)
            self._dataset_import_bound = True
        dataset.set_import_busy(True)
        dataset.show_generate_status("正在导入文件数据集…")
        from frontend_pyside.api.headless_dataset_client import HeadlessDatasetClient
        HeadlessDatasetClient(api).import_file(
            self._dataset_import_token,
            {
                "source_path": source_path,
                "dataset_name": self._pending_import_dataset_name,
                "target_name": target_backend_name(str(dataset.target.currentText() or "耦合效率")),
                "random_seed": int(dataset.seed.value()),
            },
        )

    def _on_dataset_import_completed(self, key: str, data: object) -> None:
        if str(key) != getattr(self, "_dataset_import_token", ""):
            return
        body = dict(data or {}) if isinstance(data, dict) else {}
        dataset_id = str(body.get("dataset_id") or "")
        dataset = self._widgets.get("model:dataset")
        if dataset is not None:
            dataset.set_job_busy(False)
            if dataset_id:
                dataset.mark_file_imported(dataset_id)
            else:
                dataset.set_import_busy(False)
            dataset.show_generate_status("文件已导入", [(dataset_id or "—", "文件数据集", "—", "可训练")])
        if not dataset_id:
            self._pending_import_dataset_name = ""
            self.taskRequested.emit("文件已提交，但后端没有返回数据集 ID。")
            return
        self._last_dataset_id = dataset_id
        title = str(body.get("dataset_name") or self._pending_import_dataset_name or dataset_id)
        self._pending_import_dataset_name = ""
        self._register_dataset(title, dataset_id=dataset_id)
        self.object_rail.set_selected_dataset(dataset_id)
        registry = getattr(self.context, "registry", None)
        if registry is not None:
            registry.merge_dataset({"dataset_id": dataset_id, "id": dataset_id, "name": title, **body})
            registry.set_current_dataset(dataset_id)

    def _on_dataset_import_failed(self, key: str, message: str) -> None:
        if str(key) != getattr(self, "_dataset_import_token", ""):
            return
        self._pending_import_dataset_name = ""
        dataset = self._widgets.get("model:dataset")
        if dataset is not None:
            dataset.set_job_busy(False)
            dataset.set_import_busy(False)
        self.taskRequested.emit(f"文件导入失败：{message}")

    def _start_dataset_generation(self) -> None:
        dataset = self._widgets.get("model:dataset")
        if (
            dataset is None
            or dataset.current_source_mode() != "generate"
        ):
            return
        from machine_learning.features.coupling_physics import paired_coupling_targets

        state = self.collect_simulation_state()
        project_payload = serialize_project(self.context.project.project, state)
        family = dataset.current_family()
        scheme_id = None
        lens_count = None
        if family == "sequence":
            from machine_learning.datasets.variable_schemes import resolve_lens_bindings

            lens_count = len(resolve_lens_bindings(project_payload))
            paths = dataset.sequence_variable_paths()
            if not lens_count:
                self.taskRequested.emit("当前系统没有可识别的实体镜片，无法生成序列数据集")
                return
            if not paths:
                self.taskRequested.emit("请至少选择一个用于扰动的变量")
                return
            scheme_id = "arbitrary_lens_sequence"
        else:
            from machine_learning.datasets.variable_schemes import resolve_variable_scheme
            try:
                scheme = resolve_variable_scheme(
                    project_payload,
                    lens_count=int(dataset.lens_count.currentData() or 1),
                    include_conic=dataset.variable_scheme.currentData() == "asphere",
                )
            except ValueError as exc:
                self.taskRequested.emit(str(exc))
                return
            paths = list(scheme.design_variable_paths)
            scheme_id = scheme.scheme_id
            lens_count = scheme.lens_count
        parameters = build_dataset_parameters(project_payload, explicit_paths=paths)
        if not parameters:
            self.taskRequested.emit("未选择可采样参数")
            return
        validation = min(0.45, max(0.05, float(dataset.split.value())))
        test = min(0.15, max(0.05, validation))
        self._pending_generated_dataset_name = self._next_generated_dataset_name()
        payload = {
            "dataset_name": self._pending_generated_dataset_name,
            "base_project": project_payload,
            "parameters": parameters,
            "targets": paired_coupling_targets([target_backend_name(str(dataset.target.currentText() or "耦合损耗(dB)"))]),
            "sample_count": int(dataset.samples.value()),
            "sampling_method": sampling_backend_name(str(dataset.sampling.currentText() or "")),
            "train_ratio": max(0.0, 1.0 - validation - test),
            "validation_ratio": validation,
            "test_ratio": test,
            "random_seed": int(dataset.seed.value()),
            "precision": PRECISION_MAP.get(str(dataset.precision.currentText() or ""), "standard"),
            "variable_scheme_id": scheme_id,
            "lens_count": lens_count,
            "design_variable_paths": list(paths),
            "dataset_layout": "sequence_long" if family == "sequence" else "tabular",
        }
        self._pending_generated_dataset_id = f"pending-dataset-{uuid4().hex[:10]}"
        self._register_pending_generated_dataset(
            self._pending_generated_dataset_id,
            status="生成中",
            family=family,
        )
        self.object_rail.set_selected_dataset(self._pending_generated_dataset_id)
        dataset.set_job_busy(True)
        error = self._jobs.submit("dataset", payload)
        if error:
            self._remove_pending_generated_dataset()
            self._pending_generated_dataset_name = ""
            dataset.set_job_busy(False)
            self.taskRequested.emit(error)

    def _start_model_predict(self) -> None:
        from uuid import uuid4

        from frontend_pyside.infrastructure.api.clients import TrainingClient

        predict = self._widgets.get("model:predict") or self._widgets.get("model:predict_eval")
        if predict is None:
            return
        combo = getattr(predict, "predict_model", None)
        record = combo.currentData() if combo is not None else None
        if not isinstance(record, dict) or not record.get("id"):
            predict.show_predict_status("请先在数据集页训练，再选择已训练模型。")
            return
        usable, quality_reason = model_prediction_status(record)
        if not usable:
            predict.show_predict_status(quality_reason)
            return
        model_id = str(record.get("id") or "")
        api = getattr(self.context, "api_client", None)
        if api is None:
            predict.show_predict_status("后端不可用（无 API 连接）")
            return
        predict._fill_predict_inputs()
        predict.show_predict_status("正在预测…")
        self._predict_token = f"workbench.predict.{uuid4().hex[:8]}"
        if not getattr(self, "_predict_api_bound", False):
            api.completed.connect(self._on_predict_completed)
            api.failed.connect(self._on_predict_failed)
            self._predict_api_bound = True
        model_kind = model_backend_kind(record.get("model_type") or record.get("family") or "")
        if model_kind == "bilstm_structure_sequence":
            try:
                sequence_payload = sequence_prediction_payload(
                    self.context.project.project,
                    record,
                )
            except ValueError as exc:
                predict.show_predict_status(str(exc))
                return
            TrainingClient(api).predict_bilstm(
                self._predict_token,
                model_id,
                sequence_payload,
            )
            return
        try:
            features = model_features(self.context.project.project, record)
        except FeaturePathError as exc:
            predict.show_predict_status(f"当前镜头无法构造模型特征：{exc}")
            return
        TrainingClient(api).predict(
            self._predict_token,
            model_id,
            features,
        )

    def _on_predict_completed(self, key: str, data: object) -> None:
        if str(key) != getattr(self, "_predict_token", ""):
            return
        predict = self._widgets.get("model:predict") or self._widgets.get("model:predict_eval")
        if predict is None:
            return
        body = dict(data or {}) if isinstance(data, dict) else {}
        predictions = dict(body.get("predictions") or {})
        combo = getattr(predict, "predict_model", None)
        target = str(predict.predict_target.text() or "")
        backend_target = target_backend_name(target)
        value = predictions.get(backend_target)
        if value is None and predictions:
            value = next(iter(predictions.values()))
        if value is None:
            predict.show_predict_status("这次预测没有返回数值。")
            return
        predicted = float(value)
        formal = _formal_target_value(self.context, target)
        rows = [("输出", f"{predicted:.4g}"), ("目标", target), ("模型", combo.currentText() if combo is not None else "")]
        if formal is None:
            rows.append(("光学仿真", "尚未对照仿真"))
        else:
            rows.append(("光学仿真", f"{formal:.4g}"))
            rows.append(("差值", f"{predicted - formal:.4g}"))
        predict.show_predict_result(rows)

    def _on_predict_failed(self, key: str, message: str) -> None:
        if str(key) != getattr(self, "_predict_token", ""):
            return
        predict = self._widgets.get("model:predict") or self._widgets.get("model:predict_eval")
        if predict is not None:
            predict.show_predict_status(explain_job_failure(message))

    def _set_shap_ranks(self, scores: dict[str, float]) -> None:
        self._shap_scores = dict(scores or {})
        self.object_rail.set_shap_scores(self._shap_scores)

    def _set_dataset_family(self, family: str) -> None:
        self.object_rail.set_dataset_family(family)

    def _dataset_selection_changed(self, dataset_id: str) -> None:
        self.object_rail.set_selected_dataset(str(dataset_id or ""))

    def _next_generated_dataset_name(self) -> str:
        """Return the next collision-free display name for a generated dataset."""
        numbers = []
        for item in self._datasets:
            title = str(item.get("title") or "").strip()
            suffix = title[len("数据集"):] if title.startswith("数据集") else ""
            if suffix.isdigit():
                numbers.append(int(suffix))
        number = max(numbers, default=0) + 1
        existing_titles = {str(item.get("title") or "").strip() for item in self._datasets}
        while f"数据集{number}" in existing_titles:
            number += 1
        return f"数据集{number}"

    @staticmethod
    def _model_display_type(model_type: str) -> str:
        return {
            "random_forest": "随机森林",
            "xgboost_physics_residual": "XGBoost物理残差",
            "bilstm_structure_sequence": "BiLSTM",
        }.get(str(model_type or "").strip(), str(model_type or "模型").strip() or "模型")

    def _next_model_name(self, model_type: str) -> tuple[str, int]:
        """Return a stable ``模型名字+序号`` display name for a new model."""
        prefix = self._model_display_type(model_type)
        numbers: set[int] = set()
        for item in self._trained_models:
            if self._model_display_type(item.get("model_type", "")) != prefix:
                continue
            try:
                number = int(item.get("model_number") or 0)
            except (TypeError, ValueError):
                number = 0
            title = str(item.get("title") or "")
            if number <= 0 and title.startswith(prefix):
                suffix = title[len(prefix):]
                number = int(suffix) if suffix.isdigit() else 0
            if number > 0:
                numbers.add(number)
        number = max(numbers, default=0) + 1
        while number in numbers:
            number += 1
        return f"{prefix}{number}", number

    def _register_dataset(self, title: str, *, dataset_id: str = "", kind: str = "file") -> None:
        name = str(title or "").strip()
        if not name or any(item.get("title") == name for item in self._datasets):
            return
        widget = self._widgets.get("model:dataset")
        family = widget.current_family() if widget is not None and hasattr(widget, "current_family") else "tabular"
        self._datasets.append({"id": str(dataset_id or f"file-{len(self._datasets) + 1}"), "title": name, "kind": kind, "family": family})
        self.object_rail.set_catalogs(self._datasets, self._trained_models)

    def _register_pending_generated_dataset(
        self, dataset_id: str, *, status: str = "生成中", family: str = "tabular"
    ) -> None:
        """Put a transient generation item in the dataset rail immediately."""
        ident = str(dataset_id or "").strip()
        if not ident:
            return
        self._datasets = [
            item for item in self._datasets
            if str(item.get("id") or "") != ident
        ]
        self._datasets.append(
            {
                "id": ident,
                "title": "数据集生成",
                "kind": "generated_pending",
                "family": str(family or "tabular"),
                "progress": 0.0,
                "status": str(status or "生成中"),
            }
        )
        self.object_rail.set_catalogs(self._datasets, self._trained_models)

    def _update_pending_generated_dataset(self, progress: float, stage: str = "") -> None:
        ident = str(self._pending_generated_dataset_id or "").strip()
        if not ident:
            return
        record = next(
            (item for item in self._datasets if str(item.get("id") or "") == ident),
            None,
        )
        if record is None:
            return
        try:
            value = max(0.0, min(1.0, float(progress)))
        except (TypeError, ValueError):
            value = 0.0
        record["progress"] = value
        record["status"] = "生成中"
        if str(stage or "").strip():
            record["stage"] = str(stage).strip()
        if not self.object_rail.update_dataset_progress(ident, value, "生成中"):
            self.object_rail.set_catalogs(self._datasets, self._trained_models)

    def _set_pending_generated_dataset_state(
        self,
        kind: str,
        status: str,
        *,
        error: str = "",
    ) -> None:
        """Settle a transient dataset row without erasing its job history."""
        ident = str(self._pending_generated_dataset_id or "").strip()
        if not ident:
            return
        record = next(
            (item for item in self._datasets if str(item.get("id") or "") == ident),
            None,
        )
        if record is None:
            self._pending_generated_dataset_id = ""
            return
        was_selected = self.object_rail.selected_dataset_id() == ident
        record.update({"kind": kind, "status": status})
        if error:
            record["error"] = str(error)
        self._pending_generated_dataset_id = ""
        if was_selected:
            self.object_rail.set_selected_dataset("")
        self.object_rail.set_catalogs(self._datasets, self._trained_models)
        dataset = self._widgets.get("model:dataset")
        if dataset is not None and dataset.current_dataset_source() == "generated_pending":
            dataset.set_active_dataset("", "")

    def _mark_pending_generated_dataset_cancelling(self) -> None:
        ident = str(self._pending_generated_dataset_id or "").strip()
        record = next(
            (item for item in self._datasets if str(item.get("id") or "") == ident),
            None,
        )
        if record is None:
            return
        record["status"] = "正在取消"
        value = float(record.get("progress") or 0.0)
        if not self.object_rail.update_dataset_progress(ident, value, "正在取消"):
            self.object_rail.set_catalogs(self._datasets, self._trained_models)
            return
        self.object_rail.set_dataset_cancelling(ident, True)

    def _cancel_dataset_generation(self, dataset_id: str) -> None:
        ident = str(dataset_id or "").strip()
        if not ident or ident != str(self._pending_generated_dataset_id or ""):
            return
        error = self._jobs.cancel("dataset")
        if error:
            self.taskRequested.emit(error)
            return
        self._mark_pending_generated_dataset_cancelling()
        self.taskRequested.emit("正在取消数据集生成…")

    def _remove_pending_generated_dataset(self) -> None:
        ident = str(self._pending_generated_dataset_id or "").strip()
        if not ident:
            return
        was_selected = self.object_rail.selected_dataset_id() == ident
        self._datasets = [
            item for item in self._datasets
            if str(item.get("id") or "") != ident
        ]
        self._pending_generated_dataset_id = ""
        if was_selected:
            self.object_rail.set_selected_dataset("")
        self.object_rail.set_catalogs(self._datasets, self._trained_models)

    def _finalize_pending_generated_dataset(
        self,
        dataset_id: str,
        *,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, bool]:
        """Rename the transient rail row in place when the backend returns an ID."""
        ident = str(dataset_id or "").strip()
        if not ident:
            return "", False
        pending_id = str(self._pending_generated_dataset_id or "").strip()
        pending = next(
            (item for item in self._datasets if str(item.get("id") or "") == pending_id),
            None,
        ) if pending_id else None
        was_selected = pending is not None and self.object_rail.selected_dataset_id() == pending_id
        if pending is None:
            name = self._register_generated_dataset(ident, title=title)
            return name, self.object_rail.selected_dataset_id() == ident

        name = str(title or "").strip() or self._next_generated_dataset_name()
        if any(
            item is not pending and str(item.get("title") or "") == name
            for item in self._datasets
        ):
            name = self._next_generated_dataset_name()
        pending.update(
            {
                "id": ident,
                "title": name,
                "kind": "generated",
                "progress": 1.0,
                "status": "已完成",
            }
        )
        if metadata:
            pending.update(dict(metadata))
        self._pending_generated_dataset_id = ""
        self.object_rail.set_catalogs(self._datasets, self._trained_models)
        if was_selected:
            self.object_rail.set_selected_dataset(ident)
        return name, was_selected

    def _register_generated_dataset(
        self, dataset_id: str, *, title: str = "", family: str = "tabular"
    ) -> str:
        """Register a generated dataset with a stable sequential display name."""
        ident = str(dataset_id or "").strip()
        if not ident:
            return ""
        existing = next((item for item in self._datasets if str(item.get("id") or "") == ident), None)
        if existing is not None:
            return str(existing.get("title") or ident)
        name = str(title or "").strip() or self._next_generated_dataset_name()
        if any(item.get("title") == name for item in self._datasets):
            name = self._next_generated_dataset_name()
        self._register_dataset(name, dataset_id=ident, kind="generated")
        record = next((item for item in self._datasets if str(item.get("id") or "") == ident), None)
        if record is not None:
            record["family"] = str(family or "tabular")
        return name

    def _on_registry_models_changed(self, records: list[dict[str, Any]]) -> None:
        """Mirror the authoritative model registry into the workbench rail."""
        normalized: list[dict[str, Any]] = []
        used_numbers: dict[str, set[int]] = {}
        for item in list(records or []):
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("model_id", item.get("id", "")) or "")
            if not model_id:
                continue
            model_type = str(item.get("model_type") or "")
            display_type = self._model_display_type(model_type)
            used = used_numbers.setdefault(display_type, set())
            try:
                number = int(item.get("model_number") or 0)
            except (TypeError, ValueError):
                number = 0
            title = str(item.get("title") or "")
            if number <= 0 and title.startswith(display_type):
                suffix = title[len(display_type):]
                number = int(suffix) if suffix.isdigit() else 0
            if number <= 0 or number in used:
                number = max(used, default=0) + 1
                while number in used:
                    number += 1
            used.add(number)
            record = dict(item)
            record.update(
                {
                    "id": model_id,
                    "title": f"{display_type}{number}",
                    "model_number": number,
                }
            )
            normalized.append(record)
        registry = getattr(self.context, "registry", None)
        if (
            registry is not None
            and not self._normalizing_model_names
            and normalized != list(records or [])
        ):
            self._normalizing_model_names = True
            try:
                registry.set_models(normalized)
            finally:
                self._normalizing_model_names = False
        self._trained_models = normalized
        self._sync_rail_document()

    def _load_registered_models(self) -> None:
        """Load persisted models so prediction is not limited to this session."""
        registry = getattr(self.context, "registry", None)
        api = getattr(self.context, "api_client", None)
        training = getattr(getattr(self.context, "services", None), "training", None)
        if registry is None or api is None or getattr(registry, "models", None):
            return
        list_models = getattr(training, "list_models", None)
        if not callable(list_models):
            return
        self._model_list_key = f"workbench.models.list.{id(self)}"
        if not getattr(self, "_model_list_bound", False):
            api.completed.connect(self._on_model_list_completed)
            self._model_list_bound = True
        list_models(self._model_list_key)

    def _on_model_list_completed(self, key: str, data: object) -> None:
        if str(key) != getattr(self, "_model_list_key", ""):
            return
        records = data.get("models", data.get("items", data)) if isinstance(data, dict) else data
        registry = getattr(self.context, "registry", None)
        if registry is not None:
            registry.set_models([item for item in (records or []) if isinstance(item, dict)])

    def _current_document_kind(self) -> str:
        workspace = self._workspaces.get(self.module)
        if workspace is None:
            return ""
        pane = workspace._active_pane or (workspace.panes[0] if workspace.panes else None)
        if pane is None:
            return ""
        spec = pane.spec_for_index(pane.currentIndex())
        return spec.kind if spec is not None else ""

    def _sync_rail_document(self) -> None:
        opt = self._widgets.get("optimization:opt_vars")
        opt_setter = getattr(opt, "set_trained_models", None)
        if callable(opt_setter):
            opt_setter(self._trained_models)
        self.object_rail.set_shap_scores(self._shap_scores)
        if self.module not in {"model", "explainability"}:
            return
        if self.module == "model":
            widget = self._widgets.get("model:dataset")
            family = widget.current_family() if widget is not None and hasattr(widget, "current_family") else "tabular"
            self.object_rail.set_dataset_family(family)
        self.object_rail.set_catalogs(self._datasets, self._trained_models)
        self.object_rail.set_document_kind(self._current_document_kind())
        predict = self._widgets.get("model:predict") or self._widgets.get("model:predict_eval")
        setter = getattr(predict, "set_trained_models", None)
        if callable(setter):
            setter(self._trained_models)
        filler = getattr(predict, "_fill_predict_inputs", None)
        if callable(filler):
            filler()
        for kind in ("global_contrib", "param_trend", "current_system"):
            explain = self._widgets.get(f"explainability:{kind}")
            explain_setter = getattr(explain, "set_trained_models", None)
            if callable(explain_setter):
                explain_setter(self._trained_models)

    def _detector_overlay_changed(self) -> None:
        result = getattr(self.context.project, "formal_result", None)
        if not isinstance(result, dict) or not result:
            return
        for kind in ("ray_layout", "layout_3d"):
            widget = self._widgets.get(f"simulation:{kind}")
            changed = getattr(widget, "_result_changed", None)
            if callable(changed):
                changed(result)

    def collect_simulation_state(self) -> SimulationFormState:
        source = (
            self.object_rail.source_inspector.form_state()
            if self.object_rail.source_inspector is not None
            else SourceFormState(wavelength_nm=float(self.context.project.project.wavelength_nm))
        )
        receiver = (
            self.object_rail.fiber_inspector.form_state()
            if self.object_rail.fiber_inspector is not None
            else ReceiverFormState(mode_field_diameter_x_um=float(self.context.project.project.receiver_mfd_um))
        )
        system = self._system_state
        if self.object_rail.field_inspector is not None:
            field_x, field_y = self.object_rail.field_inspector.field_angles()
            source = replace(source, field_x_deg=field_x, field_y_deg=field_y)
        if self.object_rail.environment_inspector is not None:
            system = replace(system, **self.object_rail.environment_inspector.system_patch())
        system = replace(
            system,
            pupil_radius_mm=float(self.context.project.project.pupil_radius_mm),
            field_x_deg=source.field_x_deg,
            field_y_deg=source.field_y_deg,
        )
        calculation = self._calculation_state
        analyses = list(calculation.analyses)
        if self._alignment_state.enabled and "fiber_alignment" not in analyses:
            analyses.append("fiber_alignment")
        if system.auto_best_focus and "focus_search" not in analyses:
            analyses.append("focus_search")
        if analyses != list(calculation.analyses):
            calculation = replace(calculation, analyses=tuple(analyses))
        return SimulationFormState(
            source=source,
            receiver=receiver,
            system=system,
            calculation=calculation,
            alignment=self._alignment_state,
        )

    def _refresh_current_documents(self) -> None:
        for widget in self._widgets.values():
            refresh = getattr(widget, "refresh", None)
            if callable(refresh):
                refresh()
            if getattr(widget, "kind", "") in {"ray_layout", "layout_3d", "spot", "coupling", "wavefront"}:
                mark_stale = getattr(widget, "mark_stale", None)
                if callable(mark_stale):
                    mark_stale()

    def _project_state_changed(self, _project: object) -> None:
        self._explain_current.clear()
        self._refresh_current_documents()

    def run_formal_calculation(self) -> None:
        try:
            state = self.collect_simulation_state()
        except ValueError as exc:
            self.taskRequested.emit(str(exc))
            return
        # Teaching can only reproduce a formal result when it receives both
        # the optical prescription and the numerical settings that produced
        # it.  Keep this compact contract on the shared project context rather
        # than letting the teaching module recreate a different default.
        project_payload = serialize_project(self.context.project.project, state)
        project_payload["calculation_contract"] = {
            "precision": str(state.calculation.precision),
            "options": state.request_options(),
        }
        self.context.project.set_simulation_project_payload(project_payload)
        self._simulation_controller.submit(self.context.project.project, state, visible_views=FORMAL_RESULT_VIEWS)
        self.open_document("simulation", "coupling")

    def _verify_applied_candidate(self, variables: object, label: str, baseline: object) -> None:
        try:
            before = float(baseline) if baseline is not None else None
        except (TypeError, ValueError):
            before = None
        self._pending_candidate_validation = {
            "label": str(label or "候选方案"),
            "variables": dict(variables or {}) if isinstance(variables, dict) else {},
            "before": before,
        }
        # A changed optical prescription invalidates every cached local explanation.
        # Dataset-level global SHAP remains valid for the immutable trained model.
        self._explain_current.clear()
        self.run_formal_calculation()

    def _formal_status(self, status: str, _progress: float, note: str) -> None:
        if status in {"submitting", "cached"} or str(note).startswith("正式计算失败"):
            self.taskRequested.emit(str(note or status))

    def _formal_result_ready(self, body: object, submitted_project: object) -> None:
        payload = dict(body or {}) if isinstance(body, dict) else {}
        metrics = dict(payload.get("metrics") or {})
        self.context.project.set_formal_result(payload, metrics=metrics)
        pending = self._pending_candidate_validation
        if pending is not None:
            after = _coupling_efficiency_from_result(payload)
            before = pending.get("before")
            result_document = self._widgets.get("optimization:opt_result")
            complete = getattr(result_document, "complete_candidate_validation", None)
            if callable(complete):
                complete(str(pending.get("label") or "候选方案"), before, after)
            recorder = getattr(self.context.project, "record_research_event", None)
            if callable(recorder):
                recorder(
                    "optimization_validation",
                    "优化候选正式验证",
                    {
                        "label": pending.get("label"),
                        "variables": pending.get("variables"),
                        "before_coupling_efficiency": before,
                        "after_coupling_efficiency": after,
                        "improvement": (
                            float(after) - float(before)
                            if before is not None and after is not None
                            else None
                        ),
                    },
                    source="应用方案→正式仿真",
                    dedupe_key="optimization_validation",
                )
            self._pending_candidate_validation = None
        for kind in ("ray_layout", "layout_3d", "spot", "coupling", "wavefront"):
            identifier = f"simulation:{kind}"
            widget = self._widgets.get(identifier) or self._widgets.get(f"analysis:{kind}")
            if widget is not None:
                callback = getattr(widget, "_result_changed", None)
                if callable(callback):
                    callback(payload)

    def _formal_failed(self, _kind: str, message: str) -> None:
        pending = self._pending_candidate_validation
        if pending is not None:
            result_document = self._widgets.get("optimization:opt_result")
            complete = getattr(result_document, "complete_candidate_validation", None)
            if callable(complete):
                complete(
                    str(pending.get("label") or "候选方案"),
                    pending.get("before"),
                    None,
                    error=str(message),
                )
            self._pending_candidate_validation = None
        self.taskRequested.emit(f"正式计算失败：{message}")

    def start_optimization(self) -> None:
        opt = self._widgets.get("optimization:opt_vars")
        if not self._selected_optimization:
            self.open_document("optimization", "opt_result")
            widget = self._widgets.get("optimization:opt_result")
            starter = getattr(widget, "show_progress_started", None)
            if callable(starter):
                starter("光学仿真", "未勾选变量")
            self.taskRequested.emit("请先在左栏勾选优化变量。")
            return
        goal = getattr(opt, "goal", None)
        surrogate = goal is not None and getattr(goal, "evaluation_mode", lambda: "formal")() == "surrogate"
        model_record = goal.predict_model.currentData() if goal is not None else None
        if surrogate and (not isinstance(model_record, dict) or not model_record.get("id")):
            self.open_document("optimization", "opt_result")
            widget = self._widgets.get("optimization:opt_result")
            starter = getattr(widget, "show_progress_started", None)
            if callable(starter):
                starter("已训练模型", "未选择模型")
            self.taskRequested.emit("请先训练并选择模型。")
            return
        variables = self._opt_variables_from_table()
        if not variables:
            self.open_document("optimization", "opt_result")
            self.taskRequested.emit("请先在左栏勾选优化变量。")
            return
        state = self.collect_simulation_state()
        objective_label = str(goal.goal.currentText() if goal is not None else "最大化耦合效率")
        objective_metrics = {
            "最小化 RMS 光斑": ["rms_spot_radius_um"],
            "多目标加权": ["coupling_efficiency", "rms_spot_radius_um"],
        }.get(objective_label, ["coupling_efficiency"])
        required_analyses = set(analyses_for_metrics(objective_metrics))
        existing_analyses = set(state.calculation.analyses)
        if not required_analyses.issubset(existing_analyses):
            state = replace(
                state,
                calculation=replace(
                    state.calculation,
                    analyses=tuple(sorted(existing_analyses | required_analyses)),
                ),
            )
        payload = restrict_payload(build_simulation_payload(self.context.project.project, state), ("coupling",))
        # Optimisation must keep every analysis required by the selected merit,
        # not merely coupling.  Otherwise RMS and multi-objective modes compare
        # missing values and look like successful searches.
        payload = restrict_payload(payload, tuple(sorted(set(payload.get("analyses") or ()) | required_analyses)))
        config = {
            "algorithm": "智能全局搜索",
            "objective": objective_label,
            "evaluation_plane": str(goal.evaluation.currentText() if goal is not None else "光纤模场"),
            "max_iterations": int(getattr(opt, "max_evaluations", None).value()) if opt is not None and getattr(opt, "max_evaluations", None) is not None else 300,
            "param_path": variables[0]["path"],
            "param_label": variables[0]["label"],
            "lower": variables[0]["lower_bound"],
            "upper": variables[0]["upper_bound"],
            "initial": variables[0]["initial_value"],
            "max_system_length_mm": float(goal.max_length.value()) if goal is not None else None,
            "min_center_thickness_mm": float(goal.min_center.value()) if goal is not None else None,
            "min_air_gap_mm": float(goal.min_air.value()) if goal is not None else None,
            "aperture_within_mechanical": bool(goal.aperture_limit.isChecked()) if goal is not None else False,
        }
        if goal is not None and goal.collimation.isChecked():
            config.update({
                "collimation_enabled": True,
                "collimation_surface": goal.collimation_surface.currentData(),
                "collimation_span": float(goal.collimation_span.value()),
                "collimation_radius_change": float(goal.collimation_radius.value()),
                "collimation_curvature": float(goal.collimation_curvature.value()),
                "collimation_centroid_drift": float(goal.collimation_centroid.value()),
                "collimation_axis_tilt": float(goal.collimation_tilt.value()),
            })
        kind = "optimize"
        _augment_payload(payload, "optimize", config)
        payload["opt_variables"] = variables
        payload.pop("validation_options", None)
        if surrogate and isinstance(model_record, dict):
            payload.setdefault("opt_options", {})["mode"] = "ml_inverse_prediction"
            payload["opt_options"]["surrogate_model_id"] = str(model_record.get("id") or "")
            payload["opt_options"]["coarse_fraction"] = 0.88
        path = f"已训练模型 {model_record.get('title')}" if surrogate and isinstance(model_record, dict) else "光学仿真"
        selected = "、".join(
            _display_variable(row)
            for row in _variable_rows(self.context.project.project)
            if row[0] in self._selected_optimization
        ) or "未勾选变量"
        self.open_document("optimization", "opt_result")
        widget = self._widgets.get("optimization:opt_result")
        starter = getattr(widget, "show_progress_started", None)
        if callable(starter):
            starter(path, selected)
        error = self._jobs.submit("optimize", payload)
        if error:
            handler = getattr(widget, "show_opt_failed", None)
            if callable(handler):
                handler(error)
            if widget is not None:
                widget.workspace.set_result(0, "过程曲线", {"kind": "empty", "message": error})
            self.taskRequested.emit(error)
            return
        if opt is not None and getattr(opt, "start_button", None) is not None:
            opt.start_button.setEnabled(False)

    def _start_scan(self) -> None:
        scan = self._widgets.get("optimization:scan")
        if scan is None:
            return
        ranges = scan.scan_ranges()
        if not ranges:
            scan.show_scan_status("请先在左栏勾选 1～2 个变量。")
            return
        mode_label = str(scan.mode.currentText() or "一维扫描")
        if mode_label == "二维扫描" and len(ranges) != 2:
            scan.show_scan_status("二维扫描需要在左栏勾选两个变量。")
            return
        if mode_label == "一维扫描" and len(ranges) != 1:
            scan.show_scan_status("一维扫描只能勾选一个变量；如需两个变量请切换到二维扫描。")
            return
        for _path, low, high in ranges:
            if not math.isfinite(low) or not math.isfinite(high) or low >= high:
                scan.show_scan_status("扫描范围必须是有限数值，且最小值小于最大值。")
                return
        labels = {
            row[0]: _display_variable(row)
            for row in _variable_rows(self.context.project.project)
        }
        first_path, first_low, first_high = ranges[0]
        config = {
            "scan_mode": mode_label,
            "response": str(scan.response.currentText() or "耦合效率"),
            "scale": str(scan.scale.currentText() or "线性采样"),
            "param_path": first_path,
            "param_label": labels.get(first_path, first_path),
            "start": first_low,
            "stop": first_high,
            "points": int(scan.points.value()),
        }
        if len(ranges) > 1:
            second_path, second_low, second_high = ranges[1]
            config.update({
                "param_path2": second_path,
                "param_label2": labels.get(second_path, second_path),
                "start2": second_low,
                "stop2": second_high,
                "points2": int(scan.points.value()),
            })
        response_key = {
            "耦合效率": "coupling_efficiency",
            "RMS 光斑": "rms_spot_radius_um",
            "Strehl": "strehl_estimate_marechal",
            "边缘功率": "edge_power",
        }.get(str(scan.response.currentText() or "耦合效率"), "coupling_efficiency")
        state = self.collect_simulation_state()
        required_analyses = set(analyses_for_metrics([response_key]))
        existing_analyses = set(state.calculation.analyses)
        if not required_analyses.issubset(existing_analyses):
            state = replace(
                state,
                calculation=replace(state.calculation, analyses=tuple(sorted(existing_analyses | required_analyses))),
            )
        payload = restrict_payload(
            build_simulation_payload(self.context.project.project, state),
            tuple(sorted(required_analyses)),
        )
        _augment_payload(payload, "scan", config)
        scan.show_scan_status("正在扫描…")
        if getattr(scan, "run_button", None) is not None:
            scan.run_button.setEnabled(False)
        error = self._jobs.submit("scan", payload)
        if error:
            handler = getattr(scan, "show_scan_failed", None)
            if callable(handler):
                handler(error)
            scan.show_scan_status(error)
            scan.run_button.setEnabled(bool(ranges))
            self.taskRequested.emit(error)

    def _opt_variables_from_table(self) -> list[dict[str, Any]]:
        opt = self._widgets.get("optimization:opt_vars")
        table = getattr(opt, "table", None) if opt is not None else None
        if table is None:
            return []
        variables: list[dict[str, Any]] = []
        for row in range(table.rowCount()):
            key_item = table.item(row, 0)
            key = str(key_item.data(Qt.ItemDataRole.UserRole) or "") if key_item is not None else ""
            if not key:
                continue
            compact_table = table.columnCount() == 4
            current_column = 1 if compact_table else 3
            lower_column = 2 if compact_table else 4
            upper_column = 3 if compact_table else 5
            try:
                current = float(table.item(row, current_column).text()) if table.item(row, current_column) is not None else 0.0
                low = float(table.item(row, lower_column).text()) if table.item(row, lower_column) is not None else current
                high = float(table.item(row, upper_column).text()) if table.item(row, upper_column) is not None else current
            except (TypeError, ValueError):
                continue
            label = str(table.item(row, 0).text()) if table.item(row, 0) is not None else key
            variables.append({
                "path": key,
                "label": label,
                "unit": "mm",
                "lower_bound": low,
                "upper_bound": high,
                "initial_value": current,
                "enabled": True,
            })
        return variables

    def _on_workbench_job_submitted(self, kind: str, job_id: str) -> None:
        note = f"{_job_title(kind)}已提交"
        if kind in {"train", "joint_train", "bilstm"}:
            widget = self._widgets.get("model:train_result")
            handler = getattr(widget, "show_train_progress", None)
            if callable(handler):
                handler(0.0, note)
        elif kind == "scan":
            scan = self._widgets.get("optimization:scan")
            handler = getattr(scan, "show_scan_progress", None)
            if callable(handler):
                handler(0.0, note)
        elif kind == "optimize":
            widget = self._widgets.get("optimization:opt_result")
            handler = getattr(widget, "show_opt_progress", None)
            if callable(handler):
                handler(0.0, note)
        self.taskRequested.emit(f"{_job_title(kind)}已提交")

    def _on_workbench_job_progress(self, kind: str, progress: float, stage: str) -> None:
        if kind in {"train", "joint_train", "bilstm"}:
            widget = self._widgets.get("model:train_result")
            handler = getattr(widget, "show_train_progress", None)
            if callable(handler):
                handler(progress, stage or "训练中")
        elif kind == "scan":
            scan = self._widgets.get("optimization:scan")
            handler = getattr(scan, "show_scan_progress", None)
            if callable(handler):
                handler(progress, stage or "扫描中")
        elif kind == "optimize":
            widget = self._widgets.get("optimization:opt_result")
            handler = getattr(widget, "show_opt_progress", None)
            if callable(handler):
                handler(progress, stage or "优化中")
        note = f"{_job_title(kind)} {progress:.0%}"
        if kind == "dataset":
            self._update_pending_generated_dataset(progress, stage)
        elif kind in {"train", "joint_train", "bilstm"}:
            widget = self._widgets.get("model:train_result")
            status = getattr(widget, "show_train_status", None)
            if not callable(handler) and callable(status):
                status(note)
        elif kind == "scan":
            scan = self._widgets.get("optimization:scan")
            if scan is not None:
                if not callable(handler):
                    scan.show_scan_status(note)
        elif kind == "optimize":
            widget = self._widgets.get("optimization:opt_result")
            if widget is not None:
                if callable(handler):
                    return
                widget.workspace.set_result(0, "过程曲线", {"kind": "empty", "message": note})

    def _on_workbench_job_finished(self, kind: str, result: object) -> None:
        """Commit a completed job without allowing result-shape errors to hang the UI."""
        try:
            self._on_workbench_job_finished_impl(kind, result)
        except Exception as exc:
            self._on_workbench_job_failed(
                kind,
                f"任务已完成，但结果处理失败：{type(exc).__name__}: {exc}",
            )

    def _on_workbench_job_finished_impl(self, kind: str, result: object) -> None:
        body = dict(result or {}) if isinstance(result, dict) else {}
        if kind in {"train", "joint_train", "bilstm"}:
            widget = self._widgets.get("model:train_result")
            handler = getattr(widget, "show_train_progress", None)
            if callable(handler):
                handler(1.0, "训练完成", state="complete")
        elif kind == "scan":
            scan = self._widgets.get("optimization:scan")
            handler = getattr(scan, "show_scan_progress", None)
            if callable(handler):
                handler(1.0, "扫描完成", state="complete")
        elif kind == "optimize":
            widget = self._widgets.get("optimization:opt_result")
            handler = getattr(widget, "show_opt_progress", None)
            if callable(handler):
                handler(1.0, "优化完成", state="complete")
        if kind == "dataset":
            dataset = self._widgets.get("model:dataset")
            dataset_id = str(body.get("dataset_id") or body.get("training_dataset_id") or "")
            metadata_raw = body.get("metadata") or {}
            metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
            sequence_config = (
                dict(metadata)
                if str(metadata.get("dataset_layout") or "") == "sequence_long"
                else {}
            )
            family = "sequence" if sequence_config else "tabular"
            self._last_dataset_id = dataset_id
            generated_name = ""
            selected_generated = False
            if dataset_id:
                generated_name, selected_generated = self._finalize_pending_generated_dataset(
                    dataset_id,
                    title=self._pending_generated_dataset_name,
                    metadata=sequence_config,
                )
            else:
                self._remove_pending_generated_dataset()
            self._pending_generated_dataset_name = ""
            if dataset is not None:
                dataset.set_job_busy(False)
            if dataset_id and selected_generated:
                if dataset is not None:
                    # Make the freshly generated dataset the explicit current
                    # choice. The packaged demo must not silently win over a
                    # dataset the user has just generated.
                    if family == "tabular":
                        for index in range(dataset.builtin.count() - 1, -1, -1):
                            if str(dataset.builtin.itemData(index) or "") == dataset_id:
                                dataset.builtin.removeItem(index)
                        dataset.builtin.insertItem(0, generated_name or "数据集", dataset_id)
                        dataset.builtin.setCurrentIndex(0)
                    else:
                        dataset.register_generated_sequence_dataset(dataset_id, sequence_config)
                    dataset.set_active_dataset(dataset_id, "generated")
            registry = getattr(self.context, "registry", None)
            if registry is not None and dataset_id:
                registry.merge_dataset({
                    "dataset_id": dataset_id, "id": dataset_id,
                    "name": generated_name or dataset_id, "family": family,
                    **sequence_config,
                })
                registry.set_current_dataset(dataset_id)
            return
        if kind == "joint_train":
            dataset = self._widgets.get("model:dataset")
            if dataset is not None:
                dataset.set_job_busy(False)
            for key, label in (("random_forest", "随机森林"), ("xgboost", "XGBoost物理残差")):
                child = body.get(key)
                if not isinstance(child, dict):
                    continue
                if dataset is not None:
                    dataset.model_type.setCurrentText(label)
                self._on_workbench_job_finished_impl("train", child)
            widget = self._widgets.get("model:train_result")
            marker = getattr(widget, "mark_joint_trained", None)
            if callable(marker):
                marker(body)
            return
        if kind in {"train", "bilstm"}:
            dataset = self._widgets.get("model:dataset")
            if dataset is not None:
                dataset.set_job_busy(False)
            model_id = str(body.get("model_id") or "")
            name = dataset.model_type.currentText() if dataset is not None else "模型"
            target = (
                str(dataset.sequence_target.text() or "coupling_efficiency")
                if dataset is not None and dataset.current_family() == "sequence"
                else str(dataset.target.currentText() if dataset is not None else "耦合损耗(dB)")
            )
            if model_id:
                model_title, model_number = self._next_model_name(name)
                metadata_raw = body.get("metadata") or {}
                metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
                result_targets = list(body.get("target_names") or metadata.get("target_names") or [])
                if result_targets:
                    target = str(result_targets[0])
                feature_paths = list(
                    body.get("feature_paths")
                    or metadata.get("feature_paths")
                    or []
                )
                feature_units_raw = body.get("feature_units")
                if feature_units_raw is None:
                    feature_units_raw = metadata.get("feature_units")
                record = {
                    "id": model_id,
                    "title": model_title,
                    "model_number": model_number,
                    "model_type": name,
                    "target": target,
                    "family": dataset.current_family() if dataset is not None else "tabular",
                    "dataset_id": str(body.get("dataset_id") or self._last_dataset_id),
                    "feature_paths": feature_paths,
                    "numeric_feature_names": list(
                        body.get("numeric_feature_names")
                        or metadata.get("numeric_feature_names")
                        or []
                    ),
                    "feature_units": _coerce_feature_units(feature_units_raw, feature_paths),
                    "design_variable_paths": list(body.get("design_variable_paths") or metadata.get("design_variable_paths") or []),
                    "physics_feature_paths": list(body.get("physics_feature_paths") or metadata.get("physics_feature_paths") or []),
                    "variable_scheme_id": str(body.get("variable_scheme_id") or metadata.get("variable_scheme_id") or ""),
                    "target_names": result_targets,
                    "validation_metrics": dict(body.get("validation_metrics") or {}),
                    "test_metrics": dict(body.get("test_metrics") or {}),
                    "evaluation": dict(
                        body.get("evaluation")
                        or metadata.get("evaluation")
                        or {}
                    ),
                    "training_history": dict(
                        body.get("training_history")
                        or metadata.get("training_history")
                        or {}
                    ),
                    "oob_error_curve": list(
                        body.get("oob_error_curve")
                        or metadata.get("oob_error_curve")
                        or []
                    ),
                    "training_summary": dict(body.get("training_summary") or metadata.get("training_summary") or {}),
                    "training_curve_status": str(body.get("training_curve_status") or metadata.get("training_curve_status") or "unavailable"),
                    "training_curve_label": str(body.get("training_curve_label") or metadata.get("training_curve_label") or ""),
                    "training_curve_description": str(body.get("training_curve_description") or metadata.get("training_curve_description") or ""),
                    "model_quality": dict(body.get("model_quality") or metadata.get("model_quality") or {}),
                }
                self._trained_models.append(record)
                registry = getattr(self.context, "registry", None)
                if registry is not None:
                    registry.merge_model({"model_id": model_id, **record})
                    setter = getattr(registry, "set_recent_model", None)
                    if callable(setter):
                        setter(model_id)
                self._sync_rail_document()
                self.object_rail.set_selected_model(model_id)
            self.open_document("model", "train_result")
            widget = self._widgets.get("model:train_result")
            marker = getattr(widget, "mark_trained", None)
            if callable(marker):
                marker(body)
            if model_id and shap_supported(name) and name != "XGBoost物理残差":
                self._request_train_shap(model_id)
            return
        if kind == "scan":
            scan = self._widgets.get("optimization:scan")
            if scan is not None:
                if getattr(scan, "run_button", None) is not None:
                    scan.run_button.setEnabled(bool(scan.selected))
                scan.apply_scan_result(body, str(scan.response.currentText() or "耦合效率"))
            return
        if kind == "optimize":
            opt = self._widgets.get("optimization:opt_vars")
            if opt is not None and getattr(opt, "start_button", None) is not None:
                opt.start_button.setEnabled(bool(self._selected_optimization))
            self.open_document("optimization", "opt_result")
            widget = self._widgets.get("optimization:opt_result")
            apply = getattr(widget, "apply_opt_result", None)
            if callable(apply):
                apply(body)

    def _on_workbench_job_failed(self, kind: str, message: str) -> None:
        text = str(message or "任务失败")
        if kind in {"train", "joint_train", "bilstm"}:
            widget = self._widgets.get("model:train_result")
            handler = getattr(widget, "show_train_failed", None)
            if callable(handler):
                handler(text)
        elif kind == "scan":
            scan = self._widgets.get("optimization:scan")
            handler = getattr(scan, "show_scan_failed", None)
            if callable(handler):
                handler(text)
        elif kind == "optimize":
            widget = self._widgets.get("optimization:opt_result")
            handler = getattr(widget, "show_opt_failed", None)
            if callable(handler):
                handler(text)
        if kind == "dataset":
            self._set_pending_generated_dataset_state(
                "generated_failed",
                "生成失败",
                error=text,
            )
            self._pending_generated_dataset_name = ""
            dataset = self._widgets.get("model:dataset")
            if dataset is not None:
                dataset.set_job_busy(False)
        elif kind in {"train", "joint_train", "bilstm"}:
            dataset = self._widgets.get("model:dataset")
            if dataset is not None:
                dataset.set_job_busy(False)
            widget = self._widgets.get("model:train_result")
            status = getattr(widget, "show_train_status", None)
            if callable(status):
                status(text)
        elif kind == "scan":
            scan = self._widgets.get("optimization:scan")
            if scan is not None:
                if getattr(scan, "run_button", None) is not None:
                    scan.run_button.setEnabled(bool(scan.selected))
                scan.show_scan_status(text)
        elif kind == "optimize":
            opt = self._widgets.get("optimization:opt_vars")
            if opt is not None and getattr(opt, "start_button", None) is not None:
                opt.start_button.setEnabled(bool(self._selected_optimization))
            widget = self._widgets.get("optimization:opt_result")
            if widget is not None:
                widget.workspace.set_result(0, "过程曲线", {"kind": "empty", "message": text})
        self.taskRequested.emit(text)

    def _on_workbench_job_cancelled(self, kind: str) -> None:
        if kind != "dataset":
            if kind in {"train", "joint_train", "bilstm"}:
                widget = self._widgets.get("model:train_result")
                handler = getattr(widget, "show_train_cancelled", None)
                if callable(handler):
                    handler()
                dataset = self._widgets.get("model:dataset")
                if dataset is not None:
                    dataset.set_job_busy(False)
            elif kind == "scan":
                scan = self._widgets.get("optimization:scan")
                handler = getattr(scan, "show_scan_cancelled", None)
                if callable(handler):
                    handler()
                if scan is not None and getattr(scan, "run_button", None) is not None:
                    scan.run_button.setEnabled(bool(scan.selected))
            elif kind == "optimize":
                widget = self._widgets.get("optimization:opt_result")
                handler = getattr(widget, "show_opt_cancelled", None)
                if callable(handler):
                    handler()
                opt = self._widgets.get("optimization:opt_vars")
                if opt is not None and getattr(opt, "start_button", None) is not None:
                    opt.start_button.setEnabled(bool(self._selected_optimization))
            self.taskRequested.emit(f"{_job_title(kind)}已取消")
            return
        self._set_pending_generated_dataset_state("generated_cancelled", "已取消")
        self._pending_generated_dataset_name = ""
        dataset = self._widgets.get("model:dataset")
        if dataset is not None:
            dataset.set_job_busy(False)
        self.taskRequested.emit("数据集生成已取消")

    def _on_workbench_job_cancellation_failed(self, kind: str, message: str) -> None:
        if kind == "dataset":
            ident = str(self._pending_generated_dataset_id or "").strip()
            record = next(
                (item for item in self._datasets if str(item.get("id") or "") == ident),
                None,
            )
            if record is not None:
                record["status"] = "生成中"
                value = float(record.get("progress") or 0.0)
                if not self.object_rail.update_dataset_progress(ident, value, "生成中"):
                    self.object_rail.set_catalogs(self._datasets, self._trained_models)
                else:
                    self.object_rail.set_dataset_cancelling(ident, False)
        self.taskRequested.emit(str(message or "取消任务失败"))

    def _request_train_shap(self, model_id: str) -> None:
        from uuid import uuid4

        from frontend_pyside.infrastructure.api.clients import TrainingClient

        api = getattr(self.context, "api_client", None)
        if api is None or not model_id:
            return
        self._train_shap_token = f"workbench.train.shap.{uuid4().hex[:8]}"
        if not getattr(self, "_train_shap_bound", False):
            api.completed.connect(self._on_train_shap_completed)
            api.failed.connect(self._on_train_shap_failed)
            self._train_shap_bound = True
        TrainingClient(api).explain_shap(
            self._train_shap_token,
            model_id,
            {"top_k": 8, "max_samples": 80, "background_sample_count": 80},
        )

    def _on_train_shap_completed(self, key: str, data: object) -> None:
        if str(key) != getattr(self, "_train_shap_token", ""):
            return
        body = dict(data or {}) if isinstance(data, dict) else {}
        if isinstance(body.get("result"), dict) and not body.get("top_features"):
            body = dict(body.get("result") or {})
        model_id = str(body.get("model_id") or "")
        if model_id:
            self._explain_dataset[model_id] = body
        items = list(body.get("top_features") or body.get("feature_contributions") or [])
        keys = [row[0] for row in _variable_rows(self.context.project.project)]
        self._set_shap_ranks(_variable_shap_scores(items, keys))

    def _on_train_shap_failed(self, key: str, message: str) -> None:
        if str(key) != getattr(self, "_train_shap_token", ""):
            return
        text = explain_shap_failure(message)
        self._train_shap_error = text
        self.taskRequested.emit(f"训练完成，但自动 SHAP 失败：{text}")




# Import after the shell classes have been defined.  Entry modules use the
# shared shell helpers during this compatibility-preserving extraction, and
# this order keeps direct imports of the old public names working without a
# partially initialized circular import.
from frontend_pyside.modules.simulation.documents import (
    CombinedSettingsDialog,
    EmptyDocument,
    EngineeringDialog,
    LensDataDocument,
    ResultDocument,
    SchematicDocument,
    SettingsDocument,
)
from frontend_pyside.modules.simulation.materials import MaterialsTab
from frontend_pyside.modules.simulation.fiber_coupling import FiberCouplingTab
from frontend_pyside.modules.simulation.image_quality import ImageQualityTab
from frontend_pyside.modules.simulation.layout import LayoutTab
from frontend_pyside.modules.simulation.wave_diffraction import WaveDiffractionTab
from frontend_pyside.modules.explainability.documents import AnalysisTextDocument
from frontend_pyside.modules.explainability.current_system import CurrentSystemTab
from frontend_pyside.modules.explainability.global_contrib import GlobalContributionTab
from frontend_pyside.modules.explainability.param_trend import ParameterTrendTab
from frontend_pyside.modules.model.documents import ModelDocument
from frontend_pyside.modules.model.dataset import DatasetTab
from frontend_pyside.modules.model.prediction import PredictionTab
from frontend_pyside.modules.model.training_result import TrainingResultTab
from frontend_pyside.modules.optimization.documents import OptimizationDocument
from frontend_pyside.modules.optimization.goal import OptimizationGoalInspector
from frontend_pyside.modules.optimization.result import OptimizationResultTab
from frontend_pyside.modules.optimization.scan import ScanTab
from frontend_pyside.modules.optimization.variables import VariablesTab
from frontend_pyside.modules.home.shell import WorkflowConnector, WorkflowHome, WorkflowNodeButton
from frontend_pyside.modules.teaching.shell import (
    KindDragButton,
    TeachingAnalysisVisual,
    TeachingEquipmentPopup,
    TeachingImagingCouplingPopup,
    TeachingShell,
)


__all__ = [
    "KIND_TITLES",
    "PRIMARY_MODULES",
    "SECONDARY_ITEMS",
    "DocumentWorkspace",
    "ObjectRail",
    "PrimaryBar",
    "SecondaryBar",
    "TabSpec",
    "TeachingImagingCouplingPopup",
    "TeachingShell",
    "WorkflowHome",
    "WorkbenchShell",
]

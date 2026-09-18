"""光学工作台入口模块的共享定义。

本模块包含各文档实现所共享的入口元数据与无状态 UI 辅助函数。它刻意不导入应用外壳，因此依赖方向保持为应用外壳 -> 模块 -> 共享。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from math import radians
from typing import Any, Callable

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
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
    QRadioButton,
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
    shap_beeswarm_payload,
    shap_dependence_item,
    shap_supported,
    target_backend_name,
    train_chart_payload,
    train_chart_unavailable_message,
    training_test_metrics,
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
from frontend_pyside.shared.icons import icon


def _kind_titles(module: str, kind: str) -> tuple[str, str]:
    """Resolve page titles lazily to keep the shared module acyclic."""
    from frontend_pyside.modules.navigation import kind_titles

    return kind_titles(module, kind)


def _plot_surface_z(payload: dict[str, Any], index: int | None = None) -> float:
    surfaces = [item for item in payload.get("surfaces") or [] if isinstance(item, dict)]
    if not surfaces:
        return 0.0
    if index is None:
        return float(surfaces[-1].get("z", 0.0) or 0.0)
    wanted = int(index)
    for item in surfaces:
        try:
            if int(item.get("surface_index", -1)) == wanted:
                return float(item.get("z", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
    if 0 <= wanted < len(surfaces):
        return float(surfaces[wanted].get("z", 0.0) or 0.0)
    return float(surfaces[-1].get("z", 0.0) or 0.0)


def _workbench_from(widget: QWidget) -> QWidget | None:
    current = widget
    while current is not None:
        if current.objectName() == "WorkbenchShell" or hasattr(current, "object_rail"):
            return current
        current = current.parent()
    return None


def _user_detector_object(widget: QWidget, payload: dict[str, Any]) -> dict[str, Any] | None:
    shell = _workbench_from(widget)
    inspector = getattr(getattr(shell, "object_rail", None), "detector_inspector", None)
    if inspector is None:
        return None
    observation = inspector.observation()
    if not observation.get("enabled"):
        return None
    mode = str(observation.get("mode") or "surface")
    surfaces = [item for item in payload.get("surfaces") or [] if isinstance(item, dict)]
    if mode == "custom":
        z = _plot_surface_z(payload, None) + float(observation.get("offset_mm") or 0.0)
    elif mode == "fiber":
        z = _plot_surface_z(payload, None)
        for item in payload.get("objects") or []:
            if isinstance(item, dict) and str(item.get("kind", "")) == "fiber":
                z = float(item.get("z", z) or z)
                break
    else:
        z = _plot_surface_z(payload, int(observation.get("surface_index") or 0))
    if mode == "fiber":
        fiber = getattr(getattr(shell, "object_rail", None), "fiber_inspector", None)
        radius = 0.01
        if fiber is not None:
            radius = max(float(fiber.mfd.value()) / 2000.0, 1e-4)
        return {
            "kind": "fiber",
            "name": "探测器",
            "z": z,
            "center_x": 0.0,
            "center_y": 0.0,
            "radius": radius,
            "width": 0.0,
            "height": 0.0,
            "metadata": {"user_detector": True, "mode": "fiber"},
        }
    width = float(observation.get("pixels_x") or 0) * float(observation.get("pitch_um") or 0.0) / 1000.0
    height = float(observation.get("pixels_y") or 0) * float(observation.get("pitch_um") or 0.0) / 1000.0
    if width <= 0.0:
        width = max((float(surfaces[-1].get("aperture", 0.0) or 0.0) * 2.0) if surfaces else 1.0, 0.2)
    if height <= 0.0:
        height = width
    return {
        "kind": "detector",
        "name": "探测器",
        "z": z,
        "center_x": 0.0,
        "center_y": 0.0,
        "radius": 0.0,
        "width": width,
        "height": height,
        "metadata": {"user_detector": True, "mode": mode},
    }


def _variable_rows(project) -> list[tuple[str, str, str, str]]:
    """Return (key, group, face, parameter) rows for filters and the variable table."""
    rows: list[tuple[str, str, str, str]] = []
    surfaces = list(getattr(project, "surfaces", ()) or ())
    for index, surface in enumerate(surfaces):
        group = str(getattr(surface, "group_id", "") or getattr(surface, "name", "") or f"S{index + 1}")
        name = str(getattr(surface, "name", "") or f"面{index}")
        kind = str(getattr(surface, "surface_type", "球面") or "球面")
        if kind not in {"光阑", "平面", "探测器/像面", "像面", "物面"}:
            rows.append((f"surfaces[{index}].radius_mm", group, name, "曲率"))
            if hasattr(surface, "conic"):
                rows.append((f"surfaces[{index}].conic", group, name, "圆锥系数"))
        if kind not in {"探测器/像面", "像面"}:
            rows.append((f"surfaces[{index}].distance_to_next_mm", group, name, "厚度"))
        if kind == "光阑":
            rows.append((f"surfaces[{index}].semi_aperture_mm", group, name, "半口径"))
    rows.extend(
        (
            ("receiver.axial_offset_z_um", "光纤", "接收端", "轴向位置"),
            ("receiver.offset_x_um", "光纤", "接收端", "X 偏移"),
            ("receiver.offset_y_um", "光纤", "接收端", "Y 偏移"),
        )
    )
    return rows


def _display_variable(row: tuple[str, str, str, str]) -> str:
    _key, group, face, parameter = row
    return f"{group} / {face} / {parameter}"


def _optimization_status_label(value: Any) -> str:
    labels = {
        "formal_simulation": "正式评价",
        "surrogate": "代理模型筛选",
        "completed": "已完成",
        "evaluated": "已评估",
        "best": "最佳",
        "failed": "失败",
    }
    text = str(value or "已评估").strip()
    return labels.get(text.lower(), text)


def _coupling_efficiency_from_result(result: Any) -> float | None:
    if not isinstance(result, dict):
        return None
    metrics = dict(result.get("metrics") or {})
    for key in ("total_coupling_efficiency", "coupling_efficiency"):
        value = metrics.get(key, result.get(key))
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _shap_feature_key(feature: str, variable_keys: list[str]) -> str | None:
    raw = str(feature or "").strip()
    if not raw:
        return None
    keys = set(variable_keys)
    if raw in keys:
        return raw
    thickness = raw.replace(".thickness_mm", ".distance_to_next_mm")
    if thickness in keys:
        return thickness
    lowered = raw.lower().replace(" ", "")
    aliases = (
        ("receiver.offset_x", "receiver.offset_x_um"),
        ("offset_x", "receiver.offset_x_um"),
        ("x偏移", "receiver.offset_x_um"),
        ("横向", "receiver.offset_x_um"),
        ("receiver.offset_y", "receiver.offset_y_um"),
        ("offset_y", "receiver.offset_y_um"),
        ("y偏移", "receiver.offset_y_um"),
        ("receiver.axial", "receiver.axial_offset_z_um"),
        ("offset_z", "receiver.axial_offset_z_um"),
        ("axial", "receiver.axial_offset_z_um"),
        ("轴向", "receiver.axial_offset_z_um"),
    )
    for needle, key in aliases:
        if needle.replace(" ", "") in lowered and key in keys:
            return key
    return None


def _variable_shap_scores(items: list[dict[str, Any]], variable_keys: list[str]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        feature = str(item.get("feature") or item.get("name") or "")
        mapped = _shap_feature_key(feature, variable_keys)
        if mapped is None:
            continue
        try:
            value = abs(float(item.get("mean_abs_shap", item.get("mean_shap", item.get("shap_value", 0.0))) or 0.0))
        except (TypeError, ValueError):
            continue
        scores[mapped] = max(scores.get(mapped, 0.0), value)
    return scores


def _ranked_variable_rows(
    rows: list[tuple[str, str, str, str]],
    scores: dict[str, float],
) -> list[tuple[str, str, str, str]]:
    order = {key: index for index, (key, *_rest) in enumerate(rows)}
    return sorted(rows, key=lambda row: (-float(scores.get(row[0], 0.0)), order.get(row[0], 0)))


def _current_value(project, key: str) -> str:
    if key.startswith("surfaces["):
        try:
            index = int(key.split("[", 1)[1].split("]", 1)[0])
            field = key.split("].", 1)[1]
            surface = list(getattr(project, "surfaces", ()) or ())[index]
            if field == "radius_mm":
                return f"{float(surface.radius_mm):.2f}"
            if field == "distance_to_next_mm":
                return f"{float(surface.thickness_mm):.2f}"
            if field == "semi_aperture_mm":
                return f"{float(surface.semi_aperture_mm):.2f}"
        except (ValueError, IndexError, AttributeError, TypeError):
            return "—"
    return "—"


def _apply_float(context, path: str, value: float, reason: str) -> None:
    updater = getattr(context.project, "apply_parameter_changes", None)
    if callable(updater):
        updater({path: float(value)}, reason=reason)


def _section_payload(context, section: str) -> dict[str, Any]:
    getter = getattr(context.project, "simulation_project_payload", None)
    payload = getter() if callable(getter) else (getter or {})
    if not isinstance(payload, dict):
        return {}
    nested = payload.get(section)
    return dict(nested) if isinstance(nested, dict) else {}


def _payload_float(data: dict[str, Any], *keys: str, default: float) -> float:
    for key in keys:
        if key not in data or data[key] is None:
            continue
        try:
            return float(data[key])
        except (TypeError, ValueError):
            continue
    return float(default)


def _payload_length_um(data: dict[str, Any], um_key: str, mm_key: str, default: float) -> float:
    if um_key in data and data[um_key] is not None:
        return _payload_float(data, um_key, default=default)
    if mm_key in data and data[mm_key] is not None:
        return _payload_float(data, mm_key, default=default / 1e3) * 1e3
    return float(default)


def _payload_tilt_urad(data: dict[str, Any], urad_key: str, deg_key: str, default: float = 0.0) -> float:
    if urad_key in data and data[urad_key] is not None:
        return _payload_float(data, urad_key, default=default)
    if deg_key in data and data[deg_key] is not None:
        return radians(_payload_float(data, deg_key, default=0.0)) * 1e6
    return float(default)


def _coerce_feature_units(raw_units: Any, feature_paths: list[Any] | tuple[Any, ...]) -> dict[str, str]:
    """Normalize the backend's feature-unit representations for the model registry."""
    if isinstance(raw_units, dict):
        return {str(key): str(value) for key, value in raw_units.items()}
    if isinstance(raw_units, (list, tuple)):
        return {
            str(path): str(raw_units[index])
            for index, path in enumerate(feature_paths)
            if index < len(raw_units)
        }
    return {}


def _set_combo_data(combo: QComboBox, key: str) -> None:
    index = combo.findData(key)
    if index >= 0:
        combo.setCurrentIndex(index)


def _spin(minimum: float, maximum: float, decimals: int, suffix: str, value: float) -> QDoubleSpinBox:
    control = UnitAwareDoubleSpinBox()
    control.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    control.setKeyboardTracking(False)
    control.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    control.setStepType(QDoubleSpinBox.StepType.AdaptiveDecimalStepType)
    control.setRange(minimum, maximum)
    input_decimals = max(8, int(decimals)) if int(decimals) > 0 else 0
    display_decimals = 2 if int(decimals) > 0 else 0
    control.setDisplayPrecision(display_decimals, input_decimals)
    unit_text = str(suffix or "").strip()
    control.setTargetUnit(unit_text)
    control.setProperty("unitText", unit_text)
    control.setValue(value)
    control.setToolTip("点选后直接输入；↑↓ 微调。滚轮不会改值。")
    return control


def _compact_form() -> QFormLayout:
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(8)
    form.setVerticalSpacing(4)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return form


def _rail_form() -> QFormLayout:
    form = _compact_form()
    form.setVerticalSpacing(6)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
    return form


def _stretch_table(table: QTableWidget) -> None:
    from PySide6.QtWidgets import QHeaderView

    header = table.horizontalHeader()
    header.setStretchLastSection(True)
    for column in range(table.columnCount()):
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)


def _current_lens_feature_rows(context) -> list[tuple[str, str]]:
    project = getattr(getattr(context, "project", None), "project", None)
    if project is None:
        return [("当前镜头", "未检测到工程")]
    rows: list[tuple[str, str]] = [
        ("波长", f"{float(getattr(project, 'wavelength_nm', 0.0) or 0.0):.2f} nm"),
        ("入瞳半径", f"{float(getattr(project, 'pupil_radius_mm', 0.0) or 0.0):.2f} mm"),
    ]
    for index, surface in enumerate(list(getattr(project, "surfaces", ()) or ())):
        name = str(getattr(surface, "name", "") or f"面{index}")
        rows.append((f"{name} 曲率半径", f"{float(getattr(surface, 'radius_mm', 0.0) or 0.0):.2f} mm"))
        rows.append((f"{name} 厚度", f"{float(getattr(surface, 'thickness_mm', 0.0) or 0.0):.2f} mm"))
    rows.append(("光纤模场直径", f"{float(getattr(project, 'receiver_mfd_um', 0.0) or 0.0):.2f} μm"))
    return rows


def _formal_target_value(context, target: str) -> float | None:
    result = getattr(getattr(context, "project", None), "formal_result", None)
    if not isinstance(result, dict):
        return None
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else result
    keys = {
        "耦合效率": ("coupling_efficiency", "eta", "overlap_efficiency"),
        "耦合损耗(dB)": ("coupling_loss_db", "loss_db"),
        "RMS 光斑": ("rms_spot_um", "spot_rms_um"),
        "Strehl": ("strehl", "strehl_ratio"),
    }
    for key in keys.get(str(target), ()):
        value = metrics.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        return number
    return None


def _job_title(kind: str) -> str:
    return {
        "dataset": "数据集生成",
        "train": "训练",
        "joint_train": "训练",
        "bilstm": "训练",
        "scan": "扫描",
        "optimize": "优化",
    }.get(str(kind), str(kind or "任务"))


def _field_group(title: str, parent: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(parent)
    frame.setObjectName("FieldGroup")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(8, 6, 8, 8)
    layout.setSpacing(4)
    if title:
        label = QLabel(title)
        label.setObjectName("FieldGroupTitle")
        layout.addWidget(label)
    return frame, layout


def _unit_row(editor: QWidget, unit: QWidget) -> QWidget:
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    # Keep the editor at its content width; the trailing stretch absorbs the
    # remaining form width instead of stretching the number field itself.
    row.addWidget(editor, 0)
    unit.setMaximumWidth(78)
    row.addWidget(unit, 0)
    row.addStretch(1)
    return host


def _spin_unit_row(editor: QDoubleSpinBox) -> QWidget:
    """Place a spin box beside its unit label instead of embedding the unit."""
    unit_text = str(editor.property("unitText") or "").strip()
    if not unit_text:
        return editor
    unit = QLabel(unit_text)
    unit.setObjectName("UnitLabel")
    unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return _unit_row(editor, unit)


def _action_row(*widgets: QWidget) -> QWidget:
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    for widget in widgets:
        stretch = 1 if isinstance(widget, (QComboBox, QLineEdit)) else 0
        row.addWidget(widget, stretch)
    row.addStretch(1)
    return host


def _labeled_field(title: str, widget: QWidget) -> QWidget:
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    label = QLabel(title)
    label.setMinimumWidth(72)
    row.addWidget(label)
    row.addWidget(widget, 1)
    return host


def _field_grid(widgets: list[QWidget], columns: int = 2) -> QGridLayout:
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(6)
    for column in range(max(columns, 1)):
        grid.setColumnStretch(column, 1)
    for index, widget in enumerate(widgets):
        grid.addWidget(widget, index // columns, index % columns)
    return grid


def _slider_line(title: str, slider: QSlider, value: QLabel) -> QWidget:
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    name = QLabel(title)
    name.setMinimumWidth(56)
    slider.setMaximumHeight(22)
    value.setObjectName("HelperText")
    value.setMinimumWidth(108)
    row.addWidget(name)
    row.addWidget(slider, 1)
    row.addWidget(value)
    return host


def _parse_auxiliary_wavelengths(text: str, primary: float) -> tuple[float, ...]:
    values: list[float] = []
    for token in str(text or "").replace("，", ",").replace("；", ",").replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            value = float(token)
        except (TypeError, ValueError):
            continue
        if not 100.0 <= value <= 30000.0 or abs(value - float(primary)) < 1e-9:
            continue
        if any(abs(value - existing) < 1e-9 for existing in values):
            continue
        values.append(value)
    return tuple(values)


def _set_form_row_visible(form: QFormLayout, widget: QWidget, visible: bool) -> None:
    setter = getattr(form, "setRowVisible", None)
    if callable(setter):
        try:
            setter(widget, visible)
            return
        except TypeError:
            pass
    widget.setVisible(visible)
    label = form.labelForField(widget)
    if label is not None:
        label.setVisible(visible)


@dataclass(frozen=True, slots=True)
class TabSpec:
    """A document description, never a legacy feature page."""

    id: str
    module: str
    kind: str
    title: str
    subtitle: str
    closable: bool = True
    split_group: str = "main"

    @property
    def key(self) -> str:
        return f"{self.module}:{self.kind}:{self.id}"


def _button(text: str, *, checkable: bool = False) -> QToolButton:
    button = QToolButton()
    button.setText(text)
    button.setCheckable(checkable)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    button.setMinimumHeight(32)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _icon_action_button(name: str, tooltip: str, *, color: str = "#344054") -> QToolButton:
    button = QToolButton()
    button.setObjectName("PrimaryActionButton")
    # The primary bar contains only three actions, so their icons should be
    # recognisable at a glance instead of reading as tiny decoration.
    button.setIcon(icon(name, color, 24))
    button.setIconSize(QSize(24, 24))
    button.setToolTip(tooltip)
    button.setAutoRaise(True)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    button.setFixedSize(40, 40)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _primary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("kind", "primary")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setMinimumHeight(34)
    button.setMinimumWidth(128)
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return button

"""The refactored optical workbench shells.

This module contains only shell-level widgets and document panels.
Existing optical controls are reused as leaf widgets where they already have
a stable contract.

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

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
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
from frontend_pyside.features.canvas.parameter_catalog import (
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
from frontend_pyside.features.simulation.payloads import build_simulation_payload
from frontend_pyside.features.simulation.result_adapter import formal_result_diagnostics, formal_result_to_plots
from frontend_pyside.features.simulation.simulation_session import SimulationSession
from frontend_pyside.features.simulation.workflow import SimulationPreviewWorkflow
from frontend_pyside.features.simulation.controller import SimulationController
from frontend_pyside.features.simulation.material_library import MaterialLibraryDocument, UsedMaterialInspector
from frontend_pyside.features.machine_learning.dataset_configuration import build_dataset_parameters
from frontend_pyside.features.canvas.engine_bridge import restrict_payload
from frontend_pyside.features.canvas.task_runner import _augment_payload, explain_job_failure
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
from frontend_pyside.shared.icons import icon


# ---------------------------------------------------------------------------
# Navigation and tab data
# ---------------------------------------------------------------------------


PRIMARY_MODULES: tuple[tuple[str, str], ...] = (
    ("home", "首页"),
    ("simulation", "仿真"),
    ("teaching", "教学"),
    ("model", "模型"),
    ("optimization", "优化"),
    ("explainability", "解释"),
)

RESULT_DOCUMENT_KINDS = frozenset({"ray_layout", "layout_3d", "spot", "coupling", "wavefront"})


SECONDARY_ITEMS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "home": (
        ("quick_start", "快速开始", "进入镜头数据"),
        ("help", "帮助", "查看当前功能说明"),
    ),
    "simulation": (
        ("lens_data", "镜头数据", "中央镜头表；环境、孔径和采样用弹窗"),
        ("materials", "材料库", "平台支持的材料和自定义材料"),
        ("layout", "光路图", "光线传播和聚焦；3D 从页内打开"),
        ("image_quality", "光斑图", "光斑、点列和焦面尺寸"),
        ("fiber_coupling", "光纤耦合", "系统透过、端面接收和总耦合效率"),
        ("wave_diffraction", "波前与衍射", "波前图或 PSF"),
    ),
    "teaching": (
        ("scheme", "方案", "切换单透镜、双透镜、三透镜或四透镜教学方案"),
        ("equipment", "器材库", "打开内置工程器材库"),
        ("inspector", "属性", "打开当前对象悬浮窗"),
        ("display", "显示", "控制光线、标签和视图"),
        ("measure", "测量", "测量距离、角度和光斑"),
        ("imaging", "成像", "正式计算光斑、像面位置和偏心"),
        ("coupling", "耦合", "正式计算模式重叠和总耦合效率"),
        ("calculate", "计算", "运行教学计算"),
        ("result", "结果", "打开悬浮结果窗"),
        ("sync_to_simulation", "同步到仿真", "把教学场景写入当前工程"),
        ("sync_from_simulation", "从仿真更新", "读取当前工程几何和波长"),
    ),
    "model": (
        ("dataset", "数据集", "内置或文件数据集，并在本页训练"),
        ("train_result", "训练结果", "残差图、实测对照和学习曲线"),
        ("predict_eval", "模型预测", "当前系统预测"),
    ),
    "optimization": (
        ("scan", "扫描", "最多两个已选变量的响应曲线"),
        ("opt_vars", "优化", "目标、变量范围并开始优化"),
        ("opt_result", "优化结果", "候选方案、过程曲线和对照图"),
    ),
    "explainability": (
        ("global_contrib", "全局贡献", "哪些量对模型输出更要紧"),
        ("param_trend", "单参数规律", "某一个量变大时预测往哪边"),
        ("current_system", "当前系统", "当前处方这一条样本"),
    ),
}

SECONDARY_DEFAULT_KIND: dict[tuple[str, str], str] = {
    ("simulation", "lens_data"): "lens_data",
    ("simulation", "materials"): "material_library",
    ("simulation", "layout"): "ray_layout",
    ("simulation", "image_quality"): "spot",
    ("simulation", "fiber_coupling"): "coupling",
    ("simulation", "wave_diffraction"): "wavefront",
    ("model", "dataset"): "dataset",
    ("model", "train_result"): "train_result",
    ("model", "predict_eval"): "predict",
    ("optimization", "opt_vars"): "opt_vars",
    ("optimization", "scan"): "scan",
    ("optimization", "opt_progress"): "opt_progress",
    ("optimization", "opt_result"): "opt_result",
    ("explainability", "global_contrib"): "global_contrib",
    ("explainability", "param_trend"): "param_trend",
    ("explainability", "current_system"): "current_system",
}

RESULT_PLOT_KEYS: dict[str, tuple[str, ...]] = {
    "ray_layout": ("光路",),
    "layout_3d": ("3D光路",),
    "spot": ("点列图",),
    "coupling": ("端面匹配", "模式重叠", "耦合场", "能量分解"),
    "wavefront": ("波前", "PSF"),
}

FORMAL_RESULT_VIEWS: tuple[str, ...] = (
    "光路",
    "3D光路",
    "点列图",
    "PSF",
    "波前",
    "端面匹配",
)

KIND_TO_SECONDARY: dict[tuple[str, str], str] = {
    ("simulation", "lens_data"): "lens_data",
    ("simulation", "material_library"): "materials",
    ("simulation", "ray_layout"): "layout",
    ("simulation", "layout_3d"): "layout",
    ("simulation", "spot"): "image_quality",
    ("simulation", "coupling"): "fiber_coupling",
    ("simulation", "wavefront"): "wave_diffraction",
    ("model", "dataset"): "dataset",
    ("model", "train_result"): "train_result",
    ("model", "predict"): "predict_eval",
    ("model", "evaluate"): "train_result",
    ("optimization", "opt_goal"): "opt_vars",
    ("optimization", "opt_vars"): "opt_vars",
    ("optimization", "scan"): "scan",
    ("optimization", "opt_progress"): "opt_progress",
    ("optimization", "opt_result"): "opt_result",
    ("explainability", "global_contrib"): "global_contrib",
    ("explainability", "param_trend"): "param_trend",
    ("explainability", "current_system"): "current_system",
}


KIND_TITLES: dict[tuple[str, str], tuple[str, str]] = {
    ("simulation", "lens_data"): ("镜头数据", "中央顺序表面编辑器"),
    ("simulation", "material_library"): ("材料库", "平台材料和自定义材料"),
    ("simulation", "source_schematic"): ("光源示意", "只画光源和出射光束"),
    ("simulation", "fiber_schematic"): ("光纤示意", "只画端面、模场和偏心"),
    ("simulation", "ray_layout"): ("光路图", "光线传播和聚焦"),
    ("simulation", "layout_3d"): ("3D 视图", "系统三维光路；示意图不画镜头"),
    ("simulation", "spot"): ("光斑图", "接收面光斑、尺寸和功率"),
    ("simulation", "coupling"): ("光纤耦合", "系统透过、端面接收和总耦合效率"),
    ("simulation", "wavefront"): ("波前与衍射", "波前图或 PSF"),
    ("model", "dataset"): ("数据集", "内置数据集、文件数据集和训练"),
    ("model", "train_result"): ("训练结果", "残差图、实测对照和学习曲线"),
    ("model", "predict"): ("模型预测", "当前参数的预测结果"),
    ("optimization", "scan"): ("扫描", "最多两个已选变量"),
    ("optimization", "opt_goal"): ("优化", "目标、工程约束和准直约束"),
    ("optimization", "opt_vars"): ("优化", "目标、变量范围并开始优化"),
    ("optimization", "opt_progress"): ("优化过程", "任务运行进度和当前最优值"),
    ("optimization", "opt_result"): ("优化结果", "候选方案、过程曲线和对照图"),
    ("explainability", "global_contrib"): ("全局贡献", "数据集上的平均 |SHAP|"),
    ("explainability", "param_trend"): ("单参数规律", "当前选中参数的依赖关系"),
    ("explainability", "current_system"): ("当前系统", "本条样本的瀑布贡献"),
}


def _kind_titles(module: str, kind: str) -> tuple[str, str]:
    return (
        KIND_TITLES.get((module, kind))
        or KIND_TITLES.get(("simulation", kind))
        or (kind, "")
    )


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
                return f"{float(surface.radius_mm):g}"
            if field == "distance_to_next_mm":
                return f"{float(surface.thickness_mm):g}"
            if field == "semi_aperture_mm":
                return f"{float(surface.semi_aperture_mm):g}"
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
    control.setDecimals(decimals)
    if suffix:
        control.setSuffix(suffix)
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
        ("波长", f"{float(getattr(project, 'wavelength_nm', 0.0) or 0.0):g} nm"),
        ("入瞳半径", f"{float(getattr(project, 'pupil_radius_mm', 0.0) or 0.0):g} mm"),
    ]
    for index, surface in enumerate(list(getattr(project, "surfaces", ()) or ())):
        name = str(getattr(surface, "name", "") or f"面{index}")
        rows.append((f"{name} 曲率半径", f"{float(getattr(surface, 'radius_mm', 0.0) or 0.0):g} mm"))
        rows.append((f"{name} 厚度", f"{float(getattr(surface, 'thickness_mm', 0.0) or 0.0):g} mm"))
    rows.append(("光纤模场直径", f"{float(getattr(project, 'receiver_mfd_um', 0.0) or 0.0):g} μm"))
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
        "joint_train": "联合训练",
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
    row.addWidget(editor, 1)
    unit.setMaximumWidth(78)
    row.addWidget(unit)
    return host


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
                widget.deleteLater()
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons.clear()
        for key, title, hint in SECONDARY_ITEMS.get(str(module), ()):
            button = _button(title, checkable=True)
            button.setObjectName("SecondaryFunctionButton")
            button.setToolTip(hint)
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
        form.addRow("波长", self.wavelength)
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
        self.waist_pos = _spin(-1e6, 1e6, 3, " mm", _payload_float(payload, "waist_position_mm", "waist_position_x_mm", default=defaults.waist_position_mm))
        self.m2 = _spin(1.0, 100.0, 3, "", m2_x)
        self.split_axes = QCheckBox("分轴（椭圆光斑）")
        self.split_axes.setChecked(split)
        self.waist_x = _spin(0.01, 1e6, 3, " μm", waist_x)
        self.waist_y = _spin(0.01, 1e6, 3, " μm", waist_y)
        self.m2_x = _spin(1.0, 100.0, 3, "", m2_x)
        self.m2_y = _spin(1.0, 100.0, 3, "", m2_y)
        gaussian_form.addRow("束腰半径 w₀", self.waist)
        gaussian_form.addRow("束腰位置", self.waist_pos)
        gaussian_form.addRow("光束质量 M²", self.m2)
        gaussian_form.addRow(self.split_axes)
        gaussian_form.addRow("束腰半径 wₓ", self.waist_x)
        gaussian_form.addRow("束腰半径 wᵧ", self.waist_y)
        gaussian_form.addRow("M²ₓ", self.m2_x)
        gaussian_form.addRow("M²ᵧ", self.m2_y)
        self._gaussian_form = gaussian_form
        point = QWidget()
        point_form = _rail_form()
        point.setLayout(point_form)
        self.source_na = _spin(0, 1, 5, "", na_x)
        self.split_na = QCheckBox("分轴")
        self.split_na.setChecked(split_na)
        self.source_na_y = _spin(0, 1, 5, "", na_y)
        point_form.addRow("数值孔径 NA", self.source_na)
        point_form.addRow(self.split_na)
        point_form.addRow("NAᵧ", self.source_na_y)
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
                extra.append(f"{number:g}")
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
        self.waist_x.valueChanged.connect(lambda value: self._apply("source.waist_x_um", value, "束腰半径 wₓ"))
        self.waist_y.valueChanged.connect(lambda value: self._apply("source.waist_y_um", value, "束腰半径 wᵧ"))
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
        for widget in (self.waist_x, self.waist_y, self.m2_x, self.m2_y):
            _set_form_row_visible(self._gaussian_form, widget, checked)
        self.waist.setEnabled(not checked)
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
        self.wavelength_view = QLabel(f"{float(context.project.project.wavelength_nm):g} nm")
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
        gaussian_form.addRow("模场直径 MFD", self.mfd)
        gaussian_form.addRow(self.split_mfd)
        gaussian_form.addRow("MFDᵧ", self.mfd_y)
        self._gaussian_form = gaussian_form
        guided = QWidget()
        guided_form = _rail_form()
        guided.setLayout(guided_form)
        self.core = _spin(0.1, 1000, 3, " μm", core)
        self.n_core = _spin(1.0, 5.0, 6, "", _payload_float(payload, "core_refractive_index", default=defaults.core_refractive_index))
        self.n_clad = _spin(1.0, 5.0, 6, "", _payload_float(payload, "cladding_refractive_index", default=defaults.cladding_refractive_index))
        guided_form.addRow("芯径", self.core)
        guided_form.addRow("纤芯折射率 n_core", self.n_core)
        guided_form.addRow("包层折射率 n_clad", self.n_clad)
        multimode = QWidget()
        mm_form = _rail_form()
        multimode.setLayout(mm_form)
        self.mm_core = _spin(0.1, 1000, 3, " μm", core if core >= 10 else 50.0)
        self.na = _spin(0.001, 1, 5, "", na_x)
        self.split_na = QCheckBox("分轴")
        self.split_na.setChecked(abs(na_x - na_y) > 1e-9)
        self.na_y = _spin(0.001, 1, 5, "", na_y)
        mm_form.addRow("芯径", self.mm_core)
        mm_form.addRow("数值孔径 NA", self.na)
        mm_form.addRow(self.split_na)
        mm_form.addRow("NAᵧ", self.na_y)
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
        pose.addRow("X 方向偏移", self.offset_x)
        pose.addRow("Y 方向偏移", self.offset_y)
        pose.addRow("轴向偏移 Δz", self.axial)
        pose.addRow("X 方向倾角", self.tilt_x)
        pose.addRow("Y 方向倾角", self.tilt_y)
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
        more_form.addRow("外部折射率 n_out", self.outside)
        more_form.addRow("端面透射率", self.endface)
        more_form.addRow("光纤长度", self.length)
        more_form.addRow("衰减", self.attenuation)
        more_form.addRow("连接器损耗", self.connector)
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
        self.wavelength_view.setText(f"{float(project.wavelength_nm):g} nm")


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
        air_form.addRow("环境温度", self.temperature)
        air_form.addRow("大气压", self.pressure)
        air_form.addRow(self.thermal)
        air_layout.addLayout(air_form)
        conjugate, conjugate_layout = _field_group("物像共轭")
        conjugate_form = _rail_form()
        self.object_distance = _spin(0.1, 1e9, 4, " mm", float(system.object_distance_mm))
        self.image_distance = _spin(-1e6, 1e6, 4, " mm", float(system.image_distance_mm))
        self.auto_focus = QCheckBox("最佳焦面搜索")
        self.auto_focus.setChecked(bool(system.auto_best_focus))
        conjugate_form.addRow("物距", self.object_distance)
        conjugate_form.addRow("像面位置", self.image_distance)
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
        form.addRow("入瞳半径", self.pupil)
        form.addRow("视场角 X", self.field_x)
        form.addRow("视场角 Y", self.field_y)
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
        form.addRow("相对最后一面", self.offset)
        form.addRow("像元尺寸", self.pitch)
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
        self.radius_label.setText(f"{radius:g} mm")
        self.thickness_label.setText(f"{thickness:g} mm")

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


class OptimizationGoalInspector(QFrame):
    startRequested = Signal()

    def __init__(self, context=None, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("ObjectInspector")
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 4)
        root.setSpacing(6)

        box, layout = _field_group("评价")
        self.goal = QComboBox()
        self.goal.addItems(list(OPTIMIZATION_OBJECTIVE_CHOICES))
        self.evaluation = QComboBox()
        # The optimisation objective is currently the fibre-mode overlap.  Do
        # not expose alternate planes until they are implemented as distinct
        # formal objective definitions.
        self.evaluation.addItem("光纤模场")
        self.evaluation.setToolTip("当前优化以光纤端面模场重叠为评价面。")
        self.eval_mode = QComboBox()
        self.eval_mode.addItem("光学仿真", "formal")
        self.eval_mode.addItem("已训练模型", "surrogate")
        self.predict_model = QComboBox()
        self._eval_model_row = _labeled_field("模型", self.predict_model)
        layout.addLayout(
            _field_grid(
                [
                    _labeled_field("目标", self.goal),
                    _labeled_field("面", self.evaluation),
                    _labeled_field("方式", self.eval_mode),
                    self._eval_model_row,
                ],
                columns=2,
            )
        )
        root.addWidget(box)

        engineering, engineering_layout = _field_group("工程约束")
        self.max_length = _spin(0.1, 1e6, 3, " mm", 80.0)
        self.min_edge = _spin(0.0, 100.0, 3, " mm", 0.3)
        # Edge thickness needs two explicitly paired optical surfaces and a
        # sag calculation.  The current generic surface table has neither, so
        # leave it visibly unavailable rather than accept a value we cannot
        # enforce truthfully.
        self.min_edge.setEnabled(False)
        self.min_edge.setToolTip("当前表面模型未声明透镜前后面配对，暂不能可靠约束边缘厚度。")
        self.min_center = _spin(0.0, 100.0, 3, " mm", 0.3)
        self.min_air = _spin(0.0, 100.0, 3, " mm", 0.1)
        self.aperture_limit = QCheckBox("半口径不超过机械口径")
        self.aperture_limit.setChecked(True)
        engineering_layout.addLayout(
            _field_grid(
                [
                    _labeled_field("最大系统总长", self.max_length),
                    _labeled_field("最小边缘厚度", self.min_edge),
                    _labeled_field("最小厚度", self.min_center),
                    _labeled_field("最小空气厚度", self.min_air),
                ],
                columns=2,
            )
        )
        engineering_layout.addWidget(self.aperture_limit)
        root.addWidget(engineering)

        collimation, collimation_layout = _field_group("准直约束")
        self.collimation = QCheckBox("启用")
        self.collimation_surface = QComboBox()
        self.collimation_surface.addItem("自动识别准直输出面", "")
        surfaces = list(getattr(getattr(getattr(context, "project", None), "project", None), "surfaces", ()) or ())
        for index, surface in enumerate(surfaces):
            name = str(getattr(surface, "name", "") or f"面{index}")
            self.collimation_surface.addItem(f"S{index + 1} · {name}", index)
        self.collimation_span = _spin(0.1, 1000.0, 3, " mm", 10.0)
        self.collimation_radius = _spin(0.01, 100.0, 3, " %", 2.0)
        self.collimation_curvature = _spin(0.00001, 10.0, 5, "", 0.05)
        self.collimation_centroid = _spin(0.001, 100.0, 3, " %", 1.0)
        self.collimation_tilt = _spin(0.001, 1000.0, 3, " mrad", 1.0)
        self._collimation_hosts = [
            _labeled_field("评价面", self.collimation_surface),
            _labeled_field("评价段", self.collimation_span),
            _labeled_field("最大半径变化", self.collimation_radius),
            _labeled_field("最大归一化曲率", self.collimation_curvature),
            _labeled_field("最大质心漂移", self.collimation_centroid),
            _labeled_field("最大光轴倾角", self.collimation_tilt),
        ]
        collimation_layout.addWidget(self.collimation)
        collimation_layout.addLayout(_field_grid(self._collimation_hosts, columns=2))
        root.addWidget(collimation)

        self.eval_mode.currentIndexChanged.connect(lambda _index: self._sync_eval_mode())
        self.collimation.toggled.connect(self._sync_collimation)
        self._sync_eval_mode()
        self._sync_collimation()

    def set_trained_models(self, models: list[dict[str, Any]]) -> None:
        previous = self.predict_model.currentText()
        self.predict_model.blockSignals(True)
        self.predict_model.clear()
        for item in models:
            self.predict_model.addItem(str(item.get("title") or item.get("id") or "模型"), dict(item))
        self.predict_model.blockSignals(False)
        if previous and self.predict_model.findText(previous) >= 0:
            self.predict_model.setCurrentText(previous)
        elif self.predict_model.count():
            self.predict_model.setCurrentIndex(0)
        self._sync_eval_mode()

    def evaluation_mode(self) -> str:
        return str(self.eval_mode.currentData() or "formal")

    def _sync_eval_mode(self) -> None:
        ml = self.evaluation_mode() == "surrogate"
        self._eval_model_row.setVisible(ml)
        self.predict_model.setVisible(ml)
        if ml and self.predict_model.count() == 0:
            self.predict_model.setPlaceholderText("请先在模型页训练")
            self.predict_model.setToolTip("请先在数据集页训练，再选择已训练模型。")
        else:
            self.predict_model.setToolTip("")

    def _sync_collimation(self, *_args) -> None:
        enabled = self.collimation.isChecked()
        for host in self._collimation_hosts:
            host.setVisible(enabled)
        for widget in (
            self.collimation_surface,
            self.collimation_span,
            self.collimation_radius,
            self.collimation_curvature,
            self.collimation_centroid,
            self.collimation_tilt,
        ):
            widget.setVisible(enabled)


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


class ObjectRail(QFrame):
    objectRequested = Signal(str)
    optimizationSelectionChanged = Signal(str, bool)

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
        self.search = QLineEdit()
        self.search.setPlaceholderText("筛选…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        root.addWidget(self.search)
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
        self.shap_button.setToolTip("请先训练并对着同一目标看过全局贡献")
        self.shap_button.toggled.connect(self._set_shap_sort)
        filter_layout.addWidget(self.shap_button, 2, 0, 1, 3)
        for column in range(3):
            filter_layout.setColumnStretch(column, 1)
        root.addWidget(self.filter_row)
        self.accordion = QScrollArea()
        self.accordion.setWidgetResizable(True)
        self.accordion.setFrameShape(QFrame.Shape.NoFrame)
        self.accordion.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.accordion_host = QWidget()
        self.accordion_layout = QVBoxLayout(self.accordion_host)
        self.accordion_layout.setContentsMargins(0, 0, 0, 0)
        self.accordion_layout.setSpacing(4)
        self.accordion_layout.addStretch(1)
        self.accordion.setWidget(self.accordion_host)
        root.addWidget(self.accordion, 1)
        self.list = QListWidget()
        self.list.setObjectName("ObjectList")
        self.list.itemClicked.connect(self._clicked)
        self.list.itemChanged.connect(self._item_changed)
        root.addWidget(self.list, 1)
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
        self.lens_list: QListWidget | None = None
        self._document_kind = ""
        self._datasets: list[dict[str, Any]] = []
        self._models: list[dict[str, Any]] = []
        self._dataset_family = "tabular"
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
            "optimization": "参数筛选",
            "explainability": "参数",
        }.get(self._module, "对象"))
        simulation = self._module == "simulation"
        filtered = self._module in {"optimization", "explainability"}
        self.search.setVisible(self._module in {"optimization", "explainability"})
        self.filter_row.setVisible(filtered)
        self.shap_button.setVisible(self._module == "optimization")
        self.accordion.setVisible(simulation)
        self.list.setVisible(not simulation)
        self._rail_layout.setStretch(self._rail_layout.indexOf(self.accordion), 1 if simulation else 0)
        self._rail_layout.setStretch(self._rail_layout.indexOf(self.list), 0 if simulation else 1)
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

    def _clear_accordion(self) -> None:
        while self.accordion_layout.count() > 1:
            item = self.accordion_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._sections.clear()
        self.goal_inspector = None
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
        lens = AccordionSection("lens_group", "镜头组")
        lens.set_body_widget(self.lens_sliders)
        materials = AccordionSection("materials", "材料")
        materials.set_body_widget(self.materials_inspector)
        fiber = AccordionSection("fiber", "光纤")
        fiber.set_body_widget(self.fiber_inspector)
        detector = AccordionSection("detector", "探测器")
        detector.set_body_widget(self.detector_inspector)
        for section in (environment, field, source, lens, materials, fiber, detector):
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
                    self._add_item(f"dataset:{item.get('id', '')}", str(item.get("title") or item.get("id") or "数据集"), str(item.get("kind") or ""))
            else:
                self.heading.setText("训练结果" if kind == "train_result" else "模型")
                for item in self._models:
                    self._add_item(f"model:{item.get('id', '')}", str(item.get("title") or item.get("id") or "模型"), "已训练")
        elif module == "explainability":
            kind = self._document_kind or "global_contrib"
            if kind in {"global_contrib", "current_system"}:
                self.heading.setText("模型")
                self.search.setVisible(False)
                self.filter_row.setVisible(False)
                for item in self._models:
                    self._add_item(f"model:{item.get('id', '')}", str(item.get("title") or item.get("id") or "模型"), "已训练")
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
            self.shap_button.setVisible(True)
            rows = list(_variable_rows(self.context.project.project))
            if self._shap_sort and self._shap_scores:
                rows = _ranked_variable_rows(rows, self._shap_scores)
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

    def _add_item(self, key: str, title: str, hint: str) -> None:
        item = QListWidgetItem(title)
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setToolTip(hint)
        self.list.addItem(item)

    def set_shap_scores(self, scores: dict[str, float]) -> None:
        self._shap_scores = {str(key): float(value) for key, value in dict(scores or {}).items()}
        has = bool(self._shap_scores)
        self.shap_button.setEnabled(has)
        self.shap_button.setToolTip(
            "按全局贡献从高到低排列变量" if has else "请先训练并对着同一目标看过全局贡献"
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
        if self._module == "optimization":
            return
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
            label = item.text().lower()
            item_group = str(item.data(Qt.ItemDataRole.UserRole + 1) or "")
            hidden = bool(query) and query not in label
            if group == "fiber":
                hidden = hidden or item_group != "光纤"
            elif group != "all":
                hidden = hidden or not item_group.startswith(group)
            item.setHidden(hidden)


class EmptyDocument(QWidget):
    def __init__(self, title: str, subtitle: str, message: str = "当前页签等待数据。", parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("DocumentTitle")
        root.addWidget(heading)
        root.addStretch(2)


class LensDataDocument(QWidget):
    settingsRequested = Signal(str)

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(5)
        self.editor = OpticalSystemEditor(context.project, self)
        # This is the one central editor.  The sidebar never opens another full
        # editor window; it only selects and scrolls this table.
        button = getattr(self.editor, "full_editor_button", None)
        if button is not None:
            button.hide()
        root.addWidget(self.editor, 1)

    def select_surface(self, row: int) -> None:
        table = getattr(self.editor, "table", None)
        if table is None:
            return
        if 0 <= int(row) < table.rowCount():
            table.selectRow(int(row))
            table.scrollToItem(table.item(int(row), 0))


class ObjectSchematicView(QWidget):
    """Paint a source-only or fiber-only sketch. Never draws the lens group."""

    def __init__(self, kind: str, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.mode = "gaussian"
        self.setObjectName("SchematicCanvas")
        self.setMinimumHeight(220)

    def set_mode(self, mode: str) -> None:
        self.mode = str(mode or "gaussian")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
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
            self._paint_source(painter, width, height, mid_y)
        else:
            self._paint_fiber(painter, width, height, mid_y)

    def _paint_source(self, painter: QPainter, width: float, height: float, mid_y: float) -> None:
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
            for offset in (-18, -6, 6, 18):
                painter.drawLine(int(start_x), int(mid_y + offset), int(end_x), int(mid_y + offset))
            painter.drawText(int(width / 2 - 40), 28, "均匀/平行光 · 视场")
        elif self.mode == "point":
            painter.drawEllipse(int(start_x), int(mid_y - 4), 8, 8)
            for offset in (-40, -20, 0, 20, 40):
                painter.drawLine(int(start_x + 8), int(mid_y), int(end_x), int(mid_y + offset))
            painter.drawText(int(width / 2 - 30), 28, "点光源 · NA")
        else:
            painter.drawLine(int(start_x), int(mid_y - 22), int(end_x), int(mid_y - 8))
            painter.drawLine(int(start_x), int(mid_y + 22), int(end_x), int(mid_y + 8))
            painter.drawLine(int(start_x), int(mid_y), int(end_x), int(mid_y))
            painter.drawText(int(width / 2 - 40), 28, "高斯光束 · 束腰")

    def _paint_fiber(self, painter: QPainter, width: float, height: float, mid_y: float) -> None:
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
            painter.drawText(40, height - 24, "多模")
        elif self.mode in {"import", "imported", "user_mode"}:
            painter.drawText(40, height - 24, "导入复场")
        else:
            painter.drawText(40, height - 24, "单模")


class SchematicDocument(QWidget):
    def __init__(self, context, kind: str, parent=None) -> None:
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
        context.project.project_changed.connect(lambda _project: self.refresh())

    def set_mode(self, mode: str) -> None:
        self.canvas.set_mode(mode)
        self.refresh()

    def refresh(self) -> None:
        project = self.context.project.project
        if self.kind == "source_schematic":
            self.summary.setText(f"波长：{float(project.wavelength_nm):g} nm")
        else:
            self.summary.setText(f"模场直径：{float(project.receiver_mfd_um):g} μm")


class EngineeringDialog(QDialog):
    """Popup engineering settings. These never occupy the secondary bar."""

    runRequested = Signal()

    def __init__(
        self,
        kind: str,
        context,
        parent=None,
        *,
        system: SystemFormState | None = None,
        calculation: CalculationFormState | None = None,
        alignment: AlignmentFormState | None = None,
    ) -> None:
        super().__init__(parent)
        self.kind = str(kind)
        self.context = context
        self._system = system or SystemFormState(pupil_radius_mm=float(context.project.project.pupil_radius_mm))
        self._calculation = calculation or CalculationFormState()
        self._alignment = alignment or AlignmentFormState()
        titles = {
            "software": "软件设置",
            "environment": "系统环境",
            "aperture": "孔径与视场",
            "compute": "采样与运行",
        }
        self.setWindowTitle(titles.get(self.kind, "设置"))
        self.setObjectName("EngineeringDialog")
        self.setModal(True)
        self.setSizeGripEnabled(True)
        self.resize(480, 420)
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        form = QFormLayout(host)
        if self.kind == "software":
            self.theme_box = QComboBox()
            self.theme_box.addItems(["跟随系统", "浅色", "深色"])
            self.backend_url = QLineEdit("http://127.0.0.1:8000")
            form.addRow("外观", self.theme_box)
            form.addRow("后端地址", self.backend_url)
        elif self.kind == "environment":
            self.temperature = _spin(-273, 1000, 3, " ℃", float(self._system.environment_temperature_c))
            self.pressure = _spin(0, 10000, 3, " kPa", float(self._system.environment_pressure_kpa))
            self.thermal = QCheckBox("温度补偿")
            self.thermal.setChecked(bool(self._system.thermal_compensation))
            self.object_distance = _spin(0.1, 1e9, 4, " mm", float(self._system.object_distance_mm))
            self.image_distance = _spin(-1e6, 1e6, 4, " mm", float(self._system.image_distance_mm))
            self.auto_focus = QCheckBox("最佳焦面搜索")
            self.auto_focus.setChecked(bool(self._system.auto_best_focus))
            form.addRow("环境温度", self.temperature)
            form.addRow("大气压", self.pressure)
            form.addRow("", self.thermal)
            form.addRow("物距", self.object_distance)
            form.addRow("像面位置", self.image_distance)
            form.addRow("", self.auto_focus)
        elif self.kind == "aperture":
            self.pupil = _spin(0.01, 10000, 3, " mm", float(context.project.project.pupil_radius_mm))
            self.field_x = _spin(-90, 90, 3, " °", float(self._system.field_x_deg))
            self.field_y = _spin(-90, 90, 3, " °", float(self._system.field_y_deg))
            form.addRow("入瞳半径", self.pupil)
            form.addRow("视场角 X", self.field_x)
            form.addRow("视场角 Y", self.field_y)
            self.pupil.valueChanged.connect(lambda value: context.project.update_pupil_radius(float(value)))
        else:
            self.precision = QComboBox()
            self.precision.addItems(["预览", "标准", "高精度"])
            self.precision.setCurrentText({"preview": "预览", "standard": "标准", "high": "高精度"}.get(self._calculation.precision, "标准"))
            self.grid = QComboBox()
            self.grid.addItems(["65×65", "129×129", "257×257", "513×513", "1025×1025"])
            self.grid.setCurrentText(f"{int(self._calculation.output_grid_size)}×{int(self._calculation.output_grid_size)}")
            if self.grid.currentIndex() < 0:
                self.grid.setCurrentText(str(DEFAULT_CALCULATION_PRECISION_TEXT).replace(" ", ""))
            self.layout_pupil = QComboBox()
            self.layout_pupil.addItems(["7×7", "9×9", "13×13", "17×17"])
            self.layout_pupil.setCurrentText(f"{int(self._calculation.layout_pupil_sample_count)}×{int(self._calculation.layout_pupil_sample_count)}")
            self.pupil_samples = QComboBox()
            self.pupil_samples.addItems(["17×17", "33×33", "49×49", "65×65"])
            self.pupil_samples.setCurrentText(f"{int(self._calculation.pupil_sample_count)}×{int(self._calculation.pupil_sample_count)}")
            self.propagation = QComboBox()
            self.propagation.addItems(list(PROPAGATION_MAP.keys()))
            reverse_prop = {value: key for key, value in PROPAGATION_MAP.items()}
            self.propagation.setCurrentText(reverse_prop.get(self._calculation.propagation_model, DEFAULT_PROPAGATION_TEXT))
            self.padding = _spin(1, 16, 0, " ×", float(self._calculation.zero_padding_factor))
            self.extent = _spin(0.001, 1000, 3, " mm", float(self._calculation.output_extent_mm))
            self.auto_expand = QCheckBox("自动扩展计算窗口")
            self.auto_expand.setChecked(bool(self._calculation.auto_expand_output))
            form.addRow("计算精度", self.precision)
            form.addRow("接收面网格", self.grid)
            form.addRow("光路采样", self.layout_pupil)
            form.addRow("分析光瞳", self.pupil_samples)
            form.addRow("传播方法", self.propagation)
            form.addRow("零填充", self.padding)
            form.addRow("计算窗口", self.extent)
            form.addRow("", self.auto_expand)
            self.analysis_boxes: dict[str, QCheckBox] = {}
            selected = set(self._calculation.analyses or ())
            analysis_items = (
                ("raytrace", "光路"),
                ("spot", "点列图"),
                ("psf", "点扩散函数 PSF"),
                ("coupling", "耦合效率"),
                ("mtf", "MTF"),
                ("power_audit", "能量检查"),
            )
            for index, (key, label) in enumerate(analysis_items):
                box = QCheckBox(label)
                default_on = key in {"raytrace", "spot", "psf", "coupling"}
                box.setChecked(key in selected if selected else default_on)
                self.analysis_boxes[key] = box
                form.addRow("计算内容" if index == 0 else "", box)
            self.high_precision = QCheckBox("完整复场耦合")
            self.high_precision.setChecked(bool(self._calculation.high_precision_coupling_enabled))
            self.only_visible = QCheckBox("只计算当前结果")
            self.only_visible.setChecked(bool(self._calculation.only_visible_results))
            self.sampling_convergence = QCheckBox("检查采样收敛")
            self.sampling_convergence.setChecked(bool(self._calculation.sampling_convergence_enabled))
            self.save_arrays = QCheckBox("保存完整数组")
            self.save_arrays.setChecked(bool(self._calculation.save_large_arrays))
            form.addRow("", self.high_precision)
            form.addRow("", self.only_visible)
            form.addRow("", self.sampling_convergence)
            form.addRow("", self.save_arrays)
            self.align_enabled = QCheckBox("光纤对准")
            self.align_enabled.setChecked(bool(self._alignment.enabled))
            self.align_dz = QCheckBox("包含轴向对准")
            self.align_dz.setChecked(bool(self._alignment.include_dz))
            self.align_offset = _spin(0, 1e6, 3, " μm", float(self._alignment.max_offset_um))
            self.align_axial = _spin(0, 1e6, 3, " μm", float(self._alignment.max_axial_offset_um))
            self.align_tilt = _spin(0, 1e7, 1, " μrad", float(self._alignment.max_tilt_urad))
            self.align_iterations = _spin(1, 1e6, 0, "", float(self._alignment.max_iterations))
            self.align_evals = _spin(1, 1e6, 0, "", float(self._alignment.max_function_evaluations))
            self.align_timeout = _spin(1, 1e6, 1, " s", float(self._alignment.timeout_seconds))
            form.addRow("", self.align_enabled)
            form.addRow("", self.align_dz)
            form.addRow("最大横向偏移", self.align_offset)
            form.addRow("最大轴向偏移", self.align_axial)
            form.addRow("最大倾角", self.align_tilt)
            form.addRow("最大迭代次数", self.align_iterations)
            form.addRow("最大函数求值次数", self.align_evals)
            form.addRow("对准超时", self.align_timeout)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close is not None:
            close.clicked.connect(self.accept)
        root.addWidget(buttons)

    def _emit_run(self) -> None:
        self.runRequested.emit()

    def system_state(self) -> SystemFormState:
        if self.kind == "environment":
            return SystemFormState(
                object_distance_mm=float(self.object_distance.value()),
                pupil_radius_mm=float(self.context.project.project.pupil_radius_mm),
                image_distance_mm=float(self.image_distance.value()),
                field_x_deg=self._system.field_x_deg,
                field_y_deg=self._system.field_y_deg,
                auto_best_focus=self.auto_focus.isChecked(),
                environment_temperature_c=float(self.temperature.value()),
                environment_pressure_kpa=float(self.pressure.value()),
                thermal_compensation=self.thermal.isChecked(),
            )
        if self.kind == "aperture":
            return SystemFormState(
                object_distance_mm=self._system.object_distance_mm,
                pupil_radius_mm=float(self.pupil.value()),
                image_distance_mm=self._system.image_distance_mm,
                field_x_deg=float(self.field_x.value()),
                field_y_deg=float(self.field_y.value()),
                auto_best_focus=self._system.auto_best_focus,
                environment_temperature_c=self._system.environment_temperature_c,
                environment_pressure_kpa=self._system.environment_pressure_kpa,
                thermal_compensation=self._system.thermal_compensation,
            )
        return self._system

    def calculation_state(self) -> CalculationFormState:
        if self.kind != "compute":
            return self._calculation
        analyses = [key for key, box in self.analysis_boxes.items() if box.isChecked()]
        if self.high_precision.isChecked() and "coupling" not in analyses:
            analyses.append("coupling")
        if not analyses:
            analyses = ["raytrace"]
        return CalculationFormState(
            precision=PRECISION_MAP.get(self.precision.currentText(), "standard"),
            output_grid_size=parse_grid_size(self.grid.currentText(), DEFAULT_OUTPUT_GRID_SIZE),
            pupil_sample_count=parse_grid_size(self.pupil_samples.currentText(), DEFAULT_PUPIL_SAMPLE_COUNT),
            layout_pupil_sample_count=parse_grid_size(self.layout_pupil.currentText(), DEFAULT_LAYOUT_PUPIL_SAMPLE_COUNT),
            propagation_model=PROPAGATION_MAP.get(self.propagation.currentText(), "scaled_fresnel"),
            zero_padding_factor=float(self.padding.value()),
            output_extent_mm=float(self.extent.value()),
            auto_expand_output=self.auto_expand.isChecked(),
            analyses=tuple(analyses),
            only_visible_results=self.only_visible.isChecked(),
            include_energy_audit=bool(self.analysis_boxes.get("power_audit") and self.analysis_boxes["power_audit"].isChecked()),
            sampling_convergence_enabled=self.sampling_convergence.isChecked(),
            save_large_arrays=self.save_arrays.isChecked(),
            high_precision_coupling_enabled=self.high_precision.isChecked(),
        )

    def alignment_state(self) -> AlignmentFormState:
        if self.kind != "compute":
            return self._alignment
        return AlignmentFormState(
            enabled=self.align_enabled.isChecked(),
            include_dz=self.align_dz.isChecked(),
            max_offset_um=float(self.align_offset.value()),
            max_axial_offset_um=float(self.align_axial.value()),
            max_tilt_urad=float(self.align_tilt.value()),
            max_iterations=int(self.align_iterations.value()),
            max_function_evaluations=int(self.align_evals.value()),
            timeout_seconds=float(self.align_timeout.value()),
        )


class CombinedSettingsDialog(QDialog):
    """Top-bar 设置: sampling / formal-run parameters only."""

    def __init__(
        self,
        context,
        parent=None,
        *,
        calculation: CalculationFormState | None = None,
        alignment: AlignmentFormState | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("计算设置")
        self.setObjectName("CombinedSettingsDialog")
        self.setModal(True)
        self.setSizeGripEnabled(True)
        self.resize(540, 580)
        self.compute = EngineeringDialog(
            "compute",
            context,
            self,
            calculation=calculation,
            alignment=alignment,
        )
        self.compute.setWindowFlags(Qt.WindowType.Widget)
        self.compute.setSizeGripEnabled(False)
        for box in self.compute.findChildren(QDialogButtonBox):
            box.hide()
        root = QVBoxLayout(self)
        root.addWidget(self.compute, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close is not None:
            close.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)


class SettingsDocument(EngineeringDialog):
    """Kept as a dialog alias; simulation no longer opens these as tabs."""

    def __init__(self, context, compute: bool = False, on_run: Callable[[], None] | None = None, parent=None) -> None:
        super().__init__("compute" if compute else "environment", context, parent)
        if on_run is not None:
            self.runRequested.connect(on_run)


class ResultDocument(QWidget):
    """One analysis document; the outer shell never adds a second result bar."""

    relatedRequested = Signal(str)

    def __init__(self, context, kind: str, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.kind = kind
        self._result_revision = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)
        header = QHBoxLayout()
        header.addStretch(1)
        source = QLabel("光学仿真结果未生成")
        source.setObjectName("ResultSource")
        header.addWidget(source)
        if kind == "ray_layout":
            view3d = QToolButton()
            view3d.setText("3D 视图")
            view3d.setToolTip("系统三维光路；仿真示意图不画镜头")
            view3d.clicked.connect(lambda: self.relatedRequested.emit("layout_3d"))
            header.addWidget(view3d)
        root.addLayout(header)
        self.workspace = LazyResultWorkspace(self)
        self.workspace.set_single_view_only(True)
        self.workspace.set_toolbar_visible(False)
        self.workspace.set_pane_header_visible(False)
        self.workspace.set_pane_source_visible(False)
        self.workspace.set_plot_tools_visible(False)
        self.workspace.set_maximize_controls_visible(False)
        self.workspace.set_footer_visible(False)
        root.addWidget(self.workspace, 1)
        self.metrics = QLabel("当前页指标：等待正式计算")
        self.metrics.setObjectName("DocumentMetric")
        self.metrics.setWordWrap(True)
        root.addWidget(self.metrics)
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
        self._last_plot: dict[str, Any] = {"kind": "empty", "message": ""}
        self._sync_export_enabled()
        context.project.formal_result_changed.connect(self._result_changed)
        context.project.metrics_changed.connect(lambda _metrics: self._refresh_metrics())
        self._refresh_metrics()
        existing = getattr(context.project, "formal_result", None)
        if isinstance(existing, dict) and existing:
            self._result_changed(existing)
        else:
            self._show_placeholder()

    def _show_placeholder(self) -> None:
        self._set_source("等待正式结果")
        self._last_plot = {"kind": "empty", "message": "提交正式计算后，这里显示对应结果。"}
        self.workspace.set_result(0, "等待正式结果", self._last_plot)
        self._sync_export_enabled()

    def _result_changed(self, result: object) -> None:
        if not isinstance(result, dict) or not result:
            self._show_placeholder()
            return
        metrics = dict(result.get("metrics") or {})
        self._result_revision = int(getattr(self.context.project, "design_revision", 0) or 0)
        self._set_source("正式计算")
        self.metrics.setText(self._metric_text(metrics))
        data = self._result_plot(result)
        self._last_plot = data
        self.workspace.set_result(0, _kind_titles("simulation", self.kind)[0], data)
        self._text.setText(self._detail_text(result))
        self._sync_export_enabled()

    def refresh(self) -> None:
        """Refresh metrics and mark a formal result stale after a design edit."""
        self._refresh_metrics()
        current_revision = int(getattr(self.context.project, "design_revision", 0) or 0)
        if self._result_revision and current_revision != self._result_revision:
            self.mark_stale()

    def mark_stale(self) -> None:
        current_revision = int(getattr(self.context.project, "design_revision", 0) or 0)
        if not self._result_revision or current_revision == self._result_revision:
            return
        self._set_source("当前系统已修改 · 需重新计算")
        current = self._metric_text(dict(getattr(self.context.project.project, "metrics", {}) or {}))
        self.metrics.setText(f"{current}　·　结果已过期")

    def _set_source(self, text: str) -> None:
        source = self.findChild(QLabel, "ResultSource")
        if source is not None:
            source.setText(text)
            source.setProperty("stale", str(text).startswith("当前系统已修改"))
            source.style().unpolish(source)
            source.style().polish(source)

    def _refresh_metrics(self) -> None:
        metrics = dict(getattr(self.context.project.project, "metrics", {}) or {})
        self.metrics.setText(self._metric_text(metrics))

    def _metric_text(self, metrics: dict[str, Any]) -> str:
        def pct(key: str) -> str:
            value = metrics.get(key)
            return "—" if not isinstance(value, (int, float)) else f"{float(value) * 100:.2f}%"
        if self.kind == "coupling":
            # The formal backend exposes the physical breakdown names while
            # older preview payloads use the compact UI names.  Prefer the
            # explicit UI value and fall back to the corresponding backend
            # metric so a real result is never shown as a dash.
            system_key = "system_efficiency" if metrics.get("system_efficiency") is not None else "transmission_efficiency"
            receiver_key = "receiver_efficiency" if metrics.get("receiver_efficiency") is not None else "fiber_interface_efficiency"
            total_key = "total_coupling_efficiency" if metrics.get("total_coupling_efficiency") is not None else "coupling_efficiency"
            return (
                f"系统效率：{pct(system_key)}　"
                f"端面接收效率：{pct(receiver_key)}　"
                f"总耦合效率：{pct(total_key)}"
            )
        if self.kind == "spot":
            value = metrics.get("rms_spot_radius_um", metrics.get("rms_um", "—"))
            return f"光斑半径：{value} μm　·　峰值位置：{metrics.get('peak_position', '—')}"
        if self.kind == "ray_layout":
            return f"光线数量：{metrics.get('ray_count', '—')}　·　聚焦位置：{metrics.get('focus_position', '—')}"
        if self.kind == "wavefront":
            return f"波前 RMS：{metrics.get('wavefront_rms', '—')}　·　斯特列尔：{metrics.get('strehl', '—')}"
        if self.kind == "layout_3d":
            return "系统三维视图　·　与光路图使用同一份正式结果"
        return "当前页指标：等待正式结果"

    def _result_plot(self, result: dict[str, Any]) -> dict[str, Any]:
        keys = RESULT_PLOT_KEYS.get(self.kind, ())
        try:
            project = serialize_project(self.context.project.project)
        except Exception:
            project = {}
        plots = formal_result_to_plots(result, project, requested_keys=set(keys))
        for key in keys:
            payload = plots.get(key)
            if isinstance(payload, dict) and str(payload.get("kind", "empty")) != "empty":
                return self._apply_detector_overlay(payload)
        message = "正式结果已返回，但当前页暂未找到可绘制的数据。"
        diagnostics = formal_result_diagnostics(result)
        if diagnostics:
            message = f"{message}\n{diagnostics}"
        return {"kind": "empty", "message": message}

    def _apply_detector_overlay(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.kind not in {"ray_layout", "layout_3d"}:
            return payload
        overlay = _user_detector_object(self, payload)
        copied = dict(payload)
        objects = [
            dict(item)
            for item in payload.get("objects") or []
            if isinstance(item, dict) and not dict(item.get("metadata") or {}).get("user_detector")
        ]
        if overlay is not None:
            objects.append(overlay)
        copied["objects"] = objects
        return copied

    def _detail_text(self, result: dict[str, Any]) -> str:
        lines = [
            f"结果来源：{result.get('source', '正式计算')}",
            f"状态：{result.get('status', '—')}",
            formal_result_diagnostics(result),
        ]
        return "\n".join(item for item in lines if item)

    def _open_plot_window(self) -> None:
        window = QWidget(self, Qt.WindowType.Window)
        window.setWindowTitle(f"{_kind_titles('simulation', self.kind)[0]} · 独立窗口")
        window.resize(900, 620)
        layout = QVBoxLayout(window)
        view = LazyResultWorkspace(window)
        view.set_single_view_only(True)
        view.set_result(0, _kind_titles("simulation", self.kind)[0], self._last_plot)
        layout.addWidget(view, 1)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.show()
        self._plot_window = window

    def _sync_export_enabled(self) -> None:
        plot = dict(getattr(self, "_last_plot", {}) or {})
        self.export_button.setEnabled(str(plot.get("kind") or "empty") != "empty")

    def _export_plot(self) -> None:
        figure = getattr(self.workspace, "figure", None)
        if figure is None or str((self._last_plot or {}).get("kind") or "empty") == "empty":
            self.export_button.setEnabled(False)
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出结果", "analysis_result.png", "PNG 图像 (*.png)")
        if not path:
            return
        figure.savefig(path, dpi=220, bbox_inches="tight")


class AnalysisTextDocument(QWidget):
    shapRanksReady = Signal(object)

    def __init__(self, kind: str, selected: str = "", parent=None, context=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.selected = selected
        self.context = context
        self._dataset_cache: dict[str, dict[str, Any]] = {}
        self._current_cache: dict[str, dict[str, Any]] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        title, subtitle = KIND_TITLES.get(("explainability", kind), (kind, ""))
        del subtitle
        self.model = QComboBox()
        self.compute = _primary_button("计算解释")
        self.compute.clicked.connect(self._compute)
        self.feature_caption = QLabel(self._parameter_caption())
        self.scope_note = QLabel()
        self.scope_note.setObjectName("HelperText")
        self.scope_note.setWordWrap(True)
        if kind == "global_contrib":
            root.addWidget(_action_row(QLabel("解释模型"), self.model, self.compute))
            message = "选择已训练模型后计算，这里显示该模型全部训练特征在数据集上的平均 |SHAP|。"
            self.scope_note.setText("说明：全局贡献图按模型 manifest 的全部特征计算；左栏勾选项只用于优化，不会过滤 SHAP。")
        elif kind == "param_trend":
            root.addWidget(_action_row(QLabel("解释模型"), self.model, self.feature_caption, self.compute))
            message = "在左栏点一个参数后计算，这里显示该量取值与 SHAP 贡献。"
            self.scope_note.setText("说明：单参数依赖图只显示左栏当前选中的参数。")
        else:
            root.addWidget(_action_row(QLabel("解释模型"), self.model, self.compute))
            message = "计算后把当前镜头当作一条样本，用瀑布图拆开各参数贡献。"
            self.scope_note.setText("说明：当前系统图使用当前镜头组的实时参数，并按模型训练特征顺序解释。")
        root.addWidget(self.scope_note)
        self.workspace = LazyResultWorkspace(self)
        self.workspace.set_single_view_only(True)
        self.workspace.set_toolbar_visible(False)
        self.workspace.set_pane_header_visible(False)
        root.addWidget(self.workspace, 1)
        self.analysis_text = QLabel()
        self.analysis_text.setObjectName("HelperText")
        self.analysis_text.setWordWrap(True)
        self.analysis_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.analysis_text.hide()
        root.addWidget(self.analysis_text)
        # Formulas belong to the interpretation of a selected SHAP factor, not
        # to the teaching bench.  Keep this card below the conclusion so the
        # graph stays primary while the causal relation remains inspectable.
        self.formula_text = QLabel()
        self.formula_text.setObjectName("ExplainFormulaCard")
        self.formula_text.setWordWrap(True)
        self.formula_text.setTextFormat(Qt.TextFormat.RichText)
        self.formula_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.formula_text.hide()
        root.addWidget(self.formula_text)
        self.model.currentIndexChanged.connect(lambda _index: self._sync_compute_enabled())
        self._show(title, message)
        self._sync_compute_enabled()

    def set_explain_cache(self, dataset_cache: dict[str, dict[str, Any]], current_cache: dict[str, dict[str, Any]]) -> None:
        self._dataset_cache = dataset_cache
        self._current_cache = current_cache

    def set_trained_models(self, models: list[dict[str, Any]]) -> None:
        previous = self.model.currentData()
        previous_id = str((previous or {}).get("id") or "") if isinstance(previous, dict) else ""
        self.model.blockSignals(True)
        self.model.clear()
        for item in models:
            record = dict(item)
            self.model.addItem(str(record.get("title") or record.get("id") or "模型"), record)
        self.model.blockSignals(False)
        if previous_id:
            for index in range(self.model.count()):
                data = self.model.itemData(index)
                if isinstance(data, dict) and str(data.get("id") or "") == previous_id:
                    self.model.setCurrentIndex(index)
                    break
        self._sync_compute_enabled()

    def set_selected(self, key: str) -> None:
        self.selected = str(key or "")
        self.feature_caption.setText(self._parameter_caption())
        self._sync_compute_enabled()

    def set_model(self, title: str) -> None:
        text = str(title or "")
        if not text:
            return
        index = self.model.findText(text)
        if index >= 0:
            self.model.setCurrentIndex(index)
        self._sync_compute_enabled()

    def _parameter_caption(self) -> str:
        if self.kind != "param_trend":
            return ""
        if not self.selected:
            return "未选择参数"
        return display_feature_name(self.selected)

    def _current_record(self) -> dict[str, Any]:
        data = self.model.currentData()
        return dict(data) if isinstance(data, dict) else {}

    def _heading(self) -> str:
        return {
            "global_contrib": "全局贡献图",
            "param_trend": "单参数依赖图",
            "current_system": "当前系统瀑布图",
        }.get(self.kind, "解释图")

    def _sync_compute_enabled(self) -> None:
        record = self._current_record()
        model_id = str(record.get("id") or "")
        family = str(record.get("family") or record.get("model_type") or "")
        enabled = bool(model_id)
        reason = ""
        if not model_id:
            reason = "请先在模型页训练，再选择该模型。"
            enabled = False
        elif not shap_supported(family):
            reason = "这一版不算 SHAP"
            enabled = False
        elif self.kind == "param_trend" and not self.selected:
            reason = "请先在左栏选择一个参数。"
            enabled = False
        self.compute.setEnabled(enabled)
        self.compute.setToolTip(reason)
        if not enabled and reason and self.model.count() == 0:
            self._show(self._heading(), reason)

    def _compute(self) -> None:
        heading = self._heading()
        record = self._current_record()
        model_id = str(record.get("id") or "")
        family = str(record.get("family") or record.get("model_type") or "")
        if not model_id:
            self._show(heading, "请先在模型页训练，再选择该模型。")
            return
        if not shap_supported(family):
            self._show(heading, "这一版不算 SHAP")
            return
        if self.kind == "param_trend" and not self.selected:
            self._show(heading, "请先在左栏选择一个参数。")
            return
        cache = self._current_cache if self.kind == "current_system" else self._dataset_cache
        cached = dict(cache.get(model_id) or {})
        if cached:
            self._render_shap(cached)
            return
        api = getattr(self.context, "api_client", None) if self.context is not None else None
        if api is None:
            self._show(heading, "后端不可用（无 API 连接）")
            return
        from uuid import uuid4

        from frontend_pyside.features.canvas.explain_node import explain_shap_failure
        from frontend_pyside.infrastructure.api.clients import TrainingClient

        payload: dict[str, Any] = {"top_k": 8, "max_samples": 80, "background_sample_count": 80}
        design_paths = [str(path) for path in list(record.get("design_variable_paths") or []) if str(path)]
        if design_paths:
            payload["display_feature_paths"] = design_paths
        if self.kind == "current_system":
            project = getattr(getattr(self.context, "project", None), "project", None)
            try:
                payload["features"] = model_features(project, record)
            except FeaturePathError as exc:
                self._show(heading, f"当前镜头无法构造模型特征：{exc}")
                return
        self._token = f"workbench.explain.{uuid4().hex[:8]}"
        self._show(heading, "正在计算解释…")
        if not getattr(self, "_api_bound", False):
            api.completed.connect(self._on_explain_completed)
            api.failed.connect(self._on_explain_failed)
            self._api_bound = True
        self._failure_text = explain_shap_failure
        TrainingClient(api).explain_shap(self._token, model_id, payload)

    def _on_explain_completed(self, key: str, data: object) -> None:
        if str(key) != getattr(self, "_token", ""):
            return
        body = dict(data or {}) if isinstance(data, dict) else {}
        if isinstance(body.get("result"), dict) and not body.get("top_features"):
            body = dict(body.get("result") or {})
        record = self._current_record()
        model_id = str(record.get("id") or "")
        if model_id:
            cache = self._current_cache if self.kind == "current_system" else self._dataset_cache
            cache[model_id] = body
        self._render_shap(body)

    def _on_explain_failed(self, key: str, message: str) -> None:
        if str(key) != getattr(self, "_token", ""):
            return
        from frontend_pyside.features.canvas.explain_node import explain_shap_failure

        self._show(self._heading(), explain_shap_failure(message))

    def _render_shap(self, body: dict[str, Any]) -> None:
        from frontend_pyside.shared.feature_labels import display_feature_name as label_of
        from frontend_pyside.features.explainability.actions import (
            formula_binding_for_feature,
            formula_latex,
            physical_mechanism_for_feature,
            suggested_action_for_feature,
        )
        from frontend_pyside.features.explainability.formula_presentation import formula_html

        target_name = str(body.get("target_name") or "模型输出")
        target_unit = str(body.get("target_unit") or "").strip()
        target_label = f"{target_name}（{target_unit}）" if target_unit else target_name
        run_id = str(body.get("explanation_run_id") or "")
        hidden_count = int(body.get("hidden_feature_count") or 0)

        def feature_label(value: object) -> str:
            key = str(value or "")
            return "其他模型特征（合并）" if key == "__other_model_features__" else label_of(key)

        def show_analysis(feature: str, importance: float, direction: str, *, verified: bool = False) -> None:
            if not feature:
                self.analysis_text.hide()
                self.formula_text.hide()
                return
            name = feature_label(feature)
            mechanism = physical_mechanism_for_feature(feature)
            action = suggested_action_for_feature(feature)
            parts = [
                f"模型分析：{name}是当前结果中的主要影响变量，贡献幅度为 {importance:.4g}{(' ' + target_unit) if target_unit else ''}。",
                f"物理联系：{mechanism}",
            ]
            if direction:
                parts.append(f"趋势判断：{direction}")
            parts.append(f"下一步：{action}，并用正式光学计算复核。")
            parts.append("验证状态：已关联当前正式仿真。" if verified else "验证状态：模型推断，尚未经过本次正式仿真验证。")
            if hidden_count:
                parts.append(f"说明：模型还使用了 {hidden_count} 个内部物理特征；主排行仅展示可调整设计变量，局部图将其合并为“其他模型特征”。")
            if run_id:
                parts.append(f"解释任务：{run_id}")
            self.analysis_text.setText("\n".join(parts))
            self.analysis_text.show()
            category, item, level, note = formula_binding_for_feature(feature)
            if category and item:
                relation = formula_html(category, item, formula_latex(category, item))
                self.formula_text.setText(
                    f"<b>物理公式：{category} · {item}</b>{relation}"
                    f"<div style='padding:0 8px 8px; color:#465467;'>"
                    f"关联方式：{level}。{note}<br>"
                    "说明：公式描述物理传播关系；SHAP 仅用于模型贡献排序，结论须由正式仿真验证。"
                    "</div>"
                )
                self.formula_text.show()
            else:
                self.formula_text.hide()

        if self.kind == "param_trend":
            item = shap_dependence_item(body, self.selected)
            if not item:
                for feature, data in dict(body.get("shap_dependence") or {}).items():
                    if _shap_feature_key(str(feature), [self.selected]) == self.selected:
                        item = dict(data)
                        break
            xs = list(item.get("feature_value") or item.get("x") or [])
            ys = list(item.get("shap_value") or item.get("y") or [])
            if not xs or not ys:
                self._show("单参数依赖图", "这次解释没有返回该参数的 SHAP 依赖。")
                return
            self.workspace.set_result(
                0,
                "单参数依赖图",
                {
                    "kind": "scatter",
                    "x": xs,
                    "y": ys,
                    "x_label": label_of(self.selected),
                    "y_label": f"SHAP 贡献 · {target_label}",
                    "zero_line": True,
                },
            )
            direction = "样本范围内未形成稳定方向。"
            if len(xs) >= 2:
                delta = float(ys[-1]) - float(ys[0])
                if abs(delta) > 1.0e-12:
                    direction = "变量增大时模型输出总体上升。" if delta > 0 else "变量增大时模型输出总体下降。"
            show_analysis(self.selected, max((abs(float(value)) for value in ys), default=0.0), direction)
            return
        if self.kind == "current_system":
            targets = list(body.get("targets") or [])
            sample = {}
            if targets:
                rows = list(targets[0].get("sample_shap_values") or [])
                sample = dict(rows[0]) if rows else {}
            values = sample.get("shap_values") or sample.get("values") or {}
            if not isinstance(values, dict) or not values:
                contrib = list(body.get("feature_contributions") or body.get("top_features") or [])
                labels = [label_of(item.get("feature")) for item in contrib]
                shap_values = [float(item.get("shap_value", item.get("mean_shap", 0.0)) or 0.0) for item in contrib]
            else:
                labels = [label_of(name) for name in values]
                shap_values = [float(values[name] or 0.0) for name in values]
            if not labels:
                self._show("当前系统瀑布图", "这次解释没有返回当前样本的贡献。")
                return
            additivity_error = sample.get("additivity_error", body.get("additivity_error"))
            prediction = sample.get("prediction")
            if additivity_error is not None:
                tolerance = 1.0e-6 * max(1.0, abs(float(prediction or 0.0)))
                if abs(float(additivity_error)) > tolerance:
                    self._show(
                        "当前系统瀑布图",
                        f"SHAP贡献无法闭合当前预测（加性误差 {float(additivity_error):.4g}），已停止绘图。",
                    )
                    self.analysis_text.setText("解释结果无效：基准值与各变量贡献之和不等于模型预测值。")
                    self.analysis_text.show()
                    return
            self.workspace.set_result(
                0,
                "当前系统瀑布图",
                {
                    "kind": "waterfall",
                    "labels": [feature_label(label) for label in (values.keys() if isinstance(values, dict) and values else labels)],
                    "values": shap_values,
                    "base_value": float((body.get("base_values") or {}).get(str(body.get("target_name") or ""), 0.0) or 0.0),
                    "summary": f"目标：{target_label}",
                },
            )
            top_index = max(range(len(shap_values)), key=lambda index: abs(shap_values[index]))
            raw_features = list(values.keys()) if isinstance(values, dict) and values else labels
            top_feature = str(raw_features[top_index])
            if top_feature == "__other_model_features__":
                self.analysis_text.setText(
                    "模型分析：当前样本主要受内部物理特征的合并贡献影响。\n"
                    "物理联系：这些量由设计变量和正式光学计算共同产生，不能当作可直接调整参数。\n"
                    "下一步：返回全局贡献或单参数规律，选择曲率半径、厚度或圆锥系数进行验证。\n"
                    "验证状态：模型推断，尚未经过本次正式仿真验证。"
                )
                self.analysis_text.show()
                self.formula_text.hide()
            else:
                formal_result = getattr(getattr(self.context, "project", None), "formal_result", None)
                show_analysis(
                    top_feature,
                    abs(shap_values[top_index]),
                    "该变量在当前样本中提高模型输出。" if shap_values[top_index] >= 0 else "该变量在当前样本中降低模型输出。",
                    verified=isinstance(formal_result, dict) and bool(formal_result),
                )
            return
        items = list(body.get("top_features") or body.get("feature_contributions") or body.get("global_importance") or [])
        if not items:
            self._show("全局贡献图", "这次解释没有返回全局贡献。")
            return
        labels = [feature_label(item.get("feature") or item.get("name")) for item in items]
        values = [float(item.get("mean_abs_shap", abs(float(item.get("mean_shap", 0.0) or 0.0))) or 0.0) for item in items]
        self.workspace.set_result(
            0,
            "全局贡献图",
            {
                "kind": "barh",
                "labels": labels,
                "values": values,
                "show_values": True,
                "source": "模型解释",
                "x_label": f"平均 |SHAP| · {target_label}",
                "description": "数值越大表示模型越依赖该设计变量；不等同于物理因果。",
            },
        )
        top = dict(items[0])
        feature = str(top.get("feature") or top.get("name") or "")
        signed = float(top.get("mean_shap", top.get("mean_signed_shap", 0.0)) or 0.0)
        share = float(top.get("relative_importance", 0.0) or 0.0)
        direction = (
            "不同样本中的正负影响可能抵消，请在单参数规律中判断趋势。"
            if abs(signed) < 1.0e-12
            else ("平均上使模型输出提高。" if signed > 0 else "平均上使模型输出降低。")
        )
        if share > 0.0:
            direction += f" 在当前展示变量中的相对重要性为 {share * 100.0:.1f}%。"
        show_analysis(feature, values[0], direction)
        project = getattr(getattr(self.context, "project", None), "project", None) if self.context is not None else None
        keys = [row[0] for row in _variable_rows(project)] if project is not None else []
        self.shapRanksReady.emit(_variable_shap_scores(items, keys))

    def _show(self, title: str, message: str) -> None:
        self.workspace.set_result(0, title, {"kind": "empty", "message": message})
        self.analysis_text.hide()
        self.formula_text.hide()


class ModelDocument(QWidget):
    trainRequested = Signal()
    generateRequested = Signal()
    predictRequested = Signal()
    datasetGenerated = Signal(str)
    fileImportRequested = Signal(str)
    dataKindChanged = Signal(str)

    def __init__(self, kind: str, context, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.context = context
        self._trained = False
        self._train_result: dict[str, Any] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        if kind == "dataset":
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            content = QWidget()
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(8)
            self._build_dataset(content_layout)
            scroll.setWidget(content)
            root.addWidget(scroll)
            self.dataset_scroll = scroll
        elif kind == "train_result":
            self._build_train_result(root)
        else:
            self._build_predict(root)

    def current_family(self) -> str:
        combo = getattr(self, "data_kind", None)
        if combo is None:
            return "tabular"
        return str(combo.currentData() or "tabular")

    def _build_dataset(self, root: QVBoxLayout) -> None:
        layout = root
        source, source_layout = _field_group("1. 选择数据")
        kind_row = QHBoxLayout()
        kind_row.setContentsMargins(0, 0, 0, 0)
        kind_row.setSpacing(8)
        self.data_kind = QComboBox()
        self.data_kind.addItem("按镜头采样", "tabular")
        self.data_kind.addItem("按元件排列", "sequence")
        kind_row.addWidget(QLabel("方式"))
        kind_row.addWidget(self.data_kind, 1)
        source_layout.addLayout(kind_row)
        pick_row = QHBoxLayout()
        pick_row.setContentsMargins(0, 0, 0, 0)
        pick_row.setSpacing(8)
        self.builtin = QComboBox()
        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText("选择 CSV / JSONL 样本文件")
        browse = QPushButton("选择文件")
        browse.clicked.connect(self._choose_file)
        pick_row.addWidget(QLabel("内置"))
        pick_row.addWidget(self.builtin, 1)
        pick_row.addWidget(self.file_path, 2)
        pick_row.addWidget(browse)
        source_layout.addLayout(pick_row)
        layout.addWidget(source)

        generate, generate_layout = _field_group("2. 生成样本")
        self.generate_host = generate
        param_grid = QGridLayout()
        param_grid.setContentsMargins(0, 0, 0, 0)
        param_grid.setHorizontalSpacing(12)
        self.generate_checks: dict[str, QCheckBox] = {}
        self.lens_count = QComboBox()
        for label, value in (("单透镜", 1), ("双透镜", 2), ("三透镜", 3), ("四透镜", 4)):
            self.lens_count.addItem(label, value)
        self.lens_count.setCurrentIndex(3)
        self.variable_scheme = QComboBox()
        self.variable_scheme.addItem("曲率半径 + 厚度", "basic")
        self.variable_scheme.addItem("曲率半径 + 厚度 + 圆锥系数", "asphere")
        self.scheme_summary = QLabel("四透镜·基础方案 · 12 个设计变量；内部物理量自动计算")
        self.scheme_summary.setObjectName("HelperText")
        param_grid.addWidget(QLabel("研究对象"), 0, 0)
        param_grid.addWidget(self.lens_count, 0, 1)
        param_grid.addWidget(QLabel("变量方案"), 0, 2)
        param_grid.addWidget(self.variable_scheme, 0, 3)
        param_grid.addWidget(self.scheme_summary, 1, 0, 1, 4)
        self.lens_count.currentIndexChanged.connect(self._sync_scheme_summary)
        self.variable_scheme.currentIndexChanged.connect(self._sync_scheme_summary)
        generate_layout.addLayout(param_grid)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.sampling = QComboBox()
        self.sampling.addItems(list(DATASET_SAMPLING_CHOICES))
        self.samples = _spin(8, 100000, 0, "", 50)
        self.target = QComboBox()
        self.target.addItems(list(DATASET_TARGET_CHOICES))
        self.split = _spin(0.05, 0.4, 2, "", 0.15)
        self.seed = _spin(0, 1e9, 0, "", 42)
        self.precision = QComboBox()
        self.precision.addItems(list(DATASET_PRECISION_CHOICES))
        self.precision.setCurrentText("257×257")
        grid.addWidget(QLabel("采样方法"), 0, 0)
        grid.addWidget(self.sampling, 0, 1)
        grid.addWidget(QLabel("样本数"), 0, 2)
        grid.addWidget(self.samples, 0, 3)
        grid.addWidget(QLabel("目标变量"), 1, 0)
        grid.addWidget(self.target, 1, 1)
        grid.addWidget(QLabel("验证集比例"), 1, 2)
        grid.addWidget(self.split, 1, 3)
        grid.addWidget(QLabel("随机种子"), 2, 0)
        grid.addWidget(self.seed, 2, 1)
        grid.addWidget(QLabel("计算精度"), 2, 2)
        grid.addWidget(self.precision, 2, 3)
        generate_layout.addLayout(grid)
        self.generate_button = _primary_button("生成数据集")
        self.generate_button.clicked.connect(self.generateRequested.emit)
        generate_layout.addWidget(self.generate_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(generate)

        sequence, sequence_layout = _field_group("列对应（自定义文件）")
        self.sequence_host = sequence
        self.system_id_column = QLineEdit("system_id")
        self.order_column = QLineEdit("element_index")
        self.element_type_column = QLineEdit("element_type")
        self.numeric_columns = QLineEdit("radius_mm,thickness_mm")
        self.sequence_target = QLineEdit("coupling_efficiency")
        sequence_layout.addLayout(
            _field_grid(
                [
                    _labeled_field("系统编号列", self.system_id_column),
                    _labeled_field("元件顺序列", self.order_column),
                    _labeled_field("元件类型列", self.element_type_column),
                    _labeled_field("半径/厚度列", self.numeric_columns),
                    _labeled_field("目标列", self.sequence_target),
                ],
                columns=2,
            )
        )
        layout.addWidget(sequence)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["编号", "选择的参数", "波长属性", "状态"])
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.setMinimumHeight(120)
        _stretch_table(self.table)
        layout.addWidget(self.table, 1)

        train_box, train_layout = _field_group("3. 训练")
        self.model_type = QComboBox()
        self.rf_trees = _spin(1, 10000, 0, "", 300)
        self.rf_depth = _spin(0, 256, 0, "", 0)
        self.rf_min_leaf = _spin(1, 100, 0, "", 1)
        self.rf_max_features = QComboBox()
        self.rf_max_features.addItems(["sqrt", "log2", "1.0"])
        self.xgb_rounds = _spin(10, 10000, 0, "", 300)
        self.xgb_lr = _spin(0.000001, 1.0, 6, "", 0.05)
        self.xgb_depth = _spin(1, 32, 0, "", 4)
        self.xgb_subsample = _spin(0.01, 1.0, 2, "", 0.9)
        self.xgb_colsample = _spin(0.01, 1.0, 2, "", 0.95)
        self.lstm_epochs = _spin(1, 5000, 0, "", 200)
        self.lstm_batch = _spin(1, 1024, 0, "", 32)
        self.rf_training_group, rf_layout = _field_group("随机森林 · 直接效率基准")
        rf_layout.addLayout(_field_grid([
            _labeled_field("树数量", self.rf_trees),
            _labeled_field("最大深度（0=自动）", self.rf_depth),
            _labeled_field("叶节点最小样本", self.rf_min_leaf),
            _labeled_field("最大特征", self.rf_max_features),
        ], columns=2))
        self.xgb_training_group, xgb_layout = _field_group("XGBoost · 物理公式残差主模型")
        xgb_layout.addLayout(_field_grid([
            _labeled_field("迭代轮数", self.xgb_rounds),
            _labeled_field("学习率", self.xgb_lr),
            _labeled_field("最大深度", self.xgb_depth),
            _labeled_field("样本采样率", self.xgb_subsample),
            _labeled_field("特征采样率", self.xgb_colsample),
        ], columns=2))
        self.sequence_training_group, sequence_train_layout = _field_group("BiLSTM · 序列模型")
        self.bilstm_placeholder = QLabel("暂未纳入当前闭环；仅在选择序列数据时启用。")
        self.bilstm_placeholder.setObjectName("HelperText")
        sequence_train_layout.addWidget(self.bilstm_placeholder)
        sequence_train_layout.addLayout(_field_grid([
            _labeled_field("最大轮数", self.lstm_epochs),
            _labeled_field("批大小", self.lstm_batch),
        ], columns=2))
        train_layout.addWidget(self.rf_training_group)
        train_layout.addWidget(self.xgb_training_group)
        train_layout.addWidget(self.sequence_training_group)
        self.train_button = _primary_button("开始联合训练")
        self.train_button.clicked.connect(self.trainRequested.emit)
        train_layout.addWidget(_action_row(self.model_type, self.train_button))
        layout.addWidget(train_box)
        self.data_kind.currentIndexChanged.connect(lambda _index: self._apply_family())
        self.file_path.textChanged.connect(lambda _text: self._refresh_sequence_mapping())
        self.model_type.currentTextChanged.connect(lambda _text: self._sync_train_hypers())
        self._apply_family(emit=False)
        self._sync_scheme_summary()

    def _sync_scheme_summary(self) -> None:
        count = int(self.lens_count.currentData() or 1)
        conic = self.variable_scheme.currentData() == "asphere"
        total = count * (5 if conic else 3)
        try:
            from machine_learning.datasets.variable_schemes import resolve_variable_scheme

            project = serialize_project(self.context.project.project)
            total = len(resolve_variable_scheme(
                project, lens_count=count, include_conic=conic
            ).design_variable_paths)
        except (AttributeError, TypeError, ValueError, IndexError):
            pass
        prefix = ("单", "双", "三", "四")[count - 1]
        self.scheme_summary.setText(
            f"{prefix}透镜·{'非球面' if conic else '基础'}方案 · {total} 个当前可变设计变量；内部物理量自动计算"
        )

    def _refresh_sequence_mapping(self) -> None:
        family = self.current_family()
        has_file = bool(self.file_path.text().strip())
        host = getattr(self, "sequence_host", None)
        if host is not None:
            host.setVisible(family == "sequence" and has_file)

    def _fill_builtins(self, family: str) -> None:
        # The packaged item below is an actual registered dataset ID.  Do not
        # offer decorative names that cannot be submitted to the training API.
        records = (
            (("内置演示·780 nm 四透镜耦合", "dataset-880bdde6c292"),)
            if family == "tabular" else ()
        )
        current = self.builtin.currentText()
        self.builtin.blockSignals(True)
        self.builtin.clear()
        for label, dataset_id in records:
            self.builtin.addItem(label, dataset_id)
        if not records:
            self.builtin.addItem("序列模型请使用自定义文件", "")
        index = self.builtin.findText(current)
        if index >= 0:
            self.builtin.setCurrentIndex(index)
        self.builtin.blockSignals(False)

    def _apply_family(self, *, emit: bool = True) -> None:
        family = self.current_family()
        has_file = bool(self.file_path.text().strip())
        self.generate_host.setVisible(family == "tabular")
        self.sequence_host.setVisible(family == "sequence" and has_file)
        self._fill_builtins(family)
        self.model_type.clear()
        self.model_type.addItems(list(TABULAR_MODEL_CHOICES if family == "tabular" else SEQUENCE_MODEL_CHOICES))
        self._sync_train_hypers()
        if family == "tabular":
            self.table.setHorizontalHeaderLabels(["编号", "选择的参数", "波长属性", "状态"])
            self.file_path.setPlaceholderText("选择 CSV / JSONL 表格样本")
        else:
            self.table.setHorizontalHeaderLabels(["系统", "元件顺序", "类型", "状态"])
            if not has_file:
                self.table.setRowCount(0)
            self.file_path.setPlaceholderText("选择自定义长表后映射列；内置结构表无需映射")
        _stretch_table(self.table)
        if emit:
            self.dataKindChanged.emit(family)

    def _set_family(self, family: str) -> None:
        index = self.data_kind.findData(family)
        if index < 0:
            return
        if self.data_kind.currentIndex() != index:
            blocked = self.data_kind.blockSignals(True)
            self.data_kind.setCurrentIndex(index)
            self.data_kind.blockSignals(blocked)
            self._apply_family()
        elif str(self.data_kind.currentData() or "") != family:
            self._apply_family()

    def _sync_train_hypers(self) -> None:
        tabular = self.current_family() == "tabular"
        self.model_type.setVisible(not tabular)
        self.rf_training_group.setVisible(tabular)
        self.xgb_training_group.setVisible(tabular)
        self.sequence_training_group.setVisible(not tabular)
        self.train_button.setText("开始联合训练" if tabular else "训练 BiLSTM")

    def train_hyperparameters(self) -> dict[str, Any]:
        name = str(self.model_type.currentText() or "")
        if name == "随机森林":
            return {"n_estimators": int(self.rf_trees.value()), "max_depth": int(self.rf_depth.value())}
        if name == "XGBoost物理残差":
            return {"n_estimators": int(self.xgb_rounds.value()), "learning_rate": float(self.xgb_lr.value())}
        if name == "BiLSTM":
            return {"max_epochs": int(self.lstm_epochs.value()), "batch_size": int(self.lstm_batch.value())}
        return {}

    def random_forest_hyperparameters(self) -> dict[str, Any]:
        value = str(self.rf_max_features.currentText() or "sqrt")
        max_features: Any = float(value) if value == "1.0" else value
        return {
            "n_estimators": int(self.rf_trees.value()),
            "max_depth": int(self.rf_depth.value()),
            "min_samples_leaf": int(self.rf_min_leaf.value()),
            "max_features": max_features,
        }

    def xgboost_hyperparameters(self) -> dict[str, Any]:
        return {
            "n_estimators": int(self.xgb_rounds.value()),
            "learning_rate": float(self.xgb_lr.value()),
            "max_depth": int(self.xgb_depth.value()),
            "subsample": float(self.xgb_subsample.value()),
            "colsample_bytree": float(self.xgb_colsample.value()),
        }

    def set_job_busy(self, busy: bool) -> None:
        generate = getattr(self, "generate_button", None)
        train = getattr(self, "train_button", None)
        if generate is not None:
            generate.setEnabled(not busy)
        if train is not None:
            train.setEnabled(not busy)

    def _build_train_result(self, root: QVBoxLayout) -> None:
        self.chart = QComboBox()
        self.chart.addItems(["残差图", "实测对照", "学习曲线"])
        self.chart.currentTextChanged.connect(self._show_train_chart)
        root.addWidget(_action_row(self.chart))
        self.train_summary = QLabel("尚未训练")
        self.train_summary.setObjectName("DocumentMetric")
        self.train_summary.setWordWrap(True)
        root.addWidget(self.train_summary)
        self.workspace = LazyResultWorkspace(self)
        self.workspace.set_single_view_only(True)
        self.workspace.set_toolbar_visible(False)
        self.workspace.set_pane_header_visible(False)
        root.addWidget(self.workspace, 1)
        self._show_train_chart(self.chart.currentText())

    def _build_predict(self, root: QVBoxLayout) -> None:
        setup, setup_layout = _field_group("1. 设置")
        self.predict_model = QComboBox()
        self.predict_target = QLabel("尚未训练")
        self.predict_target.setObjectName("HelperText")
        run = _primary_button("预测")
        self.predict_run = run
        setup_layout.addWidget(
            _action_row(QLabel("已训练模型"), self.predict_model, QLabel("目标"), self.predict_target, run)
        )
        root.addWidget(setup)

        inputs, input_layout = _field_group("2. 当前镜头")
        inputs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.input_table = QTableWidget(0, 2)
        self.input_table.setHorizontalHeaderLabels(["参数", "当前值"])
        _stretch_table(self.input_table)
        input_layout.addWidget(self.input_table, 1)
        root.addWidget(inputs, 1)

        result, result_layout = _field_group("3. 结果")
        self.result_table = QTableWidget(0, 2)
        self.result_table.setHorizontalHeaderLabels(["量", "值"])
        _stretch_table(self.result_table)
        result_layout.addWidget(self.result_table)
        self.metrics = QLabel("选择已训练模型后，用上面这组当前镜头参数做预测。")
        self.metrics.setObjectName("DocumentMetric")
        self.metrics.setWordWrap(True)
        result_layout.addWidget(self.metrics)
        root.addWidget(result)
        run.clicked.connect(self.predictRequested.emit)
        self.predict_model.currentIndexChanged.connect(self._sync_predict_target)
        self._fill_predict_inputs()
        self._set_predict_models([])

    def set_trained_models(self, models: list[dict[str, Any]]) -> None:
        if self.kind != "predict_eval" and self.kind != "predict":
            return
        self._set_predict_models(models)

    def _set_predict_models(self, models: list[dict[str, Any]]) -> None:
        combo = getattr(self, "predict_model", None)
        if combo is None:
            return
        previous = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        for item in models:
            record = dict(item)
            title = str(record.get("title") or record.get("id") or "模型")
            _usable, reason = model_prediction_status(record)
            combo.addItem(title, record)
            index = combo.count() - 1
            if reason:
                combo.setItemData(index, reason, Qt.ItemDataRole.ToolTipRole)
        combo.blockSignals(False)
        if previous and combo.findText(previous) >= 0:
            combo.setCurrentText(previous)
        elif combo.count():
            combo.setCurrentIndex(0)
        self._sync_predict_target()

    def _sync_predict_target(self) -> None:
        label = getattr(self, "predict_target", None)
        combo = getattr(self, "predict_model", None)
        if label is None or combo is None:
            return
        record = combo.currentData()
        if isinstance(record, dict) and record.get("target"):
            target = str(record.get("target"))
            usable, reason = model_prediction_status(record)
            label.setText(target if usable else f"{target}（模型质量未达标）")
            label.setToolTip(reason)
        elif combo.count() == 0:
            label.setText("尚未训练")
            label.setToolTip("")
        else:
            label.setText("耦合损耗(dB)")
            label.setToolTip("")
        button = getattr(self, "predict_run", None)
        if button is not None:
            usable, reason = model_prediction_status(record if isinstance(record, dict) else None)
            button.setEnabled(combo.count() > 0 and usable)
            button.setToolTip(reason)
        self._fill_predict_inputs()

    def _fill_predict_inputs(self) -> None:
        table = getattr(self, "input_table", None)
        if table is None:
            return
        record = self.predict_model.currentData() if getattr(self, "predict_model", None) is not None else None
        if isinstance(record, dict) and record.get("feature_paths"):
            try:
                values = model_features(self.context.project.project, record)
                raw_units = record.get("feature_units") or []
                units = (
                    {str(key): str(value) for key, value in raw_units.items()}
                    if isinstance(raw_units, dict)
                    else {
                        str(path): str(raw_units[index])
                        for index, path in enumerate(record.get("feature_paths") or [])
                        if index < len(raw_units)
                    }
                )
                display_paths = [str(path) for path in (record.get("design_variable_paths") or [])]
                if not display_paths:
                    display_paths = [
                        str(path)
                        for path in record.get("feature_paths") or []
                        if str(path).endswith((".radius_mm", ".distance_to_next_mm", ".conic"))
                    ]
                if not display_paths:
                    display_paths = [str(path) for path in record.get("feature_paths") or []]
                rows = [
                    (
                        display_feature_name(path),
                        f"{float(values[path]):.6g} {units.get(str(path), '')}".rstrip(),
                    )
                    for path in display_paths
                    if str(path) in values
                ]
            except FeaturePathError as exc:
                rows = [("模型输入", f"当前镜头无法构造：{exc}")]
        else:
            rows = _current_lens_feature_rows(self.context)
        table.setRowCount(len(rows))
        for index, (name, value) in enumerate(rows):
            table.setItem(index, 0, QTableWidgetItem(name))
            table.setItem(index, 1, QTableWidgetItem(value))
        _stretch_table(table)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择数据集文件", "", "数据文件 (*.csv *.jsonl *.json)")
        if path:
            self.file_path.setText(path)
            self.fileImportRequested.emit(path)

    def _generate(self) -> None:
        self.generateRequested.emit()

    def show_generate_status(self, message: str, rows: list[tuple[str, str, str, str]] | None = None) -> None:
        table = getattr(self, "table", None)
        if table is None:
            return
        records = list(rows or [("—", "—", "—", message)])
        table.setRowCount(len(records))
        for index, (ident, selected, wavelength, status) in enumerate(records):
            table.setItem(index, 0, QTableWidgetItem(ident))
            table.setItem(index, 1, QTableWidgetItem(selected))
            table.setItem(index, 2, QTableWidgetItem(wavelength))
            table.setItem(index, 3, QTableWidgetItem(status))
        _stretch_table(table)

    def select_dataset(self, title: str) -> None:
        text = str(title or "")
        if text in SEQUENCE_DATASET_CHOICES:
            self._set_family("sequence")
        elif text in TABULAR_DATASET_CHOICES:
            self._set_family("tabular")
        index = self.builtin.findText(text)
        if index >= 0:
            self.builtin.setCurrentIndex(index)

    def select_predict_model(self, title: str) -> None:
        combo = getattr(self, "predict_model", None)
        if combo is None:
            return
        text = str(title)
        if combo.findText(text) >= 0:
            combo.setCurrentText(text)
        self._sync_predict_target()

    def show_train_chart(self, name: str) -> None:
        combo = getattr(self, "chart", None)
        if combo is not None:
            combo.setCurrentText(str(name))

    def mark_trained(self, result: dict[str, Any] | None = None) -> None:
        self._trained = True
        self._train_result = dict(result or {})
        summary = dict(self._train_result.get("training_summary") or {})
        test = dict(self._train_result.get("test_metrics") or {})
        parts = ["训练完成"]
        sample_count = summary.get("sample_count") or summary.get("training_samples")
        if sample_count is not None:
            parts.append(f"训练样本 {sample_count}")
        if test.get("r2") is not None:
            parts.append(f"测试 R²={float(test['r2']):.3f}")
        if test.get("rmse") is not None:
            parts.append(f"RMSE={float(test['rmse']):.4g}")
        if getattr(self, "train_summary", None) is not None:
            self.train_summary.setText(" · ".join(parts) + "。图中只展示返回的真实测试集记录。")
        if self.kind == "train_result":
            self._show_train_chart(self.chart.currentText())

    def mark_joint_trained(self, result: dict[str, Any]) -> None:
        body = dict(result or {})
        rf = dict(body.get("random_forest") or {})
        xgb = dict(body.get("xgboost") or {})
        partial = str(body.get("status") or "completed") == "partial" or not xgb
        self._trained = bool(xgb or rf)
        self._train_result = xgb or rf

        def score(item: dict[str, Any]) -> str:
            value = dict(item.get("test_metrics") or {}).get("r2")
            return f"R²={float(value):.3f}" if isinstance(value, (int, float)) else "已完成"

        if partial:
            warning = "；".join(str(item) for item in list(body.get("warnings") or []))
            self.train_summary.setText(
                f"联合训练部分完成 · 随机森林 {score(rf)} · XGBoost 未完成。"
                + (f"原因：{warning}" if warning else "")
                + " 随机森林结果可用于设计变量解释；请修复数据后再训练 XGBoost。"
            )
        else:
            self.train_summary.setText(
                f"联合训练完成 · 随机森林 {score(rf)} · XGBoost {score(xgb)} · "
                "XGBoost为主预测，随机森林用于设计变量解释和对照。"
            )
        self._show_train_chart(self.chart.currentText())

    def show_train_status(self, message: str) -> None:
        self._trained = False
        self._train_result = {}
        if getattr(self, "train_summary", None) is not None:
            self.train_summary.setText(str(message))
        workspace = getattr(self, "workspace", None)
        if workspace is not None:
            workspace.set_result(0, "训练结果", {"kind": "empty", "message": message})

    def _show_train_chart(self, name: str) -> None:
        if not self._trained:
            self.workspace.set_result(0, name, {"kind": "empty", "message": "先在数据集页训练，再查看残差图等训练结果。"})
            return
        payload = train_chart_payload(getattr(self, "_train_result", {}) or {}, name)
        if payload is None:
            self.workspace.set_result(
                0,
                name,
                {"kind": "empty", "message": train_chart_unavailable_message(self._train_result, name)},
            )
            return
        self.workspace.set_result(0, name, payload)

    def show_predict_status(self, message: str) -> None:
        self.metrics.setVisible(True)
        self.metrics.setText(message)
        self.result_table.setRowCount(0)

    def show_predict_result(self, rows: list[tuple[str, str]]) -> None:
        self.metrics.hide()
        self.result_table.setRowCount(len(rows))
        for index, (name, value) in enumerate(rows):
            self.result_table.setItem(index, 0, QTableWidgetItem(name))
            self.result_table.setItem(index, 1, QTableWidgetItem(value))
        _stretch_table(self.result_table)

    def _run_predict(self) -> None:
        self.predictRequested.emit()


class QSpinBoxCompat(QDoubleSpinBox):
    """Integer-looking control without adding another dependency to the shell."""

    def __init__(self, value: int, minimum: int, maximum: int, parent=None) -> None:
        super().__init__(parent)
        self.setDecimals(0)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setKeyboardTracking(False)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setRange(minimum, maximum)
        self.setValue(value)


class OptimizationDocument(QWidget):
    startRequested = Signal()
    scanRequested = Signal()
    applyAndVerifyRequested = Signal(object, str, object)

    def __init__(self, kind: str, context, selected: set[str], parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.context = context
        self.selected = selected
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        if kind == "scan":
            settings, settings_layout = _field_group("设置")
            self.mode = QComboBox()
            self.mode.addItems(list(SCAN_MODE_CHOICES))
            self.response = QComboBox()
            self.response.addItems(list(SCAN_RESPONSE_CHOICES))
            self.scale = QComboBox()
            self.scale.addItems(list(SCAN_SCALE_CHOICES))
            self.points = _spin(5, 401, 0, "", 21)
            self.scan_summary = QLabel("（未勾选）")
            self.range_table = QTableWidget(0, 3)
            self.range_table.setHorizontalHeaderLabels(["参数", "最小", "最大"])
            _stretch_table(self.range_table)
            settings_layout.addLayout(
                _field_grid(
                    [
                        _labeled_field("模式", self.mode),
                        _labeled_field("响应量", self.response),
                        _labeled_field("采样尺度", self.scale),
                        _labeled_field("采样点数", self.points),
                        _labeled_field("变量", self.scan_summary),
                    ],
                    columns=2,
                )
            )
            settings_layout.addWidget(self.range_table)
            self.run_button = _primary_button("运行")
            self.run_button.clicked.connect(self.scanRequested.emit)
            settings_layout.addWidget(self.run_button, 0, Qt.AlignmentFlag.AlignLeft)
            root.addWidget(settings)
            self.workspace = LazyResultWorkspace(self)
            self.workspace.set_single_view_only(True)
            self.workspace.set_toolbar_visible(False)
            self.workspace.set_pane_header_visible(False)
            root.addWidget(self.workspace, 1)
            self.workspace.set_result(0, "响应曲线", {"kind": "empty", "message": "勾选 1～2 个变量并运行后，这里显示响应曲线。"})
            self._fill_scan()
        elif kind == "opt_vars":
            self.goal = OptimizationGoalInspector(self.context)
            root.addWidget(self.goal)
            self.max_evaluations = _spin(10, 100000, 0, "", 300)
            self.start_button = _primary_button("开始优化")
            self.start_button.clicked.connect(self.startRequested.emit)
            self.start_button.setEnabled(bool(self.selected))
            self.start_button.setToolTip("" if self.selected else "请先在左栏勾选优化变量。")
            root.addWidget(_action_row(_labeled_field("最大评价次数", self.max_evaluations), self.start_button))
            self.table = QTableWidget(0, 7)
            self.table.setHorizontalHeaderLabels(["对象", "面", "参数", "当前值", "最小", "最大", "步长"])
            _stretch_table(self.table)
            root.addWidget(self.table, 1)
            self._rebuild_table()
        elif kind == "opt_progress":
            self.workspace = LazyResultWorkspace(self)
            self.workspace.set_single_view_only(True)
            self.workspace.set_toolbar_visible(False)
            root.addWidget(self.workspace, 1)
            self.workspace.set_result(0, "过程曲线", {"kind": "empty", "message": "开始优化后，这里显示过程曲线。"})
        else:
            self.table = QTableWidget(0, 4)
            self.table.setHorizontalHeaderLabels(["方案", "总耦合效率", "光斑半径", "状态"])
            _stretch_table(self.table)
            self.table.itemSelectionChanged.connect(self._sync_apply_button)
            root.addWidget(self.table, 1)
            self.chart = QComboBox()
            self.chart.addItems(["过程曲线", "候选对照"])
            self.chart.currentTextChanged.connect(self._show_opt_chart)
            self.apply_button = _primary_button("应用方案")
            self.apply_button.setEnabled(False)
            self.apply_button.setToolTip("先在上方候选方案表中选择一行")
            self.apply_button.clicked.connect(self._apply_selected_result)
            self.apply_status = QLabel("")
            self.apply_status.setObjectName("HelperText")
            self.apply_status.setMinimumWidth(360)
            self.apply_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.apply_status.setWordWrap(False)
            root.addWidget(_action_row(self.chart, self.apply_button, self.apply_status))
            self.workspace = LazyResultWorkspace(self)
            self.workspace.set_single_view_only(True)
            self.workspace.set_toolbar_visible(False)
            self.workspace.set_pane_header_visible(False)
            root.addWidget(self.workspace, 1)
            self._started = False
            self._progress_path = ""
            self._progress_selected = ""
            self._opt_result: dict[str, Any] = {}
            self._show_opt_chart(self.chart.currentText())

    def set_selected(self, selected: set[str]) -> None:
        self.selected = set(selected)
        if self.kind == "opt_vars":
            self._rebuild_table()
            button = getattr(self, "start_button", None)
            if button is not None:
                button.setEnabled(bool(self.selected))
                button.setToolTip("" if self.selected else "请先在左栏勾选优化变量。")
        elif self.kind == "scan":
            self._fill_scan()

    def set_trained_models(self, models: list[dict[str, Any]]) -> None:
        goal = getattr(self, "goal", None)
        setter = getattr(goal, "set_trained_models", None)
        if callable(setter):
            setter(models)

    def _fill_scan(self) -> None:
        rows = _variable_rows(self.context.project.project)
        labels = [_display_variable(row) for row in rows if row[0] in self.selected]
        self.scan_summary.setText("、".join(labels[:2]) if labels else "（未勾选）")
        selected = [row for row in rows if row[0] in self.selected][:2]
        table = getattr(self, "range_table", None)
        if table is not None:
            table.setRowCount(len(selected))
            for index, (key, _group, _face, parameter) in enumerate(selected):
                current = _current_value(self.context.project.project, key)
                try:
                    number = float(current)
                    span = max(abs(number) * 0.10, 1e-6)
                    low, high = f"{number - span:g}", f"{number + span:g}"
                except ValueError:
                    low = high = "—"
                table.setItem(index, 0, QTableWidgetItem(parameter))
                table.setItem(index, 1, QTableWidgetItem(low))
                table.setItem(index, 2, QTableWidgetItem(high))
                table.item(index, 0).setData(Qt.ItemDataRole.UserRole, key)
            _stretch_table(table)
        button = getattr(self, "run_button", None)
        if button is not None:
            button.setEnabled(bool(selected))
            button.setToolTip("" if selected else "请先在左栏勾选 1～2 个变量。")

    def show_progress_started(self, path: str = "", selected: str = "") -> None:
        self._started = True
        self._progress_path = path or "光学仿真"
        self._progress_selected = selected or "未勾选变量"
        self._opt_result = {}
        chart = getattr(self, "chart", None)
        if chart is not None:
            chart.setCurrentText("过程曲线")
        self._show_opt_chart("过程曲线")

    def apply_opt_result(self, result: dict[str, Any]) -> None:
        self._started = True
        self._opt_result = dict(result or {})
        self._fill_result_table(self._opt_result)
        self._show_opt_chart(self.chart.currentText() if getattr(self, "chart", None) is not None else "过程曲线")

    def _fill_result_table(self, result: dict[str, Any]) -> None:
        table = getattr(self, "table", None)
        if table is None:
            return
        candidates = list(result.get("candidates") or [])
        history = candidates or list(result.get("history") or [])
        active_paths = [str(path) for path in list(result.get("metadata", {}).get("active_variables") or [])]
        rows = []
        row_variables: list[dict[str, float]] = []
        for index, item in enumerate(history[:100]):
            if not isinstance(item, dict):
                continue
            metrics = dict(item.get("metrics") or {})
            coupling = metrics.get(
                "total_coupling_efficiency",
                metrics.get("coupling_efficiency", item.get("coupling_efficiency")),
            )
            spot = metrics.get("rms_spot_radius_um", item.get("rms_spot_radius_um", item.get("spot_radius_um")))
            if coupling is None and spot is None and not item.get("status"):
                continue
            rows.append((
                str(item.get("label") or item.get("name") or f"候选 {index + 1}"),
                "—" if coupling is None else f"{float(coupling):.4g}",
                "—" if spot is None else f"{float(spot):.4g}",
                _optimization_status_label(item.get("status") or item.get("verification_status") or "已评估"),
            ))
            variables = item.get("variables")
            if isinstance(variables, dict):
                row_variables.append({str(key): float(value) for key, value in variables.items()})
            elif isinstance(variables, (list, tuple)) and len(variables) == len(active_paths):
                row_variables.append({path: float(value) for path, value in zip(active_paths, variables)})
            else:
                row_variables.append({})
        best = dict(result.get("best_metrics") or {})
        if best and not rows:
            rows.append(("最佳方案", str(best.get("coupling_efficiency", "—")), str(best.get("rms_spot_radius_um", "—")), "最佳"))
            row_variables.append({str(key): float(value) for key, value in dict(result.get("best_variables") or {}).items()})
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
            if row < len(row_variables) and table.item(row, 0) is not None:
                table.item(row, 0).setData(Qt.ItemDataRole.UserRole, row_variables[row])
        _stretch_table(table)
        self._sync_apply_button()

    def _sync_apply_button(self) -> None:
        button = getattr(self, "apply_button", None)
        table = getattr(self, "table", None)
        if button is None or table is None:
            return
        item = table.item(table.currentRow(), 0) if table.currentRow() >= 0 else None
        variables = item.data(Qt.ItemDataRole.UserRole) if item is not None else {}
        enabled = isinstance(variables, dict) and bool(variables)
        button.setEnabled(enabled)
        button.setToolTip("" if enabled else "先在上方候选方案表中选择一行")

    def _apply_selected_result(self) -> None:
        table = getattr(self, "table", None)
        context = getattr(self, "context", None)
        if table is None or context is None or table.currentRow() < 0:
            return
        item = table.item(table.currentRow(), 0)
        variables = item.data(Qt.ItemDataRole.UserRole) if item is not None else {}
        if not isinstance(variables, dict) or not variables:
            self.apply_status.setText("该行没有可应用的变量")
            return
        updater = getattr(getattr(context, "project", None), "apply_parameter_changes", None)
        if not callable(updater):
            self.apply_status.setText("当前项目不支持应用方案")
            return
        previous_result = getattr(getattr(context, "project", None), "formal_result", None)
        baseline = _coupling_efficiency_from_result(previous_result)
        if updater(variables, reason="应用优化候选方案"):
            self.apply_status.setText(f"已应用：{item.text()}，正在正式验证…")
            self.apply_button.setEnabled(False)
            self.applyAndVerifyRequested.emit(dict(variables), item.text(), baseline)
        else:
            self.apply_status.setText("方案与当前系统相同")

    def complete_candidate_validation(
        self,
        label: str,
        before: float | None,
        after: float | None,
        *,
        error: str = "",
    ) -> None:
        if error:
            self.apply_status.setText(f"{label} 正式验证失败：{error}")
        elif after is None:
            self.apply_status.setText(f"{label} 已应用，但正式结果没有返回耦合效率")
        elif before is None:
            self.apply_status.setText(f"{label} 正式验证完成：耦合效率 {after:.4g}（缺少应用前基线）")
        else:
            delta = after - before
            conclusion = "提高" if delta > 0 else "降低" if delta < 0 else "不变"
            self.apply_status.setText(
                f"{label} 正式验证完成：{before:.4g} → {after:.4g}，{conclusion} {abs(delta):.4g}"
            )
        self._sync_apply_button()

    def show_scan_status(self, message: str) -> None:
        workspace = getattr(self, "workspace", None)
        if workspace is not None:
            workspace.set_result(0, "响应曲线", {"kind": "empty", "message": message})

    def apply_scan_result(self, result: dict[str, Any], response: str) -> None:
        payload = scan_curve_payload(result, response)
        if payload is None:
            self.show_scan_status("扫描完成，但没有可绘制的响应曲线。")
            return
        self.workspace.set_result(0, "响应曲线", payload)

    def scan_ranges(self) -> list[tuple[str, float, float]]:
        table = getattr(self, "range_table", None)
        if table is None:
            return []
        rows: list[tuple[str, float, float]] = []
        for index in range(table.rowCount()):
            item = table.item(index, 0)
            key = str(item.data(Qt.ItemDataRole.UserRole) or "") if item is not None else ""
            if not key:
                continue
            try:
                low = float(table.item(index, 1).text()) if table.item(index, 1) is not None else 0.0
                high = float(table.item(index, 2).text()) if table.item(index, 2) is not None else 0.0
            except (TypeError, ValueError):
                continue
            rows.append((key, low, high))
        return rows

    def _show_opt_chart(self, name: str) -> None:
        workspace = getattr(self, "workspace", None)
        if workspace is None:
            return
        result = dict(getattr(self, "_opt_result", {}) or {})
        if result:
            payload = opt_chart_payload(result, name)
            if payload is not None:
                workspace.set_result(0, name, payload)
                return
            workspace.set_result(0, name, {"kind": "empty", "message": "优化完成，暂无该图数据。"})
            return
        started = bool(getattr(self, "_started", False))
        path = str(getattr(self, "_progress_path", "") or "光学仿真")
        selected = str(getattr(self, "_progress_selected", "") or "未勾选变量")
        if name == "候选对照":
            message = (
                "优化完成后，这里显示候选方案对照。"
                if not started
                else f"已按{path}提交。候选对照将显示在这里。"
            )
        else:
            message = (
                "开始优化后，这里显示过程曲线。"
                if not started
                else f"已按{path}、当前目标和 {selected} 提交优化，过程曲线将显示在这里。"
            )
        workspace.set_result(0, name, {"kind": "empty", "message": message})

    def _run_scan(self) -> None:
        self.scanRequested.emit()

    def _rebuild_table(self) -> None:
        table = getattr(self, "table", None)
        if table is None:
            return
        table.setRowCount(0)
        for key, group, face, parameter in _variable_rows(self.context.project.project):
            if key not in self.selected:
                continue
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(group))
            table.setItem(row, 1, QTableWidgetItem(face))
            table.setItem(row, 2, QTableWidgetItem(parameter))
            current = _current_value(self.context.project.project, key)
            table.setItem(row, 3, QTableWidgetItem(current))
            try:
                number = float(current)
                span = max(abs(number) * 0.10, 1e-6)
                low, high, step = f"{number - span:g}", f"{number + span:g}", f"{span / 5:g}"
            except ValueError:
                low = high = step = "—"
            table.setItem(row, 4, QTableWidgetItem(low))
            table.setItem(row, 5, QTableWidgetItem(high))
            table.setItem(row, 6, QTableWidgetItem(step))
            table.item(row, 0).setData(Qt.ItemDataRole.UserRole, key)


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


class WorkflowHome(QWidget):
    nodeRequested = Signal(str, str)
    homeActionRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("WorkflowHome")
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)
        subbar = QFrame()
        subbar.setObjectName("SecondaryBar")
        subrow = QHBoxLayout(subbar)
        subrow.setContentsMargins(8, 3, 8, 3)
        subrow.setSpacing(4)
        for key, label in (("quick_start", "快速开始"), ("help", "帮助")):
            button = _button(label)
            button.clicked.connect(lambda _checked=False, value=key: self.homeActionRequested.emit(value))
            subrow.addWidget(button)
        subrow.addStretch(1)
        root.addWidget(subbar)
        title = QLabel("光学研究工作流")
        title.setObjectName("HomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        nodes = [
            ("teaching", "教学入门", "认识器材与光路", 0, 1),
            ("lens_data", "搭建系统", "进入仿真镜头表", 1, 0),
            ("ray_layout", "观察结果", "进入仿真光路图", 1, 1),
            ("spot", "测量数据", "进入仿真光斑图", 1, 2),
            ("coupling", "分析结果", "进入仿真光纤耦合", 2, 1),
            ("dataset", "建立模型", "进入数据集生成", 3, 0),
            ("opt_vars", "优化参数", "进入优化变量", 3, 1),
            ("global_contrib", "解释原因", "进入解释全局贡献", 3, 2),
        ]
        for kind, title_text, subtitle, row, column in nodes:
            button = QPushButton(f"{title_text}\n{subtitle}")
            button.setObjectName("WorkflowNode")
            button.setMinimumHeight(76)
            module = "teaching" if kind == "teaching" else (
                "simulation" if kind in {"lens_data", "ray_layout", "spot", "coupling"} else
                "model" if kind == "dataset" else
                "optimization" if kind == "opt_vars" else "explainability"
            )
            button.clicked.connect(lambda _checked=False, m=module, k=kind: self.nodeRequested.emit(m, k))
            grid.addWidget(button, row, column)
        root.addLayout(grid)
        root.addStretch(1)

    def assistant_context(self) -> dict:
        return {"page": "首页", "current_view": "平台总览"}


class WorkbenchShell(QWidget):
    """Common shell for all ordinary modules."""

    secondaryRequested = Signal(str)
    navigateRequested = Signal(str)
    taskRequested = Signal(str)

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("WorkbenchShell")
        self.module = "simulation"
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
            {"id": "dataset-880bdde6c292", "title": "内置演示·780 nm 四透镜耦合", "kind": "builtin", "family": "tabular"},
        ]
        self._trained_models: list[dict[str, Any]] = []
        self._shap_scores: dict[str, float] = {}
        self._last_dataset_id = ""
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
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.secondary)
        body = QSplitter(Qt.Orientation.Horizontal, self)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(5)
        body.addWidget(self.object_rail)
        body.addWidget(self._workspace_stack)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([280, 1000])
        root.addWidget(body, 1)
        self.secondary.itemRequested.connect(self._secondary_clicked)
        self.object_rail.objectRequested.connect(self._object_clicked)
        self.object_rail.optimizationSelectionChanged.connect(self._optimization_selected)
        self.context.project.project_changed.connect(self._project_state_changed)
        self.set_module("simulation")

    def set_module(self, module: str) -> None:
        if str(module) == "analysis":
            module = "simulation"
        self.module = str(module)
        self.secondary.set_module(self.module)
        self.object_rail.setVisible(self.module != "home")
        self.object_rail.set_module(self.module)
        workspace = self._workspaces.get(self.module)
        if workspace is not None:
            self.workspace = workspace
            self._workspace_stack.setCurrentWidget(workspace)
        self._workspace_stack.setVisible(self.module != "home")
        self._connect_rail_editors()
        self._sync_rail_document()

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
            title = next((item["title"] for item in self._datasets if item["id"] == ident), ident)
            widget = self._widgets.get("model:dataset")
            if widget is not None:
                widget.select_dataset(title)
            return
        if not key.startswith("model:"):
            return
        ident = key.split(":", 1)[1]
        title = next((item["title"] for item in self._trained_models if item["id"] == ident), ident)
        kind = self._current_document_kind()
        if kind == "train_result":
            widget = self._widgets.get("model:train_result")
            if widget is not None:
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
                return MaterialLibraryDocument(self.context)
            if spec.kind in {"source_schematic", "fiber_schematic"}:
                document = SchematicDocument(self.context, spec.kind)
                self._sync_widget_mode(document)
                return document
            if spec.kind in RESULT_DOCUMENT_KINDS:
                document = ResultDocument(self.context, spec.kind)
                document.relatedRequested.connect(lambda kind: self.open_document("simulation", kind))
                return document
        if spec.module == "model":
            document = ModelDocument(spec.kind, self.context)
            document.trainRequested.connect(self._start_model_training)
            generate = getattr(document, "generateRequested", None)
            if generate is not None:
                generate.connect(self._start_dataset_generation)
            predict = getattr(document, "predictRequested", None)
            if predict is not None:
                predict.connect(self._start_model_predict)
            generated = getattr(document, "datasetGenerated", None)
            if generated is not None:
                generated.connect(self._register_dataset)
            importer = getattr(document, "fileImportRequested", None)
            if importer is not None:
                importer.connect(self._import_dataset_file)
            kind_changed = getattr(document, "dataKindChanged", None)
            if kind_changed is not None:
                kind_changed.connect(self._set_dataset_family)
            setter = getattr(document, "set_trained_models", None)
            if callable(setter):
                setter(self._trained_models)
            return document
        if spec.module == "optimization":
            document = OptimizationDocument(spec.kind, self.context, self._selected_optimization)
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
            document = AnalysisTextDocument(spec.kind, self._selected_explain, context=self.context)
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
        kind = "bilstm" if family == "sequence" else "train"
        if family == "sequence":
            path = str(dataset.file_path.text() or "").strip()
            if not path:
                self.open_document("model", "train_result")
                widget = self._widgets.get("model:train_result")
                status = getattr(widget, "show_train_status", None)
                if callable(status):
                    status("请先选择序列数据文件。")
                return
            payload = {
                "dataset_path": path,
                "system_id_column": str(dataset.system_id_column.text() or "system_id"),
                "order_column": str(dataset.order_column.text() or "element_index"),
                "element_type_column": str(dataset.element_type_column.text() or "element_type"),
                "numeric_feature_columns": [item.strip() for item in str(dataset.numeric_columns.text() or "").split(",") if item.strip()],
                "target_columns": [item.strip() for item in str(dataset.sequence_target.text() or "coupling_efficiency").split(",") if item.strip()],
                "config": dataset.train_hyperparameters(),
            }
        else:
            selected_dataset_id = str(dataset.builtin.currentData() or self._last_dataset_id or "")
            if not selected_dataset_id:
                self.open_document("model", "train_result")
                widget = self._widgets.get("model:train_result")
                status = getattr(widget, "show_train_status", None)
                if callable(status):
                    status("请选择内置数据集、导入文件，或先生成数据集，再训练。")
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
            dataset.set_job_busy(False)
            if callable(status):
                status(error)
            self.taskRequested.emit(error)

    def _import_dataset_file(self, path: str) -> None:
        """Import the selected local table before allowing tabular training."""
        dataset = self._widgets.get("model:dataset")
        api = getattr(self.context, "api_client", None)
        if dataset is None or api is None:
            return
        source_path = str(path or "").strip()
        if not source_path:
            return
        self._dataset_import_token = f"workbench.dataset.import.{uuid4().hex[:8]}"
        if not getattr(self, "_dataset_import_bound", False):
            api.completed.connect(self._on_dataset_import_completed)
            api.failed.connect(self._on_dataset_import_failed)
            self._dataset_import_bound = True
        dataset.set_job_busy(True)
        dataset.show_generate_status("正在导入文件数据集…")
        from frontend_pyside.api.headless_dataset_client import HeadlessDatasetClient
        HeadlessDatasetClient(api).import_file(
            self._dataset_import_token,
            {
                "source_path": source_path,
                "dataset_name": source_path.replace("\\", "/").rsplit("/", 1)[-1],
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
            dataset.show_generate_status("文件已导入", [(dataset_id or "—", "文件数据集", "—", "可训练")])
        if not dataset_id:
            self.taskRequested.emit("文件已提交，但后端没有返回数据集 ID。")
            return
        self._last_dataset_id = dataset_id
        title = str(body.get("dataset_name") or dataset_id)
        self._register_dataset(title, dataset_id=dataset_id)
        registry = getattr(self.context, "registry", None)
        if registry is not None:
            registry.merge_dataset({"dataset_id": dataset_id, "id": dataset_id, "name": title, **body})
            registry.set_current_dataset(dataset_id)

    def _on_dataset_import_failed(self, key: str, message: str) -> None:
        if str(key) != getattr(self, "_dataset_import_token", ""):
            return
        dataset = self._widgets.get("model:dataset")
        if dataset is not None:
            dataset.set_job_busy(False)
            dataset.show_generate_status(f"文件导入失败：{message}")

    def _start_dataset_generation(self) -> None:
        dataset = self._widgets.get("model:dataset")
        if dataset is None or dataset.current_family() != "tabular":
            return
        from uuid import uuid4

        from machine_learning.features.coupling_physics import paired_coupling_targets

        state = self.collect_simulation_state()
        project_payload = serialize_project(self.context.project.project, state)
        from machine_learning.datasets.variable_schemes import resolve_variable_scheme
        try:
            scheme = resolve_variable_scheme(
                project_payload,
                lens_count=int(dataset.lens_count.currentData() or 1),
                include_conic=dataset.variable_scheme.currentData() == "asphere",
            )
        except ValueError as exc:
            dataset.show_generate_status(str(exc))
            return
        parameters = build_dataset_parameters(project_payload, explicit_paths=scheme.design_variable_paths)
        if not parameters:
            dataset.show_generate_status("未选择可采样参数")
            return
        validation = min(0.45, max(0.05, float(dataset.split.value())))
        test = min(0.15, max(0.05, validation))
        payload = {
            "dataset_name": f"workbench-{uuid4().hex[:8]}",
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
            "variable_scheme_id": scheme.scheme_id,
            "lens_count": scheme.lens_count,
            "design_variable_paths": list(scheme.design_variable_paths),
        }
        dataset.show_generate_status(
            "生成中", [("—", f"{scheme.label} · {len(parameters)} 个变量", "固定", "生成中")]
        )
        dataset.set_job_busy(True)
        error = self._jobs.submit("dataset", payload)
        if error:
            dataset.set_job_busy(False)
            dataset.show_generate_status(error)
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
        try:
            features = model_features(self.context.project.project, record)
        except FeaturePathError as exc:
            predict.show_predict_status(f"当前镜头无法构造模型特征：{exc}")
            return
        predict._fill_predict_inputs()
        predict.show_predict_status("正在预测…")
        self._predict_token = f"workbench.predict.{uuid4().hex[:8]}"
        if not getattr(self, "_predict_api_bound", False):
            api.completed.connect(self._on_predict_completed)
            api.failed.connect(self._on_predict_failed)
            self._predict_api_bound = True
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

    def _register_dataset(self, title: str, *, dataset_id: str = "") -> None:
        name = str(title or "").strip()
        if not name or any(item.get("title") == name for item in self._datasets):
            return
        widget = self._widgets.get("model:dataset")
        family = widget.current_family() if widget is not None and hasattr(widget, "current_family") else "tabular"
        self._datasets.append({"id": str(dataset_id or f"file-{len(self._datasets) + 1}"), "title": name, "kind": "file", "family": family})
        self.object_rail.set_catalogs(self._datasets, self._trained_models)

    def _on_registry_models_changed(self, records: list[dict[str, Any]]) -> None:
        """Mirror the authoritative model registry into the workbench rail."""
        reverse_types = {
            "random_forest": "随机森林",
            "xgboost_physics_residual": "XGBoost物理残差",
            "bilstm_structure_sequence": "BiLSTM",
        }
        normalized: list[dict[str, Any]] = []
        for item in list(records or []):
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("model_id", item.get("id", "")) or "")
            if not model_id:
                continue
            model_type = str(item.get("model_type") or "")
            display_type = reverse_types.get(model_type, model_type or "模型")
            title = str(item.get("title") or "")
            if not title:
                name = str(item.get("name") or "")
                title = name if name and name != model_id else f"{display_type} · {model_id[-8:]}"
            record = dict(item)
            record.update({"id": model_id, "title": title})
            normalized.append(record)
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
            try:
                current = float(table.item(row, 3).text()) if table.item(row, 3) is not None else 0.0
                low = float(table.item(row, 4).text()) if table.item(row, 4) is not None else current
                high = float(table.item(row, 5).text()) if table.item(row, 5) is not None else current
            except (TypeError, ValueError):
                continue
            label = " ".join(
                str(table.item(row, column).text())
                for column in range(3)
                if table.item(row, column) is not None
            )
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
        self.taskRequested.emit(f"{_job_title(kind)}已提交")

    def _on_workbench_job_progress(self, kind: str, progress: float, stage: str) -> None:
        note = f"{_job_title(kind)} {progress:.0%}"
        if kind == "dataset":
            dataset = self._widgets.get("model:dataset")
            if dataset is not None:
                dataset.show_generate_status(note)
        elif kind in {"train", "joint_train", "bilstm"}:
            widget = self._widgets.get("model:train_result")
            status = getattr(widget, "show_train_status", None)
            if callable(status):
                status(note)
        elif kind == "scan":
            scan = self._widgets.get("optimization:scan")
            if scan is not None:
                scan.show_scan_status(note)
        elif kind == "optimize":
            widget = self._widgets.get("optimization:opt_result")
            if widget is not None:
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
        if kind == "dataset":
            dataset = self._widgets.get("model:dataset")
            dataset_id = str(body.get("dataset_id") or body.get("training_dataset_id") or "")
            self._last_dataset_id = dataset_id
            count = int(body.get("sample_count") or 0)
            if dataset is not None:
                dataset.set_job_busy(False)
                dataset.show_generate_status(
                    "已完成",
                    [(dataset_id or "数据集", f"{count} 条", "—", "已完成")],
                )
            if dataset_id:
                self._register_dataset(dataset_id)
                if dataset is not None:
                    # Make the freshly generated dataset the explicit current
                    # choice. The packaged demo must not silently win over a
                    # dataset the user has just generated.
                    for index in range(dataset.builtin.count() - 1, -1, -1):
                        if str(dataset.builtin.itemData(index) or "") == dataset_id:
                            dataset.builtin.removeItem(index)
                    dataset.builtin.insertItem(0, f"本次生成·{dataset_id[-8:]}", dataset_id)
                    dataset.builtin.setCurrentIndex(0)
            registry = getattr(self.context, "registry", None)
            if registry is not None and dataset_id:
                registry.merge_dataset({"dataset_id": dataset_id, "id": dataset_id, "name": dataset_id})
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
                    "title": f"{name} · {model_id[-8:]}",
                    "model_type": name,
                    "target": target,
                    "family": dataset.current_family() if dataset is not None else "tabular",
                    "dataset_id": str(body.get("dataset_id") or self._last_dataset_id),
                    "feature_paths": feature_paths,
                    "feature_units": _coerce_feature_units(feature_units_raw, feature_paths),
                    "design_variable_paths": list(body.get("design_variable_paths") or metadata.get("design_variable_paths") or []),
                    "physics_feature_paths": list(body.get("physics_feature_paths") or metadata.get("physics_feature_paths") or []),
                    "variable_scheme_id": str(body.get("variable_scheme_id") or metadata.get("variable_scheme_id") or ""),
                    "target_names": result_targets,
                    "validation_metrics": dict(body.get("validation_metrics") or {}),
                    "test_metrics": dict(body.get("test_metrics") or {}),
                    "training_summary": dict(body.get("training_summary") or metadata.get("training_summary") or {}),
                    "training_curve_status": str(body.get("training_curve_status") or metadata.get("training_curve_status") or "unavailable"),
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
        if kind == "dataset":
            dataset = self._widgets.get("model:dataset")
            if dataset is not None:
                dataset.set_job_busy(False)
                dataset.show_generate_status(text)
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
        from frontend_pyside.features.canvas.explain_node import explain_shap_failure

        text = explain_shap_failure(message)
        self._train_shap_error = text
        self.taskRequested.emit(f"训练完成，但自动 SHAP 失败：{text}")


class KindDragButton(QPushButton):
    """Click to add, or drag onto the bench."""

    def __init__(self, kind: str, title: str, parent=None) -> None:
        super().__init__(title, parent)
        self._kind = str(kind)
        self._press = None

    def mousePressEvent(self, event) -> None:
        self._press = event.position().toPoint() if hasattr(event, "position") else event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and self._press is not None:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if (pos - self._press).manhattanLength() >= 8:
                drag = QDrag(self)
                mime = QMimeData()
                payload = QByteArray(self._kind.encode("utf-8"))
                mime.setData(TEACHING_KIND_MIME, payload)
                mime.setText(self._kind)
                drag.setMimeData(mime)
                drag.exec(Qt.DropAction.CopyAction)
                self._press = None
                return
        super().mouseMoveEvent(event)


TEACHING_ANALYSIS_INFO: dict[str, dict[str, Any]] = {
    "spot": {
        "key": "imaging",
        "title": "成像分析",
        "empty": "尚未进行成像计算。请先放置并启用 CCD 或光纤，再点击开始正式计算。",
        "metrics": (
            ("rms_spot_radius_um", "RMS 光斑半径", "μm"),
            ("centroid_x_mm", "光斑质心 X", "mm"),
            ("centroid_y_mm", "光斑质心 Y", "mm"),
            ("image_distance_mm", "像面位置", "mm"),
            ("valid_ray_count", "有效光线数", "条"),
        ),
    },
    "coupling": {
        "key": "coupling",
        "title": "耦合分析",
        "empty": "尚未进行耦合计算。请先放置并启用光纤，再点击开始正式计算。",
        "metrics": (
            ("coupling_efficiency", "模式耦合效率", "%"),
            ("mode_overlap_efficiency", "模式重叠效率", "%"),
            ("fiber_interface_efficiency", "端面接收效率", "%"),
            ("total_coupling_efficiency", "总耦合效率", "%"),
            ("coupling_loss_db", "耦合损耗", "dB"),
        ),
    },
}


def _format_teaching_metric(key: str, value: Any, unit: str = "") -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "无效"
    if unit == "%":
        return f"{number * 100:.4g}%"
    if unit == "条":
        return f"{int(number)} 条"
    if unit:
        return f"{number:.6g} {unit}"
    return f"{number:.6g}"


class TeachingAnalysisVisual(QWidget):
    """Compact visual reading of the formal teaching result.

    This intentionally supplements the exact metric table: a beginner can see
    whether a spot is centred and concentrated, or where power is lost, before
    reading micrometre-level values.
    """

    def __init__(self, analysis: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.analysis = str(analysis)
        self.metrics: dict[str, Any] = {}
        self.available = False
        self.setObjectName("TeachingAnalysisVisual")
        self.setMinimumHeight(270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_metrics(self, metrics: dict[str, Any], *, available: bool) -> None:
        self.metrics = dict(metrics or {})
        self.available = bool(available)
        self.update()

    @staticmethod
    def _number(metrics: dict[str, Any], *keys: str, default: float = 0.0) -> float:
        for key in keys:
            try:
                value = float(metrics.get(key))
                if math.isfinite(value):
                    return value
            except (TypeError, ValueError):
                continue
        return default

    @staticmethod
    def _fraction(value: float) -> float:
        return max(0.0, min(1.0, value / 100.0 if value > 1.000001 else value))

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.fillRect(rect, QColor("#101828"))
        painter.setPen(QPen(QColor("#344054"), 1))
        painter.drawRoundedRect(rect, 8, 8)
        if not self.available:
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(rect.adjusted(0, -30, 0, 0), Qt.AlignmentFlag.AlignCenter, "尚无正式计算结果")
            painter.setPen(QColor("#98A2B3"))
            painter.drawText(rect.adjusted(0, 28, 0, 0), Qt.AlignmentFlag.AlignCenter,
                             "点击上方“开始正式计算”获取当前指标")
            return
        if self.analysis == "spot":
            rms = self._number(self.metrics, "rms_spot_radius_um", "rms_um", default=0.0)
            center = rect.center()
            radius = max(20, min(68, 22 + rms * 1.4))
            for factor, colour in ((2.0, "#7F1D1D"), (1.45, "#DC2626"), (0.9, "#F97316"), (0.42, "#FEF3C7")):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(colour))
                painter.drawEllipse(center, int(radius * factor), int(radius * factor))
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(rect.adjusted(0, 10, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                             f"接收面光斑 · RMS 半径 {rms:.3g} μm")
        else:
            eta = self._fraction(self._number(self.metrics, "total_coupling_efficiency", "coupling_efficiency", default=0.0))
            center = rect.center()
            radius = min(rect.height(), rect.width()) // 4
            painter.setPen(QPen(QColor("#34D399"), 10))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius, radius)
            painter.setPen(QColor("#FFFFFF"))
            font = painter.font()
            font.setPointSize(max(15, font.pointSize() + 7))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignCenter,
                f"η  {_format_teaching_metric('total_coupling_efficiency', eta, '%')}",
            )
            painter.setPen(QColor("#A7F3D0"))
            painter.drawText(rect.adjusted(0, 70, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                             "总耦合效率（正式波动光学计算）")

    def _paint_spot(self, painter: QPainter, rect) -> None:
        title_rect = rect.adjusted(14, 8, -14, 0)
        painter.setPen(QColor("#0A327A"))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "接收面光斑与像心")
        plot = rect.adjusted(18, 30, -18, -14)
        side = min(plot.height(), max(72, plot.width() // 2))
        target = plot
        target.setWidth(side)
        target.setHeight(side)
        painter.fillRect(target, QColor("#172554"))
        center = target.center()
        rms = self._number(self.metrics, "rms_spot_radius_um", "rms_um", default=12.0)
        radius = max(13.0, min(float(side) * 0.32, 12.0 + rms * 0.65))
        x = self._number(self.metrics, "centroid_x_mm", "centroid_x", default=0.0)
        y = self._number(self.metrics, "centroid_y_mm", "centroid_y", default=0.0)
        # Centroid is deliberately clipped: the plot signals off-axis imaging
        # without pretending that a different scale is a physical calculation.
        offset_x = max(-side * 0.28, min(side * 0.28, x * 12.0))
        offset_y = max(-side * 0.28, min(side * 0.28, -y * 12.0))
        spot = center + QPoint(int(offset_x), int(offset_y))
        for factor, colour in ((2.2, "#1D4ED8"), (1.55, "#2563EB"), (1.0, "#60A5FA"), (0.55, "#FDE68A")):
            painter.setBrush(QColor(colour))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(spot, int(radius * factor), int(radius * factor))
        painter.setPen(QPen(QColor("#FFFFFF"), 1.5, Qt.PenStyle.DashLine))
        painter.drawLine(center.x() - 12, center.y(), center.x() + 12, center.y())
        painter.drawLine(center.x(), center.y() - 12, center.x(), center.y() + 12)
        painter.setPen(QPen(QColor("#F97316"), 2))
        painter.drawLine(spot.x() - 6, spot.y(), spot.x() + 6, spot.y())
        painter.drawLine(spot.x(), spot.y() - 6, spot.x(), spot.y() + 6)
        info = rect.adjusted(side + 34, 35, -12, -12)
        painter.setPen(QColor("#344054"))
        painter.drawText(info, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                         f"RMS 半径  {rms:.3g} μm\n\n"
                         f"光斑质心  ({x:.3g}, {y:.3g}) mm\n\n"
                         "白色十字：理想像心\n橙色十字：实际质心")

    def _paint_coupling(self, painter: QPainter, rect) -> None:
        painter.setPen(QColor("#0A327A"))
        painter.drawText(rect.adjusted(14, 8, -14, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                         "功率如何到达光纤基模")
        system = self._fraction(self._number(self.metrics, "system_efficiency", "transmission_efficiency", default=0.0))
        facet = self._fraction(self._number(self.metrics, "fiber_interface_efficiency", "receiver_efficiency", default=1.0))
        total = self._fraction(self._number(self.metrics, "total_coupling_efficiency", "coupling_efficiency", default=0.0))
        overlap = self._fraction(self._number(self.metrics, "mode_overlap_efficiency", default=total))
        stages = (("系统透过", system), ("模场重叠", overlap), ("端面接收", facet), ("总耦合", total))
        left = rect.left() + 18
        top = rect.top() + 40
        width = max(90, rect.width() - 158)
        bar_h = 18
        for index, (label, value) in enumerate(stages):
            y = top + index * 25
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#DCE9FF"))
            painter.drawRoundedRect(left, y, width, bar_h, 5, 5)
            painter.setBrush(QColor("#155EEF") if index < 3 else QColor("#0E7490"))
            painter.drawRoundedRect(left, y, int(width * value), bar_h, 5, 5)
            painter.setPen(QColor("#344054"))
            painter.drawText(left + width + 10, y, 100, bar_h, Qt.AlignmentFlag.AlignVCenter,
                             f"{label}  {value * 100:.1f}%")
        painter.setPen(QColor("#667085"))
        painter.drawText(rect.adjusted(18, -4, -18, -4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                         "每一行表示相对于该环节输入的保留比例；总耦合效率以正式引擎结果为准。")


class TeachingAnalysisPopup(QFrame):
    """Modeless formal-analysis window used by the teaching bench."""

    calculateRequested = Signal(str)

    def __init__(self, analysis: str, parent=None) -> None:
        info = TEACHING_ANALYSIS_INFO[str(analysis)]
        super().__init__(parent, Qt.WindowType.Tool)
        self.analysis = str(analysis)
        self.setObjectName(f"Teaching{info['key'].title()}Popup")
        self.setWindowTitle(str(info["title"]))
        self.setMinimumSize(700, 520)
        self.resize(780, 590)
        self._result_scene_revision: int | None = None
        self._scene_revision: int | None = None
        self._busy_message = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)
        heading = QLabel(str(info["title"]))
        heading.setObjectName("TeachingPopupTitle")
        root.addWidget(heading)

        action_row = QHBoxLayout()
        self.run_button = QPushButton("开始正式计算")
        self.run_button.setObjectName("teachingV2PrimaryButton")
        self.run_button.setMinimumHeight(38)
        self.run_button.setMinimumWidth(156)
        self.run_button.clicked.connect(lambda: self.calculateRequested.emit(self.analysis))
        action_row.addWidget(self.run_button)
        self.status = QLabel("尚未计算")
        self.status.setObjectName("TeachingPopupStatus")
        self.status.setWordWrap(True)
        action_row.addWidget(self.status, 1)
        root.addLayout(action_row)

        # Wave-optics analysis does not have a truthful percentage before the
        # engine returns.  An indeterminate bar communicates active work
        # without inventing a completion number.
        self.progress = QProgressBar(self)
        self.progress.setObjectName("TeachingAnalysisProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.hide()
        root.addWidget(self.progress)

        self.summary = QLabel("等待波动光学计算")
        self.summary.setObjectName("TeachingAnalysisSummary")
        root.addWidget(self.summary)
        self.visual = TeachingAnalysisVisual(self.analysis, self)
        root.addWidget(self.visual)
        self.notes = QLabel(str(info["empty"]))
        self.notes.setObjectName("TeachingPopupNotes")
        self.notes.setWordWrap(True)
        root.addWidget(self.notes)

    def set_scene_revision(self, revision: int) -> None:
        self._scene_revision = int(revision)
        if self._result_scene_revision is not None and self._result_scene_revision != int(revision):
            self.run_button.setEnabled(True)
            self.status.setText("场景已修改，当前指标已过期")
            self.summary.setText("结果已过期 · 请重新计算")
            self.notes.setText("修改教学台后，旧结果不会作为当前场景的结论。")
            self.visual.set_metrics({}, available=False)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.run_button.setEnabled(not bool(busy))
        if busy:
            self._busy_message = str(message or "正在计算，界面仍可操作")
            self.status.setText(self._busy_message)
            self.progress.setRange(0, 0)
            self.progress.show()
        elif message:
            self.status.setText(str(message))
            self.progress.hide()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        else:
            self.progress.hide()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)

    def set_result(self, result: object) -> None:
        info = TEACHING_ANALYSIS_INFO[self.analysis]
        artifacts = getattr(result, "artifacts", {}) or {}
        artifact = artifacts.get(self.analysis) if isinstance(artifacts, dict) else None
        artifact = dict(artifact or {})
        metrics = dict(artifact.get("metrics") or getattr(result, "metrics", {}) or {})
        status = str(artifact.get("status") or getattr(result, "status", "failed") or "failed")
        success = bool(getattr(result, "success", status == "completed"))
        scene_revision = getattr(result, "scene_revision", None)
        self._result_scene_revision = int(scene_revision) if scene_revision is not None else self._scene_revision
        self.run_button.setEnabled(True)
        self.progress.hide()
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.visual.set_metrics(metrics, available=bool(success and status == "completed"))
        if self.analysis == "coupling":
            value = metrics.get("total_coupling_efficiency", metrics.get("coupling_efficiency"))
            self.summary.setText(f"总耦合效率  {_format_teaching_metric('total_coupling_efficiency', value, '%')}")
        else:
            value = metrics.get("rms_spot_radius_um", metrics.get("rms_um"))
            self.summary.setText(f"RMS 光斑半径  {_format_teaching_metric('rms_spot_radius_um', value, 'μm')}")

        errors = [str(item).strip() for item in (artifact.get("errors") or getattr(result, "errors", ()) or ())]
        errors = [item for item in errors if item]
        raw_warnings = [str(item).strip() for item in (artifact.get("warnings") or getattr(result, "warnings", ()) or ())]
        raw_warnings = [item for item in raw_warnings if item]
        quality_needs_review = bool(raw_warnings)
        comparison_note = str(artifact.get("comparison_note") or "教学场景正式计算")
        if status == "missed":
            self.status.setText("光束未命中接收端")
        elif success and status == "completed":
            elapsed = float(getattr(result, "elapsed_ms", 0.0) or 0.0)
            suffix = f" · {elapsed:.0f} ms" if elapsed > 0 else ""
            self.status.setText(f"正式计算完成{suffix}")
        else:
            self.status.setText("正式计算未完成")
        if errors:
            self.notes.setText(f"计算未完成：{errors[0]}")
        elif quality_needs_review:
            self.notes.setText(f"{comparison_note}；计算质量：建议提高采样精度后复核。")
        else:
            self.notes.setText(f"{comparison_note}；计算质量：正常。")


class TeachingEquipmentPopup(QFrame):
    addRequested = Signal(str)
    presetRequested = Signal(str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Tool)
        self.setObjectName("TeachingEquipmentPopup")
        self.setWindowTitle("器材库")
        self.setMinimumSize(420, 560)
        self.resize(440, 640)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("器材库"))
        close = QToolButton()
        close.setText("×")
        close.clicked.connect(self.close)
        title_row.addStretch(1)
        title_row.addWidget(close)
        root.addLayout(title_row)
        search = QLineEdit()
        search.setPlaceholderText("搜索器材…")
        root.addWidget(search)
        hint = QLabel("拖到台上放置，或点击添加")
        hint.setObjectName("TeachingHint")
        root.addWidget(hint)
        self._preset_kind = ""
        self._preset_label = QLabel("")
        self._preset_label.setObjectName("PopupGroupTitle")
        self._preset_label.setWordWrap(True)
        self._preset_label.hide()
        root.addWidget(self._preset_label)
        self.preset_box = QComboBox()
        self.preset_box.setVisible(False)
        root.addWidget(self.preset_box)
        self.custom_value = QDoubleSpinBox()
        self.custom_value.setRange(0.01, 30000.0)
        self.custom_value.setDecimals(3)
        self.custom_value.setSuffix(" nm")
        self.custom_value.setVisible(False)
        root.addWidget(self.custom_value)
        self.apply_preset = QPushButton("应用当前规格")
        self.apply_preset.setVisible(False)
        self.apply_preset.clicked.connect(self._apply_preset)
        root.addWidget(self.apply_preset)
        catalog = QWidget()
        catalog_layout = QVBoxLayout(catalog)
        catalog_layout.setContentsMargins(0, 0, 0, 0)
        catalog_layout.setSpacing(4)
        self._kind_buttons: list[QPushButton] = []
        for group, values in (
            ("光源", [item for item in PLACEABLE_KINDS if item[0] == "laser"]),
            ("光学元件", [item for item in PLACEABLE_KINDS if item[0] in {
                "isolator", "waveplate", "lens", "cylindrical_lens", "beam_expander",
                "aperture", "pbs", "splitter", "beam_sampler", "grating", "mirror",
            }]),
            ("接收与测量", [item for item in PLACEABLE_KINDS if item[0] in {
                "fiber", "ccd", "power_meter", "wavefront_sensor",
            }]),
            ("台面", [item for item in PLACEABLE_KINDS if item[0] == "oscilloscope"]),
        ):
            if not values:
                continue
            label = QLabel(group)
            label.setObjectName("PopupGroupTitle")
            catalog_layout.addWidget(label)
            for key, title in values:
                button = KindDragButton(key, title)
                button.setProperty("kindKey", key)
                button.clicked.connect(lambda _checked=False, value=key: self._select_equipment(value))
                catalog_layout.addWidget(button)
                self._kind_buttons.append(button)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(catalog)
        scroll.setMinimumHeight(280)
        scroll.setMaximumHeight(420)
        root.addWidget(scroll)
        search.textChanged.connect(self._filter_equipment)
        self.adjustSize()

    def _filter_equipment(self, text: str) -> None:
        needle = str(text or "").strip().lower()
        for button in self._kind_buttons:
            title = button.text().lower()
            key = str(button.property("kindKey") or "").lower()
            button.setVisible(not needle or needle in title or needle in key)

    def _select_equipment(self, kind: str) -> None:
        kind = str(kind)
        self.addRequested.emit(kind)
        presets: dict[str, tuple[str, list[tuple[str, object]]]] = {
            "laser": (
                "工业常用激光器规格",
                [("780 nm 外腔二极管 · 50 mW · 0.70 mm", {"wavelength_nm": 780.0, "power_mw": 50.0, "beam_radius_mm": 0.70}),
                 ("850 nm VCSEL · 10 mW · 0.35 mm", {"wavelength_nm": 850.0, "power_mw": 10.0, "beam_radius_mm": 0.35}),
                 ("1064 nm DPSS · 100 mW · 0.80 mm", {"wavelength_nm": 1064.0, "power_mw": 100.0, "beam_radius_mm": 0.80}),
                 ("1310 nm DFB · 10 mW · 0.45 mm", {"wavelength_nm": 1310.0, "power_mw": 10.0, "beam_radius_mm": 0.45}),
                 ("1550 nm DFB · 10 mW · 0.50 mm", {"wavelength_nm": 1550.0, "power_mw": 10.0, "beam_radius_mm": 0.50}),
                 ("自定义波长", None)],
            ),
            "lens": (
                "工程常用透镜规格",
                [("焦距 25 mm · 直径 12.7 mm", {"focal_length_mm": 25.0, "diameter_mm": 12.7}),
                 ("焦距 50 mm · 直径 25.4 mm", {"focal_length_mm": 50.0, "diameter_mm": 25.4}),
                 ("焦距 100 mm · 直径 25.4 mm", {"focal_length_mm": 100.0, "diameter_mm": 25.4})],
            ),
            "mirror": (
                "工程常用反射镜规格",
                [("圆形 12.7 mm", {"diameter_mm": 12.7}), ("圆形 25.4 mm", {"diameter_mm": 25.4})],
            ),
            "aperture": (
                "工程常用光阑规格",
                [("通光直径 4 mm", {"diameter_mm": 4.0}), ("通光直径 8 mm", {"diameter_mm": 8.0}),
                 ("通光直径 12 mm", {"diameter_mm": 12.0})],
            ),
            "fiber": (
                "工程常用光纤规格",
                [("单模 · 模场 5.6 μm · NA 0.12", {"mfd_um": 5.6, "na": 0.12}),
                 ("单模 · 模场 10.4 μm · NA 0.14", {"mfd_um": 10.4, "na": 0.14}),
                 ("多模 · 芯径 50 μm · NA 0.22", {"core_diameter_um": 50.0, "na": 0.22})],
            ),
            "detector": (
                "工程常用探测器规格",
                [("小面阵 6.4 × 4.8 mm", {"sensor_width_mm": 6.4, "sensor_height_mm": 4.8}),
                 ("大面阵 13.2 × 8.8 mm", {"sensor_width_mm": 13.2, "sensor_height_mm": 8.8})],
            ),
        }
        self._preset_kind = kind
        title, values = presets.get(kind, ("", []))
        self._preset_label.setText(title)
        self._preset_label.setVisible(bool(title))
        self.preset_box.clear()
        for label, payload in values:
            self.preset_box.addItem(label, payload)
        enabled = bool(values)
        self.preset_box.setVisible(enabled)
        self.apply_preset.setVisible(enabled)
        custom = kind == "laser"
        self.custom_value.setVisible(custom)
        if custom:
            self.custom_value.setValue(780.0)
        self.adjustSize()

    def _apply_preset(self) -> None:
        if not self._preset_kind or self.preset_box.currentIndex() < 0:
            return
        payload = self.preset_box.currentData()
        if self._preset_kind == "laser" and payload is None:
            payload = {"wavelength_nm": float(self.custom_value.value())}
        if isinstance(payload, dict):
            self.presetRequested.emit(self._preset_kind, payload)


class TeachingResultPopup(QFrame):
    def __init__(self, origin: str = "教学示意", parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("TeachingResultPopup")
        self.setWindowTitle("教学结果")
        self.setMinimumSize(680, 480)
        self.resize(760, 560)
        root = QVBoxLayout(self)
        title = QLabel("当前教学结果")
        title.setObjectName("TeachingPopupTitle")
        root.addWidget(title)
        self.source = QLabel(f"来源：{origin}")
        self.source.setObjectName("TeachingResultSource")
        root.addWidget(self.source)
        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setObjectName("TeachingResultBody")
        root.addWidget(self.body, 1)
        self.set_snapshot(None)

    def set_origin(self, origin: str) -> None:
        self.source.setText(f"来源：{origin}")

    def set_snapshot(self, snapshot) -> None:
        if snapshot is None:
            self.body.setText("尚未进行正式成像或耦合计算。\n请从教学工具栏打开分析窗口。")
            return
        lines = [f"场景版本：{int(snapshot.revision)}"]
        geometry = dict(snapshot.results.get("geometry") or {})
        geometry_metrics = dict(geometry.get("metrics") or {})
        if geometry_metrics:
            path_count = geometry_metrics.get("path_count")
            if path_count is not None:
                lines.append(f"光路示意：{int(float(path_count))} 条光路")
        for analysis, title, metric_specs in (
            ("spot", "成像", TEACHING_ANALYSIS_INFO["spot"]["metrics"]),
            ("coupling", "耦合", TEACHING_ANALYSIS_INFO["coupling"]["metrics"]),
        ):
            payload = dict(snapshot.results.get(analysis) or {})
            if not payload:
                lines.append(f"{title}：尚未计算")
                continue
            if payload.get("stale") or payload.get("scene_revision") != snapshot.revision:
                lines.append(f"{title}：结果已过期，请重新计算")
                continue
            if str(payload.get("status") or "") != "completed":
                errors = "；".join(str(item) for item in (payload.get("errors") or ()) if str(item))
                lines.append(f"{title}：{errors or '计算未完成'}")
                continue
            metrics = dict(payload.get("metrics") or {})
            visible = []
            for key, label, unit in metric_specs:
                if key in metrics:
                    visible.append(f"{label} {_format_teaching_metric(key, metrics[key], unit)}")
            lines.append(f"{title}：" + ("；".join(visible) if visible else "已完成，但引擎未返回可显示指标"))
        self.body.setText("\n".join(lines))


class TeachingShell(QWidget):
    """Large teaching canvas shell.  It deliberately has no document tabs."""

    statusMessage = Signal(str)

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("TeachingShell")
        self.store = SceneStore(self, start_empty=True)
        self.equipment_popup: TeachingEquipmentPopup | None = None
        self.analysis_popups: dict[str, TeachingAnalysisPopup] = {}
        self.result_popup: TeachingResultPopup | None = None
        self._last_equipment_id: str | None = None
        self._teaching_result_origin = "教学示意"
        self._active_analysis = ""
        self._tool_buttons: dict[str, QToolButton] = {}
        self._engineering_contract: dict[str, Any] | None = None
        self._engineering_sync_scene_revision: int | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        toolbar = QFrame()
        toolbar.setObjectName("TeachingToolbar")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(10, 5, 10, 5)
        row.setSpacing(5)
        for key, title in (("scheme", "方案"), ("equipment", "器材库"), ("inspector", "属性"), ("display", "显示"), ("measure", "测量"), ("imaging", "成像"), ("coupling", "耦合"), ("calculate", "计算"), ("result", "结果"), ("sync_to_simulation", "同步到仿真"), ("sync_from_simulation", "从仿真更新")):
            button = QToolButton()
            button.setText(title)
            button.setObjectName("TeachingToolButton")
            button.setCheckable(key in {"equipment", "inspector", "imaging", "coupling", "result"})
            if key == "scheme":
                button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                scheme_menu = QMenu(button)
                for count, label in ((1, "单透镜"), (2, "双透镜"), (3, "三透镜"), (4, "四非球面 · 780 nm 高效耦合")):
                    action = scheme_menu.addAction(label)
                    action.triggered.connect(lambda _checked=False, value=count: self._apply_scheme(value))
                button.setMenu(scheme_menu)
            button.clicked.connect(lambda _checked=False, value=key: self._toolbar_action(value))
            row.addWidget(button)
            self._tool_buttons[key] = button
        row.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("TeachingStatus")
        row.addWidget(self.status)
        row.addWidget(QLabel("画布"))
        self.canvas_mode = QComboBox()
        self.canvas_mode.setObjectName("TeachingCanvasMode")
        self.canvas_mode.addItems(["二维", "三维"])
        self.canvas_mode.setToolTip("切换中央画布视图，不把二维和三维压缩成上下两栏")
        self.canvas_mode.currentTextChanged.connect(self._canvas_mode_changed)
        row.addWidget(self.canvas_mode)
        root.addWidget(toolbar)
        self.scene = BenchScene(self.store, self)
        self.scene.moved.connect(self._scene_item_moved)
        self.scene.activated.connect(self._open_selected_inspector)
        self.view = BenchView(self.scene, self)
        try:
            from PySide6.QtWidgets import QApplication
            if QApplication.instance() is not None and QApplication.instance().platformName() == "offscreen":
                raise RuntimeError("当前运行平台为 offscreen，跳过 3D 视口")
            self.view3d = BenchView3D(self.store, self)
        except Exception as exc:
            self.view3d = QLabel(f"3D 视口不可用：{exc}", self)
            self.view3d.setObjectName("Teaching3DFallback")
        self.view_stack = QStackedWidget(self)
        self.view_stack.addWidget(self.view)
        self.view_stack.addWidget(self.view3d)
        self.inspector = Inspector(self.store, self)
        self.inspector.setWindowFlags(Qt.WindowType.Tool)
        self.inspector.setWindowTitle("当前对象")
        self.inspector.hide()
        self.inspector.publishRequested.connect(lambda: self._toolbar_action("sync_to_simulation"))
        self.controller = ComputationController(
            self.store,
            gateway=FormalTeachingGateway(
                engineering_request_provider=self._engineering_request_for_current_scene,
            ),
            parent=self,
        )
        self.controller.stateChanged.connect(self._on_compute_state)
        self.controller.previewReady.connect(self._apply_preview_rays)
        self.controller.resultReady.connect(self._on_formal_result)
        root.addWidget(self.view_stack, 1)
        self._create_quick_actions()
        self._install_teaching_shortcuts()
        self.store.sceneChanged.connect(self._scene_changed)
        self.store.resultChanged.connect(lambda _kind, _result: self._refresh_result_popup())
        project_context = getattr(self.context, "project", None)
        project_changed = getattr(project_context, "project_changed", None)
        if project_changed is not None:
            project_changed.connect(self._invalidate_engineering_contract)
        payload_changed = getattr(project_context, "simulation_project_payload_changed", None)
        if payload_changed is not None:
            payload_changed.connect(self._invalidate_engineering_contract)
        self.view.fit_scene()
        reset_camera = getattr(self.view3d, "reset_camera", None)
        if callable(reset_camera):
            reset_camera()
        if not isinstance(self.view3d, QLabel):
            self.canvas_mode.setCurrentText("三维")
        self.controller.request_preview()
        bridge = getattr(self.view3d, "bridge", None)
        if bridge is not None and hasattr(bridge, "kindDropped"):
            bridge.kindDropped.connect(self._drop_component)

    def _create_quick_actions(self) -> None:
        """Visible, recoverable edit controls kept at the canvas lower-right."""
        self.quick_actions = QFrame(self)
        self.quick_actions.setObjectName("TeachingQuickActions")
        row = QHBoxLayout(self.quick_actions)
        row.setContentsMargins(7, 5, 7, 5)
        row.setSpacing(6)
        self._quick_action_buttons: dict[str, QToolButton] = {}
        for key, glyph, label, tip, color, callback in (
            ("undo", "undo", "撤销", "撤销上一步", "#155EEF", self._undo_scene),
            ("redo", "redo", "下一步", "重做下一步", "#155EEF", self._redo_scene),
            ("delete", "delete", "删除", "删除当前选中器件", "#B42318", self._delete_selected),
            ("clear", "reset", "清空", "清空教学台（可撤销）", "#B42318", self._clear_scene),
        ):
            button = QToolButton(self.quick_actions)
            button.setObjectName("TeachingQuickAction")
            button.setIcon(icon(glyph, color, 22))
            button.setIconSize(QSize(22, 22))
            button.setText(label)
            button.setToolTip(tip)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.clicked.connect(callback)
            row.addWidget(button)
            self._quick_action_buttons[key] = button
        self.quick_actions.adjustSize()
        self.quick_actions.show()
        self._position_overlay_controls()
        self._refresh_quick_actions()

    def _install_teaching_shortcuts(self) -> None:
        bindings = (
            (QKeySequence.StandardKey.Delete, self._delete_selected),
            (QKeySequence.StandardKey.Undo, self._undo_scene),
            (QKeySequence.StandardKey.Redo, self._redo_scene),
            (QKeySequence("Ctrl+Shift+Z"), self._redo_scene),
        )
        self._teaching_shortcuts: list[QShortcut] = []
        for sequence, callback in bindings:
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._teaching_shortcuts.append(shortcut)

    def _position_overlay_controls(self) -> None:
        if not hasattr(self, "quick_actions") or not hasattr(self, "view_stack"):
            return
        self.quick_actions.adjustSize()
        view_origin = self.view_stack.mapTo(self, QPoint(0, 0))
        right = view_origin.x() + self.view_stack.width() - 18
        bottom = view_origin.y() + self.view_stack.height() - 18
        self.quick_actions.move(
            max(10, right - self.quick_actions.width()),
            max(view_origin.y() + 10, bottom - self.quick_actions.height()),
        )
        self.quick_actions.raise_()

    def _refresh_quick_actions(self) -> None:
        if not hasattr(self, "_quick_action_buttons"):
            return
        selected = self.store.selected_component_id in self.store.components
        self._quick_action_buttons["delete"].setEnabled(selected)
        self._quick_action_buttons["undo"].setEnabled(self.store.can_undo())
        self._quick_action_buttons["redo"].setEnabled(self.store.can_redo())
        self._quick_action_buttons["clear"].setEnabled(bool(self.store.components))

    def _delete_selected(self) -> None:
        component_id = self.store.selected_component_id
        if component_id and self.store.remove_component(component_id):
            self.status.setText("已删除当前器件；可点撤销恢复")

    def _scene_item_moved(self, component_id: str, x_mm: float, y_mm: float) -> None:
        component = self.store.components.get(component_id)
        if component is not None:
            self.status.setText(f"{component.label}：沿导轨 {x_mm:.1f} mm · 横向 {y_mm:.1f} mm")

    def _open_selected_inspector(self, _component_id: str) -> None:
        self._toolbar_action("inspector")
        if not self.inspector.isVisible():
            self._toolbar_action("inspector")

    def _undo_scene(self) -> None:
        if self.store.undo():
            self.status.setText("已撤销")

    def _redo_scene(self) -> None:
        if self.store.redo():
            self.status.setText("已重做")

    def _clear_scene(self) -> None:
        self.store.clear_scene()
        self.status.setText("教学台已清空；可点撤销恢复")

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        QTimer.singleShot(0, self._position_overlay_controls)

    def _invalidate_engineering_contract(self, *_args) -> None:
        """Do not retain a comparison claim after either source has changed."""
        self._engineering_contract = None
        self._engineering_sync_scene_revision = None

    def _engineering_request_for_current_scene(self) -> dict[str, Any] | None:
        if (
            not self._engineering_contract
            or self._engineering_sync_scene_revision != int(self.store.revision)
        ):
            return None
        return {
            "project": dict(self._engineering_contract.get("project") or {}),
            "options": dict(self._engineering_contract.get("options") or {}),
            "precision": str(self._engineering_contract.get("precision") or "standard"),
        }

    @staticmethod
    def _engineering_lens_groups(project: object) -> list[list[object]]:
        """Return consecutive lens-surface groups, preserving prescription order."""
        surfaces = list(getattr(project, "surfaces", ()) or ())
        groups: list[list[object]] = []
        current: list[object] = []
        current_key = ""
        for index, surface in enumerate(surfaces):
            kind = str(getattr(surface, "surface_type", "") or "").strip().lower()
            if kind in {"detector", "探测器/像面", "coordinate_break", "坐标断点"}:
                continue
            key = str(getattr(surface, "group_id", "") or "").strip() or f"pair-{index // 2 + 1}"
            if current and key != current_key:
                groups.append(current)
                current = []
            current.append(surface)
            current_key = key
        if current:
            groups.append(current)
        return groups

    def _sync_scene_from_engineering_project(self) -> None:
        project_context = getattr(self.context, "project", None)
        project = getattr(project_context, "project", None)
        if project is None:
            self.status.setText("当前没有仿真工程")
            return
        serialized = serialize_project(project)
        stored_payload = getattr(project_context, "simulation_project_payload", {}) or {}
        if isinstance(stored_payload, dict) and stored_payload.get("surfaces"):
            serialized = dict(stored_payload)
        source = dict(serialized.get("source") or {})
        receiver = dict(serialized.get("receiver") or {})
        system = dict(serialized)
        axis_height = float(self.store.reference.axis_height_mm)
        wavelength = float(source.get("wavelength_nm") or getattr(project, "wavelength_nm", 0.0) or 780.0)
        waist = max(0.01, float(source.get("waist_x_mm") or 0.5))
        mfd = float(receiver.get("mode_field_diameter_x_um") or getattr(project, "receiver_mfd_um", 0.0) or 5.0)
        na = float(receiver.get("na_x") or 0.12)
        components: list[dict[str, Any]] = [
            {
                "component_id": "laser-001",
                "kind": "laser",
                "label": "工程光源",
                "pose": {"x_mm": 0.0, "y_mm": 0.0, "z_mm": axis_height},
                "params": {"wavelength_nm": wavelength, "beam_radius_mm": waist},
            }
        ]
        axial = 0.0
        for ordinal, group in enumerate(self._engineering_lens_groups(project), start=1):
            front = group[0]
            rear = group[-1] if len(group) > 1 else None
            thickness = max(0.1, float(getattr(front, "thickness_mm", 0.0) or 0.0))
            axial += thickness * 0.5
            first_radius = float(getattr(front, "radius_mm", 0.0) or 0.0)
            second_radius = float(getattr(rear, "radius_mm", 0.0) or 0.0) if rear is not None else 0.0
            aperture = float(getattr(front, "semi_aperture_mm", 0.0) or 0.0)
            label = str(getattr(front, "group_id", "") or f"L{ordinal}")
            components.append(
                {
                    "component_id": f"lens-{ordinal + 1:03d}",
                    "kind": "lens",
                    "label": f"{label} 透镜",
                    "pose": {"x_mm": max(8.0, axial), "y_mm": 0.0, "z_mm": axis_height},
                    "params": {
                        "radius1_mm": first_radius,
                        "radius2_mm": second_radius,
                        "center_thickness_mm": thickness,
                        "material": str(getattr(front, "material", "N-BK7") or "N-BK7"),
                        "clear_aperture_mm": aperture,
                        "diameter_mm": max(2.0 * aperture, 1.0),
                        "conic": float(getattr(front, "conic", 0.0) or 0.0),
                    },
                }
            )
            axial += max(0.0, sum(float(getattr(item, "thickness_mm", 0.0) or 0.0) for item in group) - thickness * 0.5)
        image_distance = max(4.0, float(system.get("image_distance_mm") or 8.0))
        components.append(
            {
                "component_id": f"fiber-{len(components) + 1:03d}",
                "kind": "fiber",
                "label": "工程光纤接收端",
                "pose": {"x_mm": max(24.0, axial + image_distance), "y_mm": 0.0, "z_mm": axis_height},
                "params": {"mfd_um": mfd, "na": na},
            }
        )
        snapshot = self.store.to_dict()
        snapshot.update(
            {
                "revision": int(self.store.revision) + 1,
                "components": components,
                "selected_component_id": components[1]["component_id"] if len(components) > 2 else components[0]["component_id"],
                "results": {},
                "active_result_revision": None,
            }
        )
        self.store.restore_dict(snapshot, reason="从仿真更新教学台")
        contract = serialized.get("calculation_contract") if isinstance(serialized, dict) else None
        if isinstance(contract, dict) and isinstance(contract.get("options"), dict):
            self._engineering_contract = {
                "project": serialized,
                "options": dict(contract["options"]),
                "precision": str(contract.get("precision") or "standard"),
            }
            self._engineering_sync_scene_revision = int(self.store.revision)
            comparison = "后续不修改教学台时，成像和耦合将与仿真工程同处方、同数值配置。"
        else:
            self._engineering_contract = None
            self._engineering_sync_scene_revision = None
            comparison = "已载入工程处方；请先在仿真页完成一次正式计算，再更新教学台以继承数值配置。"
        self._last_equipment_id = None
        self.set_result_origin("教学示意")
        self.view.fit_scene()
        reset_camera = getattr(self.view3d, "reset_camera", None)
        if callable(reset_camera):
            reset_camera()
        self.controller.request_preview()
        self.status.setText(f"已从仿真更新 {len(components) - 2} 片透镜、波长和光纤模场；{comparison}")

    def _toolbar_action(self, key: str) -> None:
        # Tool windows stay modeless, but their pressed state makes it obvious
        # which analysis or panel the user just opened.
        if key in {"equipment", "inspector", "imaging", "coupling", "result"}:
            for name in {"equipment", "inspector", "imaging", "coupling", "result"}:
                button = self._tool_buttons.get(name)
                if button is not None:
                    button.setChecked(name == key)
        if key == "equipment":
            if self.equipment_popup is None:
                self.equipment_popup = TeachingEquipmentPopup(self)
                self.equipment_popup.addRequested.connect(self._add_component)
                self.equipment_popup.presetRequested.connect(self._apply_equipment_preset)
            self._place_tool_window(self.equipment_popup, "equipment")
            self.equipment_popup.show()
            self.equipment_popup.raise_()
        elif key == "inspector":
            self._place_tool_window(self.inspector, "inspector", corner="right")
            self.inspector.setVisible(not self.inspector.isVisible())
            if self.inspector.isVisible():
                self.inspector.raise_()
        elif key == "result":
            if self.result_popup is None:
                self.result_popup = TeachingResultPopup(self._teaching_result_origin, self)
            else:
                self.result_popup.set_origin(self._teaching_result_origin)
            self.result_popup.set_snapshot(self.store.snapshot())
            self._place_tool_window(self.result_popup, "result", corner="right")
            self.result_popup.show()
            self.result_popup.raise_()
        elif key in {"imaging", "coupling"}:
            self._show_analysis_popup(key)
        elif key == "calculate":
            self.set_result_origin("近似计算")
            self.controller.request_preview()
            self.status.setText("光路示意已更新")
        elif key == "sync_to_simulation":
            payload = self.store.to_publish_dict()
            changes: dict[str, float] = {}
            for item in self.store.components.values():
                if not item.enabled:
                    continue
                if item.kind == "laser":
                    try:
                        wavelength = float(item.params.get("wavelength_nm", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        wavelength = 0.0
                    if wavelength > 0.0:
                        changes["source.wavelength_nm"] = wavelength
                elif item.kind == "fiber":
                    try:
                        mfd = float(item.params.get("mfd_um", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        mfd = 0.0
                    if mfd > 0.0:
                        changes["receiver.mode_field_diameter_x_um"] = mfd
            project_context = getattr(self.context, "project", None)
            apply_changes = getattr(project_context, "apply_parameter_changes", None)
            applied = bool(callable(apply_changes) and apply_changes(changes, reason="教学方案同步到仿真"))
            updater = getattr(self.context.project, "update_research_profile", None)
            if callable(updater):
                updater({"active_snapshot_source": "teaching", "teaching_snapshot": payload})
            if applied:
                self._invalidate_engineering_contract()
                self.status.setText(f"已同步 {len(changes)} 项可映射参数并保存教学快照；请从仿真更新后再比较指标")
            elif changes:
                self.status.setText("参数与当前仿真相同；已保存教学快照")
            else:
                self.status.setText("未发现可同步的波长或模场参数；已保存教学快照")
        elif key == "sync_from_simulation":
            self._sync_scene_from_engineering_project()
        elif key == "display":
            self._show_display_menu()
        elif key == "measure":
            self._measure_selected()

    def _apply_scheme(self, lens_count: int) -> None:
        if int(lens_count) == 4:
            # The four-lens teaching preset is the same engineering project
            # used by simulation, including receiver and numerical settings.
            # This prevents the menu from loading the old independent 808 nm
            # scene whose efficiency could not be compared with simulation.
            from frontend_pyside.state.project_context import default_project

            project_context = getattr(self.context, "project", None)
            project = default_project()
            state = SimulationFormState()
            payload = serialize_project(project, state)
            payload["calculation_contract"] = {
                "precision": str(state.calculation.precision),
                "options": state.request_options(),
            }
            project_context.set_project(project, dirty=False)
            project_context.set_simulation_project_payload(payload)
            self._sync_scene_from_engineering_project()
            self.status.setText("已载入四非球面 · 780 nm 高效耦合演示；教学与仿真共用同一计算处方")
            return
        self.store.apply_optical_scheme(int(lens_count))
        self._invalidate_engineering_contract()
        self._last_equipment_id = None
        self.set_result_origin("教学示意")
        self.view.fit_scene()
        reset_camera = getattr(self.view3d, "reset_camera", None)
        if callable(reset_camera):
            reset_camera()
        self.controller.request_preview()
        self.status.setText(f"已载入{int(lens_count)}透镜方案：808 nm 激光器 → 透镜组 → 单模光纤")

    def _show_display_menu(self) -> None:
        menu = QMenu(self)
        reset_camera = getattr(self.view3d, "reset_camera", None)
        look_top = getattr(self.view3d, "look_top", None)
        if callable(reset_camera):
            menu.addAction("重置三维视角", reset_camera)
        if callable(look_top):
            menu.addAction("俯视", look_top)
        menu.addAction("二维适配画面", self.view.fit_scene)
        button = self._tool_buttons.get("display")
        origin = button.mapToGlobal(button.rect().bottomLeft()) if button is not None else self.mapToGlobal(self.rect().topLeft())
        menu.exec(origin)

    def _measure_selected(self) -> None:
        cid = self.store.selected_component_id
        item = self.store.components.get(str(cid or ""))
        if item is None:
            self.status.setText("未选择对象")
            return
        pose = item.pose
        self.status.setText(
            f"{item.label}  沿导轨 {pose.x_mm:.1f} mm  横向 {pose.y_mm:.1f} mm  离台 {pose.z_mm:.1f} mm"
        )

    def _show_analysis_popup(self, key: str) -> None:
        analysis = {"imaging": "spot", "coupling": "coupling"}.get(str(key), "")
        if not analysis:
            return
        popup = self.analysis_popups.get(analysis)
        if popup is None:
            popup = TeachingAnalysisPopup(analysis, self)
            popup.calculateRequested.connect(self._request_formal_analysis)
            self.analysis_popups[analysis] = popup
        popup.set_scene_revision(self.store.revision)
        self._place_tool_window(popup, key, corner="right")
        popup.show()
        popup.raise_()

    def _request_formal_analysis(self, analysis: str) -> None:
        analysis = str(analysis or "")
        popup = self.analysis_popups.get(analysis)
        if popup is None:
            return
        self._active_analysis = analysis
        popup.set_busy(True, "正在提交正式光学计算…")
        self.set_result_origin("正式计算")
        self.controller.request_formal(analysis)

    def _on_formal_result(self, analysis: str, result: object) -> None:
        analysis = str(analysis or "")
        popup = self.analysis_popups.get(analysis)
        if popup is not None:
            popup.set_result(result)
        self.set_result_origin("正式计算")
        self._refresh_result_popup()
        self._active_analysis = ""

    def _refresh_result_popup(self) -> None:
        if self.result_popup is not None:
            self.result_popup.set_snapshot(self.store.snapshot())

    def _on_compute_state(self, _state: str, message: str) -> None:
        if message:
            self.status.setText(message)
        popup = self.analysis_popups.get(self._active_analysis)
        if popup is None:
            return
        state = str(_state or "")
        if state == "running":
            popup.set_busy(True, message)
        elif state in {"blocked", "failed", "cancelled", "stale", "missed"}:
            popup.set_busy(False, message)
        elif state == "completed":
            popup.set_busy(False)

    def _apply_preview_rays(self, result) -> None:
        from frontend_pyside.features.teaching_v2.physics import ray_segment_to_dict

        rays = [ray_segment_to_dict(ray) for ray in getattr(result, "rays", ()) or ()]
        self.scene.set_rays(rays)
        set_rays = getattr(self.view3d, "set_rays", None)
        if callable(set_rays):
            set_rays(rays, self.store.snapshot())

    def _canvas_mode_changed(self, text: str) -> None:
        is_3d = str(text) == "三维"
        self.view_stack.setCurrentWidget(self.view3d if is_3d else self.view)
        QTimer.singleShot(0, self._position_overlay_controls)
        self.status.setText("")

    def set_result_origin(self, origin: str) -> None:
        allowed = {"教学示意", "近似计算", "正式计算"}
        value = str(origin or "教学示意")
        self._teaching_result_origin = value if value in allowed else "教学示意"
        if self.result_popup is not None:
            self.result_popup.set_origin(self._teaching_result_origin)

    def _place_tool_window(self, widget, button_key: str, *, corner: str = "left") -> None:
        button = self._tool_buttons.get(button_key)
        if corner == "right":
            origin = self.view_stack.mapToGlobal(self.view_stack.rect().topRight())
            widget.move(origin.x() - max(widget.width(), 320) - 8, origin.y() + 8)
            return
        if button is None:
            return
        widget.move(button.mapToGlobal(button.rect().bottomLeft()))

    def _drop_component(self, kind: str, x_mm: float, y_mm: float, z_mm: float) -> None:
        self._add_component(kind, Pose(float(x_mm), float(y_mm), float(z_mm)))

    def _add_component(self, kind: str, pose: Pose | None = None) -> None:
        mapping = {"detector": "ccd", "power": "power_meter", "camera": "ccd"}
        resolved = mapping.get(str(kind), str(kind))
        kwargs = {"pose": pose} if pose is not None else {}
        self._last_equipment_id = self.store.add_component(resolved, **kwargs)
        self.status.setText(f"已添加 {dict(PLACEABLE_KINDS).get(resolved, resolved)}")
        # A click in the equipment library should immediately expose editable
        # X/Y/Z coordinates for the newly selected component.
        if not self.inspector.isVisible():
            self._place_tool_window(self.inspector, "inspector", corner="right")
            self.inspector.show()
        self.inspector.raise_()

    def _apply_equipment_preset(self, kind: str, payload: object) -> None:
        component_id = self._last_equipment_id or self.store.selected_component_id
        if not component_id or not isinstance(payload, dict):
            return
        if self.store.update_params(component_id, payload, reason=f"应用{kind}工程常用规格"):
            self.status.setText("已应用工程规格")

    def _scene_changed(self, snapshot, _reason: str = "") -> None:
        if (
            self._engineering_sync_scene_revision is not None
            and int(snapshot.revision) != int(self._engineering_sync_scene_revision)
        ):
            self._invalidate_engineering_contract()
        rays = (snapshot.results.get("geometry") or {}).get("rays") or []
        self.scene.set_rays(rays)
        set_rays = getattr(self.view3d, "set_rays", None)
        if callable(set_rays):
            set_rays(rays, snapshot)
        for popup in self.analysis_popups.values():
            popup.set_scene_revision(snapshot.revision)
        self._refresh_result_popup()
        self._refresh_quick_actions()
        self._position_overlay_controls()

    def assistant_context(self) -> dict:
        snapshot = self.store.snapshot()
        return {
            "page": "教学中心",
            "current_view": "教学实验台",
            "node_count": len(getattr(snapshot, "components", ()) or ()),
            "selected_component_id": getattr(snapshot, "selected_component_id", ""),
        }


__all__ = [
    "KIND_TITLES",
    "PRIMARY_MODULES",
    "SECONDARY_ITEMS",
    "DocumentWorkspace",
    "ObjectRail",
    "PrimaryBar",
    "SecondaryBar",
    "TabSpec",
    "TeachingAnalysisPopup",
    "TeachingShell",
    "WorkflowHome",
    "WorkbenchShell",
]

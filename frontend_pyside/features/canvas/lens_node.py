"""镜头组 source 节点：纯顺序表面表格经 NodeHost proxy 嵌入。

- 展开时懒加载纯表格编辑器（与主窗口共用同一 ProjectContext）；
- 编辑表面 → ProjectContext.project_changed → L0 即时估计 + sourceChanged
  → scene 沿边传播「!」；
- surface_rows() 从 ProjectContext 读当前表面，作为引擎桥的真实输入；
- 折叠态隐藏嵌入 widget（lesson：折叠不缩放，避免 proxy 事件冲突）。
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
    QVBoxLayout,
)

from frontend_pyside.features.canvas.engine_bridge import default_surface_rows
from frontend_pyside.shared.qt_zh import localize_dialog_buttons
from frontend_pyside.features.canvas.lens_table import LensSurfaceTable
from frontend_pyside.features.canvas.node import CanvasNode
from frontend_pyside.features.canvas.node_host import NodeHost
from frontend_pyside.features.canvas.parameter_catalog import (
    ANALYSIS_PUPIL_CHOICES,
    APERTURE_TYPE_CHOICES,
    CALC_PRECISION_CHOICES,
    COATING_CHOICES,
    LAYOUT_PUPIL_CHOICES,
    MATERIAL_CHOICES,
    OUTPUT_GRID_CHOICES,
    POWER_UNIT_CHOICES,
    PROPAGATION_CHOICES,
    RECEIVER_MODE_CHOICES,
    RECEIVER_TYPE_CHOICES,
    SOURCE_TYPE_CHOICES,
    STOP_ROLE_CHOICES,
    STOP_SHAPE_CHOICES,
    OPTIMIZATION_ALGORITHM_CHOICES,
    OPTIMIZATION_OBJECTIVE_CHOICES,
)
from frontend_pyside.features.simulation.dirty_state import DirtyScope
from frontend_pyside.features.simulation.instant_metrics import estimate_efficiency
from frontend_pyside.features.canvas.engine_bridge import form_state, surfaces_to_project
from frontend_pyside.features.canvas.model_node import ParameterCapsule, ParameterEdge
from frontend_pyside.features.simulation.surface_registry import (
    apply_type_defaults,
    ensure_surface_defaults,
    get_surface_type,
    surface_type_names,
)
from frontend_pyside.state.project_context import ProjectContext


def lens_table_factory(project_context):
    """NodeHost 工厂：只创建镜头面组表格。"""
    return LensSurfaceTable(project_context)


class LensNode(CanvasNode):
    """镜头组数据源节点：纯 Surface 表格 proxy。"""

    sourceChanged = Signal(str, int)  # (reason, DirtyScope) → scene 按 §6.3 过滤传播

    def __init__(self, node_id: str, spec, project_context=None, parent=None):
        super().__init__(node_id, spec, parent)
        self._project: ProjectContext = project_context or ProjectContext()
        # 下拉值属于当前系统状态，不能因为节点化而丢失。
        self._config = {
            "source_type": "高斯模式",
            "source_axis_split": False,
            "source_waist_x_um": 893.0,
            "source_waist_y_um": 1050.0,
            "source_waist_position_mm": 0.0,
            "source_m2_x": 3.05,
            "source_m2_y": 1.33,
            "source_na_x": 0.00018,
            "source_na_y": 0.00018,
            "field_x_deg": 0.0,
            "field_y_deg": 0.0,
            "power_value": 1.0,
            "power_unit": "mW",
            "auxiliary_wavelengths_nm": "",
            "object_distance_mm": 18.182441199500627,
            "image_distance_mm": 8.973730675077647,
            "environment_temperature_c": 20.0,
            "environment_pressure_kpa": 101.325,
            "thermal_compensation": False,
            "auto_best_focus": False,
            "receiver_type": "单模光纤",
            "mode_model": "高斯近似",
            "receiver_axis_split": False,
            "receiver_mfd_x_um": 5.0,
            "receiver_mfd_y_um": 5.0,
            "receiver_na_x": 0.13,
            "receiver_na_y": 0.13,
            "receiver_core_diameter_um": 3.0,
            "receiver_n_core": 1.45,
            "receiver_n_clad": 1.44,
            "receiver_outside_index": 1.0,
            "receiver_offset_x_um": 0.0,
            "receiver_offset_y_um": 0.0,
            "receiver_offset_z_um": 0.0,
            "receiver_tilt_x_urad": 0.0,
            "receiver_tilt_y_urad": 0.0,
            "receiver_endface_transmission": 0.995,
            "receiver_length_m": 0.0,
            "receiver_attenuation_db_per_km": 0.0,
            "receiver_connector_loss_db": 0.0,
            "imported_mode_source": "",
            "calc_precision": "257×257",
            "calc_grid": "513 × 513",
            "calc_layout_pupil": "9 × 9",
            "calc_pupil": "49 × 49",
            "calc_propagation": "缩放 Fresnel",
            "calc_zero_padding": 2.0,
            "calc_output_extent_mm": 0.024,
            "calc_auto_expand_output": True,
            "calc_only_visible_results": True,
            "calc_sampling_convergence": False,
            "calc_save_large_arrays": True,
            "calc_high_precision_coupling": True,
            "analysis_raytrace": True,
            "analysis_spot": True,
            "analysis_psf": True,
            "analysis_coupling": True,
            "analysis_mtf": False,
            "analysis_power_audit": False,
            "optimization_algorithm": "智能全局搜索",
            "optimization_objective": "最大化耦合效率",
            "alignment_enabled": False,
            "alignment_include_dz": True,
            "alignment_max_offset_um": 20.0,
            "alignment_max_axial_offset_um": 200.0,
            "alignment_max_tilt_urad": 5000.0,
            "alignment_max_iterations": 40,
            "alignment_max_function_evaluations": 300,
            "alignment_timeout_seconds": 60.0,
        }
        self._eta_l0 = float("nan")
        self._last_signature = self._surfaces_signature()
        self._chrome_settings = True
        self._settings_open = False
        self._settings_capsules: list[ParameterCapsule] = []
        self._settings_edges: list[ParameterEdge] = []
        self.settingsRequested.connect(self.toggle_settings_capsules)
        # 初次构造只建立共享引用，不把默认值误记成用户修改。
        self._project.project._canvas_form_config = deepcopy(self._config)

        self._host = NodeHost(
            self, "frontend_pyside.features.canvas.lens_node:lens_table_factory"
        )
        self._host.sync_geometry(
            12.0, self.HEADER_H + 8.0, self._full_w - 24.0, self._full_h - self.HEADER_H - 16.0
        )
        self._host.setVisible(False)  # 默认折叠：不显示嵌入面板

        # 真实数据链路：编辑器写入 ProjectContext → project_changed → 脏传播
        self._project.project_changed.connect(self._on_project_changed)
        self._update_l0()  # 启动即给出 L0，不触发脏传播

    # ---- 几何 -----------------------------------------------------------

    def _content_geometry(self) -> tuple[float, float, float, float]:
        return (12.0, self.HEADER_H + 8.0, self._full_w - 24.0, self._full_h - self.HEADER_H - 16.0)

    def _on_resize(self) -> None:
        self._host.sync_geometry(*self._content_geometry())
        self._layout_settings_capsules()

    def _on_expand_state(self) -> None:
        if not self._collapsed:
            self._host.ensure_loaded((self._project,))
            self._host.sync_geometry(*self._content_geometry())
        self._host.setVisible(not self._collapsed)
        self._layout_settings_capsules()

    def toggle_settings_capsules(self) -> None:
        if self._settings_open:
            self._clear_settings_capsules()
            return
        self._settings_open = True
        self._layout_settings_capsules()

    def _clear_settings_capsules(self) -> None:
        for edge in self._settings_edges:
            scene = edge.scene()
            if scene is not None:
                scene.removeItem(edge)
            edge.setParentItem(None)
        for capsule in self._settings_capsules:
            scene = capsule.scene()
            if scene is not None:
                scene.removeItem(capsule)
            capsule.setParentItem(None)
        self._settings_edges.clear()
        self._settings_capsules.clear()
        self._settings_open = False

    def _layout_settings_capsules(self) -> None:
        if not self._settings_open:
            return
        self._clear_settings_capsules()
        self._settings_open = True
        groups = (
            ("basic", "基本信息", f"{len(self._project.project.surfaces)} 个表面"),
            ("aperture", "光阑与孔径", f"入瞳 {self._project.project.pupil_radius_mm:g} mm"),
            ("wave", "光源与视场", f"{self._project.project.wavelength_nm:g} nm · {self._config['source_type']}"),
            ("receiver", "接收与装调", f"{self._config['receiver_type']} · MFD {self._config['receiver_mfd_x_um']:g} μm"),
            ("system", "系统环境", f"物距 {self._config['object_distance_mm']:g} mm"),
            ("constraints", "求解与约束", str(self._config["optimization_algorithm"])),
            ("analysis", "分析设置", str(self._config["calc_propagation"])),
        )
        direction = self._settings_direction(len(groups))
        for index, (key, title, summary) in enumerate(groups):
            capsule = ParameterCapsule(key, title, summary, self)
            x = -ParameterCapsule.WIDTH - 24.0 if direction < 0 else self._w + 24.0
            capsule.setPos(x, 34.0 + index * (ParameterCapsule.HEIGHT + 7.0))
            capsule.clicked.connect(self._edit_settings_group)
            edge = ParameterEdge(self, capsule, direction, self)
            self._settings_capsules.append(capsule)
            self._settings_edges.append(edge)
        self.update()

    def _settings_direction(self, count: int) -> int:
        if float(self.pos().x()) < ParameterCapsule.WIDTH + 48.0:
            return 1
        scene = self.scene()
        if scene is None:
            return -1
        rect = QRectF(
            self.pos().x() - ParameterCapsule.WIDTH - 24.0,
            self.pos().y() + 28.0,
            ParameterCapsule.WIDTH,
            count * (ParameterCapsule.HEIGHT + 7.0),
        )
        for item in scene.items(rect):
            if item is self or item in self._settings_capsules or item in self._settings_edges:
                continue
            if hasattr(item, "spec"):
                return 1
        return -1

    def _edit_settings_group(self, group_key: str) -> None:
        handlers = {
            "basic": self._edit_basic_group,
            "aperture": self._edit_aperture_group,
            "wave": self._edit_wave_group,
            "receiver": self._edit_receiver_group,
            "system": self._edit_system_group,
            "constraints": self._edit_constraints_group,
            "analysis": self._edit_analysis_group,
        }
        handler = handlers.get(str(group_key))
        if handler is not None:
            handler()

    @staticmethod
    def _add_combo(form: QFormLayout, label: str, values: tuple[str, ...] | list[str], current: str) -> QComboBox:
        combo = QComboBox()
        combo.addItems(list(values))
        combo.setCurrentText(str(current))
        form.addRow(label, combo)
        return combo

    @staticmethod
    def _add_float(form: QFormLayout, label: str, value: float, minimum: float, maximum: float, suffix: str = "", decimals: int = 6) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(float(minimum), float(maximum))
        spin.setDecimals(int(decimals))
        spin.setValue(float(value))
        if suffix:
            spin.setSuffix(suffix)
        form.addRow(label, spin)
        return spin

    def _finish_dialog(self, dialog: QDialog, form: QFormLayout) -> bool:
        buttons = localize_dialog_buttons(
            QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
                parent=dialog,
            )
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _surface_combo(self, form: QFormLayout, label: str = "编辑表面") -> QComboBox:
        combo = QComboBox()
        for index, surface in enumerate(self._project.project.surfaces):
            combo.addItem(f"S{index + 1} · {surface.group_id} · {surface.name}", index)
        form.addRow(label, combo)
        return combo

    def _edit_basic_group(self) -> None:
        if not self._project.project.surfaces:
            return
        dialog = QDialog()
        dialog.setSizeGripEnabled(True)
        dialog.setWindowTitle("镜头组 · 基本信息")
        form = QFormLayout(dialog)
        surface_combo = self._surface_combo(form)
        surface = self._project.project.surfaces[0]
        name = QLineEdit(str(surface.name))
        surface_type = self._add_combo(form, "表面类型", surface_type_names(), str(surface.surface_type))
        material = self._add_combo(form, "材料 / 后介质", MATERIAL_CHOICES, str(surface.material))
        material.setEditable(True)
        radius = self._add_float(form, "曲率半径 R", surface.radius_mm, -1e9, 1e9, " mm")
        thickness = self._add_float(form, "厚度", surface.thickness_mm, 0.0, 1e9, " mm")
        aperture = self._add_float(form, "半口径", surface.semi_aperture_mm, 0.000001, 1e9, " mm")
        conic = self._add_float(form, "圆锥系数 k", surface.conic, -1e9, 1e9, "", 9)
        form.insertRow(1, "表面名称", name)

        # 旧版 SurfacePropertyMixin 的专用参数页在节点化后仍然完整保留，
        # 只是改成当前胶囊的平面编辑区域：非球面、光阑、反射镜、光栅、
        # 坐标断点、DOE、探测器和用户自定义面都从 surface_registry 动态生成。
        dynamic_form = QFormLayout()
        # QFormLayout can be added directly as a row and does not introduce a
        # second canvas/scrolling surface.
        form.addRow("表面专用参数", dynamic_form)
        dynamic_controls: dict[str, object] = {}
        dynamic_specs: dict[str, object] = {}

        coating = self._add_combo(form, "镀膜", COATING_CHOICES, str(getattr(surface, "coating", "无") or "无"))
        coating.setEditable(True)
        roughness = self._add_float(form, "表面粗糙度", getattr(surface, "roughness_nm", 0.0), 0.0, 1e9, " nm RMS")
        mechanical = self._add_float(
            form, "机械直径", getattr(surface, "mechanical_diameter_mm", 2.0 * surface.semi_aperture_mm),
            0.0001, 1e9, " mm",
        )
        enabled = QCheckBox("参与追迹和正式计算")
        enabled.setChecked(bool(getattr(surface, "enabled", True)))
        form.addRow("启用状态", enabled)
        note = QLineEdit(str(getattr(surface, "note", "") or ""))
        note.setPlaceholderText("元件型号、装配位置或制造备注")
        form.addRow("备注", note)

        def create_control(parameter, value):
            if parameter.kind == "float":
                control = QDoubleSpinBox(dialog)
                control.setRange(float(parameter.minimum), float(parameter.maximum))
                control.setDecimals(int(parameter.decimals))
                if parameter.unit:
                    control.setSuffix(f" {parameter.unit}")
                control.setValue(float(value if value is not None else parameter.default))
            elif parameter.kind == "int":
                control = QSpinBox(dialog)
                control.setRange(int(parameter.minimum), int(parameter.maximum))
                control.setValue(int(value if value is not None else parameter.default))
            elif parameter.kind == "choice":
                control = QComboBox(dialog)
                control.addItems(list(parameter.choices))
                control.setCurrentText(str(value if value is not None else parameter.default))
            elif parameter.kind == "bool":
                control = QCheckBox("启用", dialog)
                control.setChecked(bool(value if value is not None else parameter.default))
            else:
                control = QLineEdit(str(value if value is not None else parameter.default or ""), dialog)
            return control

        def control_value(control, parameter):
            if parameter.kind == "float":
                return float(control.value())
            if parameter.kind == "int":
                return int(control.value())
            if parameter.kind == "choice":
                return control.currentText()
            if parameter.kind == "bool":
                return bool(control.isChecked())
            return control.text().strip()

        def clear_dynamic_rows() -> None:
            while dynamic_form.rowCount():
                dynamic_form.removeRow(0)
            dynamic_controls.clear()
            dynamic_specs.clear()

        def rebuild_dynamic(type_name: str, current_surface=None) -> None:
            clear_dynamic_rows()
            surface_spec = get_surface_type(type_name)
            description = QLabel(surface_spec.description, dialog)
            description.setWordWrap(True)
            dynamic_form.addRow(description)
            values = dict(getattr(current_surface, "type_parameters", {}) or {}) if current_surface is not None else {}
            if not surface_spec.parameters:
                empty = QLabel("该表面类型没有额外专用参数；使用公共参数与面形参数即可。", dialog)
                empty.setWordWrap(True)
                dynamic_form.addRow(empty)
                return
            for parameter in surface_spec.parameters:
                control = create_control(parameter, values.get(parameter.key, parameter.default))
                dynamic_controls[parameter.key] = control
                dynamic_specs[parameter.key] = parameter
                dynamic_form.addRow(parameter.label, control)

        def load(index: int) -> None:
            if not 0 <= int(index) < len(self._project.project.surfaces):
                return
            current = self._project.project.surfaces[int(index)]
            name.setText(str(current.name))
            surface_type.setCurrentText(str(current.surface_type))
            material.setCurrentText(str(current.material))
            radius.setValue(float(current.radius_mm))
            thickness.setValue(float(current.thickness_mm))
            aperture.setValue(max(0.000001, float(current.semi_aperture_mm)))
            conic.setValue(float(getattr(current, "conic", 0.0) or 0.0))
            coating.setCurrentText(str(getattr(current, "coating", "无") or "无"))
            roughness.setValue(float(getattr(current, "roughness_nm", 0.0) or 0.0))
            mechanical.setValue(max(0.0001, float(getattr(current, "mechanical_diameter_mm", 0.0) or 2.0 * current.semi_aperture_mm)))
            enabled.setChecked(bool(getattr(current, "enabled", True)))
            note.setText(str(getattr(current, "note", "") or ""))
            rebuild_dynamic(str(current.surface_type), current)

        def type_changed(type_name: str) -> None:
            index = int(surface_combo.currentData() or 0)
            current = self._project.project.surfaces[index] if 0 <= index < len(self._project.project.surfaces) else None
            rebuild_dynamic(str(type_name), current if current is not None and current.surface_type == type_name else None)

        surface_combo.currentIndexChanged.connect(load)
        surface_type.currentTextChanged.connect(type_changed)
        load(0)
        if not self._finish_dialog(dialog, form):
            return
        index = int(surface_combo.currentData() or 0)
        if not 0 <= index < len(self._project.project.surfaces):
            return
        current = deepcopy(self._project.project.surfaces[index])
        ensure_surface_defaults(current)
        apply_type_defaults(current, surface_type.currentText())
        current.name = name.text().strip() or f"S{index + 1}"
        current.material = material.currentText().strip() or "AIR"
        current.radius_mm = float(radius.value())
        current.thickness_mm = float(thickness.value())
        current.semi_aperture_mm = float(aperture.value())
        current.conic = float(conic.value())
        current.coating = coating.currentText().strip() or "无"
        current.roughness_nm = float(roughness.value())
        current.mechanical_diameter_mm = float(mechanical.value())
        current.enabled = bool(enabled.isChecked())
        current.note = note.text().strip()
        current.type_parameters.update(
            {
                key: control_value(control, dynamic_specs[key])
                for key, control in dynamic_controls.items()
                if key in dynamic_specs
            }
        )
        self._project.update_surface(
            self._project.project.surfaces[index].surface_id,
            name=current.name,
            surface_type=current.surface_type,
            material=current.material,
            radius_mm=current.radius_mm,
            thickness_mm=current.thickness_mm,
            semi_aperture_mm=current.semi_aperture_mm,
            conic=current.conic,
            coating=current.coating,
            roughness_nm=current.roughness_nm,
            mechanical_diameter_mm=current.mechanical_diameter_mm,
            enabled=current.enabled,
            note=current.note,
            type_parameters=current.type_parameters,
        )

    def _edit_aperture_group(self) -> None:
        if not self._project.project.surfaces:
            return
        dialog = QDialog()
        dialog.setWindowTitle("镜头组 · 光阑与孔径")
        form = QFormLayout(dialog)
        pupil = self._add_float(
            form, "系统入瞳半径", getattr(self._project.project, "pupil_radius_mm", 3.0),
            0.000001, 1e6, " mm",
        )
        surface_combo = self._surface_combo(form, "孔径表面")
        surface = self._project.project.surfaces[0]
        parameters = dict(getattr(surface, "type_parameters", {}) or {})
        aperture_type = self._add_combo(form, "孔径类型", APERTURE_TYPE_CHOICES, str(parameters.get("_aperture_type", "圆形通光孔径")))
        shape = self._add_combo(form, "光阑形状", STOP_SHAPE_CHOICES, str(parameters.get("aperture_shape", "圆形")))
        role = self._add_combo(form, "光阑角色", STOP_ROLE_CHOICES, str(parameters.get("stop_role", "孔径光阑")))
        semi = self._add_float(form, "表面半口径", surface.semi_aperture_mm, 0.000001, 1e6, " mm")
        clear = self._add_float(form, "有效通光直径", parameters.get("_clear_aperture_mm", 2.0 * surface.semi_aperture_mm), 0.000001, 2e6, " mm")
        width = self._add_float(form, "矩形宽度", parameters.get("width_mm", 6.0), 0.000001, 1e6, " mm")
        height = self._add_float(form, "矩形高度", parameters.get("height_mm", 6.0), 0.000001, 1e6, " mm")

        def load(index: int) -> None:
            if not 0 <= int(index) < len(self._project.project.surfaces):
                return
            current = self._project.project.surfaces[int(index)]
            values = dict(getattr(current, "type_parameters", {}) or {})
            aperture_type.setCurrentText(str(values.get("_aperture_type", "圆形通光孔径")))
            shape.setCurrentText(str(values.get("aperture_shape", "圆形")))
            role.setCurrentText(str(values.get("stop_role", "孔径光阑")))
            semi.setValue(max(0.000001, float(current.semi_aperture_mm)))
            clear.setValue(max(0.000001, float(values.get("_clear_aperture_mm", 2.0 * current.semi_aperture_mm))))
            width.setValue(max(0.000001, float(values.get("width_mm", 6.0))))
            height.setValue(max(0.000001, float(values.get("height_mm", 6.0))))

        surface_combo.currentIndexChanged.connect(load)
        if not self._finish_dialog(dialog, form):
            return
        index = int(surface_combo.currentData() or 0)
        if not 0 <= index < len(self._project.project.surfaces):
            return
        current = self._project.project.surfaces[index]
        updated_parameters = dict(getattr(current, "type_parameters", {}) or {})
        updated_parameters.update({
            "_aperture_type": aperture_type.currentText(),
            "_clear_aperture_mm": float(clear.value()),
            "aperture_shape": shape.currentText(),
            "stop_role": role.currentText(),
            "width_mm": float(width.value()),
            "height_mm": float(height.value()),
        })
        self._project.update_surface(
            current.surface_id,
            semi_aperture_mm=float(semi.value()),
            type_parameters=updated_parameters,
        )
        self._project.update_pupil_radius(float(pupil.value()))
        self._persist_form_config()

    def _edit_wave_group(self) -> None:
        dialog = QDialog()
        dialog.setWindowTitle("镜头组 · 光源与视场")
        form = QFormLayout(dialog)
        wavelength = self._add_float(form, "工作波长", self._project.project.wavelength_nm, 200.0, 30000.0, " nm", 1)
        source_type = self._add_combo(form, "光源模式", SOURCE_TYPE_CHOICES, self._config["source_type"])
        source_axis = QCheckBox("启用 X/Y 分轴参数")
        source_axis.setChecked(bool(self._config.get("source_axis_split", False)))
        form.addRow("对称方式", source_axis)
        waist_x = self._add_float(form, "束腰半径 / X", self._config["source_waist_x_um"], 0.1, 10000.0, " μm", 3)
        waist_y = self._add_float(form, "束腰半径 / Y", self._config["source_waist_y_um"], 0.1, 10000.0, " μm", 3)
        waist_position = self._add_float(form, "束腰位置", self._config["source_waist_position_mm"], -10000.0, 10000.0, " mm", 3)
        m2_x = self._add_float(form, "M² / X", self._config["source_m2_x"], 1.0, 100.0, "", 3)
        m2_y = self._add_float(form, "M² / Y", self._config["source_m2_y"], 1.0, 100.0, "", 3)
        na_x = self._add_float(form, "数值孔径 / X", self._config["source_na_x"], 0.0, 1.0, "", 6)
        na_y = self._add_float(form, "数值孔径 / Y", self._config["source_na_y"], 0.0, 1.0, "", 6)
        field_x = self._add_float(form, "视场角 / X", self._config["field_x_deg"], -90.0, 90.0, " °", 4)
        field_y = self._add_float(form, "视场角 / Y", self._config["field_y_deg"], -90.0, 90.0, " °", 4)
        power = self._add_float(form, "总功率", self._config["power_value"], 0.0, 1e9, "", 6)
        power_unit = self._add_combo(form, "功率单位", POWER_UNIT_CHOICES, self._config["power_unit"])
        auxiliary = QLineEdit(str(self._config.get("auxiliary_wavelengths_nm", "") or ""))
        auxiliary.setPlaceholderText("例如：1064, 1310, 1590")
        form.addRow("辅助波长", auxiliary)
        if not self._finish_dialog(dialog, form):
            return
        self._config.update({
            "source_type": source_type.currentText(), "power_unit": power_unit.currentText(),
            "source_axis_split": source_axis.isChecked(),
            "source_waist_x_um": waist_x.value(), "source_waist_y_um": waist_y.value(),
            "source_waist_position_mm": waist_position.value(),
            "source_m2_x": m2_x.value(), "source_m2_y": m2_y.value(),
            "source_na_x": na_x.value(), "source_na_y": na_y.value(),
            "field_x_deg": field_x.value(), "field_y_deg": field_y.value(),
            "power_value": power.value(), "auxiliary_wavelengths_nm": auxiliary.text().strip(),
        })
        self._persist_form_config()
        self._project.apply_parameter_changes(
            {"source.wavelength_nm": wavelength.value()},
            reason="镜头组光源与视场参数已修改",
        )

    def _edit_receiver_group(self) -> None:
        dialog = QDialog()
        dialog.setWindowTitle("镜头组 · 接收与装调")
        form = QFormLayout(dialog)
        receiver_type = self._add_combo(form, "接收类型", RECEIVER_TYPE_CHOICES, self._config["receiver_type"])
        mode_model = self._add_combo(form, "模式模型", RECEIVER_MODE_CHOICES, self._config["mode_model"])
        axis = QCheckBox("启用 X/Y 分轴参数")
        axis.setChecked(bool(self._config.get("receiver_axis_split", False)))
        form.addRow("对称方式", axis)
        mfd_x = self._add_float(form, "模场直径 / X", self._config["receiver_mfd_x_um"], 0.1, 10000.0, " μm", 3)
        mfd_y = self._add_float(form, "模场直径 / Y", self._config["receiver_mfd_y_um"], 0.1, 10000.0, " μm", 3)
        na_x = self._add_float(form, "数值孔径 / X", self._config["receiver_na_x"], 0.001, 1.0, "", 6)
        na_y = self._add_float(form, "数值孔径 / Y", self._config["receiver_na_y"], 0.001, 1.0, "", 6)
        core = self._add_float(form, "芯径", self._config["receiver_core_diameter_um"], 0.1, 10000.0, " μm", 3)
        n_core = self._add_float(form, "纤芯折射率", self._config["receiver_n_core"], 1.0, 5.0, "", 6)
        n_clad = self._add_float(form, "包层折射率", self._config["receiver_n_clad"], 1.0, 5.0, "", 6)
        outside = self._add_float(form, "外部折射率", self._config["receiver_outside_index"], 0.1, 5.0, "", 6)
        offset_x = self._add_float(form, "X 方向偏移", self._config["receiver_offset_x_um"], -10000.0, 10000.0, " μm", 3)
        offset_y = self._add_float(form, "Y 方向偏移", self._config["receiver_offset_y_um"], -10000.0, 10000.0, " μm", 3)
        offset_z = self._add_float(form, "轴向偏移", self._config["receiver_offset_z_um"], -10000.0, 10000.0, " μm", 3)
        tilt_x = self._add_float(form, "X 方向倾角", self._config["receiver_tilt_x_urad"], -1e6, 1e6, " μrad", 3)
        tilt_y = self._add_float(form, "Y 方向倾角", self._config["receiver_tilt_y_urad"], -1e6, 1e6, " μrad", 3)
        transmission = self._add_float(form, "端面透射率", self._config["receiver_endface_transmission"], 0.0, 1.0, "", 5)
        length = self._add_float(form, "光纤长度", self._config["receiver_length_m"], 0.0, 1e6, " m", 3)
        attenuation = self._add_float(form, "衰减", self._config["receiver_attenuation_db_per_km"], 0.0, 1e6, " dB/km", 4)
        connector = self._add_float(form, "连接器损耗", self._config["receiver_connector_loss_db"], 0.0, 1e6, " dB", 4)
        imported_source = QLineEdit(str(self._config.get("imported_mode_source", "") or ""))
        imported_source.setPlaceholderText("导入复场文件路径（需要时填写）")
        imported_row = QWidget(dialog)
        imported_layout = QHBoxLayout(imported_row)
        imported_layout.setContentsMargins(0, 0, 0, 0)
        imported_layout.addWidget(imported_source, 1)
        choose_file = QPushButton("选择…", imported_row)

        def choose_imported_file() -> None:
            path, _filter = QFileDialog.getOpenFileName(
                dialog,
                "选择导入复场文件",
                str(imported_source.text() or ""),
                "复场数据 (*.npy *.npz *.mat *.csv);;所有文件 (*.*)",
            )
            if path:
                imported_source.setText(path)

        choose_file.clicked.connect(choose_imported_file)
        imported_layout.addWidget(choose_file)
        form.addRow("复场文件", imported_row)
        if not self._finish_dialog(dialog, form):
            return
        self._config.update({
            "receiver_type": receiver_type.currentText(), "mode_model": mode_model.currentText(),
            "receiver_axis_split": axis.isChecked(),
            "receiver_mfd_x_um": mfd_x.value(), "receiver_mfd_y_um": mfd_y.value(),
            "receiver_na_x": na_x.value(), "receiver_na_y": na_y.value(),
            "receiver_core_diameter_um": core.value(), "receiver_n_core": n_core.value(),
            "receiver_n_clad": n_clad.value(), "receiver_outside_index": outside.value(),
            "receiver_offset_x_um": offset_x.value(), "receiver_offset_y_um": offset_y.value(),
            "receiver_offset_z_um": offset_z.value(), "receiver_tilt_x_urad": tilt_x.value(),
            "receiver_tilt_y_urad": tilt_y.value(), "receiver_endface_transmission": transmission.value(),
            "receiver_length_m": length.value(), "receiver_attenuation_db_per_km": attenuation.value(),
            "receiver_connector_loss_db": connector.value(), "imported_mode_source": imported_source.text().strip(),
        })
        self._persist_form_config()
        self._project.apply_parameter_changes(
            {"receiver.mode_field_diameter_x_um": mfd_x.value()},
            reason="镜头组接收与装调参数已修改",
        )

    def _edit_system_group(self) -> None:
        dialog = QDialog()
        dialog.setWindowTitle("镜头组 · 系统环境")
        form = QFormLayout(dialog)
        object_distance = self._add_float(form, "物距", self._config["object_distance_mm"], 0.1, 1e9, " mm", 6)
        image_distance = self._add_float(form, "像面位置", self._config["image_distance_mm"], -10000.0, 10000.0, " mm", 6)
        temperature = self._add_float(form, "环境温度", self._config["environment_temperature_c"], -273.0, 1000.0, " ℃", 3)
        pressure = self._add_float(form, "环境压力", self._config["environment_pressure_kpa"], 0.0, 10000.0, " kPa", 3)
        thermal = QCheckBox("启用温度补偿")
        thermal.setChecked(bool(self._config.get("thermal_compensation", False)))
        form.addRow("材料补偿", thermal)
        auto_focus = QCheckBox("最佳焦面搜索")
        auto_focus.setChecked(bool(self._config.get("auto_best_focus", False)))
        form.addRow("自动焦面", auto_focus)
        if not self._finish_dialog(dialog, form):
            return
        self._config.update({
            "object_distance_mm": object_distance.value(), "image_distance_mm": image_distance.value(),
            "environment_temperature_c": temperature.value(), "environment_pressure_kpa": pressure.value(),
            "thermal_compensation": thermal.isChecked(), "auto_best_focus": auto_focus.isChecked(),
        })
        self._persist_form_config()
        self.set_stale(True, "系统环境参数已修改")
        self._layout_settings_capsules()
        self.update()

    def _edit_constraints_group(self) -> None:
        dialog = QDialog()
        dialog.setWindowTitle("镜头组 · 求解与约束")
        form = QFormLayout(dialog)
        objective = self._add_combo(form, "目标函数", OPTIMIZATION_OBJECTIVE_CHOICES, self._config["optimization_objective"])
        algorithm = self._add_combo(form, "优化算法", OPTIMIZATION_ALGORITHM_CHOICES, self._config["optimization_algorithm"])
        iterations = QSpinBox(); iterations.setRange(10, 5000); iterations.setValue(int(self._config.get("max_iterations", 300))); form.addRow("最大迭代", iterations)
        collimation = QCheckBox("启用准直硬约束"); collimation.setChecked(bool(self._config.get("collimation_enabled", False))); form.addRow(collimation)
        collimation_surface = QComboBox()
        collimation_surface.addItem("自动识别准直输出面", "")
        for index, surface in enumerate(self._project.project.surfaces):
            collimation_surface.addItem(f"S{index + 1} · {surface.name}", index)
        saved_surface = self._config.get("collimation_surface", "")
        selected_surface = collimation_surface.findData(int(saved_surface)) if str(saved_surface).isdigit() else collimation_surface.findData("")
        collimation_surface.setCurrentIndex(selected_surface if selected_surface >= 0 else 0)
        form.addRow("准直评价面", collimation_surface)
        collimation_span = self._add_float(form, "准直评价段", self._config.get("collimation_span", 10.0), 0.1, 1000.0, " mm", 3)
        collimation_radius = self._add_float(form, "最大半径变化", self._config.get("collimation_radius_change", 2.0), 0.01, 100.0, " %", 3)
        collimation_curvature = self._add_float(form, "最大归一化曲率", self._config.get("collimation_curvature", 0.05), 0.00001, 10.0, "", 5)
        collimation_centroid = self._add_float(form, "最大质心漂移", self._config.get("collimation_centroid_drift", 1.0), 0.001, 100.0, " %", 3)
        collimation_tilt = self._add_float(form, "最大光轴倾角", self._config.get("collimation_axis_tilt", 1.0), 0.001, 1000.0, " mrad", 3)
        alignment = QCheckBox("启用光纤对准优化"); alignment.setChecked(bool(self._config.get("alignment_enabled", False))); form.addRow("对准求解", alignment)
        include_dz = QCheckBox("包含轴向偏移 dz"); include_dz.setChecked(bool(self._config.get("alignment_include_dz", True))); form.addRow("对准自由度", include_dz)
        max_offset = self._add_float(form, "最大横向偏移", self._config.get("alignment_max_offset_um", 20.0), 0.0, 1e6, " μm", 3)
        max_axial = self._add_float(form, "最大轴向偏移", self._config.get("alignment_max_axial_offset_um", 200.0), 0.0, 1e6, " μm", 3)
        max_tilt = self._add_float(form, "最大对准倾角", self._config.get("alignment_max_tilt_urad", 5000.0), 0.0, 1e9, " μrad", 3)
        alignment_iterations = QSpinBox(); alignment_iterations.setRange(1, 5000); alignment_iterations.setValue(int(self._config.get("alignment_max_iterations", 40))); form.addRow("对准最大迭代", alignment_iterations)
        function_evaluations = QSpinBox(); function_evaluations.setRange(1, 100000); function_evaluations.setValue(int(self._config.get("alignment_max_function_evaluations", 300))); form.addRow("对准函数评估", function_evaluations)
        timeout = self._add_float(form, "对准超时", self._config.get("alignment_timeout_seconds", 60.0), 0.1, 86400.0, " s", 1)
        if not self._finish_dialog(dialog, form):
            return
        self._config.update({
            "optimization_objective": objective.currentText(), "optimization_algorithm": algorithm.currentText(),
            "max_iterations": int(iterations.value()), "collimation_enabled": collimation.isChecked(),
            "collimation_surface": collimation_surface.currentData() if collimation_surface.currentData() not in (None, "") else "",
            "collimation_span": collimation_span.value(), "collimation_radius_change": collimation_radius.value(),
            "collimation_curvature": collimation_curvature.value(), "collimation_centroid_drift": collimation_centroid.value(),
            "collimation_axis_tilt": collimation_tilt.value(),
            "alignment_enabled": alignment.isChecked(), "alignment_include_dz": include_dz.isChecked(),
            "alignment_max_offset_um": max_offset.value(), "alignment_max_axial_offset_um": max_axial.value(),
            "alignment_max_tilt_urad": max_tilt.value(), "alignment_max_iterations": int(alignment_iterations.value()),
            "alignment_max_function_evaluations": int(function_evaluations.value()), "alignment_timeout_seconds": timeout.value(),
        })
        self._persist_form_config()
        self.set_stale(True, "求解与约束参数已修改")
        self._layout_settings_capsules()
        self.update()

    def _edit_analysis_group(self) -> None:
        dialog = QDialog()
        dialog.setWindowTitle("镜头组 · 分析设置")
        form = QFormLayout(dialog)
        precision = self._add_combo(form, "主网格", CALC_PRECISION_CHOICES, self._config["calc_precision"])
        grid = self._add_combo(form, "接收面网格", OUTPUT_GRID_CHOICES, self._config["calc_grid"])
        layout_pupil = self._add_combo(form, "光路采样", LAYOUT_PUPIL_CHOICES, self._config["calc_layout_pupil"])
        pupil = self._add_combo(form, "分析光瞳", ANALYSIS_PUPIL_CHOICES, self._config["calc_pupil"])
        propagation = self._add_combo(form, "传播方法", PROPAGATION_CHOICES, self._config["calc_propagation"])
        zero_padding = self._add_float(form, "零填充", self._config["calc_zero_padding"], 1.0, 16.0, " ×", 0)
        output_extent = self._add_float(form, "计算窗口", self._config["calc_output_extent_mm"], 0.001, 1000.0, " mm", 6)
        auto_expand = QCheckBox("自动扩展输出窗口")
        auto_expand.setChecked(bool(self._config.get("calc_auto_expand_output", True)))
        form.addRow("输出范围", auto_expand)
        only_visible = QCheckBox("只计算当前结果")
        only_visible.setChecked(bool(self._config.get("calc_only_visible_results", True)))
        form.addRow("结果范围", only_visible)
        convergence = QCheckBox("检查采样收敛")
        convergence.setChecked(bool(self._config.get("calc_sampling_convergence", False)))
        form.addRow("采样检查", convergence)
        save_arrays = QCheckBox("保存完整数组")
        save_arrays.setChecked(bool(self._config.get("calc_save_large_arrays", True)))
        form.addRow("数组输出", save_arrays)
        high_precision = QCheckBox("完整复场耦合")
        high_precision.setChecked(bool(self._config.get("calc_high_precision_coupling", True)))
        form.addRow("耦合计算", high_precision)
        checks = {}
        for key, label, default in (
            ("analysis_raytrace", "光路 / 3D 光路", True), ("analysis_spot", "点列图", True),
            ("analysis_psf", "焦面光斑", True), ("analysis_coupling", "模场匹配与耦合效率", True),
            ("analysis_mtf", "MTF", False), ("analysis_power_audit", "能量检查", False),
        ):
            box = QCheckBox(label); box.setChecked(bool(self._config.get(key, default))); form.addRow(box); checks[key] = box
        if not self._finish_dialog(dialog, form):
            return
        self._config.update({
            "calc_precision": precision.currentText(), "calc_grid": grid.currentText(),
            "calc_layout_pupil": layout_pupil.currentText(), "calc_pupil": pupil.currentText(),
            "calc_propagation": propagation.currentText(),
            "calc_zero_padding": zero_padding.value(), "calc_output_extent_mm": output_extent.value(),
            "calc_auto_expand_output": auto_expand.isChecked(), "calc_only_visible_results": only_visible.isChecked(),
            "calc_sampling_convergence": convergence.isChecked(), "calc_save_large_arrays": save_arrays.isChecked(),
            "calc_high_precision_coupling": high_precision.isChecked(),
            **{key: box.isChecked() for key, box in checks.items()},
        })
        self._persist_form_config()
        self.set_stale(True, "分析设置已修改")
        self._layout_settings_capsules()
        self.update()

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    def restore_config(self, config: dict[str, Any] | None) -> None:
        if not isinstance(config, dict):
            return
        for key in self._config:
            if key in config:
                self._config[key] = config[key]
        self._persist_form_config()
        self._layout_settings_capsules()
        self.update()

    def _persist_form_config(self) -> None:
        """把胶囊状态挂回共享项目，供仿真、扫描和数据集任务共同读取。"""
        values = deepcopy(self._config)
        values["pupil_radius_mm"] = float(getattr(self._project.project, "pupil_radius_mm", 3.0) or 3.0)
        setter = getattr(self._project, "set_canvas_form_config", None)
        if callable(setter):
            setter(values, reason="镜头组节点参数已修改")
        else:
            self._project.project._canvas_form_config = values

    def editor(self):
        """已加载的纯镜头表格（未展开时为 None）。"""
        return self._host.content

    # ---- 引擎输入 -------------------------------------------------------

    def surface_rows(self) -> list[dict[str, Any]]:
        """ProjectContext 当前表面 → 引擎桥可消费的行字典。"""
        surfaces = list(self._project.project.surfaces)
        if not surfaces:
            return default_surface_rows()
        rows: list[dict[str, Any]] = []
        for surface in surfaces:
            rows.append(
                {
                    "name": str(surface.name),
                    "surface_type": str(surface.surface_type),
                    "radius_mm": float(surface.radius_mm or 0.0),
                    "thickness_mm": float(surface.thickness_mm or 0.0),
                    "material": str(surface.material or "AIR"),
                    "semi_aperture_mm": float(surface.semi_aperture_mm or 1.0),
                    "mechanical_diameter_mm": surface.mechanical_diameter_mm,
                    "conic": float(getattr(surface, "conic", 0.0) or 0.0),
                    "enabled": bool(getattr(surface, "enabled", True)),
                    "coating": str(getattr(surface, "coating", "无") or "无"),
                    "roughness_nm": float(getattr(surface, "roughness_nm", 0.0) or 0.0),
                    "note": str(getattr(surface, "note", "") or ""),
                    "group_id": str(surface.group_id or ""),
                    "type_parameters": deepcopy(getattr(surface, "type_parameters", {}) or {}),
                    "pupil_radius_mm": float(getattr(self._project.project, "pupil_radius_mm", 3.0) or 3.0),
                    "_form_config": deepcopy({**self._config, "pupil_radius_mm": float(getattr(self._project.project, "pupil_radius_mm", 3.0) or 3.0)}),
                }
            )
        return rows

    # ---- L0 即时估计 + 脏传播 ---------------------------------------------

    def _surfaces_signature(self) -> tuple:
        """表面物理参数签名（classify 依据：表面 = 系统参数 → RAY_TRACE）。"""
        return tuple(
            (
                str(s.surface_type),
                float(s.radius_mm or 0.0),
                float(s.thickness_mm or 0.0),
                str(s.material or "AIR"),
                float(s.semi_aperture_mm or 0.0),
                float(getattr(s, "conic", 0.0) or 0.0),
                tuple(sorted((str(key), str(value)) for key, value in (getattr(s, "type_parameters", {}) or {}).items())),
                str(getattr(s, "coating", "无") or "无"),
                bool(getattr(s, "enabled", True)),
            )
            for s in self._project.project.surfaces
        ) + (float(getattr(self._project.project, "pupil_radius_mm", 3.0) or 3.0),)

    def _update_l0(self) -> None:
        # L0：instant_metrics 的真实物理近似（透射率 × 模式重叠）
        try:
            estimate = estimate_efficiency(surfaces_to_project(self.surface_rows()), form_state())
            self._eta_l0 = estimate.total
        except Exception:
            self._eta_l0 = float("nan")
        self.update()

    def _on_project_changed(self, *_args) -> None:
        self._update_l0()
        signature = self._surfaces_signature()
        if signature == self._last_signature:
            return  # 非表面变更（元数据等）：不动依赖图
        self._last_signature = signature
        # classify_form_change 语义（§6.2）：表面/系统参数修改 → RAY_TRACE
        self.sourceChanged.emit("镜头组表面参数已修改", int(DirtyScope.RAY_TRACE))

    # ---- 摘要 -----------------------------------------------------------

    def summary_text(self) -> str:
        count = len(self._project.project.surfaces)
        eta = "—" if math.isnan(self._eta_l0) else f"{self._eta_l0:.3f}"
        return f"{count} 面 · L0 η≈{eta}"


__all__ = ["LensNode", "lens_table_factory"]

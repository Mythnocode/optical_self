"""仿真工程设置对话框。

本模块把仿真设置按使用场景拆成四类弹窗：软件、系统环境、孔径与视场、
采样与运行。弹窗内部编辑的是表单控件，调用方通过 ``system_state``、
``calculation_state`` 和 ``alignment_state`` 读取规范化后的状态对象。

这些设置页是弹窗而不是二级页面，因此不会在仿真二级功能栏中占据一个
独立入口。
"""

from __future__ import annotations

from frontend_pyside.modules import shared as _shared

globals().update(
    {
        name: value
        for name, value in vars(_shared).items()
        if not name.startswith("__")
    }
)


class EngineeringDialog(QDialog):
    """仿真工程设置弹窗；它们不占用仿真二级功能栏。"""

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
        """根据 kind 创建对应表单，并用传入状态作为初始值。"""
        super().__init__(parent)
        self.kind = str(kind)
        self.context = context
        # 未传入状态时，从当前工程或默认配置构造一份可编辑副本。
        self._system = system or SystemFormState(pupil_radius_mm=float(context.project.project.pupil_radius_mm))
        self._calculation = calculation or CalculationFormState()
        self._alignment = alignment or AlignmentFormState()
        # kind 是内部路由键，标题只负责用户可见文本。
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
        # 表单放在滚动容器内，保证高精度和对准选项较多时仍可操作。
        host = QWidget()
        form = QFormLayout(host)
        if self.kind == "software":
            # 软件设置目前只提供外观和后端地址字段。
            self.theme_box = QComboBox()
            self.theme_box.addItems(["跟随系统", "浅色", "深色"])
            self.backend_url = QLineEdit("http://127.0.0.1:8000")
            form.addRow("外观", self.theme_box)
            form.addRow("后端地址", self.backend_url)
        elif self.kind == "environment":
            # 环境设置影响折射率、物像位置和最佳焦面搜索。
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
            # 孔径和视场修改会直接更新当前工程的入瞳半径。
            self.pupil = _spin(0.01, 10000, 3, " mm", float(context.project.project.pupil_radius_mm))
            self.field_x = _spin(-90, 90, 3, " °", float(self._system.field_x_deg))
            self.field_y = _spin(-90, 90, 3, " °", float(self._system.field_y_deg))
            form.addRow("入瞳半径", self.pupil)
            form.addRow("视场角 X", self.field_x)
            form.addRow("视场角 Y", self.field_y)
            self.pupil.valueChanged.connect(lambda value: context.project.update_pupil_radius(float(value)))
        else:
            # compute 分支集中放置采样、传播、分析内容和对准参数。
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
            # 每个复选框的 key 与后端分析类型保持一致。
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
            # 以下选项控制复场耦合、结果范围、收敛检查和大数组保存策略。
            self.high_precision = QCheckBox("完整复场耦合")
            self.high_precision.setChecked(bool(self._calculation.high_precision_coupling_enabled))
            self.only_visible = QCheckBox("只计算当前结果")
            self.only_visible.setChecked(bool(self._calculation.only_visible_results))
            self.sampling_convergence = QCheckBox("检查采样收敛")
            self.sampling_convergence.setChecked(bool(self._calculation.sampling_convergence_enabled))
            self.save_arrays = QCheckBox("保存完整数组")
            self.save_arrays.setChecked(bool(self._calculation.save_large_arrays))
            self.incident_intensity_only = QCheckBox("端面匹配只显示入射光光强")
            self.incident_intensity_only.setToolTip("开启后，端面匹配图和导出图只保留入射光强度，不显示光纤模式、剖面线、图例和中心标记。")
            self.incident_intensity_only.setChecked(bool(self._calculation.incident_intensity_only))
            form.addRow("", self.high_precision)
            form.addRow("", self.only_visible)
            form.addRow("", self.sampling_convergence)
            form.addRow("", self.save_arrays)
            form.addRow("", self.incident_intensity_only)
            # 对准参数用于正式耦合计算的横向、轴向和倾角搜索。
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
        """发出运行请求；实际任务由外层控制器提交。"""
        self.runRequested.emit()

    def system_state(self) -> SystemFormState:
        """读取当前弹窗中的系统环境、物像位置和视场状态。"""
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
        # 软件设置没有系统字段，返回创建弹窗时保存的原始状态。
        return self._system

    def calculation_state(self) -> CalculationFormState:
        """读取计算设置，并转换为后端使用的计算状态对象。"""
        if self.kind != "compute":
            return self._calculation
        # 只收集勾选的分析项；完整复场耦合会强制包含 coupling。
        analyses = [key for key, box in self.analysis_boxes.items() if box.isChecked()]
        if self.high_precision.isChecked() and "coupling" not in analyses:
            analyses.append("coupling")
        if not analyses:
            # 至少保留光线追迹，避免提交一个没有任何分析目标的请求。
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
            incident_intensity_only=self.incident_intensity_only.isChecked(),
        )

    def alignment_state(self) -> AlignmentFormState:
        """读取光纤对准搜索的开关、范围、预算和超时设置。"""
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
    """顶部“计算设置”弹窗，只展示采样和正式运行参数。"""

    def __init__(
        self,
        context,
        parent=None,
        *,
        calculation: CalculationFormState | None = None,
        alignment: AlignmentFormState | None = None,
    ) -> None:
        """把 compute 工程设置嵌入一个更适合顶部入口的独立弹窗。"""
        super().__init__(parent)
        self.setWindowTitle("计算设置")
        self.setObjectName("CombinedSettingsDialog")
        self.setModal(True)
        self.setSizeGripEnabled(True)
        self.resize(540, 580)
        # 复用 EngineeringDialog，确保顶部设置和工程设置使用同一套状态逻辑。
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
            # 内嵌对话框不显示自己的关闭按钮，由外层统一管理。
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
    """兼容旧调用的设置别名；仿真现在以弹窗形式打开设置。"""

    def __init__(self, context, compute: bool = False, on_run: Callable[[], None] | None = None, parent=None) -> None:
        """按 compute 选择计算设置或环境设置，并可绑定运行回调。"""
        super().__init__("compute" if compute else "environment", context, parent)
        if on_run is not None:
            # 通过设置页统一转发运行回调，不改变当前设置页的生命周期。
            self.runRequested.connect(on_run)

__all__ = ["CombinedSettingsDialog","EngineeringDialog","SettingsDocument"]

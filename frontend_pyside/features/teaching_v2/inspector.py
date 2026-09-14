"""Context inspector: one selected object, compact parameters, explicit actions."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .model import (
    PITCH_DEG_MAX,
    KIND_PARAM_SPECS,
    OPTIONAL_UNSET_PARAM_NAMES,
    OpticalComponent,
    Pose,
    SceneSnapshot,
    SceneStore,
    component_kind_label,
)


POSE_FIELDS = (
    ("x_mm", "X 坐标（沿导轨）", "mm", -1000.0, 1000.0, 2, "X：沿光轴/导轨方向的位置，单位 mm"),
    ("y_mm", "Y 坐标（横向）", "mm", -1000.0, 1000.0, 2, "Y：台面左右偏移，俯视图能看见"),
    ("z_mm", "Z 坐标（离台高度）", "mm", 0.0, 1000.0, 2, "Z：光心离台面的高度，默认与梁高相同"),
    ("yaw_deg", "绕Z倾斜", "°", -360.0, 360.0, 1, "台面上左右打。俯视图能看见光线偏转。"),
    ("pitch_deg", "绕Y倾斜", "°", -PITCH_DEG_MAX, PITCH_DEG_MAX, 1, "抬头或低头。请把 3D 转到侧面看。"),
    ("roll_deg", "绕光轴旋转", "°", -360.0, 360.0, 1, "绕光束转一圈。圆透镜不会改变出射方向。"),
)

HIDDEN_PARAM_ALIASES = {"focal_mm", "active_area_mm"}


class _Section(QFrame):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("teachingV2Section")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 10, 12, 10)
        self.layout.setSpacing(7)
        heading = QLabel(title)
        heading.setObjectName("teachingV2SectionTitle")
        self.layout.addWidget(heading)


class Inspector(QWidget):
    publishRequested = Signal()
    baselineRequested = Signal()

    def __init__(self, store: SceneStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.setObjectName("teachingV2Inspector")
        # Coordinate and optical-parameter editors need enough width to keep
        # labels, units and their value fields visible without manual resize.
        self.setMinimumSize(560, 620)
        self.setMinimumWidth(560)
        self.setMaximumWidth(760)
        self.resize(620, 700)
        self._bound_id: str | None = None
        self._param_names: tuple[str, ...] = ()
        self._syncing = False
        self._pose_editors: dict[str, QDoubleSpinBox] = {}
        self._param_editors: dict[str, QWidget] = {}
        self._enabled_box: QCheckBox | None = None
        self._title: QLabel | None = None
        self._hint: QLabel | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.object_page = QWidget()
        object_layout = QVBoxLayout(self.object_page)
        object_layout.setContentsMargins(0, 0, 0, 0)
        self.object_scroll = QScrollArea()
        self.object_scroll.setWidgetResizable(True)
        self.object_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.object_body = QWidget()
        self.object_layout = QVBoxLayout(self.object_body)
        self.object_layout.setContentsMargins(12, 12, 12, 12)
        self.object_layout.setSpacing(10)
        self.object_scroll.setWidget(self.object_body)
        object_layout.addWidget(self.object_scroll)
        self.tabs.addTab(self.object_page, "当前对象")

        self.settings_page = QWidget()
        settings_layout = QVBoxLayout(self.settings_page)
        settings_layout.setContentsMargins(12, 12, 12, 12)
        settings_layout.setSpacing(10)
        settings_layout.addWidget(QLabel("位置与朝向"))
        settings_layout.addWidget(QLabel("X：沿导轨　Y：台面左右　Z：离台面（mm）"))
        settings_layout.addWidget(QLabel("绕Z倾斜看俯视；绕Y倾斜看 3D 侧面；绕光轴旋转不改圆光束方向。"))
        settings_layout.addWidget(QLabel("坐标原点是实验台，不是激光器。"))
        baseline = QPushButton("设置当前对象为基准位置")
        baseline.clicked.connect(self._set_baseline_from_selected)
        settings_layout.addWidget(baseline)
        self.baseline_check = QCheckBox("显示基准线")
        self.baseline_check.setChecked(True)
        self.baseline_check.toggled.connect(lambda value: self.store.set_baseline(bool(value)))
        settings_layout.addWidget(self.baseline_check)
        settings_layout.addStretch(1)
        self.tabs.addTab(self.settings_page, "实验设置")
        root.addWidget(self.tabs)
        self.store.sceneChanged.connect(self._on_scene)
        self.store.selectionChanged.connect(lambda _cid: self._on_selection())
        self._rebuild(self._selected_component())

    def _selected_component(self) -> OpticalComponent | None:
        snapshot = self.store.snapshot()
        selected = snapshot.selected_component_id
        if not selected:
            return None
        return next((item for item in snapshot.components if item.component_id == selected), None)

    def _visible_param_names(self, component: OpticalComponent) -> tuple[str, ...]:
        names: list[str] = []
        seen: set[str] = set()
        for name, _label, _suffix in KIND_PARAM_SPECS.get(component.kind, ()):
            if name in HIDDEN_PARAM_ALIASES:
                continue
            names.append(name)
            seen.add(name)
        for name, value in component.params.items():
            if name in seen or name in HIDDEN_PARAM_ALIASES:
                continue
            if isinstance(value, bool):
                continue
            names.append(str(name))
        return tuple(names)

    def _on_selection(self) -> None:
        self._rebuild(self._selected_component())

    def _on_scene(self, snapshot: SceneSnapshot, _reason: str) -> None:
        self.baseline_check.blockSignals(True)
        self.baseline_check.setChecked(snapshot.baseline_enabled)
        self.baseline_check.blockSignals(False)
        component = next(
            (item for item in snapshot.components if item.component_id == snapshot.selected_component_id),
            None,
        )
        if component is None or component.component_id != self._bound_id:
            self._rebuild(component)
            return
        if self._visible_param_names(component) != self._param_names:
            self._rebuild(component)
            return
        self._sync_component(component)

    def _clear(self) -> None:
        while self.object_layout.count():
            item = self.object_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._pose_editors = {}
        self._param_editors = {}
        self._enabled_box = None
        self._title = None
        self._hint = None

    def _rebuild(self, component: OpticalComponent | None) -> None:
        self._clear()
        if component is None:
            self._bound_id = None
            self._param_names = ()
            empty = QLabel("未选择对象\n\n在画布或左侧项目树选择器件，\n这里显示可编辑参数。")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setObjectName("teachingV2EmptyInspector")
            self.object_layout.addWidget(empty)
            self.object_layout.addStretch(1)
            return
        self._bound_id = component.component_id
        self._param_names = self._visible_param_names(component)
        head = _Section("当前对象")
        self._title = QLabel(f"{component.label}\n{component_kind_label(component.kind)}")
        self._title.setObjectName("teachingV2ObjectTitle")
        head.layout.addWidget(self._title)
        self._enabled_box = QCheckBox("启用")
        self._enabled_box.setToolTip("关掉后不参与光路示意和光学计算。")
        self._enabled_box.setChecked(component.enabled)
        self._enabled_box.toggled.connect(self._on_enabled)
        head.layout.addWidget(self._enabled_box)
        self._hint = QLabel()
        self._hint.setObjectName("teachingV2SetupHint")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(
            "QLabel { color: #9a3412; background: #fff7ed; border: 1px solid #fdba74;"
            " border-radius: 6px; padding: 8px; }"
        )
        head.layout.addWidget(self._hint)
        self._refresh_hint()
        self.object_layout.addWidget(head)

        pose_section = _Section("位置（X / Y / Z）与朝向")
        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        pose_values = {
            "x_mm": component.pose.x_mm,
            "y_mm": component.pose.y_mm,
            "z_mm": component.pose.z_mm,
            "yaw_deg": component.pose.yaw_deg,
            "pitch_deg": component.pose.pitch_deg,
            "roll_deg": component.pose.roll_deg,
        }
        for name, label, suffix, minimum, maximum, decimals, tip in POSE_FIELDS:
            editor = QDoubleSpinBox()
            editor.setRange(minimum, maximum)
            editor.setDecimals(decimals)
            editor.setSuffix(f" {suffix}")
            editor.setKeyboardTracking(False)
            editor.setValue(float(pose_values[name]))
            editor.setToolTip(tip)
            editor.valueChanged.connect(lambda val, field=name: self._set_pose(field, val))
            row_label = QLabel(label)
            row_label.setToolTip(tip)
            form.addRow(row_label, editor)
            self._pose_editors[name] = editor
        pose_section.layout.addLayout(form)
        self.object_layout.addWidget(pose_section)

        if self._param_names:
            parameter_section = _Section("光学参数")
            parameter_form = QFormLayout()
            parameter_form.setHorizontalSpacing(10)
            for name in self._param_names:
                spec = next((item for item in KIND_PARAM_SPECS.get(component.kind, ()) if item[0] == name), None)
                label = spec[1] if spec else name
                suffix = spec[2] if spec else ""
                value = component.params.get(name, 0.0 if spec else "")
                if name in OPTIONAL_UNSET_PARAM_NAMES:
                    line = QLineEdit()
                    line.setPlaceholderText("未设")
                    try:
                        number = float(value)
                    except (TypeError, ValueError):
                        number = 0.0
                    line.setText("" if abs(number) < 1.0e-12 else f"{number:g}")
                    line.editingFinished.connect(lambda field=name, widget=line: self._set_optional_param(field, widget.text()))
                    parameter_form.addRow(label, line)
                    self._param_editors[name] = line
                elif isinstance(value, (int, float)) or (spec is not None and suffix):
                    editor = QDoubleSpinBox()
                    editor.setRange(-1_000_000.0, 1_000_000.0)
                    editor.setDecimals(1 if "wavelength" in name else 2)
                    if suffix:
                        editor.setSuffix(f" {suffix}")
                    editor.setKeyboardTracking(False)
                    try:
                        editor.setValue(float(value or 0.0))
                    except (TypeError, ValueError):
                        editor.setValue(0.0)
                    editor.valueChanged.connect(lambda val, field=name: self._set_param(field, val))
                    parameter_form.addRow(label, editor)
                    self._param_editors[name] = editor
                else:
                    line = QLineEdit(str(value))
                    line.editingFinished.connect(lambda field=name, widget=line: self._set_param(field, widget.text()))
                    parameter_form.addRow(label, line)
                    self._param_editors[name] = line
            if component.kind == "laser":
                presets = QComboBox()
                presets.setObjectName("teachingV2PresetBox")
                presets.addItem("选择工业常用激光器规格…", None)
                for label, payload in self._laser_presets():
                    presets.addItem(label, payload)
                presets.setToolTip("一键写入波长、输出功率和近似出射束腰；仍可在下方逐项微调。")
                presets.activated.connect(lambda _index, widget=presets: self._apply_laser_preset(widget.currentData()))
                parameter_form.addRow("工业常用规格", presets)
            parameter_section.layout.addLayout(parameter_form)
            self.object_layout.addWidget(parameter_section)

        actions = _Section("下一步")
        publish = QPushButton("同步到仿真")
        publish.setObjectName("teachingV2PrimaryButton")
        publish.setToolTip("将教学台支持的波长和模场参数写入当前仿真，并保存教学快照")
        publish.clicked.connect(self.publishRequested)
        actions.layout.addWidget(publish)
        actions.layout.addWidget(QLabel("点击后才会写入当前仿真；器材类型和自由摆放位置不会自动转换。"))
        self.object_layout.addWidget(actions)
        self.object_layout.addStretch(1)

    @staticmethod
    def _laser_presets() -> tuple[tuple[str, dict[str, float]], ...]:
        return (
            ("780 nm 外腔二极管 · 50 mW · 0.70 mm", {"wavelength_nm": 780.0, "power_mw": 50.0, "beam_radius_mm": 0.70}),
            ("850 nm VCSEL · 10 mW · 0.35 mm", {"wavelength_nm": 850.0, "power_mw": 10.0, "beam_radius_mm": 0.35}),
            ("1064 nm DPSS · 100 mW · 0.80 mm", {"wavelength_nm": 1064.0, "power_mw": 100.0, "beam_radius_mm": 0.80}),
            ("1310 nm DFB · 10 mW · 0.45 mm", {"wavelength_nm": 1310.0, "power_mw": 10.0, "beam_radius_mm": 0.45}),
            ("1550 nm DFB · 10 mW · 0.50 mm", {"wavelength_nm": 1550.0, "power_mw": 10.0, "beam_radius_mm": 0.50}),
        )

    def _apply_laser_preset(self, payload: object) -> None:
        if self._syncing or not self._bound_id or not isinstance(payload, dict):
            return
        self.store.update_params(self._bound_id, payload, reason="应用工业常用激光器规格")

    def _sync_component(self, component: OpticalComponent) -> None:
        self._syncing = True
        try:
            if self._title is not None:
                self._title.setText(f"{component.label}\n{component_kind_label(component.kind)}")
            if self._enabled_box is not None:
                self._enabled_box.blockSignals(True)
                self._enabled_box.setChecked(component.enabled)
                self._enabled_box.blockSignals(False)
            pose_values = {
                "x_mm": component.pose.x_mm,
                "y_mm": component.pose.y_mm,
                "z_mm": component.pose.z_mm,
                "yaw_deg": component.pose.yaw_deg,
                "pitch_deg": component.pose.pitch_deg,
                "roll_deg": component.pose.roll_deg,
            }
            for name, editor in self._pose_editors.items():
                editor.blockSignals(True)
                editor.setValue(float(pose_values[name]))
                editor.blockSignals(False)
            for name, editor in self._param_editors.items():
                value = component.params.get(name)
                editor.blockSignals(True)
                if name in OPTIONAL_UNSET_PARAM_NAMES and isinstance(editor, QLineEdit):
                    try:
                        number = float(value or 0.0)
                    except (TypeError, ValueError):
                        number = 0.0
                    editor.setText("" if abs(number) < 1.0e-12 else f"{number:g}")
                elif isinstance(editor, QDoubleSpinBox) and isinstance(value, (int, float)):
                    editor.setValue(float(value))
                elif isinstance(editor, QLineEdit):
                    editor.setText(str(value))
                editor.blockSignals(False)
            self._refresh_hint()
        finally:
            self._syncing = False

    def _refresh_hint(self) -> None:
        if self._hint is None:
            return
        from .physics import setup_warnings

        notes = setup_warnings(self.store.snapshot())
        if not notes:
            self._hint.hide()
            self._hint.clear()
            return
        self._hint.setText("\n".join(notes[:3]))
        self._hint.show()

    def _on_enabled(self, value: bool) -> None:
        if self._syncing or not self._bound_id:
            return
        self.store.set_enabled(self._bound_id, bool(value))

    def _set_pose(self, field: str, value: float) -> None:
        if self._syncing or not self._bound_id:
            return
        component = self._selected_component()
        if component is None:
            return
        values = {
            "x_mm": component.pose.x_mm,
            "y_mm": component.pose.y_mm,
            "z_mm": component.pose.z_mm,
            "yaw_deg": component.pose.yaw_deg,
            "pitch_deg": component.pose.pitch_deg,
            "roll_deg": component.pose.roll_deg,
        }
        values[field] = float(value)
        self.store.update_pose(self._bound_id, Pose.from_degrees(**values), reason=f"修改{component.label}的{field}")

    def _set_optional_param(self, field: str, raw: str) -> None:
        text = str(raw or "").strip()
        if text in {"", "未设", "-", "none", "None"}:
            self._set_param(field, 0.0)
            return
        self._set_param(field, text)

    def _set_param(self, field: str, value: Any) -> None:
        if self._syncing or not self._bound_id:
            return
        self.store.update_param(self._bound_id, field, value)

    def _set_baseline_from_selected(self) -> None:
        selected = self._selected_component()
        if selected is not None:
            self.store.set_baseline(True, selected.pose.x_mm)
            self.baselineRequested.emit()


__all__ = ["Inspector"]

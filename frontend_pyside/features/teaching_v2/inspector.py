"""Context inspector: one selected object, compact parameters, explicit actions.

默认只摆出位置（X/Y/Z 一行）和三个倾角，其余光学参数与基准线操作收在"更多"
里：属性窗口由画布右侧的“属性”按钮打开，不因点击器件自动出现。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
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
    ("x_mm", "X", "mm", -1000.0, 1000.0, 2, "X：沿光轴/导轨方向的位置，单位 mm"),
    ("y_mm", "Y", "mm", -1000.0, 1000.0, 2, "Y：台面左右偏移，俯视图能看见"),
    ("z_mm", "Z", "mm", 0.0, 1000.0, 2, "Z：光心离台面的高度，默认与梁高相同"),
    ("yaw_deg", "绕Z", "°", -360.0, 360.0, 1, "台面上左右打。俯视图能看见光线偏转。"),
    ("pitch_deg", "绕Y", "°", -PITCH_DEG_MAX, PITCH_DEG_MAX, 1, "抬头或低头。请把 3D 转到侧面看。"),
    ("roll_deg", "绕光轴", "°", -360.0, 360.0, 1, "绕光束转一圈。圆透镜不会改变出射方向。"),
)

# 默认只显示的三组坐标（X/Y/Z）和三个倾角，顺序即界面顺序。
POSE_ROWS = (("x_mm", "y_mm", "z_mm"), ("yaw_deg", "pitch_deg", "roll_deg"))

HIDDEN_PARAM_ALIASES = {"focal_mm", "active_area_mm"}

# 输入框比表单默认值（132px）窄，但要放得下 "450.00" 这种三位整数+两位小数
# （文字 72px + 箭头和边框 28px），再窄就会把末尾数字裁掉。
FIELD_MIN_WIDTH = 84
FIELD_MAX_WIDTH = 100
# 单位标签的宽度按文字实测给足：写死宽度在不同字号/DPI 下会把 "mm" 裁掉。
UNIT_MIN_WIDTH = 34
UNIT_TEXT_PADDING = 12


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
        # 默认视图只有坐标和倾角；宽度随后由 _fit_to_content 按三列坐标的实际
        # 需要补足，避免右侧那一列被裁掉。
        self.setMinimumSize(440, 300)
        self.setMaximumWidth(760)
        self.resize(560, 400)
        self._bound_id: str | None = None
        self._param_names: tuple[str, ...] = ()
        self._syncing = False
        self._pose_editors: dict[str, QDoubleSpinBox] = {}
        self._param_editors: dict[str, QWidget] = {}
        self._enabled_box: QCheckBox | None = None
        self._title: QLabel | None = None
        self._hint: QLabel | None = None
        self._detail: QWidget | None = None
        self.baseline_check: QCheckBox | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.object_scroll = QScrollArea()
        self.object_scroll.setWidgetResizable(True)
        self.object_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.object_body = QWidget()
        self.object_layout = QVBoxLayout(self.object_body)
        self.object_layout.setContentsMargins(12, 12, 12, 12)
        self.object_layout.setSpacing(10)
        self.object_scroll.setWidget(self.object_body)
        root.addWidget(self.object_scroll)
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
        if self.baseline_check is not None:
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
        self._detail = None
        self.baseline_check = None

    @staticmethod
    def _unit_label(text: str) -> QLabel:
        raw = str(text or "")
        label = QLabel(raw)
        # 单位单独成块（与仿真页一致），不再塞进输入框内部做后缀。
        # 用教学自己的样式名：全局 UnitLabel 把高度钉死在 28px，和这里的输入框
        # 不一样高；高度在 _match_field_heights 里按输入框的期望高度对齐。
        label.setObjectName("teachingV2UnitLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_width = label.fontMetrics().horizontalAdvance(raw)
        label.setFixedWidth(max(UNIT_MIN_WIDTH, text_width + UNIT_TEXT_PADDING))
        # 固定尺寸：否则网格里的行会被拉伸，单位块跟着变成一整条。
        label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return label

    def _pose_field(self, name: str, label: str, suffix: str, minimum: float, maximum: float,
                    decimals: int, tip: str, value: float) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        caption = QLabel(label)
        caption.setToolTip(tip)
        caption.setMinimumWidth(26)
        editor = QDoubleSpinBox()
        editor.setRange(minimum, maximum)
        editor.setDecimals(decimals)
        editor.setKeyboardTracking(False)
        editor.setMinimumWidth(FIELD_MIN_WIDTH)
        editor.setMaximumWidth(FIELD_MAX_WIDTH)
        editor.setValue(float(value))
        editor.setToolTip(tip)
        editor.valueChanged.connect(lambda val, field=name: self._set_pose(field, val))
        row.addWidget(caption)
        row.addWidget(editor)
        if suffix:
            row.addWidget(self._unit_label(suffix))
        row.addStretch(1)
        self._pose_editors[name] = editor
        return host

    def _rebuild(self, component: OpticalComponent | None) -> None:
        self._clear()
        if component is None:
            self._bound_id = None
            self._param_names = ()
            empty = QLabel("未选择对象\n\n先点击画布中的器件，再点右侧“属性”按钮，\n这里显示它的坐标和参数。")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setObjectName("teachingV2EmptyInspector")
            self.object_layout.addWidget(empty)
            self.object_layout.addStretch(1)
            QTimer.singleShot(0, self._fit_to_content)
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

        pose_values = {
            "x_mm": component.pose.x_mm,
            "y_mm": component.pose.y_mm,
            "z_mm": component.pose.z_mm,
            "yaw_deg": component.pose.yaw_deg,
            "pitch_deg": component.pose.pitch_deg,
            "roll_deg": component.pose.roll_deg,
        }
        pose_section = _Section("位置与朝向")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        for row_index, names in enumerate(POSE_ROWS):
            for column, name in enumerate(names):
                spec = next(item for item in POSE_FIELDS if item[0] == name)
                _name, label, suffix, minimum, maximum, decimals, tip = spec
                grid.addWidget(
                    self._pose_field(
                        name, label, suffix, minimum, maximum, decimals, tip, pose_values[name]
                    ),
                    row_index,
                    column,
                )
            grid.setColumnStretch(len(names), 1)
        pose_section.layout.addLayout(grid)
        self.object_layout.addWidget(pose_section)

        self.detail_button = QToolButton()
        self.detail_button.setObjectName("teachingV2MoreButton")
        self.detail_button.setText("更多参数")
        self.detail_button.setCheckable(True)
        self.detail_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.detail_button.setArrowType(Qt.ArrowType.RightArrow)
        self.detail_button.toggled.connect(self._on_detail_toggled)
        self.object_layout.addWidget(self.detail_button)

        self._detail = QWidget()
        detail_layout = QVBoxLayout(self._detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(10)
        if self._param_names:
            detail_layout.addWidget(self._build_parameters(component))
        detail_layout.addWidget(self._build_baseline())
        self._detail.setVisible(False)
        self.object_layout.addWidget(self._detail)

        actions = _Section("下一步")
        publish = QPushButton("同步到仿真")
        publish.setObjectName("teachingV2PrimaryButton")
        publish.setToolTip("将教学台支持的波长和模场参数写入当前仿真，并保存教学快照")
        publish.clicked.connect(self.publishRequested)
        actions.layout.addWidget(publish)
        self.object_layout.addWidget(actions)
        self.object_layout.addStretch(1)
        # 布局跑完才知道输入框的期望高度，那时再对齐单位块并定窗口尺寸。
        QTimer.singleShot(0, self._after_layout_build)

    def _build_parameters(self, component: OpticalComponent) -> QWidget:
        parameter_section = _Section("光学参数")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        for row, name in enumerate(self._param_names):
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
                line.editingFinished.connect(
                    lambda field=name, widget=line: self._set_optional_param(field, widget.text())
                )
                editor: QWidget = line
            elif isinstance(value, (int, float)) or (spec is not None and suffix):
                spin = QDoubleSpinBox()
                spin.setRange(-1_000_000.0, 1_000_000.0)
                spin.setDecimals(1 if "wavelength" in name else 2)
                spin.setKeyboardTracking(False)
                try:
                    spin.setValue(float(value or 0.0))
                except (TypeError, ValueError):
                    spin.setValue(0.0)
                spin.valueChanged.connect(lambda val, field=name: self._set_param(field, val))
                editor = spin
            else:
                line = QLineEdit(str(value))
                line.editingFinished.connect(lambda field=name, widget=line: self._set_param(field, widget.text()))
                editor = line
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(editor, row, 1)
            grid.addWidget(self._unit_label(suffix) if suffix else QLabel(""), row, 2)
            grid.setColumnStretch(3, 1)
            self._param_editors[name] = editor
        parameter_section.layout.addLayout(grid)
        if component.kind == "laser":
            presets = QComboBox()
            presets.setObjectName("teachingV2PresetBox")
            presets.addItem("选择工业常用激光器规格…", None)
            for label, payload in self._laser_presets():
                presets.addItem(label, payload)
            presets.setToolTip("一键写入波长、输出功率和近似出射束腰；仍可在下方逐项微调。")
            presets.activated.connect(lambda _index, widget=presets: self._apply_laser_preset(widget.currentData()))
            parameter_section.layout.addWidget(presets)
        return parameter_section

    def _build_baseline(self) -> QWidget:
        section = _Section("基准线")
        baseline = QPushButton("设置当前对象为基准位置")
        baseline.clicked.connect(self._set_baseline_from_selected)
        section.layout.addWidget(baseline)
        self.baseline_check = QCheckBox("显示基准线")
        self.baseline_check.setChecked(self.store.snapshot().baseline_enabled)
        self.baseline_check.toggled.connect(lambda value: self.store.set_baseline(bool(value)))
        section.layout.addWidget(self.baseline_check)
        return section

    def _after_layout_build(self) -> None:
        """第一遍布局结束后：单位块对齐输入框高度，窗口尺寸贴合内容。"""
        self._match_field_heights()
        self._fit_to_content()

    def _match_field_heights(self) -> None:
        """把单位块的高度对齐到同排输入框。

        高度取输入框的期望高度，不能取布局跑完的实测高度：布局可能已经把行
        拉伸过，那一读就把单位块钉成了整条。
        """
        editors = list(self._pose_editors.values()) + [
            editor for editor in self._param_editors.values() if isinstance(editor, QDoubleSpinBox)
        ]
        for editor in editors:
            holder = editor.parentWidget()
            if holder is None:
                continue
            height = max(editor.sizeHint().height(), editor.minimumSizeHint().height())
            for label in holder.findChildren(QLabel):
                if label.objectName() == "teachingV2UnitLabel":
                    label.setFixedHeight(height)

    def _fit_to_content(self) -> None:
        """窗口按内容给足尺寸：宽度不够会裁掉右边那列坐标，高度不够就多一条滚动条。

        宽度取"期望宽度"而不是最小宽度，否则输入框会被压到最小值、数字挤在一起；
        最小宽度只保留下限，用户想收窄还能收窄。
        """
        frame = 2 * self.object_scroll.frameWidth() + 4
        preferred = self.object_body.sizeHint().width()
        smallest = self.object_body.minimumSizeHint().width()
        height = max(320, min(self.object_body.sizeHint().height() + frame, 720))
        self.setMinimumWidth(max(400, min(smallest + frame, 760)))
        self.resize(max(440, min(preferred + frame, 760)), height)

    def _on_detail_toggled(self, expanded: bool) -> None:
        if self._detail is not None:
            self._detail.setVisible(bool(expanded))
        self.detail_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.detail_button.setText("收起参数" if expanded else "更多参数")

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

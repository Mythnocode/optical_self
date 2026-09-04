from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QSplitter,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import (
    Card,
    InfoRow,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.tables import DataTable
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace


class TeachingExperimentMixin:
    def _scan_panel(self):
        widget = QWidget()
        root = QHBoxLayout(widget)
        root.setContentsMargins(8, 8, 8, 8)
        form_card = Card("控制变量设置", compact=True)
        form_card.setMinimumWidth(330)
        form_card.setMaximumWidth(400)
        form = QFormLayout()
        self.scan_parameter = QComboBox()
        self.scan_metric = QComboBox()
        self.scan_start = QDoubleSpinBox()
        self.scan_start.setRange(-10000, 10000)
        self.scan_stop = QDoubleSpinBox()
        self.scan_stop.setRange(-10000, 10000)
        self.scan_points = QSpinBox()
        self.scan_points.setRange(5, 201)
        self.scan_points.setValue(41)
        form.addRow("扫描参数", self.scan_parameter)
        form.addRow("输出指标", self.scan_metric)
        form.addRow("起点", self.scan_start)
        form.addRow("终点", self.scan_stop)
        form.addRow("点数", self.scan_points)
        button = PrimaryButton("开始规律探索")
        button.clicked.connect(self._run_scan)
        form.addRow(button)
        form_card.body.addLayout(form)
        root.addWidget(form_card)
        self.scan_result = ResultWorkspace()
        root.addWidget(self.scan_result, 1)
        self.scan_parameter.currentTextChanged.connect(self._sync_scan_range)
        self._populate_scan_controls()
        return widget

    def _populate_scan_controls(self) -> None:
        if not hasattr(self, "scan_parameter") or not self.current_module:
            return
        spec = self.catalog.get("modules", {}).get(self.current_module, {})
        self.scan_parameter.blockSignals(True)
        self.scan_metric.blockSignals(True)
        try:
            self.scan_parameter.clear()
            self.scan_parameter.addItems(list(spec.get("parameters", {})))
            self.scan_metric.clear()
            self.scan_metric.addItems(list(spec.get("scan_metrics", [])))
        finally:
            self.scan_parameter.blockSignals(False)
            self.scan_metric.blockSignals(False)
        if self.scan_parameter.count():
            self._sync_scan_range(self.scan_parameter.currentText())

    def _sync_scan_range(self, name):
        spec = self.catalog["modules"].get(self.current_module, {}).get("parameters", {}).get(name)
        if spec:
            self.scan_start.setValue(spec["minimum"])
            self.scan_stop.setValue(spec["maximum"])

    def _run_scan(self):
        output = self.workflow.scan(
            self.current_module,
            self.current_inputs,
            self.scan_parameter.currentText(),
            self.scan_metric.currentText(),
            self.scan_start.value(),
            self.scan_stop.value(),
            self.scan_points.value(),
        )
        x_values = list(output.get("x", []) or [])
        y_values = list(output.get("y", []) or [])
        maximum = dict(output.get("maximum", {}) or {})
        self.scan_result.set_layout_mode("左右双图")
        self.scan_result.set_result(
            0,
            "参数响应",
            {
                "kind": "parameter_response",
                "x": x_values,
                "y": y_values,
                "best_point": [maximum.get("x"), maximum.get("y")],
                "title": self.scan_metric.currentText(),
                "x_label": self.scan_parameter.currentText(),
                "y_label": self.scan_metric.currentText(),
                "source": "教学近似",
            },
        )
        linked = []
        for name, values in dict(output.get("series", {}) or {}).items():
            if name == output.get("metric"):
                continue
            linked.append({"label": name, "y": list(values)})
        self.scan_result.set_result(
            1,
            "物理联动",
            {
                "kind": "teaching_scan",
                "x": x_values,
                "primary": y_values,
                "primary_label": self.scan_metric.currentText(),
                "linked_series": linked[:4],
                "best_point": [maximum.get("x"), maximum.get("y")],
                "x_label": self.scan_parameter.currentText(),
                "y_label": self.scan_metric.currentText(),
                "source": "教学近似",
            },
        )

    def _trajectory_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        self.trajectory_workspace = ResultWorkspace()
        self.trajectory_workspace.set_single_view_only(True)
        self.trajectory_workspace.set_toolbar_visible(False)
        layout.addWidget(self.trajectory_workspace, 1)
        refresh = SecondaryButton("刷新轨迹")
        refresh.clicked.connect(self._refresh_trajectory_plot)
        layout.addWidget(refresh)
        self._refresh_trajectory_plot()
        return widget

    def _refresh_trajectory_plot(self):
        if not hasattr(self, "trajectory_workspace"):
            return
        from frontend_pyside.shared.plotting.engineering_views import build_adjustment_trajectory
        records = self.workflow.session(self.current_module).get("records", [])
        self.trajectory_workspace.set_result(0, "调节轨迹", build_adjustment_trajectory(records))

    def _compare_panel(self):
        widget = QWidget()
        root = QVBoxLayout(widget)
        buttons = QHBoxLayout()
        save_a = SecondaryButton("保存快照 A")
        save_b = SecondaryButton("保存快照 B")
        compare = PrimaryButton("比较 A / B")
        buttons.addWidget(save_a)
        buttons.addWidget(save_b)
        buttons.addWidget(compare)
        buttons.addStretch()
        buttons.addWidget(QLabel("建议只改变一个关键变量，便于解释差异。"))
        root.addLayout(buttons)
        self.compare_table = DataTable(0, 4)
        self.compare_table.setHorizontalHeaderLabels(["指标", "快照 A", "快照 B", "差值 / 结论"])
        root.addWidget(self.compare_table)
        self.scheme_a = None
        self.scheme_b = None
        save_a.clicked.connect(lambda: self._save_scheme("a"))
        save_b.clicked.connect(lambda: self._save_scheme("b"))
        compare.clicked.connect(self._compare_schemes)
        return widget

    def _save_scheme(self, which):
        value = {"inputs": dict(self.current_inputs), "metrics": dict(self.current_result.get("metrics", {}))}
        if which == "a":
            self.scheme_a = value
        else:
            self.scheme_b = value

    def _compare_schemes(self):
        if not self.scheme_a or not self.scheme_b:
            return
        keys = sorted(set(self.scheme_a["metrics"]) | set(self.scheme_b["metrics"]))
        self.compare_table.setRowCount(len(keys))
        for row, key in enumerate(keys):
            a = self.scheme_a["metrics"].get(key, "")
            b = self.scheme_b["metrics"].get(key, "")
            try:
                difference = f"{float(b) - float(a):+.4g}"
            except (TypeError, ValueError):
                difference = "—"
            for column, value in enumerate([key, a, b, difference]):
                self.compare_table.setItem(row, column, QTableWidgetItem(str(value)))

    def _mismatch_panel(self):

        widget = QWidget()
        root = QHBoxLayout(widget)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)

        controls = Card("失配参数", compact=True)
        controls.setMinimumWidth(280)
        controls.setMaximumWidth(360)
        form = QFormLayout()
        form.setVerticalSpacing(5)
        self.mismatch_dx = QDoubleSpinBox()
        self.mismatch_dy = QDoubleSpinBox()
        self.mismatch_dz = QDoubleSpinBox()
        self.mismatch_tx = QDoubleSpinBox()
        self.mismatch_ty = QDoubleSpinBox()
        self.mismatch_wx = QDoubleSpinBox()
        self.mismatch_wy = QDoubleSpinBox()
        self.mismatch_mfd = QDoubleSpinBox()
        self.mismatch_lambda = QDoubleSpinBox()
        for spin, minimum, maximum, value, suffix in (
            (self.mismatch_dx, -50, 50, 0.0, "μm"),
            (self.mismatch_dy, -50, 50, 0.0, "μm"),
            (self.mismatch_dz, -1000, 1000, 0.0, "μm"),
            (self.mismatch_tx, -100, 100, 0.0, "mrad"),
            (self.mismatch_ty, -100, 100, 0.0, "mrad"),
            (self.mismatch_wx, 0.2, 100, 5.2, "μm"),
            (self.mismatch_wy, 0.2, 100, 5.2, "μm"),
            (self.mismatch_mfd, 0.4, 200, 10.4, "μm"),
            (self.mismatch_lambda, 100, 30000, 1550.0, "nm"),
        ):
            spin.setRange(minimum, maximum)
            spin.setDecimals(4)
            spin.setValue(value)
            spin.setSuffix(" " + suffix)
            spin.valueChanged.connect(self._refresh_mismatch_panel)
        for label, spin in (
            ("横向偏移 X", self.mismatch_dx),
            ("横向偏移 Y", self.mismatch_dy),
            ("轴向离焦", self.mismatch_dz),
            ("倾角 X", self.mismatch_tx),
            ("倾角 Y", self.mismatch_ty),
            ("输入束腰 X", self.mismatch_wx),
            ("输入束腰 Y", self.mismatch_wy),
            ("目标 MFD", self.mismatch_mfd),
            ("波长", self.mismatch_lambda),
        ):
            form.addRow(label, spin)
        controls.body.addLayout(form)
        reset = SecondaryButton("恢复匹配状态")
        reset.clicked.connect(self._reset_mismatch_controls)
        controls.body.addWidget(reset)
        controls.body.addWidget(
            InfoRow(
                "计算方式",
                "解析 Gaussian 复场，用于教学趋势与相位诊断",
                "教学近似",
                "warning",
            )
        )
        splitter.addWidget(controls)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(6)
        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("视图"))
        self.mismatch_view_selector = QComboBox()
        self.mismatch_view_selector.addItems(
            ["2D 光强", "相位差", "复场贡献", "中心截面", "3D 光强"]
        )
        self.mismatch_view_selector.currentIndexChanged.connect(self._mismatch_view_changed)
        view_row.addWidget(self.mismatch_view_selector)
        view_row.addStretch(1)
        center_layout.addLayout(view_row)
        self.mismatch_workspace = ResultWorkspace()
        self.mismatch_workspace.set_single_view_only(True)
        self.mismatch_workspace.set_toolbar_visible(False)
        self.mismatch_workspace.set_maximize_controls_visible(False)
        center_layout.addWidget(self.mismatch_workspace, 1)
        splitter.addWidget(center)

        diagnosis = Card("诊断摘要", compact=True)
        diagnosis.setMinimumWidth(280)
        diagnosis.setMaximumWidth(370)
        self.mismatch_efficiency = InfoRow("耦合效率", "—")
        self.mismatch_main_factor = InfoRow("主要失配", "—")
        self.mismatch_phase_quality = InfoRow("相位一致性", "—")
        diagnosis.body.addWidget(self.mismatch_efficiency)
        diagnosis.body.addWidget(self.mismatch_main_factor)
        diagnosis.body.addWidget(self.mismatch_phase_quality)
        self.mismatch_metric_text = QLabel()
        self.mismatch_metric_text.setWordWrap(True)
        self.mismatch_metric_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        diagnosis.body.addWidget(self.mismatch_metric_text)
        self.mismatch_advice = QLabel()
        self.mismatch_advice.setObjectName("helperText")
        self.mismatch_advice.setWordWrap(True)
        diagnosis.body.addWidget(self.mismatch_advice)
        splitter.addWidget(diagnosis)

        splitter.setSizes([320, 900, 330])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        root.addWidget(splitter)
        self._refresh_mismatch_panel()
        return widget

    def _reset_mismatch_controls(self) -> None:
        values = (
            (self.mismatch_dx, 0.0),
            (self.mismatch_dy, 0.0),
            (self.mismatch_dz, 0.0),
            (self.mismatch_tx, 0.0),
            (self.mismatch_ty, 0.0),
            (self.mismatch_wx, 5.2),
            (self.mismatch_wy, 5.2),
            (self.mismatch_mfd, 10.4),
            (self.mismatch_lambda, 1550.0),
        )
        for widget, value in values:
            blocked = widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(blocked)
        self._refresh_mismatch_panel()

    def _mismatch_arrays(self) -> dict:
        import numpy as np

        dx = float(self.mismatch_dx.value())
        dy = float(self.mismatch_dy.value())
        dz = float(self.mismatch_dz.value())
        tx = float(self.mismatch_tx.value()) * 1e-3
        ty = float(self.mismatch_ty.value()) * 1e-3
        wx = max(float(self.mismatch_wx.value()), 1e-6)
        wy = max(float(self.mismatch_wy.value()), 1e-6)
        wf = max(float(self.mismatch_mfd.value()) / 2.0, 1e-6)
        wavelength_um = max(float(self.mismatch_lambda.value()) * 1e-3, 1e-9)
        extent = max(wx, wy, wf) * 3.2 + max(abs(dx), abs(dy))
        axis = np.linspace(-extent, extent, 161)
        x, y = np.meshgrid(axis, axis)
        input_amp = np.exp(-(((x - dx) / wx) ** 2 + ((y - dy) / wy) ** 2))
        target_amp = np.exp(-((x / wf) ** 2 + (y / wf) ** 2))
        k = 2.0 * np.pi / wavelength_um
        rayleigh = np.pi * (0.5 * (wx + wy)) ** 2 / wavelength_um
        if abs(dz) < 1e-12:
            curvature = 0.0
        else:
            curvature = dz * (1.0 + (rayleigh / dz) ** 2)
        phase = k * (tx * x + ty * y)
        if curvature:
            phase = phase + k * (x * x + y * y) / (2.0 * curvature)
        input_field = input_amp * np.exp(1j * phase)
        target_field = target_amp.astype(complex)
        norm_i = float(np.sum(np.abs(input_field) ** 2))
        norm_t = float(np.sum(np.abs(target_field) ** 2))
        overlap_complex = np.sum(input_field * np.conj(target_field))
        eta = float(abs(overlap_complex) ** 2 / max(norm_i * norm_t, 1e-30))
        input_i = np.abs(input_field) ** 2
        target_i = np.abs(target_field) ** 2
        contribution = np.real(input_field * np.conj(target_field))
        phase_difference = np.angle(input_field * np.conj(target_field))
        center = len(axis) // 2
        return {
            "axis": axis,
            "input_i": input_i / max(float(input_i.max()), 1e-30),
            "target_i": target_i / max(float(target_i.max()), 1e-30),
            "difference": input_i / max(float(input_i.max()), 1e-30) - target_i / max(float(target_i.max()), 1e-30),
            "contribution": contribution / max(float(np.max(np.abs(contribution))), 1e-30),
            "phase": phase_difference,
            "eta": eta,
            "center": center,
            "curvature": curvature,
        }

    def _mismatch_views(self) -> list[dict]:
        arrays = self._mismatch_arrays()
        axis = arrays["axis"].tolist()
        center = arrays["center"]
        return [
            {
                "kind": "heatmap_pair",
                "x": axis,
                "y": axis,
                "z1": arrays["input_i"].tolist(),
                "z2": arrays["target_i"].tolist(),
                "title1": "输入场光强",
                "title2": "光纤目标模式",
                "title": "归一化光强对比",
                "x_label": "x (μm)",
                "y_label": "y (μm)",
                "source": "教学 Gaussian 复场",
            },
            {
                "kind": "heatmap",
                "x": axis,
                "y": axis,
                "z": arrays["phase"].tolist(),
                "title": "输入场与目标模式相位差",
                "x_label": "x (μm)",
                "y_label": "y (μm)",
                "source": "教学 Gaussian 复场",
            },
            {
                "kind": "heatmap",
                "x": axis,
                "y": axis,
                "z": arrays["contribution"].tolist(),
                "title": "局部复场重叠贡献 Re(Ein·Ef*)",
                "x_label": "x (μm)",
                "y_label": "y (μm)",
                "source": "教学 Gaussian 复场",
            },
            {
                "kind": "line_multi",
                "x": axis,
                "series": [
                    {"label": "输入场 X 截面", "y": arrays["input_i"][center, :].tolist()},
                    {"label": "目标模式 X 截面", "y": arrays["target_i"][center, :].tolist()},
                    {"label": "输入场 Y 截面", "y": arrays["input_i"][:, center].tolist()},
                    {"label": "目标模式 Y 截面", "y": arrays["target_i"][:, center].tolist()},
                ],
                "title": "X/Y 中心截面对比",
                "x_label": "位置 (μm)",
                "y_label": "归一化光强",
                "source": "教学 Gaussian 复场",
            },
            {
                "kind": "surface3d",
                "x": axis,
                "y": axis,
                "z": arrays["input_i"].tolist(),
                "title": "输入场 3D 光强",
                "x_label": "x (μm)",
                "y_label": "y (μm)",
                "z_label": "归一化光强",
                "source": "教学 Gaussian 复场",
            },
        ]

    def _mismatch_view_changed(self, index: int) -> None:
        if not hasattr(self, "mismatch_workspace"):
            return
        views = self._mismatch_views()
        index = max(0, min(int(index), len(views) - 1))
        data = dict(views[index])
        title = data.get("title") or self.mismatch_view_selector.itemText(index)
        self.mismatch_workspace.set_result(0, str(title), data)
        self.mismatch_workspace.select_result(0)

    def _refresh_mismatch_panel(self, *_args) -> None:
        if not hasattr(self, "mismatch_workspace"):
            return
        arrays = self._mismatch_arrays()
        eta = float(arrays["eta"])
        self._set_info_value(self.mismatch_efficiency, "耦合效率", f"{eta * 100.0:.3f}%")
        dx = abs(float(self.mismatch_dx.value())) + abs(float(self.mismatch_dy.value()))
        tilt = abs(float(self.mismatch_tx.value())) + abs(float(self.mismatch_ty.value()))
        dz = abs(float(self.mismatch_dz.value()))
        wf = max(float(self.mismatch_mfd.value()) / 2.0, 1e-9)
        size_error = abs(float(self.mismatch_wx.value()) / wf - 1.0) + abs(float(self.mismatch_wy.value()) / wf - 1.0)
        scores = {
            "尺寸失配": size_error,
            "横向偏移": dx / max(wf, 1e-9),
            "角度倾斜": tilt / 10.0,
            "轴向/曲率": dz / 100.0,
        }
        main = max(scores, key=scores.get)
        if max(scores.values()) < 1e-8:
            main = "匹配良好"
        self._set_info_value(self.mismatch_main_factor, "主要失配", main)
        phase_rms = float((arrays["phase"] ** 2).mean() ** 0.5)
        self._set_info_value(self.mismatch_phase_quality, "相位一致性", f"RMS {phase_rms:.3f} rad")
        self.mismatch_metric_text.setText(
            f"输入束腰：{self.mismatch_wx.value():.3f} × {self.mismatch_wy.value():.3f} μm\n"
            f"目标束腰：{wf:.3f} μm\n"
            f"横向偏移：({self.mismatch_dx.value():.3f}, {self.mismatch_dy.value():.3f}) μm\n"
            f"倾角：({self.mismatch_tx.value():.3f}, {self.mismatch_ty.value():.3f}) mrad\n"
            f"等效波前曲率：{arrays['curvature']:.5g} μm"
        )
        advice = {
            "尺寸失配": "优先调整输入束腰或光纤 MFD，使 X/Y 模场尺寸接近。",
            "横向偏移": "优先校正光纤横向位置，再判断其他失配。",
            "角度倾斜": "光强可能看似接近，应根据相位梯度校正倾角。",
            "轴向/曲率": "调整最佳焦面与波前曲率，重点查看抛物形相位差。",
            "匹配良好": "当前解析模场匹配良好，可继续研究多因素灵敏度。",
        }
        self.mismatch_advice.setText(advice[main] + "\n总效率以完整复场重叠为准，不能把单因素效率简单相乘。")
        self._mismatch_view_changed(self.mismatch_view_selector.currentIndex())

    @staticmethod
    def _set_info_value(row: InfoRow, label: str, value: str) -> None:
        layout = row.layout()
        if layout and layout.count() >= 2:
            layout.itemAt(0).widget().setText(label)
            layout.itemAt(1).widget().setText(value)

    def _diagnostic_panel(self):
        widget = QWidget()
        root = QHBoxLayout(widget)
        root.setContentsMargins(8, 8, 8, 8)
        settings = Card("采样设置", compact=True)
        settings.setMaximumWidth(390)
        form = QFormLayout()
        self.grid_points = QSpinBox()
        self.grid_points.setRange(17, 513)
        self.grid_points.setValue(65)
        self.window_factor = QDoubleSpinBox()
        self.window_factor.setRange(1.2, 8)
        self.window_factor.setValue(3)
        form.addRow("网格数", self.grid_points)
        form.addRow("窗口系数", self.window_factor)
        button = PrimaryButton("运行采样演示")
        button.clicked.connect(self._diagnose)
        form.addRow(button)
        settings.body.addLayout(form)
        settings.body.addWidget(InfoRow("教学目的", "观察欠采样、截断和能量闭合问题"))
        settings.body.addWidget(InfoRow("说明", "该诊断为简化教学模型，不等同于正式收敛测试"))
        root.addWidget(settings)
        result = Card("诊断结果与解释", compact=True)
        self.diagnostic_text = QLabel("尚未运行")
        self.diagnostic_text.setWordWrap(True)
        result.body.addWidget(self.diagnostic_text)
        root.addWidget(result, 1)
        return widget

    def _diagnose(self):
        output = self.workflow.diagnostics(
            self.current_module,
            self.current_inputs,
            self.grid_points.value(),
            self.window_factor.value(),
        )
        self.diagnostic_text.setText(
            f"采样检查：{'通过' if output['sampling_pass'] else '未通过'}\n"
            f"混叠风险：{output['aliasing_risk']}\n"
            f"每特征半径像素：{output['pixels_per_characteristic_radius']:.2f}\n"
            f"边缘功率：{output['edge_power_fraction']:.4g}\n"
            f"能量闭合误差：{output['energy_closure_error']:.4g}\n\n"
            + "\n".join(output["warnings"])
            + "\n\n"
            + output["note"]
        )

"""Optimization document tabs.

The shell owns navigation and orchestration; this module owns the optimization document surfaces.
"""

from __future__ import annotations

from frontend_pyside.modules import shared as _shared
from .goal import OptimizationGoalInspector

# Shared Qt imports and helper functions remain in the neutral tab-shared
# module during this compatibility-preserving extraction.
globals().update(
    {
        name: value
        for name, value in vars(_shared).items()
        if not name.startswith("__")
    }
)

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


__all__ = ["OptimizationDocument", "QSpinBoxCompat"]

from __future__ import annotations

from pathlib import Path
from math import sqrt
import json

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QMessageBox, QProgressBar, QScrollArea, QTableWidgetItem, QVBoxLayout, QWidget,
)

from frontend_pyside.shared.components.basic import (
    Card, CollapsiblePanel, InfoRow, InlineMetric, PrimaryButton, SecondaryButton,
)
from frontend_pyside.shared.components.tables import DataTable
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace
from frontend_pyside.shared.dialogs.plot_actions import open_workspace_plot
from frontend_pyside.shared.research_summary import latest_optimization_result
from frontend_pyside.shared.settings import SimulationNumericsProfileStore
from .experiment_validation_data import (
    ValidationRow, comparison_metrics, load_validation_rows, row_diagnostics,
    three_db_width,
)

_VALIDATION_META = {
    "E003 耦合效率": {"unit": "%", "metric": "coupling_efficiency", "scan": False},
    "E004 横向 3 dB 全宽": {"unit": "μm", "metric": "coupling_efficiency", "scan": True},
    "E006 角度 3 dB 全宽": {"unit": "mrad", "metric": "coupling_efficiency", "scan": True},
    "自定义指标": {"unit": "", "metric": "", "scan": False},
}


class ExperimentValidationMixin:
    def _build_experiment_validation_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("experimentValidationScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 12)
        root.setSpacing(10)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(7)

        data_card = Card("验证设置与数据", compact=True)
        top_row = QHBoxLayout()
        self.validation_kind = QComboBox()
        self.validation_kind.addItems(list(_VALIDATION_META))
        self.validation_reference_type = QComboBox()
        self.validation_reference_type.addItems(["实验数据", "文献理论"])
        top_row.addWidget(QLabel("指标"))
        top_row.addWidget(self.validation_kind, 1)
        top_row.addWidget(QLabel("参考"))
        top_row.addWidget(self.validation_reference_type)
        data_card.body.addLayout(top_row)

        data_actions = QHBoxLayout()
        import_button = SecondaryButton("导入数据")
        import_button.clicked.connect(self._validation_import_rows)
        add_button = SecondaryButton("手动录入")
        add_button.clicked.connect(self._validation_add_row)
        data_actions.addWidget(import_button)
        data_actions.addWidget(add_button)
        data_actions.addStretch(1)
        self.validation_show_diagnostics = QCheckBox("详细数据")
        self.validation_show_diagnostics.setChecked(False)
        self.validation_show_diagnostics.toggled.connect(self._validation_toggle_diagnostics)
        data_actions.addWidget(self.validation_show_diagnostics)
        data_card.body.addLayout(data_actions)

        self.validation_table = DataTable(0, 12)
        self.validation_table.setHorizontalHeaderLabels([
            "工况", "参考值", "参考不确定度", "平台值", "数值收敛变化", "输入参数不确定度", "单位",
            "差值", "相对误差", "合成标准不确定度", "归一化残差", "工况参数",
        ])
        self.validation_table.stretch_columns(0)
        for column in (2, 4, 5, 6, 8, 9, 10, 11):
            self.validation_table.setColumnHidden(column, True)
        self.validation_table.itemChanged.connect(self._validation_table_changed)
        self.validation_table.setMinimumHeight(250)
        self.validation_table.hide()
        self.validation_empty_hint = QLabel("导入实验/文献参考数据，或手动录入工况后开始比较。")
        self.validation_empty_hint.setObjectName("emptyHint")
        self.validation_empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.validation_empty_hint.setMinimumHeight(92)
        data_card.body.addWidget(self.validation_empty_hint, 0)
        data_card.body.addWidget(self.validation_table, 1)

        action_row = QHBoxLayout()
        self.validation_run_platform_button = PrimaryButton("计算并比较")
        self.validation_run_platform_button.clicked.connect(self._validation_run_platform)
        self.validation_tolerance_button = SecondaryButton("容差分析")
        self.validation_tolerance_button.clicked.connect(self._validation_open_tolerance_analysis)
        action_row.addWidget(self.validation_run_platform_button)
        action_row.addWidget(self.validation_tolerance_button)
        action_row.addStretch(1)
        self.validation_data_status = InfoRow("状态", "等待数据")
        action_row.addWidget(self.validation_data_status, 1)
        data_card.body.addLayout(action_row)

        edit_panel = CollapsiblePanel("数据操作与计算设置", expanded=False)
        edit_row = QHBoxLayout()
        delete_button = SecondaryButton("删除所选")
        delete_button.clicked.connect(self._validation_delete_row)
        clear_button = SecondaryButton("清空全部")
        clear_button.clicked.connect(self._validation_clear_rows)
        edit_row.addWidget(delete_button)
        edit_row.addWidget(clear_button)
        edit_row.addStretch(1)
        edit_panel.content_layout.addLayout(edit_row)

        numerics_form = QFormLayout()
        self.validation_auto_numerics = QCheckBox("自动设置采样")
        self.validation_precision = QComboBox()
        self.validation_precision.addItems(["129×129", "257×257", "513×513", "1025×1025"])
        self.validation_convergence = QCheckBox("检查采样收敛")
        self.validation_display_frame = QCheckBox("自动调整显示范围")
        self.validation_display_fraction = QDoubleSpinBox()
        self.validation_display_fraction.setRange(40.0, 85.0)
        self.validation_display_fraction.setDecimals(0)
        self.validation_display_fraction.setSuffix(" %")
        profile = SimulationNumericsProfileStore().load()
        self.validation_auto_numerics.setChecked(bool(profile.get("automatic", True)))
        self.validation_precision.setCurrentText(str(profile.get("precision", "257×257")))
        self.validation_convergence.setChecked(bool(profile.get("sampling_convergence", True)))
        self.validation_display_frame.setChecked(bool(profile.get("auto_display_frame", True)))
        self.validation_display_fraction.setValue(float(profile.get("display_fill_fraction", 0.67)) * 100.0)
        numerics_form.addRow(self.validation_auto_numerics)
        numerics_form.addRow("网格", self.validation_precision)
        numerics_form.addRow(self.validation_convergence)
        numerics_form.addRow(self.validation_display_frame)
        numerics_form.addRow("显示占比", self.validation_display_fraction)
        edit_panel.content_layout.addLayout(numerics_form)
        numerics_buttons = QHBoxLayout()
        self.validation_fill_tolerance_button = SecondaryButton("使用容差结果")
        self.validation_fill_tolerance_button.clicked.connect(self._validation_fill_input_uncertainty)
        save_profile = SecondaryButton("应用设置")
        save_profile.clicked.connect(self._validation_save_numerics_profile)
        numerics_buttons.addWidget(self.validation_fill_tolerance_button)
        numerics_buttons.addWidget(save_profile)
        numerics_buttons.addStretch(1)
        edit_panel.content_layout.addLayout(numerics_buttons)
        data_card.body.addWidget(edit_panel)
        left_layout.addWidget(data_card, 0)
        root.addWidget(left, 0)

        right = QWidget()
        self.validation_result_panel = right
        right.setVisible(False)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(7)

        # The platform comparison can take long enough that a disabled button and
        # footer task entry are not sufficient feedback.  Keep an indeterminate
        # progress strip exactly where the comparison result will appear; the
        # backend does not expose a trustworthy percentage for this request, so
        # never fabricate one.
        self.validation_progress_panel = QFrame(right)
        self.validation_progress_panel.setObjectName("taskProgressPanel")
        progress_layout = QVBoxLayout(self.validation_progress_panel)
        progress_layout.setContentsMargins(10, 7, 10, 7)
        progress_layout.setSpacing(5)
        self.validation_progress_label = QLabel("正在准备平台比较…")
        self.validation_progress_label.setObjectName("taskProgressTitle")
        progress_layout.addWidget(self.validation_progress_label)
        self.validation_progress = QProgressBar(self.validation_progress_panel)
        self.validation_progress.setObjectName("taskProgressBar")
        self.validation_progress.setTextVisible(False)
        self.validation_progress.setRange(0, 0)
        progress_layout.addWidget(self.validation_progress)
        self.validation_progress_panel.hide()
        right_layout.addWidget(self.validation_progress_panel)

        metrics_row = QHBoxLayout()
        self.validation_count = InlineMetric("有效工况", "0", "组")
        self.validation_count.hide()
        self.validation_rmse = InlineMetric("RMSE", "—")
        self.validation_rel_rmse = InlineMetric("相对 RMSE", "—", "%")
        self.validation_mae = InlineMetric("MAE", "—")
        for card in (self.validation_rmse, self.validation_mae, self.validation_rel_rmse):
            metrics_row.addWidget(card, 1)
        self.validation_popout_button = SecondaryButton("弹出图")
        self.validation_popout_button.setToolTip("在独立科研图窗中查看当前比较图。")
        self.validation_popout_button.clicked.connect(lambda: open_workspace_plot(self, self.validation_result))
        metrics_row.addWidget(self.validation_popout_button)
        right_layout.addLayout(metrics_row)

        self.validation_result = ResultWorkspace()
        self.validation_result.set_single_view_only(True)
        self.validation_result.set_toolbar_visible(False)
        self.validation_result.set_maximize_controls_visible(False)
        self.validation_result.setMinimumHeight(390)
        self.validation_result.set_result(0, "参考数据与平台", {"kind": "empty", "message": "导入参考数据后点击“计算并比较”。"})
        right_layout.addWidget(self.validation_result, 1)
        self.validation_interpretation = QLabel("")
        self.validation_interpretation.hide()
        root.addWidget(right, 0)
        root.addStretch(1)

        self.validation_kind.currentTextChanged.connect(self._validation_kind_changed)
        self._validation_kind_changed()
        self._validation_sync_empty_state()
        scroll.setWidget(page)
        return scroll

    def _validation_sync_empty_state(self) -> None:
        if not hasattr(self, "validation_table"):
            return
        has_rows = self.validation_table.rowCount() > 0
        self.validation_table.setVisible(has_rows)
        if hasattr(self, "validation_empty_hint"):
            self.validation_empty_hint.setVisible(not has_rows)
        if hasattr(self, "validation_run_platform_button"):
            self.validation_run_platform_button.setEnabled(has_rows)

    def _validation_toggle_diagnostics(self, visible: bool) -> None:
        detailed_columns = (2, 4, 5, 6, 8, 9, 10)
        for column in detailed_columns:
            self.validation_table.setColumnHidden(column, not bool(visible))

    def _validation_kind_changed(self, *_):
        meta = _VALIDATION_META.get(self.validation_kind.currentText(), {})
        if hasattr(self, "validation_current_button"):
            self.validation_current_button.setVisible(not bool(meta.get("scan")))
        if hasattr(self, "validation_scan_button"):
            self.validation_scan_button.setVisible(bool(meta.get("scan")))
        unit = meta.get("unit", "")
        if not unit:
            return
        self.validation_table.blockSignals(True)
        try:
            for row in range(self.validation_table.rowCount()):
                item = self.validation_table.item(row, 6)
                if item is None or not item.text().strip():
                    self.validation_table.setItem(row, 6, QTableWidgetItem(unit))
        finally:
            self.validation_table.blockSignals(False)

    def _validation_import_rows(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入实验/文献数据", "", "数据文件 (*.xlsx *.xlsm *.csv *.txt);;Excel (*.xlsx *.xlsm);;CSV (*.csv *.txt)")
        if not path:
            return
        unit = _VALIDATION_META.get(self.validation_kind.currentText(), {}).get("unit", "")
        try:
            rows = load_validation_rows(path, default_unit=unit)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        if not rows:
            QMessageBox.information(self, "没有数据", "文件中没有识别到有效参考值。")
            return
        # 导入文件以实验/文献参考数据为主；平台值由本页一键计算，避免把旧平台结果当作当前结果。
        for row in rows:
            row.platform = None
            row.numerical_uncertainty = None
        self._validation_set_rows(rows)
        parameter_rows = sum(1 for row in rows if row.parameter_changes)
        suffix = f" · {parameter_rows} 组含工况参数" if parameter_rows else " · 使用当前光路参数"
        self._set_info(self.validation_data_status, "状态", f"已导入 {len(rows)} 组 · {Path(path).name}{suffix}")
        self._validation_recalculate()

    def _validation_add_row(self) -> None:
        unit = _VALIDATION_META.get(self.validation_kind.currentText(), {}).get("unit", "")
        row = ValidationRow(case=f"工况{self.validation_table.rowCount() + 1}", unit=unit)
        self._validation_append_row(row)
        self.validation_table.setCurrentCell(self.validation_table.rowCount() - 1, 0)
        self.validation_table.editItem(self.validation_table.item(self.validation_table.rowCount() - 1, 0))

    def _validation_delete_row(self) -> None:
        row = self.validation_table.currentRow()
        if row >= 0:
            self.validation_table.removeRow(row)
            self._validation_recalculate()
        self._validation_sync_empty_state()

    def _validation_clear_rows(self) -> None:
        self.validation_table.setRowCount(0)
        self._validation_recalculate()
        self._validation_sync_empty_state()
        self._set_info(self.validation_data_status, "状态", "已清空")

    def _validation_set_rows(self, rows: list[ValidationRow]) -> None:
        self.validation_table.blockSignals(True)
        try:
            self.validation_table.setRowCount(0)
            for row in rows:
                self._validation_append_row(row, recalculate=False)
        finally:
            self.validation_table.blockSignals(False)

    def _validation_append_row(self, row: ValidationRow, *, recalculate: bool = True) -> None:
        index = self.validation_table.rowCount()
        self.validation_table.insertRow(index)
        values = [
            row.case,
            self._validation_number(row.reference),
            self._validation_number(row.reference_uncertainty),
            self._validation_number(row.platform),
            self._validation_number(row.numerical_uncertainty),
            self._validation_number(row.input_uncertainty),
            row.unit,
            "", "", "", "", json.dumps(row.parameter_changes or {}, ensure_ascii=False),
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if column >= 7:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.validation_table.setItem(index, column, item)
        if recalculate:
            self._validation_recalculate()
            self._validation_sync_empty_state()

    @staticmethod
    def _validation_number(value) -> str:
        return "" if value is None else f"{float(value):.8g}"

    @staticmethod
    def _validation_float(text: str) -> float | None:
        text = str(text or "").strip().replace("%", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _validation_parameter_json(text: str) -> dict[str, float]:
        try:
            data = json.loads(str(text or "{}"))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, float] = {}
        for key, value in data.items():
            try:
                result[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        return result

    def _validation_rows(self) -> list[ValidationRow]:
        rows: list[ValidationRow] = []
        for row_index in range(self.validation_table.rowCount()):
            def text(column):
                item = self.validation_table.item(row_index, column)
                return item.text() if item else ""
            rows.append(ValidationRow(
                case=text(0) or f"工况{row_index + 1}",
                reference=self._validation_float(text(1)),
                reference_uncertainty=self._validation_float(text(2)),
                platform=self._validation_float(text(3)),
                numerical_uncertainty=self._validation_float(text(4)),
                input_uncertainty=self._validation_float(text(5)),
                unit=text(6),
                parameter_changes=self._validation_parameter_json(text(11)),
            ))
        return rows

    def _validation_table_changed(self, *_):
        self._validation_recalculate()

    def _validation_recalculate(self) -> None:
        if not hasattr(self, "validation_table"):
            return
        rows = self._validation_rows()
        self._validation_sync_empty_state()
        self.validation_table.blockSignals(True)
        try:
            for row_index, row in enumerate(rows):
                diag = row_diagnostics(row)
                values = [diag.get("residual"), diag.get("relative_error"), diag.get("combined_standard_uncertainty"), diag.get("normalized_residual")]
                for offset, value in enumerate(values, start=7):
                    text = "—" if value is None else (f"{float(value):.4g}%" if offset == 8 else f"{float(value):.4g}")
                    item = self.validation_table.item(row_index, offset)
                    created = item is None
                    if item is None:
                        item = QTableWidgetItem()
                    item.setText(text)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if created:
                        self.validation_table.setItem(row_index, offset, item)
        finally:
            self.validation_table.blockSignals(False)

        metrics = comparison_metrics(rows)
        count = int(metrics.get("count", 0) or 0)
        self.validation_count.set_value(str(count), "组")
        if hasattr(self, "validation_result_panel"):
            self.validation_result_panel.setVisible(bool(count))
        if count:
            unit = next((row.unit for row in rows if row.reference is not None and row.platform is not None and row.unit), "")
            self.validation_rmse.set_value(f"{metrics['rmse']:.4g}", unit)
            self.validation_mae.set_value(f"{metrics['mae']:.4g}", unit)
            self.validation_rel_rmse.set_value(f"{metrics['relative_rmse']:.3f}", "%")
            comparable = [row for row in rows if row.reference is not None and row.platform is not None]
            platform_errors = [
                sqrt(sum(float(value) ** 2 for value in (row.numerical_uncertainty, row.input_uncertainty) if value is not None and float(value) >= 0))
                if any(value is not None and float(value) >= 0 for value in (row.numerical_uncertainty, row.input_uncertainty))
                else 0.0
                for row in comparable
            ]
            payload = {
                "kind": "bar_grouped",
                "title": f"{self.validation_kind.currentText()}：参考数据与平台结果",
                "labels": [row.case for row in comparable],
                "series": [
                    {"label": self.validation_reference_type.currentText(), "values": [row.reference for row in comparable], "errors": [row.reference_uncertainty or 0.0 for row in comparable]},
                    {"label": "平台仿真", "values": [row.platform for row in comparable], "errors": platform_errors},
                ],
                "y_label": unit,
            }
            self.validation_result.set_result(0, "数据对比", payload)
            self.validation_result.select_result(0)
            self.validation_interpretation.setText(f"当前共 {count} 组有效对比，相对 RMSE 为 {metrics['relative_rmse']:.3f}%。平台误差条暂按数值收敛变化与输入参数不确定度平方和开根号显示；参考误差条只使用表中明确填写的参考标准不确定度。")
            try:
                self.context.project.update_research_context(current_task="实验验证", current_target=self.validation_kind.currentText())
                self.context.project.publish_finding(
                    source="实验验证",
                    parameter="",
                    display_name=self.validation_kind.currentText(),
                    scope="当前系统",
                    evidence={
                        "count": count,
                        "rmse": float(metrics["rmse"]),
                        "mae": float(metrics["mae"]),
                        "relative_rmse": float(metrics["relative_rmse"]),
                        "unit": unit,
                        "reference_type": self.validation_reference_type.currentText(),
                    },
                    status="当前",
                )
            except Exception:
                pass
        else:
            self.validation_rmse.set_value("—")
            self.validation_mae.set_value("—")
            self.validation_rel_rmse.set_value("—", "%")
            self.validation_result.set_result(0, "数据对比", {"kind": "empty", "message": "导入参考数据后，点击“计算并比较”。"})

    def _validation_run_platform(self) -> None:
        rows = self._validation_rows()
        if not rows:
            QMessageBox.information(self, "没有数据", "请先导入实验/文献数据，或手动录入参考值。")
            return
        kind_text = self.validation_kind.currentText()
        kind_map = {
            "E003 耦合效率": "E003",
            "E004 横向 3 dB 全宽": "E004",
            "E006 角度 3 dB 全宽": "E006",
        }
        kind = kind_map.get(kind_text)
        if not kind:
            QMessageBox.information(self, "暂不支持自动计算", "自定义指标请先在相应分析页面得到平台结果。")
            return
        project = self._current_research_project_payload()
        if not isinstance(project, dict) or not project.get("surfaces"):
            QMessageBox.warning(self, "没有当前光路", "请先在“仿真系统”建立并保存当前光路。")
            return
        payload = {
            "kind": kind,
            "project": project,
            "cases": [
                {"case": row.case, "parameter_changes": dict(row.parameter_changes or {})}
                for row in rows
            ],
            "check_numerical_convergence": bool(self.validation_convergence.isChecked()),
            "scan_points": 121,
            "scan_half_range_um": 30.0,
            "scan_half_range_mrad": 150.0,
        }
        if hasattr(self.validation_run_platform_button, "set_task_state"):
            self.validation_run_platform_button.set_task_state("running", "比较中")
        else:
            self.validation_run_platform_button.setEnabled(False)
        self.validation_result_panel.show()
        self.validation_progress_panel.show()
        self.validation_progress.setRange(0, 0)
        self.validation_progress.setTextVisible(False)
        self.validation_progress_label.setText(f"正在计算 {len(rows)} 组平台结果 · 等待后端返回")
        self.validation_result.set_result(0, "数据对比", {"kind": "empty", "message": "平台正在计算参考工况，请稍候。"})
        self.validation_result.select_result(0)
        self._set_info(self.validation_data_status, "状态", f"正在计算 {len(rows)} 组平台结果…")
        self.api_client.post("validation.run", "/validation/run", payload)

    def _validation_platform_completed(self, body: object) -> None:
        data = body if isinstance(body, dict) else {}
        result_rows = list(data.get("rows", []) or [])
        if not result_rows:
            self._validation_platform_failed("平台没有返回有效结果")
            return
        by_case = {str(item.get("case", "")): item for item in result_rows if isinstance(item, dict)}
        warnings: list[str] = []
        self.validation_table.blockSignals(True)
        try:
            for row_index in range(self.validation_table.rowCount()):
                case_item = self.validation_table.item(row_index, 0)
                case = case_item.text() if case_item else f"工况{row_index + 1}"
                result = by_case.get(case)
                if not result:
                    continue
                platform = result.get("platform")
                numerical = result.get("numerical_uncertainty")
                unit = str(result.get("unit", "") or "")
                self.validation_table.setItem(row_index, 3, QTableWidgetItem("" if platform is None else f"{float(platform):.8g}"))
                self.validation_table.setItem(row_index, 4, QTableWidgetItem("" if numerical is None else f"{abs(float(numerical)):.8g}"))
                if unit:
                    self.validation_table.setItem(row_index, 6, QTableWidgetItem(unit))
                for warning in list(result.get("warnings", []) or []):
                    if warning:
                        warnings.append(f"{case}：{warning}")
        finally:
            self.validation_table.blockSignals(False)
        if hasattr(self.validation_run_platform_button, "set_task_state"):
            self.validation_run_platform_button.set_task_state("success", "比较完成")
            QTimer.singleShot(1400, lambda: self.validation_run_platform_button.reset_task_state("计算并比较"))
        else:
            self.validation_run_platform_button.setEnabled(True)
        self.validation_progress.setRange(0, 100)
        self.validation_progress.setValue(100)
        self.validation_progress.setTextVisible(True)
        self.validation_progress_label.setText("平台比较完成 · 结果已更新")
        self.validation_progress_panel.show()
        self._validation_recalculate()
        completed = sum(1 for item in result_rows if isinstance(item, dict) and isinstance(item.get("platform"), (int, float)))
        status = f"平台计算完成：{completed}/{len(result_rows)} 组"
        if warnings:
            status += f" · {len(warnings)} 组需检查"
        self._set_info(self.validation_data_status, "状态", status)
        if warnings:
            QMessageBox.warning(self, "部分工况未完成", "\n".join(warnings[:8]))

    def _validation_platform_failed(self, message: str) -> None:
        if hasattr(self, "validation_run_platform_button"):
            if hasattr(self.validation_run_platform_button, "set_task_state"):
                self.validation_run_platform_button.set_task_state("error", "比较失败")
                QTimer.singleShot(1600, lambda: self.validation_run_platform_button.reset_task_state("计算并比较"))
            else:
                self.validation_run_platform_button.setEnabled(True)
        if hasattr(self, "validation_progress_panel"):
            self.validation_result_panel.show()
            self.validation_progress_panel.show()
            self.validation_progress.setRange(0, 100)
            self.validation_progress.setValue(0)
            self.validation_progress.setTextVisible(False)
            self.validation_progress_label.setText("平台比较失败 · 请检查任务错误后重试")
        self._set_info(self.validation_data_status, "状态", "平台计算失败")
        QMessageBox.warning(self, "平台计算失败", str(message))

    def _validation_fill_current_result(self) -> None:
        row = self.validation_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "请选择工况", "先选择需要写入平台结果的一行。")
            return
        kind = self.validation_kind.currentText()
        if kind != "E003 耦合效率":
            QMessageBox.information(self, "需要扫描结果", "E004/E006 请使用“从最近扫描提取 3 dB”。")
            return
        value = self.context.project.project.metrics.get("coupling_efficiency")
        if not isinstance(value, (int, float)):
            QMessageBox.information(self, "没有正式结果", "请先在“仿真系统”运行当前工况的正式耦合计算。")
            return
        pct = float(value) * 100.0 if abs(float(value)) <= 1.000001 else float(value)
        self.validation_table.setItem(row, 3, QTableWidgetItem(f"{pct:.8g}"))
        num = self.context.project.project.metrics.get("coupling_convergence_last_delta")
        if isinstance(num, (int, float)):
            num_value = float(num) * 100.0 if abs(float(num)) <= 1.000001 else float(num)
            self.validation_table.setItem(row, 4, QTableWidgetItem(f"{abs(num_value):.8g}"))
        self._validation_recalculate()

    def _validation_fill_scan_width(self) -> None:
        row = self.validation_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "请选择工况", "先选择需要写入平台结果的一行。")
            return
        kind = self.validation_kind.currentText()
        if kind not in {"E004 横向 3 dB 全宽", "E006 角度 3 dB 全宽"}:
            QMessageBox.information(self, "验证类型不匹配", "该功能用于 E004/E006 的耦合效率扫描。")
            return
        result = latest_optimization_result(self.context.tasks)
        responses = dict(result.get("response_values", {}) or {}) if isinstance(result, dict) else {}
        raw = list(responses.get("coupling_efficiency", []) or [])
        grid = [list(item) for item in list(result.get("parameter_grid", []) or []) if item] if isinstance(result, dict) else []
        if not raw or not grid:
            QMessageBox.information(self, "没有扫描数据", "请先在“规律扫描”完成对应的横向偏移或倾角扫描。")
            return
        x = [float(item[0]) for item in grid[:len(raw)]]
        y = [float(value) for value in raw[:len(x)]]
        width = three_db_width(x, y)
        if width is None:
            QMessageBox.warning(self, "无法提取 3 dB", "扫描范围没有覆盖峰值两侧的半高交点，请扩大扫描范围。")
            return
        if kind == "E004 横向 3 dB 全宽":
            width *= 1000.0
            unit = "μm"
        else:
            width = width * 3.141592653589793 / 180.0 * 1000.0
            unit = "mrad"
        self.validation_table.setItem(row, 3, QTableWidgetItem(f"{width:.8g}"))
        self.validation_table.setItem(row, 6, QTableWidgetItem(unit))
        self._validation_recalculate()

    def _validation_open_tolerance_analysis(self) -> None:
        self._open_tolerance_from_optimization()

    def _validation_fill_input_uncertainty(self) -> None:
        row = self.validation_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "请选择工况", "先选择需要写入输入参数不确定度的一行。")
            return
        value = self._latest_input_uncertainty()
        if value is None:
            QMessageBox.information(self, "没有容差结果", "请先在当前系统下展开“容差分析”并完成一次输入参数容差计算。")
            return
        self.validation_table.setItem(row, 5, QTableWidgetItem(f"{abs(float(value)):.8g}"))
        self._validation_recalculate()

    def _validation_save_numerics_profile(self) -> None:
        store = SimulationNumericsProfileStore()
        current = store.load()
        automatic = self.validation_auto_numerics.isChecked()
        # 自动模式才按精度预设更新采样值；手动模式保留高级用户已经设定的
        # 网格、光瞳采样、传播方法、零填充与计算窗口，避免“保存全局策略”
        # 意外覆盖专家参数。
        if automatic:
            current.update(store.recommended_sampling(self.validation_precision.currentText()))
        current.update({
            "automatic": automatic,
            "precision": self.validation_precision.currentText(),
            "sampling_convergence": self.validation_convergence.isChecked(),
            "auto_display_frame": self.validation_display_frame.isChecked(),
            "display_fill_fraction": self.validation_display_fraction.value() / 100.0,
        })
        saved = store.save(current)
        self.context.project.update_research_profile(validation_numerics={
            "automatic": saved["automatic"],
            "precision": saved["precision"],
            "sampling_convergence": saved["sampling_convergence"],
            "display_fill_fraction": saved["display_fill_fraction"],
        })
        self._set_info(self.validation_data_status, "状态", f"已应用计算设置：{saved['precision']} · {'自动采样' if saved['automatic'] else '手动采样'}")

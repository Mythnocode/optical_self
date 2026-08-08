from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem

from frontend_pyside.shared.components.basic import InfoRow
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace
from frontend_pyside.shared.display_names import metric_label, parameter_label
from frontend_pyside.shared.research_summary import humanize_parameter_name
from frontend_pyside.shared.plotting.engineering_views import (
    build_before_after_comparison,
    build_candidate_comparison,
    build_convergence_view,
    build_correlation_view,
)
from shared_contracts.metrics import metric_definition


class OptimizationResultMixin:


    def _render_scan_result(self, result: dict) -> None:
        if not bool(getattr(self, "_page_active", True)):
            self._pending_result_render = ("scan", dict(result or {}))
            return
        self._ensure_result_workspace("scan")
        metric = self._metric_key(self.scan_metric.currentText())
        raw_values = [float(value) for value in list(result.get("response_values", {}).get(metric, []))]
        grid = [list(row) for row in list(result.get("parameter_grid", [])) if row]
        parameter_name = self.scan_param.currentText()
        unit = self._unit_for_label(parameter_name)
        x = [float(row[0]) for row in grid[:len(raw_values)] if row]
        count = min(len(x), len(raw_values))
        x = x[:count]
        raw_values = raw_values[:count]
        is_efficiency = metric == "coupling_efficiency"
        values = [value * 100.0 if is_efficiency and abs(value) <= 1.000001 else value for value in raw_values]
        y_name = metric_label(metric) + (" / %" if is_efficiency else "")

        if not values:
            empty = {"kind": "empty", "message": "本次研究没有生成有效数据"}
            for workspace in (self.scan_result, self.main_result):
                workspace.set_layout_mode("单图")
                workspace.set_result(0, "参数响应", empty)
                workspace.set_result(1, "二维关系", empty)
            self.scan_best.set_value("—")
            self.scan_width.set_value("—")
            self.scan_sensitivity.set_value("无有效结果")
            self.scan_samples.set_value("0", "点")
            for table_name in ("scan_data_table", "scan_region_table", "scan_compare_table", "scan_verification_table"):
                table = getattr(self, table_name, None)
                if table is not None:
                    table.setRowCount(0)
            self.header_state.set_value("无有效结果")
            self.research_progress.setValue(100)
            self.start_research_button.setEnabled(True)
            self._set_job_info("scan", "无有效结果")
            return

        definition = metric_definition(metric)
        higher_is_better = definition is None or definition.higher_is_better
        best_index = max(range(count), key=values.__getitem__) if higher_is_better else min(range(count), key=values.__getitem__)
        best_x = x[best_index]
        best_y = values[best_index]
        current_raw = self._current_scan_value(parameter_name).split()[0]
        try:
            current_value = float(current_raw)
        except (TypeError, ValueError):
            current_value = None
        current_point = None
        if current_value is not None:
            nearest = min(range(count), key=lambda index: abs(x[index] - current_value))
            current_point = [x[nearest], values[nearest]]

        verified_point = result.get("verified_point")
        if isinstance(verified_point, (list, tuple)) and len(verified_point) >= 2:
            verified_point = [float(verified_point[0]), float(verified_point[1])]
            if is_efficiency and abs(verified_point[1]) <= 1.000001:
                verified_point[1] *= 100.0
        response_plot = {
            "kind": "parameter_response",
            "x": x,
            "y": values,
            "current_point": current_point,
            "best_point": [best_x, best_y],
            "verified_point": verified_point,
            "title": "参数响应",
            "x_label": f"{parameter_name}{f' / {unit}' if unit else ''}",
            "y_label": y_name,
        }
        parameter_count = max((len(row) for row in grid), default=0)
        relation_plot = {"kind": "empty", "message": "当前研究为单参数扫描"}
        if parameter_count >= 2:
            rows = grid[:count]
            unique_x = sorted({float(row[0]) for row in rows if len(row) >= 2})
            unique_y = sorted({float(row[1]) for row in rows if len(row) >= 2})
            matrix = [[float("nan") for _ in unique_x] for _ in unique_y]
            x_index = {value: index for index, value in enumerate(unique_x)}
            y_index = {value: index for index, value in enumerate(unique_y)}
            for row, value in zip(rows, values):
                if len(row) >= 2:
                    matrix[y_index[float(row[1])]][x_index[float(row[0])]] = float(value)
            names = list(result.get("parameter_names", []) or [])
            relation_plot = {
                "kind": "heatmap",
                "title": "二维参数响应",
                "x": unique_x,
                "y": unique_y,
                "z": matrix,
                "x_label": parameter_label(names[0]) if names else parameter_name,
                "y_label": parameter_label(names[1]) if len(names) > 1 else "第二参数",
            }

        self.scan_result.set_layout_mode("单图")
        self.scan_result.set_result(0, "参数响应", response_plot)
        self.scan_result.set_result(1, "二维关系", relation_plot)
        self.scan_result.set_result(2, "优化过程", {"kind": "empty", "message": "参数扫描没有优化迭代"})
        self.scan_result.set_result(3, "候选对比", {"kind": "empty", "message": "单次扫描不生成候选对比"})
        self._main_result_payloads = [
            response_plot,
            {"kind": "empty", "message": "参数扫描不生成优化前后对比。"},
            {"kind": "empty", "message": "参数扫描没有优化迭代。"},
            {"kind": "empty", "message": "单次扫描不生成候选方案排序。"},
            relation_plot,
        ]
        self._select_main_result(0)
        self._set_result_view_visibility((True, False, False, False, parameter_count >= 2))

        self.scan_best.set_value(f"{best_x:.4g}", unit)
        self.scan_width.set_value(f"{best_y:.4g}", "%" if is_efficiency else "")
        self.scan_samples.set_value(str(count), "点")

        high_ranges: list[tuple[str, float, float]] = []
        if higher_is_better and best_y != 0:
            thresholds = [("≥99%峰值", best_y * 0.99), ("≥95%峰值", best_y * 0.95)]
            for label, threshold in thresholds:
                selected = [xv for xv, yv in zip(x, values) if yv >= threshold]
                if selected:
                    high_ranges.append((label, min(selected), max(selected)))
        if high_ranges:
            widest_label, low, high = high_ranges[1] if len(high_ranges) > 1 else high_ranges[0]
            self.scan_sensitivity.set_value(f"{low:.4g}～{high:.4g}", unit)
            response_plot["high_efficiency_range"] = [low, high]
            response_plot["high_efficiency_label"] = widest_label
        else:
            self.scan_sensitivity.set_value("—")


        self.scan_data_table.setHorizontalHeaderLabels(["序号", f"{parameter_name}{f' / {unit}' if unit else ''}", y_name, "状态"])
        self.scan_data_table.setRowCount(count)
        for row_index, (parameter_value, metric_value) in enumerate(zip(x, values)):
            row_values = (row_index + 1, f"{parameter_value:.6g}", f"{metric_value:.6g}", "有效")
            for column, value in enumerate(row_values):
                item = QTableWidgetItem(str(value))
                if column != 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.scan_data_table.setItem(row_index, column, item)

        self.scan_region_table.setRowCount(len(high_ranges))
        for row_index, (label, low, high) in enumerate(high_ranges):
            row_values = (label, f"{low:.6g}", f"{high:.6g}", f"{high-low:.6g}", f"{low-best_x:+.4g}/{high-best_x:+.4g}")
            for column, value in enumerate(row_values):
                self.scan_region_table.setItem(row_index, column, QTableWidgetItem(str(value)))
        self.scan_compare_table.setRowCount(1)
        interval_width = high_ranges[1][2] - high_ranges[1][1] if len(high_ranges) > 1 else (high_ranges[0][2] - high_ranges[0][1] if high_ranges else 0.0)
        sensitivity = "高" if interval_width and interval_width < abs(self.scan_stop.value()-self.scan_start.value())*0.15 else "中" if interval_width else "—"
        for column, value in enumerate((parameter_name, f"{best_x:.6g}", f"{best_y:.6g}", f"{interval_width:.6g}", sensitivity)):
            self.scan_compare_table.setItem(0, column, QTableWidgetItem(str(value)))

        verified = result.get("verified_point")
        self.scan_verification_table.setRowCount(1 if isinstance(verified, (list, tuple)) and len(verified) >= 2 else 0)
        if self.scan_verification_table.rowCount():
            verified_y = float(verified[1])
            if is_efficiency and abs(verified_y) <= 1.000001:
                verified_y *= 100.0
            delta = verified_y - best_y
            for column, value in enumerate(("最佳点", f"{best_y:.6g}", f"{verified_y:.6g}", f"{delta:+.6g}", "完成")):
                self.scan_verification_table.setItem(0, column, QTableWidgetItem(str(value)))

        self.candidate_table.setRowCount(1)
        for column, value in enumerate(("A", f"{parameter_name}={best_x:.6g}", f"{best_y:.6g}", "正式扫描", "完成")):
            self.candidate_table.setItem(0, column, QTableWidgetItem(str(value)))
        if is_efficiency:
            self._set_info(self.summary_coupling, "耦合效率", f"{best_y:.3f}%")
            self.header_best.set_value(f"{best_y:.3f}", "%")
        self.research_progress.setValue(100)
        self.start_research_button.setEnabled(True)
        self.header_state.set_value("已完成")
        self._set_job_info("scan", "研究完成")
        self._refresh_user_summary()

    def _render_optimization_result(self, result: dict) -> None:
        if not bool(getattr(self, "_page_active", True)):
            self._pending_result_render = ("optimization", dict(result or {}))
            return
        self._ensure_result_workspace("optimization")
        metadata = dict(result.get("metadata", {}) or {})
        metric_key = str(metadata.get("metric") or metadata.get("target_metric") or "coupling_efficiency")
        metric_name = metric_label(metric_key)
        is_efficiency = metric_key == "coupling_efficiency"
        history = [item for item in list(result.get("history", [])) if isinstance(item, dict)]
        evaluations = [float(item.get("iteration", index + 1)) for index, item in enumerate(history)]
        raw_merit = [float(item.get("merit", 0.0) or 0.0) for item in history]
        maximize = bool(metadata.get("higher_is_better", True))
        running_best: list[float] = []
        for value in raw_merit:
            running_best.append(value if not running_best else (max(running_best[-1], value) if maximize else min(running_best[-1], value)))
        if is_efficiency:
            running_best = [value * 100.0 if abs(value) <= 1.000001 else value for value in running_best]
        convergence = {
            "kind": "line",
            "x": evaluations,
            "y": running_best,
            "title": "优化过程",
            "x_label": "正式仿真次数",
            "y_label": f"当前最佳{metric_name}" + (" / %" if is_efficiency else ""),
        } if running_best else {"kind": "empty", "message": "没有优化过程数据"}

        best_variables = dict(result.get("best_variables", {}) or {})
        labels = [parameter_label(name) for name in best_variables]
        parameter_lines = [
            f"{parameter_label(name)}　{float(value):.6g}" if isinstance(value, (int, float))
            else f"{parameter_label(name)}　{value}"
            for name, value in best_variables.items()
        ]
        response_summary = {
            "kind": "text",
            "title": "最佳参数",
            "text": "\n".join(parameter_lines),
        } if best_variables else {"kind": "empty", "message": "没有最佳参数数据"}

        candidate_rows = [item for item in list(result.get("candidates", []) or result.get("candidate_results", []) or []) if isinstance(item, dict)]
        candidate_labels: list[str] = []
        candidate_values: list[float] = []
        predicted_values: list[float] = []
        for index, item in enumerate(candidate_rows):
            formal = item.get("formal_efficiency", item.get("coupling_efficiency", item.get("formal_value")))
            predicted = item.get("predicted_efficiency", item.get("predicted_value"))
            if isinstance(formal, (int, float)):
                formal_value = float(formal)
                predicted_value = float(predicted) if isinstance(predicted, (int, float)) else float("nan")
                if is_efficiency:
                    formal_value = formal_value * 100.0 if abs(formal_value) <= 1.000001 else formal_value
                    predicted_value = predicted_value * 100.0 if abs(predicted_value) <= 1.000001 else predicted_value
                candidate_labels.append(str(item.get("label", item.get("name", f"方案{index + 1}"))))
                candidate_values.append(formal_value)
                predicted_values.append(predicted_value)
        candidate_plot = {"kind": "empty", "message": "没有候选对比数据"}
        if len(candidate_values) >= 2:
            order = sorted(range(len(candidate_values)), key=candidate_values.__getitem__, reverse=maximize)
            candidate_plot = {
                "kind": "bar_grouped",
                "title": "候选方案对比",
                "labels": [candidate_labels[index] for index in order],
                "series": [
                    {"label": "正式仿真", "values": [candidate_values[index] for index in order]},
                    {"label": "模型预测", "values": [predicted_values[index] for index in order]},
                ],
                "y_label": metric_name + (" / %" if is_efficiency else ""),
            }

        self.auto_result.set_layout_mode("单图")
        self.auto_result.set_result(0, "最佳参数", response_summary)
        self.auto_result.set_result(1, "二维关系", {"kind": "empty", "message": "当前结果没有二维响应数据"})
        self.auto_result.set_result(2, "优化过程", convergence)
        self.auto_result.set_result(3, "候选对比", candidate_plot)

        before_after = build_before_after_comparison(result, self.context.project.project.metrics)
        convergence_view = build_convergence_view(
            result, metric_label=metric_name, efficiency=is_efficiency
        )
        candidate_view = build_candidate_comparison(result, efficiency=is_efficiency)
        correlation_view = build_correlation_view(result)
        self._main_result_payloads = [
            response_summary,
            before_after,
            convergence_view,
            candidate_view,
            correlation_view,
        ]
        visibility = tuple(str(payload.get("kind", "empty")) != "empty" for payload in self._main_result_payloads)
        self._set_result_view_visibility(visibility)
        selected_index = 2 if visibility[2] else next((i for i, visible in enumerate(visibility) if visible), 0)
        self._select_main_result(selected_index)

        metrics = dict(result.get("best_metrics", {}) or {})
        efficiency = metrics.get("coupling_efficiency")
        system_efficiency = metrics.get("system_efficiency")
        baseline = self.context.project.project.metrics.get("coupling_efficiency")
        normalized_efficiency = None
        if isinstance(efficiency, (int, float)):
            normalized_efficiency = efficiency if efficiency <= 1.0 else efficiency / 100.0
            self.auto_candidate.set_value(f"{normalized_efficiency * 100:.3f}", "%")
            self._set_info(self.summary_coupling, "耦合效率", f"{normalized_efficiency * 100:.3f}%")
            self.header_best.set_value(f"{normalized_efficiency * 100:.3f}", "%")
            if hasattr(self, "compare_auto"):
                self.compare_auto.set_value(f"{normalized_efficiency * 100:.3f}%")
        if isinstance(baseline, (int, float)):
            self.auto_baseline.set_value(f"{baseline * 100:.3f}", "%")
            if normalized_efficiency is not None:
                gain = normalized_efficiency - baseline
                self.auto_gain.set_value(f"{gain * 100:+.3f}", "%")
                self._set_info(self.summary_gain, "效率提升", f"{gain * 100:+.3f}%")

        collimation_enabled = bool(metadata.get("collimation_constraint_enabled", False))
        collimation_feasible = float(metrics.get("collimation_feasible", 0.0)) >= 0.5
        self.auto_constraint.set_value("通过" if (not collimation_enabled or collimation_feasible) else "未通过")

        self.auto_parameter_table.setRowCount(len(best_variables))
        for row_index, (name, value) in enumerate(best_variables.items()):
            unit = "mm" if any(token in str(name) for token in ("mm", "spacing", "distance", "offset_z")) else ""
            row_values = (parameter_label(name), "—", f"{float(value):.6g}" if isinstance(value, (int, float)) else str(value), "—", unit)
            for column, cell in enumerate(row_values):
                self.auto_parameter_table.setItem(row_index, column, QTableWidgetItem(str(cell)))

        rows_for_table = candidate_rows or ([{"name": "最佳方案", "formal_efficiency": efficiency, "system_efficiency": system_efficiency}] if best_variables or metrics else [])
        self.auto_candidate_table.setRowCount(len(rows_for_table))
        for row_index, item in enumerate(rows_for_table):
            formal = item.get("formal_efficiency", item.get("coupling_efficiency", efficiency))
            system = item.get("system_efficiency", system_efficiency)
            def pct(value):
                if not isinstance(value, (int, float)):
                    return "—"
                value = float(value)
                return f"{(value * 100.0 if abs(value) <= 1.000001 else value):.3f}%"
            name = str(item.get("label", item.get("name", f"方案{chr(65 + row_index)}")))
            status = "通过" if result.get("status") == "completed" else str(result.get("status", "完成"))
            values_for_row = (row_index + 1, name, pct(formal), pct(system), self.auto_constraint.value_label.text(), status)
            for column, cell in enumerate(values_for_row):
                self.auto_candidate_table.setItem(row_index, column, QTableWidgetItem(str(cell)))

        compare_rows = []
        if isinstance(baseline, (int, float)) and normalized_efficiency is not None:
            compare_rows.append(("耦合效率", f"{baseline*100:.3f}%", f"{normalized_efficiency*100:.3f}%", f"{(normalized_efficiency-baseline)*100:+.3f}%"))
        self.auto_compare_table.setRowCount(len(compare_rows))
        for row_index, row_values in enumerate(compare_rows):
            for column, cell in enumerate(row_values):
                self.auto_compare_table.setItem(row_index, column, QTableWidgetItem(str(cell)))

        self.auto_verification_table.setRowCount(1 if normalized_efficiency is not None else 0)
        if self.auto_verification_table.rowCount():
            predicted = metadata.get("surrogate_predicted_efficiency")
            predicted_norm = float(predicted) if isinstance(predicted, (int, float)) else None
            if predicted_norm is not None and predicted_norm > 1.0:
                predicted_norm /= 100.0
            delta = (normalized_efficiency - predicted_norm) * 100.0 if predicted_norm is not None else None
            row_values = ("最佳方案", f"{predicted_norm*100:.3f}%" if predicted_norm is not None else "—", f"{normalized_efficiency*100:.3f}%", f"{delta:+.3f}%" if delta is not None else "—", "完成")
            for column, cell in enumerate(row_values):
                self.auto_verification_table.setItem(0, column, QTableWidgetItem(str(cell)))

        self.candidate_table.setRowCount(1 if best_variables or metrics else 0)
        if self.candidate_table.rowCount():
            candidate_name = "、".join(labels[:3]) or "最佳方案"
            predicted = metadata.get("surrogate_predicted_efficiency", "—")
            formal = f"{normalized_efficiency * 100:.3f}%" if normalized_efficiency is not None else "—"
            state = "通过" if result.get("status") == "completed" else str(result.get("status", "完成"))
            for column, value in enumerate(("A", candidate_name, predicted, formal, state)):
                self.candidate_table.setItem(0, column, QTableWidgetItem(str(value)))
        self.parameter_range_text.setText("\n".join(f"{parameter_label(name)}：{value}" for name, value in best_variables.items()) or "—")
        self.formal_verification_text.setText("已完成" if result.get("status") == "completed" else str(result.get("status", "等待")))
        if labels:
            self.main_factor_text.setText("\n".join(f"{index}. {name}" for index, name in enumerate(labels[:3], start=1)))
        warnings = [str(item) for item in list(result.get("warnings", []) or [])]
        self.advice_text.setText("\n".join(warnings[:3]) if warnings else "结果已加载")
        self._set_info(self.summary_verification, "正式复核", "已完成" if result.get("status") == "completed" else str(result.get("status", "等待")))
        if hasattr(self, "compare_status"):
            self.compare_status.set_value("优化已完成")
        self.research_progress.setValue(100)
        self.start_research_button.setEnabled(True)
        self.header_state.set_value("已完成")
        self._set_job_info("optimization", "研究完成")
        self._refresh_user_summary()

    def _set_result_view_visibility(self, states: tuple[bool, ...]) -> None:
        buttons = getattr(self, "result_view_buttons", [])
        for index, button in enumerate(buttons):
            button.setVisible(bool(states[index]) if index < len(states) else False)
        visible = [index for index, state in enumerate(states) if state]
        if visible:
            selected = visible[0]
            self._select_main_result(selected)

    def _show_result_view(self, index: int) -> None:
        buttons = getattr(self, "result_view_buttons", [])
        if 0 <= index < len(buttons):
            buttons[index].setVisible(True)

    def _current_scan_value(self, label: str) -> str:
        project = self.context.project.project
        path = self._path_for_label(label)
        if path == "source.wavelength_nm":
            return f"{project.wavelength_nm:.6g} nm"
        if path == "receiver.mode_field_diameter_x_um":
            return f"{project.receiver_mfd_um:.6g} μm"
        if path.startswith("surfaces["):
            try:
                index = int(path.split("[", 1)[1].split("]", 1)[0])
                surface = project.surfaces[index]
                value = surface.thickness_mm if "distance_to_next" in path else surface.radius_mm
                return f"{value:.6g} mm"
            except (IndexError, ValueError):
                pass
        return "0"

    @staticmethod
    def _formal_quality_text(result: dict, metrics: dict) -> str:
        status = "通过" if result.get("status") == "completed" else str(result.get("status", "完成"))
        metadata = dict(result.get("metadata", {}) or {})
        lines = [f"结果状态：{status}"]
        evaluations = metadata.get("total_evaluations") or result.get("total_evaluations")
        if evaluations is not None:
            lines.append(f"正式计算次数：{evaluations}")
        if "propagation_edge_power_fraction" in metrics:
            lines.append(f"边缘功率：{float(metrics['propagation_edge_power_fraction']):.4%}")
        if metadata.get("surrogate_model_id"):
            lines.append("候选经过智能模型筛选，并由正式仿真计算结果。")
        else:
            lines.append("当前结果来自正式优化任务。")
        warnings = list(result.get("warnings", []) or [])
        if warnings:
            lines.append("提示：" + "；".join(map(str, warnings[:3])))
        return "\n".join(lines)

    def _refresh_history(self) -> None:
        if not hasattr(self, "history_table"):
            return
        rows = []
        for job_id, info in self._jobs.items():
            task = next(
                (
                    item
                    for item in self.context.tasks.tasks
                    if str(item.get("id")) == info["task_id"]
                ),
                {},
            )
            rows.append(
                [
                    "扫描" if info["kind"] == "scan" else "优化",
                    "参数研究" if info["kind"] == "scan" else "正式优化",
                    task.get("status", "运行中"),
                    f"{task.get('progress', 0)}%",
                    "—",
                    job_id,
                    task.get("note", ""),
                ]
            )
        self.history_table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column in {2, 3, 4}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.history_table.setItem(row_index, column, item)

    def _set_job_info(self, kind: str, message: str) -> None:
        target = (
            getattr(self, "scan_status", None)
            if kind == "scan"
            else getattr(self, "auto_status", None)
        )
        if target is not None:
            self._set_info(target, "任务状态", message)
        guided = getattr(self, "guided_status", None)
        if guided is not None:
            self._set_info(guided, "当前状态", message)
        activity = getattr(self, "activity_label", None)
        if activity is not None:
            activity.setText(message)
            if "：" in message or "." in message:
                activity.setToolTip(message)
        header = getattr(self, "header_state", None)
        if header is not None:
            header.set_value(message.split("：", 1)[0][:12] or "运行中")
        log_widget = (
            getattr(self, "scan_log_text", None)
            if kind == "scan"
            else getattr(self, "auto_log_text", None)
        )
        if log_widget is not None:
            log_widget.setText(message)

    @staticmethod
    def _set_info(widget: InfoRow, label: str, value: str) -> None:
        layout = widget.layout()
        if layout and layout.count() >= 2:
            layout.itemAt(0).widget().setText(label)
            layout.itemAt(1).widget().setText(value)

    @staticmethod
    def _set_empty_result(workspace: ResultWorkspace, message: str) -> None:
        workspace.set_result(0, "任务结果", {"kind": "empty", "message": message})

    @staticmethod
    def _status_text(status: str) -> str:
        return {
            "queued": "等待后端",
            "running": "运行中",
            "completed": "已完成",
            "failed": "失败",
            "cancelled": "已取消",
        }.get(status, status)

    def hideEvent(self, event) -> None:
        self._poll_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        self._restore_jobs_from_tasks(self.context.tasks.tasks)
        if self.context.tasks.should_refresh_backend(ttl_s=3.0):
            self.job_client.list_jobs("optimization.jobs.refresh", limit=100)
        for job_id in list(self._jobs):
            self.job_client.get_status(f"optimization.status.{job_id}", job_id)
        if self._jobs and not self._centralized_polling:
            self._poll_timer.start()
        super().showEvent(event)

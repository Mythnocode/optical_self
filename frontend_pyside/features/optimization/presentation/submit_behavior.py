from __future__ import annotations

from uuid import uuid4

from shared_contracts.metrics import analyses_for_metrics, canonical_metric_name

from frontend_pyside.features.optimization.numerics import research_simulation_numerics


class OptimizationSubmitMixin:
    def _run_scan(self) -> bool:
        mode_text = self.scan_mode.currentText()
        mode_map = {"一维扫描": "line_1d", "二维扫描": "grid_2d", "多参数采样": "lhs"}
        mode = mode_map.get(mode_text)
        if mode is None:
            self._set_info(self.scan_status, "任务状态", "当前扫描模式无效")
            return False

        parameters = [
            self._scan_parameter(
                self.scan_param.currentText(),
                self.scan_start,
                self.scan_stop,
                self.scan_points,
            )
        ]
        if mode == "grid_2d":
            if self.scan_param2.currentIndex() == 0:
                self._set_info(self.scan_status, "任务状态", "二维扫描需要选择第二变量")
                return False
            parameters.append(
                self._scan_parameter(
                    self.scan_param2.currentText(),
                    self.scan_start2,
                    self.scan_stop2,
                    self.scan_points2,
                )
            )
        elif mode == "lhs" and self.scan_param2.currentIndex() > 0:
            parameters.append(
                self._scan_parameter(
                    self.scan_param2.currentText(),
                    self.scan_start2,
                    self.scan_stop2,
                    self.scan_points2,
                )
            )

        if not parameters or any(not str(item.get("path", "")).strip() for item in parameters):
            self._set_info(self.scan_status, "任务状态", "当前研究没有生成有效扫描参数")
            return False
        if any(float(item["stop"]) <= float(item["start"]) for item in parameters):
            self._set_info(self.scan_status, "任务状态", "扫描上限必须大于下限")
            return False
        for item in parameters:
            path = str(item.get("path", ""))
            start = float(item.get("start", 0.0))
            stop = float(item.get("stop", 0.0))
            if path == "source.wavelength_nm" and start <= 0:
                self._set_info(self.scan_status, "任务状态", "波长必须大于 0 nm")
                return False
            if "mode_field_diameter" in path and start <= 0:
                self._set_info(self.scan_status, "任务状态", "模场直径必须大于 0 μm")
                return False
            if path.endswith("distance_to_next_mm") and start < 0:
                self._set_info(self.scan_status, "任务状态", "空气间隔不能为负；请检查扫描下限")
                return False

        metric = self._metric_key(self.scan_metric.currentText())
        precision, simulation_options = research_simulation_numerics()
        payload = {
            "request_id": f"scan-{uuid4().hex[:10]}",
            "project": self._current_research_project_payload(),
            "analyses": analyses_for_metrics([metric]),
            "precision": precision,
            "random_seed": 42,
            "options": simulation_options,
            "scan_mode": mode,
            "scan_parameters": parameters,
            "scan_response_metrics": [metric],
            "scan_options": {
                "max_samples": self.scan_points.value(),
                "include_baseline": self.include_baseline.isChecked(),
                "local_refine": self.local_refine.isChecked(),
            },
        }
        try:
            self.scan_client.submit("optimization.scan.submit", payload)
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            self._set_info(self.scan_status, "任务状态", f"扫描配置无效：{exc}")
            return False
        self._set_info(self.scan_status, "任务状态", "正在提交扫描任务")
        return True

    def _run_auto(self) -> bool:
        variables = self.variable_selector.get_variables()
        if not variables:
            self._set_info(self.auto_status, "任务状态", "当前研究内容没有对应到可优化参数")
            return False
        objective = self._objective_definition()
        opt_options = {
            "multi_start": 1,
            "fixed_evaluation_budget": True,
            "timeout_seconds": 1200,
            # Keep the complete submitted parameter state with the result.  The
            # best vector alone cannot explain which values remained fixed.
            "parameter_snapshot": self.variable_selector.get_parameter_snapshot(),
        }
        if bool(getattr(self, "_ml_inverse_prediction_active", False)):
            model_id = str(getattr(self.context.registry, "current_model_id", "") or "")
            if not model_id:
                self._set_info(self.auto_status, "任务状态", "反向预测需要先采用一个可用代理模型")
                return False
            # 后端会用代理模型完成大部分粗搜索，并对最终候选执行正式物理验证。
            # 这与“物理反向设计”保持语义区分，同时不会把未经验证的 ML 候选当成真值。
            opt_options.update({
                "surrogate_model_id": model_id,
                "coarse_fraction": 0.88,
                "mode": "ml_inverse_prediction",
            })
        precision, simulation_options = research_simulation_numerics()
        payload = {
            "request_id": f"opt-{uuid4().hex[:10]}",
            "project": self._current_research_project_payload(),
            "analyses": analyses_for_metrics([objective["metric"]]),
            "precision": precision,
            "random_seed": 42,
            "options": simulation_options,
            "opt_optimizer": self._optimizer_key(self.algorithm.currentText()),
            "opt_variables": variables,
            "opt_objectives": [objective],
            "opt_constraints": self._optimization_constraints(),
            "opt_max_iterations": self.iterations.value(),
            "opt_max_evaluations": self.iterations.value(),
            "opt_convergence_tolerance": self.tolerance.value(),
            "opt_options": opt_options,
        }
        try:
            self.optimization_client.submit("optimization.auto.submit", payload)
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            self._set_info(self.auto_status, "任务状态", f"优化配置无效：{exc}")
            return False
        if bool(getattr(self, "_ml_inverse_prediction_active", False)):
            self._set_info(self.auto_status, "任务状态", "正在提交代理模型反向预测")
        else:
            self._set_info(self.auto_status, "任务状态", "正在提交优化任务")
        return True

    def _optimization_constraints(self) -> list[dict]:
        if not getattr(self, "collimation_enabled", None) or not self.collimation_enabled.isChecked():
            return []
        surface_index = self.collimation_surface.currentData()
        constraint = {
            "type": "collimation",
            "enabled": True,
            "plane_start_offset_mm": 0.0,
            "evaluation_span_mm": float(self.collimation_span.value()),
            "max_radius_change_fraction": float(self.collimation_radius_change.value()) / 100.0,
            "max_normalized_curvature": float(self.collimation_curvature.value()),
            "max_centroid_drift_fraction": float(self.collimation_centroid_drift.value()) / 100.0,
            "max_axis_tilt_mrad": float(self.collimation_axis_tilt.value()),
            "minimum_score": 0.95,
            "penalty_weight": 100.0,
            "hard": True,
            "require_clear_span": True,
        }
        if surface_index is not None:
            constraint["after_surface_index"] = int(surface_index)
        return [constraint]

    def _scan_parameter(self, label: str, start, stop, points) -> dict:
        return {"path": self._path_for_label(label), "label": label, "unit": self._unit_for_label(label), "start": start.value(), "stop": stop.value(), "points": points.value()}

    def _objective_definition(self) -> dict:
        if bool(getattr(self, "_inverse_design_active", False)):
            target_widget = getattr(self, "inverse_target_efficiency", None)
            target = float(target_widget.value()) / 100.0 if target_widget is not None else 0.95
            return {
                "metric": "coupling_efficiency",
                "goal": "target",
                "target_value": max(0.0, min(1.0, target)),
                "weight": 1.0,
            }
        text = self.objective.currentText()
        if text == "最小化 RMS 光斑":
            return {"metric": canonical_metric_name("rms_spot_radius_um"), "goal": "minimize", "weight": 1.0}
        if text == "多目标加权":
            return {"metric": "coupling_efficiency", "goal": "maximize", "weight": 1.0}
        return {"metric": "coupling_efficiency", "goal": "maximize", "weight": 1.0}

    def _path_for_label(self, label: str) -> str:
        if " / " in label:
            name, parameter = label.split(" / ", 1)
            for index, surface in enumerate(self.context.project.project.surfaces):
                if surface.name != name:
                    continue
                if "厚度" in parameter or "间隔" in parameter:
                    return f"surfaces[{index}].distance_to_next_mm"
                return f"surfaces[{index}].radius_mm"
        return {
            "波长": "source.wavelength_nm",
            "光纤模场直径": "receiver.mode_field_diameter_x_um",
            "接收面位置": "receiver.axial_offset_z_mm",
            "光纤 X 偏移": "receiver.offset_x_mm",
            "光纤 Y 偏移": "receiver.offset_y_mm",
            "光纤倾角 X": "receiver.tilt_x_deg",
            "光纤倾角 Y": "receiver.tilt_y_deg",
        }.get(label, "receiver.axial_offset_z_mm")

    @staticmethod
    def _unit_for_label(label: str) -> str:
        if label == "波长":
            return "nm"
        if "模场直径" in label:
            return "μm"
        return "deg" if "倾角" in label else "mm"

    @staticmethod
    def _metric_key(text: str) -> str:
        label_map = {
            "\u8026\u5408\u6548\u7387": "coupling_efficiency",
            "RMS \u5149\u6591": "rms_spot_radius_um",
            "Strehl": "strehl_estimate_marechal",
            "\u8fb9\u7f18\u529f\u7387": "propagation_edge_power_fraction",
        }
        return canonical_metric_name(label_map.get(text, "coupling_efficiency"))

    @staticmethod
    def _optimizer_key(text: str) -> str:
        return {
            "差分进化粗搜": "differential_evolution",
            "贝叶斯粗搜": "bayesian",
        }.get(text, "auto")

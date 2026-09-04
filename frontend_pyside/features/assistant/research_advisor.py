from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class ModelGate:
    level: str
    label: str
    usable_for_guidance: bool
    usable_for_shap: bool
    reasons: tuple[str, ...]
    metrics: dict[str, float]


@dataclass(frozen=True)
class EvidenceSummary:
    current: int
    verified: int
    stale: int
    formal: int
    scan: int
    shap: int
    optimization: int
    tolerance: int


class ResearchAdvisor:
    """Deterministic research-state advisor used by the in-app AI assistant.

    The advisor deliberately separates *evidence* from *decisions*.  It may explain,
    grade and suggest follow-up research, but never edits parameters or starts jobs.
    """

    _STATUS_CURRENT = {"当前", "已验证"}

    def answer(self, question: str, page_id: str | None, project: dict[str, Any]) -> dict[str, Any] | None:
        text = self._normalize(question)
        if self._matches(text, ("从哪里开始", "我该从哪开始", "第一次怎么用", "第一次使用", "新手怎么开始")):
            return self.getting_started(page_id, project)
        if self._matches(text, ("怎么继续", "下一步", "接下来做什么", "下一步怎么做", "然后呢", "接着做什么")):
            return self.next_step(page_id, project)
        if self._matches(text, ("当前结果可靠吗", "结果可靠吗", "能不能信", "可信", "可靠性", "可信度")):
            return self.reliability(page_id, project)
        if self._matches(text, ("解释当前结果", "怎么看当前结果", "这个结果怎么看", "解释结果", "为什么是这个结果")):
            return self.explain_current(page_id, project)
        if self._matches(text, ("当前主要问题", "现在有什么问题", "主要风险", "当前风险", "哪里有问题", "先解决什么")):
            return self.main_issues(page_id, project)
        if self._matches(text, ("总结当前研究", "总结研究状态", "当前研究状态", "现在做到哪", "目前进展", "研究进展")):
            return self.research_summary(page_id, project)
        if self._matches(text, ("哪些结果需要更新", "哪些过期", "旧结果", "需更新", "失效结果")):
            return self.stale_evidence(page_id, project)
        if self._matches(text, ("有哪些证据", "证据是什么", "依据是什么", "当前证据", "证据链")):
            return self.evidence_chain(page_id, project)
        if self._matches(text, ("模型可靠吗", "模型能用吗", "模型质量", "还能用shap", "还能用于shap", "shap能用吗", "shap可以用吗", "能不能用shap", "能不能用于shap", "为什么不能用shap", "为什么不建议shap")):
            return self.model_reliability(page_id, project)
        if self._matches(text, ("可以定型吗", "能定型吗", "可以采用吗", "能采用吗", "可以做决策吗", "能进入下一阶段吗", "决策准备度")):
            return self.decision_readiness(page_id, project)
        if self._matches(text, ("结果冲突", "证据冲突", "结论冲突", "为什么不一致", "结果不一致")):
            return self.evidence_conflicts(page_id, project)
        if self._matches(text, ("为什么最后", "为什么改成", "为什么采用", "研究记录", "操作记录", "怎么得到现在", "之前做了什么")):
            return self.research_journal_answer(page_id, project)
        if self._matches(text, ("哪些参数值得研究", "哪些参数值得优化", "帮我选参数", "帮我选优化变量", "优先研究什么参数", "关键参数有哪些", "先研究哪个参数")):
            return self.parameter_priorities(page_id, project)
        if self._matches(text, ("你能做什么", "能帮我什么", "助手能做什么", "ai助手功能", "怎么用ai助手")):
            return self.capabilities(page_id, project)
        if self._matches(text, ("为什么效率低", "耦合效率为什么低", "主要限制因素", "什么限制了效率")):
            return self.explain_current(page_id, project)
        parameter_answer = self.parameter_evidence(question, project)
        if parameter_answer is not None:
            return parameter_answer
        return None

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[\s，。！？、；：,.!?;:]", "", str(text or "").strip().lower())

    @staticmethod
    def _matches(text: str, tokens: Iterable[str]) -> bool:
        return any(ResearchAdvisor._normalize(token) in text for token in tokens)

    @staticmethod
    def _status(row: dict[str, Any]) -> str:
        value = str(row.get("status", "当前") or "当前")
        return value if value in {"当前", "已验证", "需更新"} else "当前"

    def findings(self, project: dict[str, Any]) -> list[dict[str, Any]]:
        direct = project.get("findings", [])
        if isinstance(direct, list):
            return [dict(row) for row in direct if isinstance(row, dict)]
        return []


    @staticmethod
    def _context_errors(project: dict[str, Any]) -> list[str]:
        values = project.get("context_collection_errors", []) or []
        if not isinstance(values, list):
            return []
        return [str(item) for item in values if str(item).strip()]

    def evidence_summary(self, project: dict[str, Any]) -> EvidenceSummary:
        rows = self.findings(project)
        current_rows = [row for row in rows if self._status(row) in self._STATUS_CURRENT]
        def source_count(token: str) -> int:
            return sum(1 for row in current_rows if token in str(row.get("source", "")))
        formal = 1 if dict(project.get("formal_result", {}) or {}) else 0
        return EvidenceSummary(
            current=sum(1 for row in rows if self._status(row) == "当前"),
            verified=sum(1 for row in rows if self._status(row) == "已验证"),
            stale=sum(1 for row in rows if self._status(row) == "需更新"),
            formal=formal,
            scan=source_count("扫描"),
            shap=source_count("SHAP"),
            optimization=source_count("优化"),
            tolerance=source_count("容差"),
        )

    @staticmethod
    def completed_results(project: dict[str, Any]) -> list[dict[str, Any]]:
        snapshot = dict(project.get("research_results", {}) or {})
        records = dict(snapshot.get("tasks_by_id", {}) or {})
        results = dict(snapshot.get("results_by_task_id", {}) or {})
        rows: list[dict[str, Any]] = []
        for task_id, result in results.items():
            task = dict(records.get(str(task_id), {}) or {})
            rows.append({
                "id": str(task_id),
                "name": str(task.get("name", task.get("title", ""))),
                "kind": str(task.get("kind", task.get("type", ""))),
                "status": str(task.get("status", "")),
                "progress": task.get("progress", 0),
                "result": result,
            })
        if rows:
            return rows
        legacy = snapshot.get("tasks", []) or []
        if isinstance(legacy, list):
            for item in legacy:
                if isinstance(item, dict) and item.get("result") is not None:
                    rows.append(dict(item))
        return rows

    @staticmethod
    def _finite_number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    def _model_record(self, project: dict[str, Any]) -> dict[str, Any]:
        registry = dict(project.get("registry", {}) or {})
        record = registry.get("current_model")
        return dict(record) if isinstance(record, dict) else {}

    def model_gate(self, project: dict[str, Any]) -> ModelGate:
        model = self._model_record(project)
        if not model:
            return ModelGate("missing", "— 未选择模型", False, False, ("当前没有可用模型。",), {})

        flat: dict[str, float] = {}
        metric_blocks: list[dict[str, Any]] = []
        for key in ("metrics", "test_metrics", "evaluation", "validation_metrics"):
            block = model.get(key)
            if isinstance(block, dict):
                metric_blocks.append(block)
        metric_blocks.append(model)

        # Fixed-structure models usually expose scalar metrics. BiLSTM stores metrics by target.
        nested_r2: list[float] = []
        nested_rmse: list[float] = []
        nested_mae: list[float] = []
        for block in metric_blocks:
            for key in ("r2", "test_r2", "R2"):
                number = self._finite_number(block.get(key))
                if number is not None:
                    flat.setdefault("r2", number)
            for key in ("rmse", "test_rmse"):
                number = self._finite_number(block.get(key))
                if number is not None:
                    flat.setdefault("rmse", number)
            for key in ("mae", "test_mae"):
                number = self._finite_number(block.get(key))
                if number is not None:
                    flat.setdefault("mae", number)
            for key in ("high_efficiency_rmse", "high_efficiency_mae"):
                number = self._finite_number(block.get(key))
                if number is not None:
                    flat[key] = number
            for value in block.values():
                if not isinstance(value, dict):
                    continue
                number = self._finite_number(value.get("r2"))
                if number is not None:
                    nested_r2.append(number)
                number = self._finite_number(value.get("rmse"))
                if number is not None:
                    nested_rmse.append(number)
                number = self._finite_number(value.get("mae"))
                if number is not None:
                    nested_mae.append(number)
        if "r2" not in flat and nested_r2:
            flat["r2"] = min(nested_r2)
            flat["r2_mean"] = sum(nested_r2) / len(nested_r2)
        if "rmse" not in flat and nested_rmse:
            flat["rmse"] = max(nested_rmse)
        if "mae" not in flat and nested_mae:
            flat["mae"] = max(nested_mae)

        page_context = dict(project.get("page_context", {}) or {})
        domain_text = " ".join(str(value) for value in (
            page_context.get("training_domain"), model.get("training_domain"), model.get("in_training_domain")
        ) if value not in (None, ""))
        out_of_domain = any(token in domain_text.lower() for token in ("超出", "out", "false", "域外"))
        r2 = flat.get("r2")
        reasons: list[str] = []
        if out_of_domain:
            reasons.append("当前参数可能超出了这个模型训练时见过的范围。")
        if r2 is None:
            reasons.append("还没有独立测试 R²，暂时无法判断这个模型预测得准不准。")
            return ModelGate("unknown", "⚠ 还不能判断", False, False, tuple(reasons), flat)
        if r2 < 0.0:
            reasons.append(f"独立测试 R²={r2:.4f}<0。")
            return ModelGate("poor", "× 表现较差", False, False, tuple(reasons), flat)
        if out_of_domain:
            return ModelGate("ood", "⚠ 超出模型学过的范围", False, False, tuple(reasons), flat)
        if r2 < 0.60:
            reasons.append(f"独立测试 R²={r2:.4f}，预测还不够稳定，暂时只适合看看大致趋势。")
            return ModelGate("weak", "⚠ 预测还不够准", False, False, tuple(reasons), flat)
        high_rmse = flat.get("high_efficiency_rmse")
        rmse = flat.get("rmse")
        high_region_warning = bool(
            high_rmse is not None and rmse is not None and rmse > 0.0 and high_rmse > 1.5 * rmse
        )
        if high_region_warning:
            reasons.append(
                f"高效率区域的 RMSE={high_rmse:.4g}，明显高于整体 RMSE={rmse:.4g}；模型在最值得关注的高效率区域反而更容易出错。"
            )
        if r2 < 0.80 or high_region_warning:
            if r2 < 0.80:
                reasons.append(f"独立测试 R²={r2:.4f}，可以帮助缩小候选范围，但最后仍要用完整物理仿真确认。")
            else:
                reasons.append(f"独立测试 R²={r2:.4f}，但高效率区域误差偏大，因此这里只把模型当作辅助参考。")
            return ModelGate("medium", "△ 可作辅助参考", True, True, tuple(reasons), flat)
        reasons.append(f"独立测试 R²={r2:.4f}。模型可以帮助快速比较候选结果，但不能替代完整物理仿真。")
        return ModelGate("good", "✓ 可作辅助参考", True, True, tuple(reasons), flat)

    def model_consistency(self, project: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
        registry = dict(project.get("registry", {}) or {})
        page = dict(project.get("page_context", {}) or {})
        current = str(registry.get("current_model_id", "") or "")
        recent = str(registry.get("recent_model_id", "") or "")
        selected = str(page.get("selected_model_id") or page.get("model_id") or "")
        adopted = str(page.get("adopted_model_id") or "")
        issues: list[str] = []
        if adopted and current and adopted != current:
            issues.append(f"页面记录的采用模型 {adopted} 与项目当前模型 {current} 不一致。")
        if selected and current and selected != current:
            issues.append(f"当前页面选择模型 {selected}，项目采用模型为 {current}。")
        if recent and current and recent != current:
            issues.append(f"最近训练模型 {recent} 尚未设为当前模型 {current}；训练结果不会自动替换当前模型。")
        return (not issues, tuple(issues))

    @staticmethod
    def _next_actions(page_id: str | None, formal_state: str, gate: ModelGate, *, has_shap: bool, has_scans: bool, has_optimization: bool, has_tolerance: bool, variable_structure: bool) -> list[dict[str, str]]:
        if formal_state in {"stale", "failed", "warning", "missing"}:
            return [{"label": "准备正式仿真", "target": "simulation.formal", "level": "prepare"}]
        if gate.level in {"poor", "weak", "ood", "unknown"} and str(page_id or "") in {"machine_learning", "explainability", "optimization"}:
            return [
                {"label": "准备重新训练", "target": "machine_learning.training", "level": "prepare"},
                {"label": "查看当前模型", "target": "machine_learning.current", "level": "navigate"},
            ]
        if variable_structure:
            return [{"label": "准备结构候选", "target": "optimization.variable_structure", "level": "prepare"}]
        if has_shap and not has_scans:
            return [{"label": "准备参数扫描", "target": "optimization.scan", "level": "prepare"}]
        if has_scans and not has_optimization:
            return [{"label": "准备参数优化", "target": "optimization.variables", "level": "prepare"}]
        if has_optimization and not has_tolerance:
            return [{"label": "查看容差设置", "target": "optimization.tolerance", "level": "navigate"}]
        page_key = str(page_id or "")
        if page_key == "teaching":
            return [{"label": "继续可视化探索", "target": "teaching.explore", "level": "navigate"}]
        if page_key == "tasks":
            return [{"label": "查看当前任务", "target": "tasks.current", "level": "navigate"}]
        if page_key == "home":
            return [{"label": "查看正式结果", "target": "simulation.current", "level": "navigate"}]
        if page_key in {"simulation", "optimization", "machine_learning", "explainability"}:
            return [{"label": "查看当前结果", "target": f"{page_key}.current", "level": "navigate"}]
        return []

    @staticmethod
    def _formal_state(project: dict[str, Any]) -> tuple[str, list[str]]:
        formal = dict(project.get("formal_result", {}) or {})
        page = dict(project.get("page_context", {}) or {})
        reasons: list[str] = []
        if not formal:
            return "missing", ["当前没有正式仿真结果。"]
        current_revision = int(project.get("design_revision", 0) or 0)
        formal_revision = formal.get("design_revision", formal.get("project_revision", formal.get("revision")))
        if isinstance(formal_revision, (int, float)) and current_revision and int(formal_revision) != current_revision:
            return "stale", [f"正式结果来自系统版本 {int(formal_revision)}，当前已经是版本 {current_revision}，需要重新计算。"]
        text = " ".join(str(value) for value in (
            page.get("formal_state"), formal.get("status"), formal.get("source")
        ) if value not in (None, ""))
        if "需更新" in text or "过期" in text or "stale" in text.lower():
            reasons.append("正式结果对应旧系统状态，需要重新计算。")
            return "stale", reasons
        if formal.get("converged") is False:
            reasons.append("正式仿真未收敛。")
            return "failed", reasons
        metrics = dict(formal.get("metrics", {}) or {})
        for key, label in (
            ("sampling_convergence_pass", "采样收敛检查未通过"),
            ("coupling_propagation_sampling_pass", "传播采样检查未通过"),
            ("coupling_propagation_edge_pass", "窗口边缘能量检查未通过"),
            ("coupling_propagation_energy_pass", "能量闭合检查未通过"),
        ):
            if metrics.get(key) is False:
                reasons.append(label + "。")
        if metrics.get("best_focus_minimum_at_scan_boundary") is True:
            reasons.append("最佳焦点落在扫描边界，焦面搜索范围可能不足。")
        return ("warning" if reasons else "good"), reasons

    @staticmethod
    def _result_excerpt(value: Any) -> str:
        if isinstance(value, dict):
            priority = (
                "coupling_efficiency", "system_efficiency", "best_efficiency", "best_value",
                "best_score", "rmse", "mae", "p05", "yield", "yield_rate", "mean", "std", "status",
            )
            bits: list[str] = []
            for key in priority:
                item = value.get(key)
                if isinstance(item, (int, float, str)) and str(item) not in {"", "None"}:
                    bits.append(f"{key}={item}")
            if bits:
                return "，".join(bits[:5])
            for key, item in value.items():
                if isinstance(item, (int, float, str)):
                    bits.append(f"{key}={item}")
                if len(bits) >= 4:
                    break
            return "，".join(bits)
        return str(value)[:160]

    def _active_rows(self, project: dict[str, Any]) -> list[dict[str, Any]]:
        return [row for row in self.findings(project) if self._status(row) in self._STATUS_CURRENT]


    def research_stage(self, page_id: str | None, project: dict[str, Any]) -> dict[str, str]:
        """Return one authoritative stage used before producing beginner guidance."""
        formal_state, _ = self._formal_state(project)
        gate = self.model_gate(project)
        active = self._active_rows(project)
        task_rows = list(dict(project.get("research_results", {}) or {}).get("tasks_by_id", {}).values())
        running = [row for row in task_rows if isinstance(row, dict) and str(row.get("status", "")).lower() in {"运行中", "等待后端", "等待中", "queued", "running", "submitting"}]
        if running:
            row = running[0]
            return {"code": "running", "label": "任务正在运行", "reason": str(row.get("name") or row.get("kind") or "后台任务")}
        if formal_state in {"missing", "stale", "failed", "warning"}:
            return {"code": f"formal_{formal_state}", "label": "正式仿真需要处理", "reason": formal_state}
        has_scan = any("扫描" in str(row.get("source", "")) for row in active)
        has_shap = any("SHAP" in str(row.get("source", "")) for row in active)
        has_opt = any("优化" in str(row.get("source", "")) for row in active)
        has_tol = any("容差" in str(row.get("source", "")) for row in active)
        if str(page_id or "") in {"machine_learning", "explainability"} and gate.level in {"missing", "unknown", "poor", "weak", "ood"}:
            return {"code": "model_not_ready", "label": "模型还不能用于解释", "reason": gate.level}
        if has_opt and not has_tol:
            return {"code": "candidate_needs_tolerance", "label": "已有候选，待检查稳定性", "reason": "optimization"}
        if has_shap and not has_scan:
            return {"code": "shap_needs_physics", "label": "已有模型线索，待物理扫描验证", "reason": "shap"}
        if has_scan:
            return {"code": "scan_ready", "label": "已有参数规律", "reason": "scan"}
        if formal_state == "good":
            return {"code": "formal_ready", "label": "正式结果已准备", "reason": "formal"}
        return {"code": "setup", "label": "准备当前系统", "reason": "setup"}

    @classmethod
    def _scan_curve_features(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Extract observable curve features without turning them into a causal claim.

        The four primary observations follow the learning manual: peak position,
        peak height, 3 dB width and symmetry.  This routine intentionally reports
        *what the curve looks like*; causal hypotheses are added separately.
        """
        working = dict(data or {})
        if str(working.get("kind", "")) != "parameter_response":
            # The advisor may receive either the frontend plot payload or the raw
            # backend scan result.  Normalise both so AI diagnostics do not depend
            # on which page assembled the context.
            responses = dict(working.get("response_values", {}) or {})
            grid = [list(row) for row in list(working.get("parameter_grid", []) or []) if row]
            metrics = list(working.get("response_metrics", []) or [])
            metric = str(metrics[0] if metrics else (next(iter(responses), "")))
            if not metric or metric not in responses or not grid:
                return {}
            labels = list(working.get("parameter_labels", []) or [])
            units = list(working.get("parameter_units", []) or [])
            working.update({
                "kind": "parameter_response",
                "x": [row[0] for row in grid if row],
                "y": list(responses.get(metric, []) or []),
                "x_label": str(labels[0] if labels else "扫描参数"),
                "x_unit": str(units[0] if units else ""),
                "y_label": metric,
            })
        raw_x = list(working.get("x", []) or [])
        raw_y = list(working.get("y", []) or [])
        pairs: list[tuple[float, float]] = []
        for x, y in zip(raw_x, raw_y):
            try:
                xf, yf = float(x), float(y)
            except (TypeError, ValueError):
                continue
            if math.isfinite(xf) and math.isfinite(yf):
                pairs.append((xf, yf))
        if len(pairs) < 3:
            return {}
        pairs.sort(key=lambda item: item[0])
        xs = [item[0] for item in pairs]
        ys = [item[1] for item in pairs]
        y_label = str(working.get("y_label", "") or "").lower()
        minimize = any(token in y_label for token in ("loss", "损耗", "误差", "rmse", "mae", "半径"))
        best_index = min(range(len(ys)), key=ys.__getitem__) if minimize else max(range(len(ys)), key=ys.__getitem__)
        best_x, best_y = xs[best_index], ys[best_index]
        x_min, x_max = min(xs), max(xs)
        span = max(x_max - x_min, 1e-12)
        center = (x_min + x_max) / 2.0
        normalized_shift = (best_x - center) / span
        at_boundary = best_index in {0, len(xs) - 1}

        width = None
        left_width = right_width = None
        threshold = None
        if not minimize and best_y > 0:
            # Efficiency-like quantities are power ratios, therefore the -3 dB
            # level is half the peak.  If the supplied y axis is already dB,
            # use peak-3 dB instead.
            threshold = best_y - 3.0 if "db" in y_label else best_y * 0.5
            above = [i for i, value in enumerate(ys) if value >= threshold]
            if above:
                left_i, right_i = min(above), max(above)
                width = xs[right_i] - xs[left_i]
                left_width = best_x - xs[left_i]
                right_width = xs[right_i] - best_x
        symmetry = None
        if left_width is not None and right_width is not None:
            denom = max(abs(left_width) + abs(right_width), 1e-12)
            symmetry = 1.0 - min(1.0, abs(left_width - right_width) / denom)
        width_fraction = None if width is None else width / span
        return {
            "best_x": best_x,
            "best_y": best_y,
            "scan_min": x_min,
            "scan_max": x_max,
            "scan_span": span,
            "normalized_peak_shift": normalized_shift,
            "at_boundary": at_boundary,
            "three_db_width": width,
            "three_db_width_fraction": width_fraction,
            "symmetry": symmetry,
            "threshold": threshold,
            "minimize": minimize,
            "x_label": str(working.get("x_label", "参数") or "参数"),
            "x_unit": str(working.get("x_unit", working.get("unit", "")) or ""),
        }

    @classmethod
    def _curve_diagnostic_text(cls, data: dict[str, Any]) -> tuple[str, str]:
        features = cls._scan_curve_features(data)
        if not features:
            return ("", "")
        x_label = str(features.get("x_label", "参数") or "参数")
        unit = str(features.get("x_unit", "") or "").strip()
        suffix = f" {unit}" if unit else ""
        peak = f"峰位约 {features['best_x']:.4g}{suffix}，峰高约 {features['best_y']:.4g}"
        observations = [peak]
        width_fraction = features.get("three_db_width_fraction")
        if isinstance(features.get("three_db_width"), (int, float)):
            observations.append(f"3 dB 宽度约 {float(features['three_db_width']):.4g}{suffix}")
        symmetry = features.get("symmetry")
        if isinstance(symmetry, (int, float)):
            observations.append("左右较对称" if symmetry >= 0.82 else ("存在一定不对称" if symmetry >= 0.58 else "明显不对称"))
        if features.get("at_boundary"):
            hypothesis = "最佳点贴在扫描边界，首先应扩大范围确认真正峰值；此时不适合直接解释具体失配原因。"
            phenomenon = "peak_boundary"
        elif abs(float(features.get("normalized_peak_shift", 0.0))) >= 0.18 and isinstance(symmetry, (int, float)) and symmetry < 0.58:
            hypothesis = f"{x_label}的峰位明显偏离扫描中心，而且曲线同时明显不对称。固定零点可能参与其中，但单一固定偏移不足以解释全部形状；优先扩大/细化范围，并用第二个独立扫描或二维扫描区分参数耦合。"
            phenomenon = "asymmetry"
        elif abs(float(features.get("normalized_peak_shift", 0.0))) >= 0.18:
            hypothesis = f"{x_label}的最佳位置相对扫描中心有明显平移。若曲线宽度和峰高没有同步大变，优先检查零点或固定偏移；还需要用质心/第二个扫描验证。"
            phenomenon = "peak_shift"
        elif isinstance(symmetry, (int, float)) and symmetry < 0.58:
            hypothesis = "曲线明显不对称，单一理想高斯失配往往不足以解释；优先检查离焦与其他参数耦合、像差或扫描范围，并做二维扫描区分退化。"
            phenomenon = "asymmetry"
        elif isinstance(width_fraction, (int, float)) and width_fraction < 0.28:
            hypothesis = "曲线相对较窄，说明这一自由度的容差偏紧；这描述的是敏感性，不等于已经确定了具体机械故障。"
            phenomenon = "narrow_width"
        elif isinstance(width_fraction, (int, float)) and width_fraction > 0.68:
            hypothesis = "曲线相对较宽，说明当前扫描自由度的容差较松；若另一个互补自由度反而很窄，可进一步检查模场尺寸。"
            phenomenon = "broad_width"
        else:
            hypothesis = "当前曲线没有单一特别突出的异常特征。建议把峰位、宽度、对称性与另一个独立扫描或端面光斑一起看，再决定优先怀疑方向。"
            phenomenon = "curve_features"
        return ("；".join(observations) + "。" + hypothesis, phenomenon)

    def getting_started(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        """Give a beginner a short route through the platform with one immediate action."""
        formal_state, _ = self._formal_state(project)
        gate = self.model_gate(project)
        if formal_state != "good":
            findings = [
                {"title": "第一步：先检查光路参数", "explanation": "确认光源、镜片和光纤参数是不是你准备研究的当前系统。先不用急着训练模型。"},
                {"title": "第二步：做一次完整仿真", "explanation": "完整仿真会告诉你当前系统的耦合效率和光路结果，后面的扫描和优化都要拿它作参照。"},
                {"title": "第三步：再研究关键参数", "explanation": "有了完整仿真以后，再选一个透镜间距或光纤位置做扫描，先看清变化规律。"},
            ]
            action = {"label": "从仿真系统开始", "target": "simulation.current", "level": "navigate"}
            summary = "第一次使用时不用把所有功能都打开。先把当前光路算清楚，再一步一步增加参数研究和模型分析。"
        elif gate.level in {"missing", "unknown", "poor", "weak"}:
            findings = [
                {"title": "完整仿真已经有结果", "explanation": "基础物理结果已经准备好了，不需要重复计算当前系统。"},
                {"title": "现在先做参数研究", "explanation": "选一个你最关心的间距或光纤位置，看看它改变以后耦合效率怎么变化。"},
                {"title": "模型和 SHAP 放到后面", "explanation": "等积累了足够的仿真数据，再训练模型；模型预测足够准确以后，再用 SHAP 看哪些参数最重要。"},
            ]
            action = {"label": "去参数研究", "target": "optimization.scan", "level": "prepare"}
            summary = "你已经完成了最重要的第一步。接下来先研究参数规律，比马上训练模型更容易理解结果。"
        else:
            findings = [
                {"title": "完整仿真已经有结果", "explanation": "当前系统的基础物理结果可以作为参照。"},
                {"title": "参数规律和模型都已经具备基础", "explanation": "现在可以用模型帮助筛选，但最终候选仍要回到完整仿真确认。"},
                {"title": "想理解原因时再看 SHAP", "explanation": "SHAP用来解释模型在关注哪些参数；先看主要因素，再点具体参数查看它的影响规律。"},
            ]
            action = {"label": "去失配诊断", "target": "explainability.current", "level": "navigate"}
            summary = "你已经走过基础步骤。现在可以根据目的选择：想找更好的参数就继续研究与优化，想理解原因就看失配诊断。"
        return {
            "status": "supported",
            "summary": summary,
            "findings": findings,
            "warnings": ["智能助手可以带你到对应位置并填好建议设置，但不会在你确认前开始计算。"],
            "actions": [action],
            "confidence": "high" if formal_state == "good" else "medium",
        }

    def next_step(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        """Tell a new user exactly where they are and one sensible thing to do next."""
        page = dict(project.get("page_context", {}) or {})
        context = dict(project.get("research_context", {}) or {})
        active = self._active_rows(project)
        stale = [row for row in self.findings(project) if self._status(row) == "需更新"]
        tasks = self.completed_results(project)
        gate = self.model_gate(project)
        formal_state, formal_reasons = self._formal_state(project)
        model_consistent, _model_issues = self.model_consistency(project)

        scans = [row for row in active if "扫描" in str(row.get("source", ""))]
        shap = [row for row in active if "SHAP" in str(row.get("source", ""))]
        optimizations = [row for row in active if "优化" in str(row.get("source", ""))]
        tolerances = [row for row in active if "容差" in str(row.get("source", ""))]
        task_text = " ".join((str(row.get("name", "")) + " " + str(row.get("kind", ""))) for row in tasks)
        page_name = str(page.get("page") or context.get("current_task") or page_id or "当前页面")
        view_name = str(page.get("current_view") or page.get("current_result_view") or "").strip()
        items: list[dict[str, str]] = []
        actions: list[dict[str, Any]] = []

        def add_step(done: str, meaning: str, next_title: str, why: str) -> None:
            items.extend([
                {"title": "你现在做到哪了", "explanation": done},
                {"title": "这个结果说明什么", "explanation": meaning},
                {"title": f"下一步：{next_title}", "explanation": why},
            ])

        if not model_consistent:
            add_step(
                "你正在查看机器学习结果，但当前页面使用的模型和项目里选中的模型不是同一个。",
                "不同模型的预测和 SHAP 不能混在一起看，否则很容易把旧结论当成当前结论。",
                "先查看当前模型",
                "确认正在使用哪一个模型后，再继续看预测结果或 SHAP。",
            )
            actions = [{"label": "查看当前模型", "target": "machine_learning.current", "level": "navigate"}]
        elif formal_state in {"stale", "failed"}:
            reason = formal_reasons[0] if formal_reasons else "当前系统还没有可用的完整物理仿真结果。"
            add_step(
                "当前系统已经改过，或者上一次完整仿真没有成功。",
                reason + " 因此旧结果不能代表现在这套参数。",
                "重新做一次正式仿真",
                "先得到当前系统的完整物理结果，后面的参数研究和模型分析才有可靠的参照。",
            )
            actions = [{"label": "帮我准备正式仿真", "target": "simulation.formal", "level": "prepare"}]
        elif formal_state == "warning":
            add_step(
                "你已经有完整仿真结果，但数值检查发现了需要注意的问题。",
                "；".join(formal_reasons[:2]) or "当前计算需要先确认采样和边界是否足够。",
                "查看正式结果的检查信息",
                "先确认计算本身可靠，再继续做扫描或优化，避免后面建立在有问题的结果上。",
            )
            actions = [{"label": "查看正式结果", "target": "simulation.current", "level": "navigate"}]
        elif gate.level in {"poor", "weak", "ood", "unknown"} and str(page_id or "") in {"machine_learning", "explainability"}:
            r2 = gate.metrics.get("r2")
            if isinstance(r2, (int, float)):
                meaning = f"当前测试集 R²={float(r2):.3f}。这个数值说明模型现在还不能稳定预测新的参数组合，所以暂时不要根据它的 SHAP 结果调参数。"
            else:
                meaning = "当前还缺少足够的独立测试结果，暂时不能判断这个模型是否可靠。"
            add_step(
                "你现在正在检查机器学习模型是否足够准确。",
                meaning,
                "重新训练模型",
                "先把模型的独立测试表现提高，再看 SHAP，会比现在直接根据模型解释调参更稳妥。",
            )
            actions = [{"label": "帮我准备模型训练", "target": "machine_learning.training", "level": "prepare"}]
        elif scans:
            row = scans[-1]
            evidence = dict(row.get("evidence", {}) or {})
            name = str(row.get("display_name") or row.get("parameter") or "当前参数")
            best = evidence.get("best_value")
            metric = evidence.get("best_metric")
            unit = str(evidence.get("unit") or "")
            count = evidence.get("sample_count")
            observed = evidence.get("observed_range")
            sensitivity = str(evidence.get("sensitivity") or "")
            done = f"你刚完成了“{name}”的参数扫描"
            if isinstance(count, (int, float)):
                done += f"，共计算 {int(count)} 个点"
            done += "。"
            result_bits: list[str] = []
            if isinstance(best, (int, float)):
                result_bits.append(f"最佳位置约 {float(best):.4g}{(' ' + unit) if unit else ''}")
            if isinstance(metric, (int, float)):
                result_bits.append(f"对应结果约 {float(metric):.4g}")
            if isinstance(observed, (list, tuple)) and len(observed) >= 2:
                result_bits.append(f"表现较好的范围大约是 {float(observed[0]):.4g}～{float(observed[1]):.4g}{(' ' + unit) if unit else ''}")
            meaning = "；".join(result_bits) if result_bits else "扫描已经完成，可以从曲线看出最佳点和变化趋势"
            if sensitivity == "高":
                meaning += "。这个参数变化一点，结果就会变化得比较明显"
            meaning += "。"
            if isinstance(observed, (list, tuple)) and len(observed) >= 2:
                next_title = "在最佳范围附近再扫得细一点"
                why = "现在已经知道大致的好位置，缩小范围并增加计算点，可以更准确找到峰值。"
                action: dict[str, Any] = {"label": "帮我准备精细扫描", "target": "optimization.scan", "level": "prepare", "prefill_parameter": name}
                try:
                    low, high = sorted((float(observed[0]), float(observed[1])))
                except (TypeError, ValueError):
                    pass
                else:
                    if high > low:
                        action["prefill_range"] = [low, high]
                        action["prefill_points"] = 161
                actions = [action]
            elif not (optimizations or "优化" in task_text):
                next_title = "把这个参数加入优化"
                why = "你已经知道它大致怎样影响结果，可以再和其他关键参数一起寻找更好的组合。"
                actions = [{"label": "帮我准备参数优化", "target": "optimization.variables", "level": "prepare", "prefill_parameters": [name]}]
            else:
                next_title = "检查当前系统对装调误差是否敏感"
                why = "如果候选结果已经通过完整仿真，再检查位置、角度和间距误差，才能知道它实际装调时是否容易失效。"
                actions = [{"label": "查看容差设置", "target": "optimization.tolerance", "level": "navigate"}]
            add_step(done, meaning, next_title, why)
        elif shap and gate.usable_for_shap:
            name = str(shap[0].get("display_name") or shap[0].get("parameter") or "关键参数")
            add_step(
                "你已经得到 SHAP 解释，它是在说明机器学习模型认为哪些参数更重要。",
                f"目前“{name}”等参数影响比较明显，但这只是模型给出的解释，还不能当成已经证实的物理规律。",
                f"用完整仿真研究“{name}”",
                "直接改变这个参数并计算真实响应曲线，才能确认它到底怎样影响耦合结果。",
            )
            actions = [{"label": "研究这个参数", "target": "optimization.scan", "level": "prepare", "prefill_parameter": name}]
        elif (optimizations or "优化" in task_text) and not (tolerances or "容差" in task_text):
            add_step(
                "平台已经找到一个或多个候选结果。",
                "优化结果只是告诉你哪些参数组合值得优先检查，还不能说明它在实际装调误差下也稳定。",
                "检查系统稳定性",
                "模拟位置、角度和间距的小误差，可以看出这个高效率是不是只在非常理想的条件下才出现。",
            )
            actions = [{"label": "查看容差设置", "target": "optimization.tolerance", "level": "navigate"}]
        else:
            preview = dict(page.get("current_plot") or page.get("current_view_data") or {})
            labels = [str(v) for v in list(preview.get("labels", []) or []) if str(v).strip()]
            count = preview.get("sample_count")
            if str(page_id or "") == "optimization":
                text = "、".join(labels) if labels else "你选择的参数"
                add_step(
                    f"你已经选好本次要研究的内容：{text}。",
                    f"开始后，平台会按当前设置计算{f'约 {int(count)} 个点' if isinstance(count, (int, float)) else '一组采样点'}，结果会直接显示在中间的主图里。",
                    "确认设置并开始研究",
                    "第一次研究时先看清一个或两个参数的变化规律，比一开始同时改很多参数更容易理解。",
                )
                actions = [{"label": "查看研究设置", "target": "optimization.current", "level": "navigate"}]
            elif str(page_id or "") == "simulation":
                if formal_state == "good":
                    add_step(
                        "当前系统已经有可用的完整仿真结果。",
                        "这说明现在可以开始研究“哪个参数最影响结果”，而不必重复做同一套正式仿真。",
                        "选择一个参数做扫描",
                        "先从最关心的透镜间距或光纤位置开始，能比较直观看到参数改变后耦合效率怎么变。",
                    )
                    actions = [{"label": "去参数研究", "target": "optimization.scan", "level": "prepare"}]
                else:
                    add_step(
                        "你已经把当前光路参数设置好了。",
                        "还需要先得到一次完整物理仿真结果，才能知道这套参数现在的真实表现。",
                        "做一次正式仿真",
                        "这会成为后面参数研究和优化时的参照。",
                    )
                    actions = [{"label": "帮我准备正式仿真", "target": "simulation.formal", "level": "prepare"}]
            elif str(page_id or "") == "machine_learning":
                add_step(
                    "你现在在模型分析页面。",
                    "这里主要用来检查模型预测是否足够准确；只有模型可靠时，才适合继续看 SHAP。",
                    "先看预测效果",
                    "点越接近理想线，说明模型预测越接近完整仿真；上方 R² 和 RMSE 可以帮助判断整体表现。",
                )
                actions = [{"label": "查看预测效果", "target": "machine_learning.current", "level": "navigate"}]
            elif str(page_id or "") == "explainability":
                add_step(
                    "你现在在失配诊断页面。",
                    "这里会用 SHAP 帮你看哪些参数对模型预测影响最大，但前提是当前模型本身足够准确。",
                    "先查看主要因素",
                    "先看总体上是哪类失配最明显，再决定要不要继续看某个具体参数。",
                )
                actions = [{"label": "查看主要因素", "target": "explainability.current", "level": "navigate"}]
            elif str(page_id or "") == "teaching":
                add_step(
                    "你现在在教学中心的自由实验台。",
                    "这里用于把光束、相位、扫描曲线和失配线索可视化；教学环境不会影响当前系统。",
                    "继续一个可视化探索",
                    "从可操作的失配场景开始，比只读文字更容易建立物理直觉。",
                )
                actions = [{"label": "继续可视化探索", "target": "teaching.explore", "level": "navigate"}]
            elif str(page_id or "") == "tasks":
                add_step(
                    "你现在在任务中心。",
                    "这里显示后台任务的真实排队、运行、失败、取消和结果可用状态。",
                    "查看当前任务",
                    "先选中最新任务核对进度、阶段和结果是否真正可用。",
                )
                actions = [{"label": "查看当前任务", "target": "tasks.current", "level": "navigate"}]
            elif str(page_id or "") == "home":
                add_step(
                    "你现在在首页。",
                    "首页用于查看项目和最近工作；正式科研结果仍在对应研究页面中查看。",
                    "查看当前正式结果",
                    "直接进入仿真结果区，避免一个没有实际目标的首页按钮。",
                )
                actions = [{"label": "查看正式结果", "target": "simulation.current", "level": "navigate"}]
            else:
                add_step(
                    f"你现在在“{page_name}”。",
                    "当前页面没有发现需要立即处理的错误。",
                    "继续查看当前页面",
                    "当前没有可安全自动定位的进一步动作。",
                )
                actions = []

        warning = (
            f"还有 {len(stale)} 条旧系统状态结果。它们只保留作历史参考，不会用来判断当前系统。"
            if stale else
            "智能助手可以帮你找到位置并填好建议设置，但不会在你确认之前修改当前系统或开始耗时计算。"
        )
        stage = self.research_stage(page_id, project)
        summary = f"你现在在“{page_name}”{f'，正在看“{view_name}”' if view_name else ''}。当前阶段：{stage['label']}。我先说明你做到哪了，再给一个最值得做的下一步。"
        return {"status": "supported", "summary": summary, "findings": items[:3], "warnings": [warning], "actions": actions[:1], "confidence": "high" if formal_state == "good" else "medium"}

    def reliability(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        formal_state, formal_reasons = self._formal_state(project)
        gate = self.model_gate(project)
        evidence = self.evidence_summary(project)
        findings: list[dict[str, str]] = []

        if formal_state == "good":
            findings.append({"title": "完整仿真 · ✓ 当前可用", "explanation": "当前完整仿真没有发现已经检查到的数值异常。机器学习预测仍然只是辅助，不能和完整仿真混为一谈。"})
        elif formal_state == "missing":
            findings.append({"title": "完整仿真 · — 还没有结果", "explanation": formal_reasons[0]})
        else:
            findings.append({"title": "完整仿真 · ⚠ 需要检查", "explanation": "；".join(formal_reasons)})

        findings.append({"title": f"机器学习模型 · {gate.label}", "explanation": " ".join(gate.reasons)})
        findings.append({"title": "已有结果是否还是当前的", "explanation": f"当前可以直接参考 {evidence.current} 条，已经确认 {evidence.verified} 条，另有 {evidence.stale} 条来自旧系统状态、需要重新计算。旧结果不会混进现在的判断。"})

        warnings: list[str] = []
        context_errors = self._context_errors(project)
        if context_errors:
            warnings.append(f"智能助手有 {len(context_errors)} 项页面信息没有正常读到；下面的判断可能不完整。")
        if evidence.shap and not gate.usable_for_shap:
            warnings.append("虽然已经有 SHAP 结果，但当前模型还不够可靠。这些图可以先用来理解模型，但不要直接据此决定参数怎么调。")
        return {"status": "supported", "summary": "我会分别检查：完整仿真有没有问题、机器学习模型准不准、这些结果是不是针对当前这套参数。三项都对得上，结论才更值得相信。", "findings": findings, "warnings": warnings, "confidence": "high" if formal_state == "good" and gate.level in {"good", "medium", "missing"} else "medium"}

    @staticmethod
    def _beginner_plot_explanation(data: dict[str, Any]) -> str:
        kind = str(data.get("kind", "") or "")
        if kind == "research_preview":
            labels = [str(v) for v in list(data.get("labels", []) or []) if str(v).strip()]
            subject = "、".join(labels) or "当前参数"
            count = data.get("sample_count")
            suffix = f"，计划计算约 {int(count)} 个点" if isinstance(count, (int, float)) else ""
            return f"这还不是计算结果，只是在预览这次准备研究的范围。当前准备研究 {subject}{suffix}。开始研究后，同一位置会换成真实响应曲线。"
        if kind == "parameter_response":
            diagnostic, _phenomenon = ResearchAdvisor._curve_diagnostic_text(data)
            base = "横轴是正在改变的参数，纵轴是正式扫描得到的响应。先看峰位、峰高、3 dB 宽度和左右对称性，再讨论可能原因。"
            return base + (" " + diagnostic if diagnostic else "")
        if kind == "validation_scatter":
            return "横轴是完整仿真结果，纵轴是模型预测。每个点代表一个测试样本；点越靠近中间的理想线，模型预测越准确。"
        if kind == "residual":
            return "纵轴是“模型预测减去完整仿真”。点越靠近 0 越好；整体在 0 上方表示模型常常预测偏高，在下方表示常常预测偏低。"
        if kind == "beeswarm":
            return "每个点代表一个样本。横向位置表示这个参数把模型预测往高处还是低处推；同一行分布越宽，说明这个参数对不同样本的影响越明显。"
        if kind == "scatter_formula":
            return "这张图只看一个参数。横轴是参数取值，纵轴是它对模型预测的贡献；可以用来判断参数在什么取值附近更可能提高或降低预测结果。"
        if kind == "waterfall":
            return "这张图解释当前一次预测。每一项表示某个参数把模型预测往上推了多少或往下拉了多少，最后共同得到当前预测值。"
        if kind == "mismatch_budget":
            return "这张图把多个具体参数归到更容易理解的物理失配类别里，用来先判断主要问题属于位置、尺寸、角度还是焦面/曲率。"
        if kind in {"raytrace", "raytrace_section"}:
            return "这张图显示光线经过各个光学表面后的传播位置。主要用来看光束有没有明显偏离、过早聚焦或在接收面附近错过目标位置。"
        if kind in {"raytrace3d", "optical_scene_3d"}:
            return "这是当前光路的三维布局。它主要帮助确认器件顺序、空间位置和光束传播方向；定量判断仍要看正式仿真给出的效率和端面结果。"
        if kind == "beam_match":
            return "这张图比较接收面的入射光场和光纤目标模式。两者在位置、大小和形状上越接近，通常越有利于提高耦合效率。"
        if kind in {"heatmap", "heatmap_pair"}:
            return "颜色表示不同位置上的数值大小。先看高值区域在哪里、是否居中，再结合坐标范围判断光斑大小和偏移。"
        return "这张图已经接入当前研究状态。可以先看横纵轴分别代表什么，再观察最明显的峰值、偏移或趋势；如果你告诉我想判断什么，我可以继续按这张图解释。"

    def explain_current(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        page = dict(project.get("page_context", {}) or {})
        active = self._active_rows(project)
        gate = self.model_gate(project)
        items: list[dict[str, str]] = []
        current_plot = page.get("current_view_data") or page.get("current_plot") or page.get("shap_result")
        actions: list[dict[str, Any]] = []
        if current_plot and isinstance(current_plot, dict):
            current_plot = dict(current_plot)
            items.append({
                "title": f"这张图怎么看 · {page.get('current_view') or page.get('current_result_view') or '当前结果'}",
                "explanation": self._beginner_plot_explanation(current_plot),
            })
            if str(current_plot.get("kind", "")) == "parameter_response":
                diagnostic, phenomenon = self._curve_diagnostic_text(current_plot)
                if diagnostic:
                    items.append({"title": "从曲线先得到什么线索", "explanation": diagnostic})
                    actions = [{
                        "label": "看这个现象为什么",
                        "target": "teaching.phenomenon",
                        "level": "navigate",
                        "phenomenon": phenomenon or "curve_features",
                        "return_target": "optimization.scan",
                    }]
        for row in active[:3]:
            source = str(row.get("source") or "分析")
            if "SHAP" in source and not gate.usable_for_shap:
                continue
            name = str(row.get("display_name") or row.get("parameter") or "候选结果")
            evidence = dict(row.get("evidence", {}) or {})
            details: list[str] = []
            for key, label in (("best_value", "最佳值"), ("direction", "方向"), ("sensitivity", "敏感度"), ("shap_value", "贡献")):
                if key in evidence:
                    details.append(f"{label} {evidence[key]}")
            items.append({"title": f"{name} · {source}", "explanation": "；".join(details) if details else "这个结果仍然适用于当前系统，可以打开对应页面查看曲线和数值。"})
        if not items:
            items.append({"title": "现在还没有足够的结果可以解释", "explanation": "先完成一次完整仿真或参数研究。如果机器学习模型本身还不够准确，也不要只看 SHAP 就决定怎么调参数。"})
        warning = [] if gate.usable_for_shap or not any("SHAP" in str(row.get("source", "")) for row in active) else ["已自动跳过当前不可靠模型产生的 SHAP 解释。"]
        return {"status": "supported", "summary": f"你现在在“{page.get('page', page_id or '当前页面')}”。我先按当前这张图解释，再补充和当前系统仍然对应的结果。", "findings": items[:4], "warnings": warning, "actions": actions[:1], "confidence": "medium"}

    def main_issues(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        formal_state, formal_reasons = self._formal_state(project)
        gate = self.model_gate(project)
        stale = [row for row in self.findings(project) if self._status(row) == "需更新"]
        page = dict(project.get("page_context", {}) or {})
        issues: list[dict[str, str]] = []
        context_errors = self._context_errors(project)
        if context_errors:
            issues.append({"title": "智能助手读取页面状态时遇到问题", "explanation": f"有 {len(context_errors)} 项页面信息没有正常读到。最近一项：{context_errors[-1]}。我会降低判断把握，不会把缺失信息当成正常结果。"})
        if formal_state in {"stale", "failed", "warning", "missing"}:
            issues.append({"title": "完整物理仿真结果", "explanation": "；".join(formal_reasons)})
        if gate.level in {"poor", "weak", "ood", "unknown"}:
            issues.append({"title": "模型是否足够准确", "explanation": " ".join(gate.reasons)})
        model_consistent, consistency_issues = self.model_consistency(project)
        if not model_consistent:
            issues.append({"title": "模型版本不一致", "explanation": " ".join(consistency_issues[:3])})
        if stale:
            reasons = [str(row.get("stale_reason", "")) for row in stale if row.get("stale_reason")]
            detail = f"有 {len(stale)} 条旧结果已经不适用于当前系统。" + (f" 最近原因：{reasons[-1]}。" if reasons else "")
            issues.append({"title": "有旧结果需要重新计算", "explanation": detail})
        if "边界" in str(page.get("status", "")) or "边界" in str(page.get("activity", "")):
            issues.append({"title": "搜索范围", "explanation": "当前结果提示最佳点可能贴近搜索边界，需要先扩大/重新定义范围，而不是直接接受边界点。"})
        if not issues:
            issues.append({"title": "暂时没有必须先处理的问题", "explanation": "当前没有发现会妨碍下一步的问题。你可以继续研究关键参数；如果已经有候选结果，再检查装调误差对结果的影响。"})
        return {"status": "supported", "summary": "下面按最需要先处理的顺序列出当前问题，并说明它为什么会影响下一步。", "findings": issues[:4], "warnings": [], "confidence": "high" if issues and issues[0]["title"] != "暂时没有必须先处理的问题" else "medium"}

    def research_summary(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        evidence = self.evidence_summary(project)
        gate = self.model_gate(project)
        formal_state, formal_reasons = self._formal_state(project)
        page = dict(project.get("page_context", {}) or {})
        context = dict(project.get("research_context", {}) or {})
        tasks = self.completed_results(project)
        items = [
            {"title": "当前工作", "explanation": f"{context.get('current_task') or page.get('page') or '当前研究'}；当前系统版本 {project.get('design_revision', '—')}；当前视图 {page.get('current_view') or page.get('current_result_view') or '—'}。"},
            {"title": "物理结果", "explanation": "正式结果状态：" + ({"good":"✓ 当前", "missing":"— 尚无", "stale":"⚠ 需更新", "failed":"× 未收敛", "warning":"⚠ 有数值诊断"}.get(formal_state, formal_state)) + ("；" + "；".join(formal_reasons[:2]) if formal_reasons else "")},
            {"title": "模型和已有结果", "explanation": f"模型：{gate.label}；当前可用结果 {evidence.current} 条，已确认结果 {evidence.verified} 条，旧结果 {evidence.stale} 条；另外读到了 {len(tasks)} 个已完成任务的结果。"},
        ]
        context_errors = self._context_errors(project)
        warnings = [f"智能助手有 {len(context_errors)} 项页面信息没有正常读到，因此下面的判断会更保守。"] if context_errors else []
        return {"status": "supported", "summary": "这是当前项目的简要状态。旧系统状态得到的结果会单独标出来，不会混进当前判断。", "findings": items, "warnings": warnings, "confidence": "medium" if context_errors else "high"}

    def stale_evidence(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        stale = [row for row in self.findings(project) if self._status(row) == "需更新"]
        if not stale:
            return {"status": "supported", "summary": "当前没有发现需要重新计算的旧结果。", "findings": [], "warnings": [], "confidence": "high"}
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in stale:
            groups.setdefault(str(row.get("source") or "其他分析"), []).append(row)
        items = []
        for source, rows in groups.items():
            names = "、".join(str(row.get("display_name") or row.get("parameter") or "结果") for row in rows[:3])
            reason = next((str(row.get("stale_reason")) for row in reversed(rows) if row.get("stale_reason")), "当前物理系统已经变化")
            items.append({"title": f"{source} · {len(rows)} 条", "explanation": f"{names}。失效原因：{reason}。"})
        return {"status": "supported", "summary": f"共有 {len(stale)} 条旧结果已经不适用于当前系统；它们可以留作对比，但不要再用来指导当前参数。", "findings": items[:5], "warnings": [], "confidence": "high"}

    def evidence_chain(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        evidence = self.evidence_summary(project)
        active = self._active_rows(project)
        items: list[dict[str, str]] = []
        formal_state, _ = self._formal_state(project)
        if formal_state != "missing":
            formal_label = {"good": "✓ 当前可用", "stale": "⚠ 需更新", "failed": "× 未收敛", "warning": "⚠ 有数值诊断"}.get(formal_state, formal_state)
            items.append({"title": "完整物理仿真", "explanation": f"当前正式结果状态：{formal_label}。这是判断当前系统的主要计算依据。"})
        for token, title in (("扫描", "参数扫描"), ("容差", "装调误差检查"), ("优化", "优化结果"), ("SHAP", "SHAP解释")):
            rows = [row for row in active if token in str(row.get("source", ""))]
            if rows:
                names = "、".join(str(row.get("display_name") or row.get("parameter") or "结果") for row in rows[:3])
                items.append({"title": title, "explanation": f"{len(rows)} 条：{names}。"})
        if not items:
            items.append({"title": "还没有足够的结果", "explanation": "当前还没有完整物理仿真或其他可以直接参考的分析结果。"})
        warning = [f"另有 {evidence.stale} 条旧结果只作历史参考。"] if evidence.stale else []
        return {"status": "supported", "summary": "我会区分完整物理仿真、参数扫描、优化和模型解释，不会把机器学习的判断直接当成物理结论。", "findings": items[:5], "warnings": warning, "confidence": "high"}

    def model_reliability(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        gate = self.model_gate(project)
        metrics = gate.metrics
        details = []
        for key, label in (("r2", "R²"), ("rmse", "RMSE"), ("mae", "MAE"), ("high_efficiency_rmse", "高效率区RMSE"), ("high_efficiency_mae", "高效率区MAE")):
            if key in metrics:
                details.append(f"{label}={metrics[key]:.4g}")
        findings = [
            {"title": gate.label, "explanation": " ".join(gate.reasons)},
            {"title": "已读取指标", "explanation": "，".join(details) if details else "当前模型没有暴露足够的独立测试指标。"},
            {"title": "现在适合怎么用", "explanation": ("可以用来初步筛选候选结果" if gate.usable_for_guidance else "暂时不要用它直接挑选候选结果") + "；" + ("可以参考SHAP解释" if gate.usable_for_shap else "现在不要根据SHAP直接调参数") + "；最终设计仍要用完整物理仿真确认。"},
        ]
        return {"status": "supported", "summary": "判断模型能不能继续用，主要看它在独立测试中的误差，以及当前参数有没有超出它学过的范围。", "findings": findings, "warnings": [], "confidence": "high" if gate.level != "unknown" else "medium"}

    def decision_readiness(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        formal_state, formal_reasons = self._formal_state(project)
        gate = self.model_gate(project)
        evidence = self.evidence_summary(project)
        blockers: list[str] = []
        cautions: list[str] = []
        if formal_state != "good":
            blockers.extend(formal_reasons or ["正式物理结果尚未达到当前可用状态。"])
        # 代理模型只是辅助证据。模型缺失或表现差时直接排除机器学习结论，
        # 不能反过来否定已经通过数值诊断的正式物理结果。
        if gate.level in {"poor", "ood", "unknown", "weak"} and self._model_record(project):
            cautions.append("当前不会用机器学习结果来确认最终设计：" + " ".join(gate.reasons))
        if evidence.stale:
            cautions.append(f"另有 {evidence.stale} 条旧结果已经不适用于当前系统，不会用来确认最终设计。")
        active = self._active_rows(project)
        formally_verified_candidates = [
            row for row in active
            if "优化" in str(row.get("source", "")) and bool(dict(row.get("evidence", {}) or {}).get("verified"))
        ]
        findings: list[dict[str, str]] = []
        if blockers:
            findings.append({"title": "现在还不适合确认最终设计", "explanation": "；".join(blockers[:3])})
        else:
            findings.append({"title": "当前完整仿真可以作为主要依据", "explanation": "完整仿真结果与当前系统一致，目前没有发现必须先处理的旧结果问题。"})
        if formally_verified_candidates:
            findings.append({"title": "已有经过完整仿真检查的候选结果", "explanation": f"检测到 {len(formally_verified_candidates)} 个已经过完整仿真检查的优化结果，可以继续比较装调误差和实际限制。"})
        else:
            findings.append({"title": "候选结果还需要完整仿真确认", "explanation": "预测排名或优化结果只是候选。至少还要做一次完整物理仿真，确认结果后再检查装调误差会不会让性能明显下降。"})
        return {"status": "supported", "summary": "一个预测值很高，并不代表最终设计已经可以确定；我会把候选结果和真正确认过的结果分开。", "findings": findings, "warnings": cautions, "confidence": "high" if not blockers else "medium"}

    @classmethod
    def _direction_polarity(cls, value: str) -> int | None:
        text = cls._normalize(value)
        positive = ("增加", "上升", "提高", "正向", "正相关", "变大", "增大", "促进", "提升")
        negative = ("降低", "下降", "减小", "负向", "负相关", "变小", "抑制", "减少")
        neutral = ("不明显", "无明显", "基本不变", "平坦", "弱影响", "不敏感")
        if any(token in text for token in neutral):
            return 0
        pos = any(token in text for token in positive)
        neg = any(token in text for token in negative)
        if pos and not neg:
            return 1
        if neg and not pos:
            return -1
        return None

    def evidence_conflicts(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        rows = self._active_rows(project)
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            key = str(row.get("parameter") or row.get("display_name") or "").strip()
            if key:
                groups.setdefault(key, []).append(row)
        conflicts: list[dict[str, str]] = []
        for name, items in groups.items():
            directions: list[tuple[str, str]] = []
            for row in items:
                evidence = dict(row.get("evidence", {}) or {})
                direction = str(evidence.get("direction") or evidence.get("trend") or "").strip()
                if direction:
                    directions.append((str(row.get("source") or "分析"), direction))
            polarities = {polarity for _, direction in directions if (polarity := self._direction_polarity(direction)) is not None}
            if len(polarities) > 1:
                detail = "；".join(f"{source}: {direction}" for source, direction in directions[:4])
                conflicts.append({"title": f"{name} · 方向不一致", "explanation": detail + "。优先用正式参数扫描/正式仿真复核，模型解释不自动覆盖物理结果。"})
        if not conflicts:
            return {"status": "supported", "summary": "目前没有发现同一个参数在不同结果里出现明显相反的变化方向。", "findings": [], "warnings": ["这只表示目前记录下来的变化方向没有明显矛盾，不代表所有结果完全一致。"], "confidence": "medium"}
        return {"status": "supported", "summary": f"发现 {len(conflicts)} 组结果可能互相矛盾。", "findings": conflicts[:5], "warnings": ["出现矛盾时，优先相信完整物理仿真和正式参数扫描；机器学习和SHAP只作辅助参考。"], "confidence": "high"}

    def parameter_evidence(self, question: str, project: dict[str, Any]) -> dict[str, Any] | None:
        text = self._normalize(question)
        matches: list[dict[str, Any]] = []
        for row in self.findings(project):
            names = [str(row.get("display_name") or ""), str(row.get("parameter") or "")]
            if any(len(self._normalize(name)) >= 2 and self._normalize(name) in text for name in names if name):
                matches.append(row)
        if not matches:
            return None
        current = [row for row in matches if self._status(row) in self._STATUS_CURRENT]
        stale = [row for row in matches if self._status(row) == "需更新"]
        gate = self.model_gate(project)
        findings: list[dict[str, str]] = []
        for row in current[:5]:
            source = str(row.get("source") or "分析")
            if "SHAP" in source and not gate.usable_for_shap:
                continue
            name = str(row.get("display_name") or row.get("parameter") or "参数")
            evidence = dict(row.get("evidence", {}) or {})
            detail = self._result_excerpt(evidence) or self._result_excerpt(row)
            findings.append({"title": f"{name} · {source} · {self._status(row)}", "explanation": detail or "该结果仍对应当前系统。"})
        warnings: list[str] = []
        if stale:
            warnings.append(f"另有 {len(stale)} 条匹配结果属于旧系统状态，已自动排除出当前结论。")
        if not gate.usable_for_shap and any("SHAP" in str(row.get("source", "")) for row in current):
            warnings.append("找到了这个参数的SHAP结果，但当前模型还不够可靠，所以没有把SHAP作为调参依据。")
        if not findings:
            findings.append({"title": "现在还没有可以直接采用的当前结果", "explanation": "找到的结果要么来自旧系统状态，要么依赖的模型现在还不够可靠。"})
        return {"status": "supported", "summary": "我已经把和这个参数有关、仍适用于当前系统的结果找出来了。", "findings": findings, "warnings": warnings, "confidence": "high" if findings and current else "medium"}

    def parameter_priorities(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        gate = self.model_gate(project)
        active = self._active_rows(project)
        ranked: list[tuple[int, dict[str, Any]]] = []
        for row in active:
            source = str(row.get("source") or "")
            if "SHAP" in source and not gate.usable_for_shap:
                continue
            priority = 0
            if "扫描" in source:
                priority = 40
            elif "容差" in source:
                priority = 35
            elif "优化" in source:
                priority = 25
            elif "SHAP" in source:
                priority = 15
            if priority:
                evidence = dict(row.get("evidence", {}) or {})
                # Sensitivity/contribution magnitudes refine order within the same evidence class.
                for key in ("sensitivity", "sobol", "contribution", "shap_value"):
                    value = self._finite_number(evidence.get(key))
                    if value is not None:
                        priority += min(9, int(abs(value) * 10))
                        break
                ranked.append((priority, row))
        ranked.sort(key=lambda item: item[0], reverse=True)
        seen: set[str] = set()
        findings: list[dict[str, str]] = []
        for _, row in ranked:
            name = str(row.get("display_name") or row.get("parameter") or "参数")
            key = self._normalize(name)
            if key in seen:
                continue
            seen.add(key)
            source = str(row.get("source") or "分析")
            evidence = dict(row.get("evidence", {}) or {})
            detail = self._result_excerpt(evidence) or "当前系统已经有这个参数的相关结果。"
            findings.append({"title": f"{name} · {source}", "explanation": detail + "。如加入优化，范围仍应由你确认，智能助手不会自动改写变量。"})
            if len(findings) >= 5:
                break
        warnings: list[str] = []
        if not gate.usable_for_shap and any("SHAP" in str(row.get("source", "")) for row in active):
            warnings.append("当前模型还不够可靠，所以参数排序没有使用SHAP结果。")
        if not findings:
            findings.append({"title": "暂时没有足够的当前结果", "explanation": "建议先挑少量有明确物理意义的参数做正式扫描，看清变化规律后再决定是否放进优化。"})
        return {"status": "supported", "summary": "下面按当前已有结果排出优先研究的参数。我只给建议，不会自动替你修改优化变量。", "findings": findings, "warnings": warnings, "confidence": "high" if len(findings) > 1 else "medium"}

    def research_journal_answer(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        rows = [dict(row) for row in list(project.get("research_journal", []) or []) if isinstance(row, dict)]
        current_revision = int(project.get("design_revision", 0) or 0)
        if not rows:
            return {"status": "supported", "summary": "目前还没有形成可追溯的研究记录。", "findings": [], "warnings": ["聊天记录不是研究证据；完成正式仿真、研究任务或采用模型后，平台会把关键事件写入研究记录。"], "confidence": "high"}
        items: list[dict[str, str]] = []
        for row in rows[-8:][::-1]:
            revision = int(row.get("design_revision", 0) or 0)
            state = "当前系统" if revision == current_revision else f"系统 Rev.{revision}"
            details = dict(row.get("details", {}) or {})
            bits = []
            for key, value in details.items():
                if isinstance(value, (str, int, float, bool)):
                    bits.append(f"{key}={value}")
                elif isinstance(value, dict):
                    compact = ", ".join(f"{k}={v}" for k, v in value.items() if isinstance(v, (str, int, float, bool)))
                    if compact:
                        bits.append(compact)
                if len(bits) >= 3:
                    break
            explanation = f"{row.get('time', '')} · {state} · {row.get('source', '平台')}"
            if bits:
                explanation += " · " + "；".join(bits)
            items.append({"title": str(row.get("title") or row.get("kind") or "研究记录"), "explanation": explanation})
        return {
            "status": "supported",
            "summary": "下面是平台记录的关键研究事件，不依赖聊天记忆；旧系统状态记录会保留版本号，不能自动当作当前结论。",
            "findings": items,
            "warnings": [],
            "confidence": "high",
        }

    def capabilities(self, page_id: str | None, project: dict[str, Any]) -> dict[str, Any]:
        page = dict(project.get("page_context", {}) or {})
        evidence = self.evidence_summary(project)
        return {
            "status": "supported",
            "summary": "智能助手会告诉你现在做到哪一步、结果是什么意思，并带你找到下一步要操作的位置；不会未经确认就修改当前系统或开始计算。",
            "findings": [
                {"title": "读当前状态", "explanation": f"当前页面是 {page.get('page') or page_id or '未指定'}；我可以读取当前系统版本、完整仿真结果、正在看的图、模型指标和已经完成的任务结果。"},
                {"title": "做可靠性判断", "explanation": "我会检查完整仿真有没有数值问题、模型预测是否足够准确、当前参数有没有超出模型学过的范围，以及页面里的结果是不是来自旧系统状态。"},
                {"title": "解释与规划", "explanation": f"当前可以直接参考的结果有 {evidence.current} 条，已经确认的结果有 {evidence.verified} 条，需要重新计算的旧结果有 {evidence.stale} 条。我可以解释主要问题、结果之间是否矛盾，以及下一步先做什么。"},
                {"title": "权限边界", "explanation": "我可以带你去对应页面并帮你填好设置，但修改当前系统、采用候选结果和开始耗时计算仍由你确认。"},
            ],
            "warnings": [],
            "confidence": "high",
        }


__all__ = ["ResearchAdvisor", "ModelGate", "EvidenceSummary"]

"""Explainability document tabs.

The shell owns navigation and orchestration; this module owns the explainability document surfaces.
"""

from __future__ import annotations

from frontend_pyside.modules import shared as _shared

# Shared Qt imports and helper functions remain in the neutral tab-shared
# module during this compatibility-preserving extraction.
globals().update(
    {
        name: value
        for name, value in vars(_shared).items()
        if not name.startswith("__")
    }
)

class AnalysisTextDocument(QWidget):
    shapRanksReady = Signal(object)

    def __init__(self, kind: str, selected: str = "", parent=None, context=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.selected = selected
        self.context = context
        self._dataset_cache: dict[str, dict[str, Any]] = {}
        self._current_cache: dict[str, dict[str, Any]] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        title, subtitle = _kind_titles("explainability", kind)
        del subtitle
        self.model = QComboBox()
        self.compute = _primary_button("计算解释")
        self.compute.clicked.connect(self._compute)
        self.feature_caption = QLabel(self._parameter_caption())
        self.scope_note = QLabel()
        self.scope_note.setObjectName("HelperText")
        self.scope_note.setWordWrap(True)
        if kind == "global_contrib":
            root.addWidget(_action_row(QLabel("解释模型"), self.model, self.compute))
            message = "选择已训练模型后计算，这里显示该模型全部训练特征在数据集上的平均 |SHAP|。"
            self.scope_note.setText("说明：全局贡献图按模型 manifest 的全部特征计算；左栏勾选项只用于优化，不会过滤 SHAP。")
        elif kind == "param_trend":
            root.addWidget(_action_row(QLabel("解释模型"), self.model, self.feature_caption, self.compute))
            message = "在左栏点一个参数后计算，这里显示该量取值与 SHAP 贡献。"
            self.scope_note.setText("说明：单参数依赖图只显示左栏当前选中的参数。")
        else:
            root.addWidget(_action_row(QLabel("解释模型"), self.model, self.compute))
            message = "计算后把当前镜头当作一条样本，用瀑布图拆开各参数贡献。"
            self.scope_note.setText("说明：当前系统图使用当前镜头组的实时参数，并按模型训练特征顺序解释。")
        root.addWidget(self.scope_note)
        self.workspace = LazyResultWorkspace(self)
        self.workspace.set_single_view_only(True)
        self.workspace.set_toolbar_visible(False)
        self.workspace.set_pane_header_visible(False)
        root.addWidget(self.workspace, 1)
        self.analysis_text = QLabel()
        self.analysis_text.setObjectName("HelperText")
        self.analysis_text.setWordWrap(True)
        self.analysis_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.analysis_text.hide()
        root.addWidget(self.analysis_text)
        # Formulas belong to the interpretation of a selected SHAP factor, not
        # to the teaching bench.  Keep this card below the conclusion so the
        # graph stays primary while the causal relation remains inspectable.
        self.formula_text = QLabel()
        self.formula_text.setObjectName("ExplainFormulaCard")
        self.formula_text.setWordWrap(True)
        self.formula_text.setTextFormat(Qt.TextFormat.RichText)
        self.formula_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.formula_text.hide()
        root.addWidget(self.formula_text)
        self.model.currentIndexChanged.connect(lambda _index: self._sync_compute_enabled())
        self._show(title, message)
        self._sync_compute_enabled()

    def set_explain_cache(self, dataset_cache: dict[str, dict[str, Any]], current_cache: dict[str, dict[str, Any]]) -> None:
        self._dataset_cache = dataset_cache
        self._current_cache = current_cache

    def set_trained_models(self, models: list[dict[str, Any]]) -> None:
        previous = self.model.currentData()
        previous_id = str((previous or {}).get("id") or "") if isinstance(previous, dict) else ""
        self.model.blockSignals(True)
        self.model.clear()
        for item in models:
            record = dict(item)
            self.model.addItem(str(record.get("title") or record.get("id") or "模型"), record)
        self.model.blockSignals(False)
        if previous_id:
            for index in range(self.model.count()):
                data = self.model.itemData(index)
                if isinstance(data, dict) and str(data.get("id") or "") == previous_id:
                    self.model.setCurrentIndex(index)
                    break
        self._sync_compute_enabled()

    def set_selected(self, key: str) -> None:
        self.selected = str(key or "")
        self.feature_caption.setText(self._parameter_caption())
        self._sync_compute_enabled()

    def set_model(self, title: str) -> None:
        text = str(title or "")
        if not text:
            return
        index = self.model.findText(text)
        if index >= 0:
            self.model.setCurrentIndex(index)
        self._sync_compute_enabled()

    def _parameter_caption(self) -> str:
        if self.kind != "param_trend":
            return ""
        if not self.selected:
            return "未选择参数"
        return display_feature_name(self.selected)

    def _current_record(self) -> dict[str, Any]:
        data = self.model.currentData()
        return dict(data) if isinstance(data, dict) else {}

    def _heading(self) -> str:
        return {
            "global_contrib": "全局贡献图",
            "param_trend": "单参数依赖图",
            "current_system": "当前系统瀑布图",
        }.get(self.kind, "解释图")

    def _sync_compute_enabled(self) -> None:
        record = self._current_record()
        model_id = str(record.get("id") or "")
        family = str(record.get("family") or record.get("model_type") or "")
        enabled = bool(model_id)
        reason = ""
        if not model_id:
            reason = "请先在模型页训练，再选择该模型。"
            enabled = False
        elif not shap_supported(family):
            reason = "这一版不算 SHAP"
            enabled = False
        elif self.kind == "param_trend" and not self.selected:
            reason = "请先在左栏选择一个参数。"
            enabled = False
        self.compute.setEnabled(enabled)
        self.compute.setToolTip(reason)
        if not enabled and reason and self.model.count() == 0:
            self._show(self._heading(), reason)

    def _compute(self) -> None:
        heading = self._heading()
        record = self._current_record()
        model_id = str(record.get("id") or "")
        family = str(record.get("family") or record.get("model_type") or "")
        if not model_id:
            self._show(heading, "请先在模型页训练，再选择该模型。")
            return
        if not shap_supported(family):
            self._show(heading, "这一版不算 SHAP")
            return
        if self.kind == "param_trend" and not self.selected:
            self._show(heading, "请先在左栏选择一个参数。")
            return
        cache = self._current_cache if self.kind == "current_system" else self._dataset_cache
        cached = dict(cache.get(model_id) or {})
        if cached:
            self._render_shap(cached)
            return
        api = getattr(self.context, "api_client", None) if self.context is not None else None
        if api is None:
            self._show(heading, "后端不可用（无 API 连接）")
            return
        from uuid import uuid4

        from frontend_pyside.infrastructure.api.clients import TrainingClient

        payload: dict[str, Any] = {"top_k": 8, "max_samples": 80, "background_sample_count": 80}
        design_paths = [str(path) for path in list(record.get("design_variable_paths") or []) if str(path)]
        if design_paths:
            payload["display_feature_paths"] = design_paths
        if self.kind == "current_system":
            project = getattr(getattr(self.context, "project", None), "project", None)
            try:
                payload["features"] = model_features(project, record)
            except FeaturePathError as exc:
                self._show(heading, f"当前镜头无法构造模型特征：{exc}")
                return
        self._token = f"workbench.explain.{uuid4().hex[:8]}"
        self._show(heading, "正在计算解释…")
        if not getattr(self, "_api_bound", False):
            api.completed.connect(self._on_explain_completed)
            api.failed.connect(self._on_explain_failed)
            self._api_bound = True
        self._failure_text = explain_shap_failure
        TrainingClient(api).explain_shap(self._token, model_id, payload)

    def _on_explain_completed(self, key: str, data: object) -> None:
        if str(key) != getattr(self, "_token", ""):
            return
        body = dict(data or {}) if isinstance(data, dict) else {}
        if isinstance(body.get("result"), dict) and not body.get("top_features"):
            body = dict(body.get("result") or {})
        record = self._current_record()
        model_id = str(record.get("id") or "")
        if model_id:
            cache = self._current_cache if self.kind == "current_system" else self._dataset_cache
            cache[model_id] = body
        self._render_shap(body)

    def _on_explain_failed(self, key: str, message: str) -> None:
        if str(key) != getattr(self, "_token", ""):
            return
        self._show(self._heading(), explain_shap_failure(message))

    def _render_shap(self, body: dict[str, Any]) -> None:
        from frontend_pyside.shared.feature_labels import display_feature_name as label_of
        from frontend_pyside.features.explainability.actions import (
            formula_binding_for_feature,
            formula_latex,
            physical_mechanism_for_feature,
            suggested_action_for_feature,
        )
        from frontend_pyside.features.explainability.formula_presentation import formula_html

        target_name = str(body.get("target_name") or "模型输出")
        target_unit = str(body.get("target_unit") or "").strip()
        target_label = f"{target_name}（{target_unit}）" if target_unit else target_name
        run_id = str(body.get("explanation_run_id") or "")
        hidden_count = int(body.get("hidden_feature_count") or 0)

        def feature_label(value: object) -> str:
            key = str(value or "")
            return "其他模型特征（合并）" if key == "__other_model_features__" else label_of(key)

        def show_analysis(feature: str, importance: float, direction: str, *, verified: bool = False) -> None:
            if not feature:
                self.analysis_text.hide()
                self.formula_text.hide()
                return
            name = feature_label(feature)
            mechanism = physical_mechanism_for_feature(feature)
            action = suggested_action_for_feature(feature)
            parts = [
                f"模型分析：{name}是当前结果中的主要影响变量，贡献幅度为 {importance:.4g}{(' ' + target_unit) if target_unit else ''}。",
                f"物理联系：{mechanism}",
            ]
            if direction:
                parts.append(f"趋势判断：{direction}")
            parts.append(f"下一步：{action}，并用正式光学计算复核。")
            parts.append("验证状态：已关联当前正式仿真。" if verified else "验证状态：模型推断，尚未经过本次正式仿真验证。")
            if hidden_count:
                parts.append(f"说明：模型还使用了 {hidden_count} 个内部物理特征；主排行仅展示可调整设计变量，局部图将其合并为“其他模型特征”。")
            if run_id:
                parts.append(f"解释任务：{run_id}")
            self.analysis_text.setText("\n".join(parts))
            self.analysis_text.show()
            category, item, level, note = formula_binding_for_feature(feature)
            if category and item:
                relation = formula_html(category, item, formula_latex(category, item))
                self.formula_text.setText(
                    f"<b>物理公式：{category} · {item}</b>{relation}"
                    f"<div style='padding:0 8px 8px; color:#465467;'>"
                    f"关联方式：{level}。{note}<br>"
                    "说明：公式描述物理传播关系；SHAP 仅用于模型贡献排序，结论须由正式仿真验证。"
                    "</div>"
                )
                self.formula_text.show()
            else:
                self.formula_text.hide()

        if self.kind == "param_trend":
            item = shap_dependence_item(body, self.selected)
            if not item:
                for feature, data in dict(body.get("shap_dependence") or {}).items():
                    if _shap_feature_key(str(feature), [self.selected]) == self.selected:
                        item = dict(data)
                        break
            xs = list(item.get("feature_value") or item.get("x") or [])
            ys = list(item.get("shap_value") or item.get("y") or [])
            if not xs or not ys:
                self._show("单参数依赖图", "这次解释没有返回该参数的 SHAP 依赖。")
                return
            self.workspace.set_result(
                0,
                "单参数依赖图",
                {
                    "kind": "scatter",
                    "x": xs,
                    "y": ys,
                    "x_label": label_of(self.selected),
                    "y_label": f"SHAP 贡献 · {target_label}",
                    "zero_line": True,
                },
            )
            direction = "样本范围内未形成稳定方向。"
            if len(xs) >= 2:
                delta = float(ys[-1]) - float(ys[0])
                if abs(delta) > 1.0e-12:
                    direction = "变量增大时模型输出总体上升。" if delta > 0 else "变量增大时模型输出总体下降。"
            show_analysis(self.selected, max((abs(float(value)) for value in ys), default=0.0), direction)
            return
        if self.kind == "current_system":
            targets = list(body.get("targets") or [])
            sample = {}
            if targets:
                rows = list(targets[0].get("sample_shap_values") or [])
                sample = dict(rows[0]) if rows else {}
            values = sample.get("shap_values") or sample.get("values") or {}
            if not isinstance(values, dict) or not values:
                contrib = list(body.get("feature_contributions") or body.get("top_features") or [])
                labels = [label_of(item.get("feature")) for item in contrib]
                shap_values = [float(item.get("shap_value", item.get("mean_shap", 0.0)) or 0.0) for item in contrib]
            else:
                labels = [label_of(name) for name in values]
                shap_values = [float(values[name] or 0.0) for name in values]
            if not labels:
                self._show("当前系统瀑布图", "这次解释没有返回当前样本的贡献。")
                return
            additivity_error = sample.get("additivity_error", body.get("additivity_error"))
            prediction = sample.get("prediction")
            if additivity_error is not None:
                tolerance = 1.0e-6 * max(1.0, abs(float(prediction or 0.0)))
                if abs(float(additivity_error)) > tolerance:
                    self._show(
                        "当前系统瀑布图",
                        f"SHAP贡献无法闭合当前预测（加性误差 {float(additivity_error):.4g}），已停止绘图。",
                    )
                    self.analysis_text.setText("解释结果无效：基准值与各变量贡献之和不等于模型预测值。")
                    self.analysis_text.show()
                    return
            self.workspace.set_result(
                0,
                "当前系统瀑布图",
                {
                    "kind": "waterfall",
                    "labels": [feature_label(label) for label in (values.keys() if isinstance(values, dict) and values else labels)],
                    "values": shap_values,
                    "base_value": float((body.get("base_values") or {}).get(str(body.get("target_name") or ""), 0.0) or 0.0),
                    "summary": f"目标：{target_label}",
                },
            )
            top_index = max(range(len(shap_values)), key=lambda index: abs(shap_values[index]))
            raw_features = list(values.keys()) if isinstance(values, dict) and values else labels
            top_feature = str(raw_features[top_index])
            if top_feature == "__other_model_features__":
                self.analysis_text.setText(
                    "模型分析：当前样本主要受内部物理特征的合并贡献影响。\n"
                    "物理联系：这些量由设计变量和正式光学计算共同产生，不能当作可直接调整参数。\n"
                    "下一步：返回全局贡献或单参数规律，选择曲率半径、厚度或圆锥系数进行验证。\n"
                    "验证状态：模型推断，尚未经过本次正式仿真验证。"
                )
                self.analysis_text.show()
                self.formula_text.hide()
            else:
                formal_result = getattr(getattr(self.context, "project", None), "formal_result", None)
                show_analysis(
                    top_feature,
                    abs(shap_values[top_index]),
                    "该变量在当前样本中提高模型输出。" if shap_values[top_index] >= 0 else "该变量在当前样本中降低模型输出。",
                    verified=isinstance(formal_result, dict) and bool(formal_result),
                )
            return
        items = list(body.get("top_features") or body.get("feature_contributions") or body.get("global_importance") or [])
        if not items:
            self._show("全局贡献图", "这次解释没有返回全局贡献。")
            return
        labels = [feature_label(item.get("feature") or item.get("name")) for item in items]
        values = [float(item.get("mean_abs_shap", abs(float(item.get("mean_shap", 0.0) or 0.0))) or 0.0) for item in items]
        self.workspace.set_result(
            0,
            "全局贡献图",
            {
                "kind": "barh",
                "labels": labels,
                "values": values,
                "show_values": True,
                "source": "模型解释",
                "x_label": f"平均 |SHAP| · {target_label}",
                "description": "数值越大表示模型越依赖该设计变量；不等同于物理因果。",
            },
        )
        top = dict(items[0])
        feature = str(top.get("feature") or top.get("name") or "")
        signed = float(top.get("mean_shap", top.get("mean_signed_shap", 0.0)) or 0.0)
        share = float(top.get("relative_importance", 0.0) or 0.0)
        direction = (
            "不同样本中的正负影响可能抵消，请在单参数规律中判断趋势。"
            if abs(signed) < 1.0e-12
            else ("平均上使模型输出提高。" if signed > 0 else "平均上使模型输出降低。")
        )
        if share > 0.0:
            direction += f" 在当前展示变量中的相对重要性为 {share * 100.0:.1f}%。"
        show_analysis(feature, values[0], direction)
        project = getattr(getattr(self.context, "project", None), "project", None) if self.context is not None else None
        keys = [row[0] for row in _variable_rows(project)] if project is not None else []
        self.shapRanksReady.emit(_variable_shap_scores(items, keys))

    def _show(self, title: str, message: str) -> None:
        self.workspace.set_result(0, title, {"kind": "empty", "message": message})
        self.analysis_text.hide()
        self.formula_text.hide()


__all__ = ["AnalysisTextDocument"]

from __future__ import annotations

from copy import deepcopy

from frontend_pyside.shared.display_names import (
    metric_label, readable_dataset_name, readable_model_name,
)


def _friendly_shap_error(message: object) -> str:
    text = str(message or "").strip()
    low = text.lower()
    mappings = (
        (("dependency", "not available", "failed to initialise", "shap_backend_not_configured"), "SHAP 运行库不可用或初始化失败，请安装 requirements/requirements.txt 中的依赖后重启后端。"),
        (("dataset does not match", "shap_dataset_model_mismatch"), "当前数据集不是该模型的训练数据集，已重新选择兼容数据集后可再次分析。"),
        (("model feature schema", "feature_schema", "schema mismatch"), "模型特征结构与数据集不一致，请选择该模型训练时使用的数据集。"),
        (("model preprocessing", "preprocessing"), "模型预处理无法处理当前数据，请重新训练模型或检查数据集完整性。"),
        (("dataset", "not found"), "找不到模型对应的训练数据集，请重新生成数据集并训练模型。"),
        (("computation failed", "shap_computation_failed"), "SHAP 计算失败，请检查模型文件是否完整；随机森林模型可直接重新训练后再试。"),
    )
    for tokens, friendly in mappings:
        if any(token in low for token in tokens):
            return friendly
    return text or "SHAP 分析失败，请在任务日志中查看详细原因。"


class ExplainabilityApiMixin:
    def _refresh_selectors(self, force: bool = False) -> None:

        registry = self.context.registry
        self._registry_datasets_changed(registry.datasets)
        self._registry_models_changed(registry.models)
        if registry.should_refresh("models", force=force):
            token = self.lifecycle.generations.next("explain-models-list")
            self.training_client.list_models(f"explain.models.list.{token}")
        if registry.should_refresh("datasets", force=force):
            token = self.lifecycle.generations.next("explain-datasets-list")
            self.dataset_client.list_datasets(f"explain.datasets.list.{token}")

    @staticmethod
    def _record_id(record: dict, kind: str) -> str:
        key = "dataset_id" if kind == "dataset" else "model_id"
        return str(record.get(key, record.get("id", "")) or "")

    def _api_completed(self, key: str, data) -> None:
        if key.startswith("explain.models.list."):
            token = int(key.rsplit(".", 1)[-1])
            if self.lifecycle.generations.is_current(token, "explain-models-list"):
                records = data.get("models", data.get("items", data)) if isinstance(data, dict) else data
                self.context.registry.set_models(
                    [item for item in (records or []) if isinstance(item, dict)]
                )
        elif key.startswith("explain.datasets.list."):
            token = int(key.rsplit(".", 1)[-1])
            if self.lifecycle.generations.is_current(token, "explain-datasets-list"):
                records = data.get("items", data) if isinstance(data, dict) else data
                self.context.registry.set_datasets(
                    [item for item in (records or []) if isinstance(item, dict)]
                )
        elif key.startswith("explain.shap."):
            parsed = self._parse_explain_key(key)
            if parsed is None:
                return
            token, model_id = parsed
            if not self.lifecycle.generations.is_current(token, "explain-shap"):
                return
            targets = list(data.get("targets", []) or []) if isinstance(data, dict) else []
            has_target_explanation = any(
                isinstance(target, dict)
                and any(
                    target.get(field)
                    for field in (
                        "top_features",
                        "feature_contributions",
                        "global_importance",
                        "sample_shap_values",
                    )
                )
                for target in targets
            )
            has_explanation = isinstance(data, dict) and (
                any(
                    data.get(field)
                    for field in ("top_features", "feature_contributions", "global_importance")
                )
                or has_target_explanation
            )
            if has_explanation:
                self._pending_shap_meta[token] = model_id
                self._shap_preparer.submit(
                    "explain-shap",
                    token,
                    lambda payload=deepcopy(data): self._prepare_shap_payload(payload),
                )
            else:
                self._set_explain_button_state("重新计算解释", enabled=True)
                self._set_info(
                    self.shap_status_info,
                    "当前状态",
                    "没有可用的SHAP结果",
                )

    def _registry_models_changed(self, records: list[dict]) -> None:
        selected = str(self.model.currentData() or self.context.registry.current_model_id)
        model_records = [dict(item) for item in records if isinstance(item, dict)]
        self.model.blockSignals(True)
        self.model.clear()
        for index, record in enumerate(model_records):
            model_id = self._record_id(record, "model")
            name = readable_model_name(record, index, aliases=getattr(self, "registry_aliases", None))
            self.model.addItem(name, model_id)
        if not model_records:
            self.model.addItem("无可用模型", "")
        index = self.model.findData(selected)
        self.model.setCurrentIndex(index if index >= 0 else 0)
        self.model.blockSignals(False)
        self._sync_model_selection()

    def _registry_datasets_changed(self, records: list[dict]) -> None:
        selected = str(self.dataset.currentData() or self.context.registry.current_dataset_id)
        dataset_records = [dict(item) for item in records if isinstance(item, dict)]
        self.dataset.blockSignals(True)
        self.dataset.clear()
        for index, record in enumerate(dataset_records):
            dataset_id = self._record_id(record, "dataset")
            name = readable_dataset_name(record, index, aliases=getattr(self, "registry_aliases", None))
            self.dataset.addItem(name, dataset_id)
        if not dataset_records:
            self.dataset.addItem("无可用数据集", "")
        index = self.dataset.findData(selected)
        self.dataset.setCurrentIndex(index if index >= 0 else 0)
        self.dataset.blockSignals(False)
        self._sync_model_selection()

    def _select_dataset_id(self, dataset_id: str) -> None:
        index = self.dataset.findData(str(dataset_id or ""))
        if index >= 0:
            self.dataset.setCurrentIndex(index)

    def _select_model_id(self, model_id: str) -> None:
        index = self.model.findData(str(model_id or ""))
        if index >= 0:
            self.model.setCurrentIndex(index)

    def _set_explain_button_state(self, text: str, *, enabled: bool) -> None:
        for name in ("shap_start_btn", "explain_btn"):
            button = getattr(self, name, None)
            if button is not None:
                button.setText(str(text))
                button.setEnabled(bool(enabled))

    def _selected_model_record(self) -> dict:
        model_id = str(self.model.currentData() or "")
        return next(
            (
                item
                for item in self.context.registry.models
                if self._record_id(item, "model") == model_id
            ),
            {},
        )

    def _sync_model_selection(self, *_args) -> None:
        record = self._selected_model_record()
        target_names = list(record.get("target_names", []) or [])
        current_target = str(self.output.currentData() or self.output.currentText() or "")
        self.output.blockSignals(True)
        self.output.clear()
        for target_name in target_names:
            self.output.addItem(metric_label(target_name), str(target_name))
        if not target_names:
            self.output.addItem("无输出契约", "")
        target_index = self.output.findData(current_target)
        self.output.setCurrentIndex(target_index if target_index >= 0 else 0)
        self.output.blockSignals(False)

        model_id = self._record_id(record, "model") if record else ""
        model_dataset_id = str(record.get("dataset_id", ""))
        preferred_dataset = model_dataset_id or self.context.registry.current_dataset_id
        if preferred_dataset:
            index = self.dataset.findData(preferred_dataset)
            if index >= 0:
                self.dataset.setCurrentIndex(index)
        self._refresh_context_summary()

    def _set_shap_ready_message(self, title: str, message: str, *, show_prepare: bool) -> None:
        card = getattr(self, "shap_empty_card", None)
        if card is not None and getattr(card, "title_label", None) is not None:
            card.title_label.setText(str(title))
        hint = getattr(self, "shap_empty_hint", None)
        if hint is not None:
            hint.setText(str(message))
        button = getattr(self, "shap_prepare_button", None)
        if button is not None:
            button.setVisible(bool(show_prepare))

        # Keep the main explanation area in the same place before and after the
        # calculation.  A selected model means this view is generatable, so show
        # one truthful preview slot instead of leaving the lower half of the page
        # blank.  The remaining views appear only after real SHAP data exists.
        model_id = str(self.model.currentData() or "") if hasattr(self, "model") else ""
        has_result = bool(getattr(self, "_feature_records", []) or [])
        view_card = getattr(self, "shap_view_card", None)
        tabs = getattr(self, "shap_view_tabs", None)
        if view_card is not None and not has_result:
            view_card.setVisible(bool(model_id))
        if tabs is not None and not has_result:
            tabs.setTabVisible(0, bool(model_id))
            tabs.setTabVisible(1, False)
            tabs.setTabVisible(2, False)
            tabs.setTabVisible(3, False)
            if model_id:
                tabs.setCurrentIndex(0)

    def _refresh_context_summary(self, *_args) -> None:
        dataset_id = str(self.dataset.currentData() or "")
        model_id = str(self.model.currentData() or "")
        if dataset_id:
            self.context.registry.set_current_dataset(dataset_id)
        adopted = str(getattr(self.context.registry, "current_model_id", "") or "")
        record = self._selected_model_record()
        r2 = None
        for block_name in ("test_metrics", "evaluation", "metrics", "validation_metrics"):
            block = record.get(block_name)
            if not isinstance(block, dict):
                continue
            for key in ("r2", "test_r2", "R2"):
                if isinstance(block.get(key), (int, float)):
                    r2 = float(block[key]); break
            if r2 is not None: break
        if not model_id:
            self._set_explain_button_state("先准备模型", enabled=False)
            self._set_shap_ready_message(
                "还没有可以分析的模型",
                "先去模型分析准备数据并训练一个模型。模型有了测试结果以后，再回来查看哪些参数最重要、它们在当前系统里起什么作用。",
                show_prepare=True,
            )
        elif model_id and adopted and model_id != adopted:
            self._set_explain_button_state("先确认当前模型", enabled=False)
            self._set_shap_ready_message(
                "先确认要分析哪个模型",
                "你选中的模型和项目现在使用的模型不是同一个。先去模型分析确认要使用哪一个，再回来查看这些参数为什么重要。",
                show_prepare=True,
            )
        elif r2 is None:
            self._set_explain_button_state("先看看也可以", enabled=bool(model_id))
            self._set_shap_ready_message(
                "还不能判断模型够不够准",
                "这个模型还没有独立测试结果。可以先看看 SHAP 图了解模型在关注什么，但暂时不要据此修改参数。",
                show_prepare=True,
            )
        elif r2 < 0.60:
            self._set_explain_button_state("先看看也可以", enabled=bool(model_id))
            self._set_shap_ready_message(
                "模型预测还不够准",
                f"独立测试 R²={r2:.3f}。可以先用 SHAP 了解模型，但不建议据此修改参数或确定最终设计。先改进模型会更稳妥。",
                show_prepare=True,
            )
        else:
            self._set_explain_button_state("开始分析", enabled=bool(model_id))
            self._set_shap_ready_message(
                "可以开始分析",
                f"当前模型的独立测试 R²={r2:.3f}。可以开始查看主要因素、当前系统、整体规律和单参数规律。",
                show_prepare=False,
            )

    def _request_explain(self) -> None:
        model_id = str(self.model.currentData() or "")
        dataset_id = str(self.dataset.currentData() or "")
        target_name = str(self.output.currentData() or self.output.currentText() or "")
        record = self._selected_model_record()
        if not model_id:
            self._set_info(self.shap_status_info, "当前状态", "没有可解释的真实模型")
            return
        adopted = str(getattr(self.context.registry, "current_model_id", "") or "")
        if adopted and model_id != adopted:
            self._set_info(self.shap_status_info, "当前状态", "当前选择的模型不是项目正在使用的模型。请先去模型分析确认要使用的模型。")
            return
        model_dataset_id = str(record.get("dataset_id", "") or "")
        if model_dataset_id and dataset_id != model_dataset_id:
            compatible_index = self.dataset.findData(model_dataset_id)
            if compatible_index >= 0:
                self.dataset.setCurrentIndex(compatible_index)
                dataset_id = model_dataset_id
            else:
                self._set_info(
                    self.shap_status_info,
                    "当前状态",
                    "该模型对应的训练数据集不存在，请重新生成数据集并训练模型。",
                )
                return
        if not dataset_id:
            self._set_info(self.shap_status_info, "当前状态", "请选择已注册的真实数据集")
            return
        if not list(record.get("feature_paths", []) or []):
            self._set_info(self.shap_status_info, "当前状态", "当前模型缺少特征结构，无法进行 SHAP 分析")
            return
        self._set_explain_button_state("计算中…", enabled=False)
        payload = {
            "dataset_id": dataset_id,
            "target_name": target_name or None,
            "top_k": self.shap_topn.value(),
            "max_samples": 60,
            "background_sample_count": min(self.shap_background.value(), 100),
            "random_seed": 42,
        }
        token = self.lifecycle.generations.next("explain-shap")
        self.shap_client.explain(f"explain.shap.{token}.{model_id}", model_id, payload)
        self._set_info(self.shap_status_info, "当前状态", "正在使用真实注册数据集计算 SHAP")

    @staticmethod
    def _parse_explain_key(key: str) -> tuple[int, str] | None:
        prefix = "explain.shap."
        if not key.startswith(prefix):
            return None
        token_text, separator, model_id = key[len(prefix):].partition(".")
        if not separator:
            return None
        try:
            return int(token_text), model_id
        except ValueError:
            return None

    @staticmethod
    def _prepare_shap_payload(data: dict) -> dict:
        payload = dict(data or {})
        for field in ("top_features", "feature_contributions", "global_importance"):
            records = [dict(item) for item in payload.get(field, []) if isinstance(item, dict)]
            records.sort(
                key=lambda item: abs(float(item.get("mean_abs_shap", item.get("shap_value", 0.0)) or 0.0)),
                reverse=True,
            )
            payload[field] = records
        targets = [dict(item) for item in payload.get("targets", []) if isinstance(item, dict)]
        for target in targets:
            for field in ("top_features", "feature_contributions", "global_importance"):
                records = [dict(item) for item in target.get(field, []) if isinstance(item, dict)]
                records.sort(
                    key=lambda item: abs(
                        float(item.get("mean_abs_shap", item.get("shap_value", 0.0)) or 0.0)
                    ),
                    reverse=True,
                )
                target[field] = records
            rows = [dict(row) for row in target.get("sample_shap_values", []) if isinstance(row, dict)]
            target["sample_shap_values"] = rows[:400]
        payload["targets"] = targets
        return payload

    def _shap_prepared(self, channel: str, token: int, payload: object) -> None:
        if channel != "explain-shap" or not self.lifecycle.generations.is_current(token, "explain-shap"):
            return
        model_id = self._pending_shap_meta.pop(token, None)
        data = dict(payload or {})
        record = self._selected_model_record()
        for block_name in ("test_metrics", "evaluation", "metrics", "validation_metrics"):
            block = record.get(block_name)
            if not isinstance(block, dict):
                continue
            for key in ("r2", "test_r2", "R2"):
                if isinstance(block.get(key), (int, float)):
                    data.setdefault("model_test_r2", float(block[key]))
                    break
            if "model_test_r2" in data:
                break
        self._shap_data = data
        self._shap_available = True
        self._set_explain_button_state("重新计算解释", enabled=True)
        source = "注册训练数据集" if not bool(data.get("synthetic_samples", False)) else "兼容性示例数据"
        self._set_info(self.shap_source_info, "数据来源", source)
        self._set_info(
            self.shap_status_info,
            "当前状态",
            f"分析完成：{int(data.get('sample_count', 0) or 0)} 个样本 · {data.get('explainer', 'SHAP')}",
        )
        # SHAP 向共享上下文发布结构化证据。只记录“模型观察到什么”，不自动把参数加入优化或缩小范围。
        try:
            top_features = [dict(item) for item in data.get("top_features", []) if isinstance(item, dict)]
            if not top_features:
                targets = [dict(item) for item in data.get("targets", []) if isinstance(item, dict)]
                if targets:
                    top_features = [dict(item) for item in targets[0].get("top_features", []) if isinstance(item, dict)]
            self.context.project.update_research_context(
                current_task="SHAP分析",
                current_model=str(model_id or ""),
                current_dataset=str(data.get("dataset_id", "")),
            )
            for item in top_features[:3]:
                name = str(item.get("name") or item.get("feature") or "")
                if not name:
                    continue
                signed = float(item.get("mean_shap", item.get("shap_value", 0.0)) or 0.0)
                direction = str(item.get("direction") or ("正向" if signed > 0 else "负向" if signed < 0 else "中性"))
                self.context.project.publish_finding(
                    source="SHAP",
                    parameter=name,
                    display_name=name,
                    scope="当前模型/数据集",
                    evidence={
                        "mean_abs_shap": float(item.get("mean_abs_shap", abs(signed)) or 0.0),
                        "mean_shap": signed,
                        "direction": direction,
                        "sample_count": int(data.get("sample_count", 0) or 0),
                        "model_id": str(model_id or ""),
                    },
                    status="当前",
                )
        except Exception:
            pass
        if bool(getattr(self, "_page_active", True)):
            self._update_shap_from_api(data)
        else:
            self._pending_shap_payload = data

    def _shap_prepare_failed(self, channel: str, token: int, message: str) -> None:
        if channel != "explain-shap" or not self.lifecycle.generations.is_current(token, "explain-shap"):
            return
        self._pending_shap_meta.pop(token, None)
        self._set_explain_button_state("重新计算解释", enabled=True)
        self._set_info(self.shap_status_info, "当前状态", f"SHAP 数据准备失败：{_friendly_shap_error(message)}")

    def _api_failed(self, key: str, message: str) -> None:
        if key.startswith("explain.models.list."):
            self.context.registry.refresh_failed("models")
            return
        if key.startswith("explain.datasets.list."):
            self.context.registry.refresh_failed("datasets")
            return
        if key.startswith("explain.shap."):
            parsed = self._parse_explain_key(key)
            if parsed and self.lifecycle.generations.is_current(parsed[0], "explain-shap"):
                self._set_explain_button_state("重新计算解释", enabled=True)
                self._set_info(self.shap_status_info, "当前状态", f"SHAP 请求失败：{_friendly_shap_error(message)}")

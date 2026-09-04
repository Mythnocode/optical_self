from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QThreadPool

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.machine_learning.dataset_configuration import build_dataset_parameters
from frontend_pyside.infrastructure.workers.worker import FunctionWorker
from shared_contracts.metrics import canonical_metric_name
from frontend_pyside.shared.display_names import (
    metric_label, model_type_label, readable_dataset_name, readable_model_name,
)


class MachineLearningApiMixin:
    @staticmethod
    def _dataset_status_text(value: object) -> str:
        text = str(value or "未知")
        return {
            "queued": "等待后端",
            "running": "运行中",
            "completed": "已完成",
            "failed": "失败",
            "cancelled": "已取消",
            "ready": "可用",
        }.get(text.lower(), text)

    @staticmethod
    def _short_datetime(value: object) -> str:
        text = str(value or "—").replace("T", " ")
        return text[:16]

    @staticmethod
    def _friendly_model_name(record: dict, index: int = 0) -> str:
        return readable_model_name(record, index)

    def _current_dataset_project_payload(self) -> dict:

        shared = getattr(self.context.project, "simulation_project_payload", {})
        if isinstance(shared, dict) and shared.get("surfaces"):
            return dict(shared)
        return serialize_project(self.context.project.project)


    @staticmethod
    def _record_id(record: dict, kind: str) -> str:
        key = "dataset_id" if kind == "dataset" else "model_id"
        return str(record.get(key, record.get("id", "")) or "")

    @staticmethod
    def _parse_generation_key(key: str, prefix: str) -> tuple[int, str] | None:
        marker = f"{prefix}."
        if not key.startswith(marker):
            return None
        suffix = key[len(marker):]
        token_text, separator, identifier = suffix.partition(".")
        if not separator:
            return None
        try:
            return int(token_text), identifier
        except ValueError:
            return None

    def refresh_remote(self, force: bool = False) -> None:
        registry = self.context.registry
        if registry.datasets and (hasattr(self, "datasets_table") or hasattr(self, "training_dataset")):
            self._set_datasets({"items": registry.datasets}, publish=False)
        if registry.models and hasattr(self, "models_table"):
            self._set_models({"models": registry.models}, publish=False)
        if registry.should_refresh("datasets", force=force):
            token = self.lifecycle.generations.next("ml-datasets-list")
            self.dataset_client.list_datasets(f"ml.datasets.list.{token}")
        if registry.should_refresh("models", force=force):
            token = self.lifecycle.generations.next("ml-models-list")
            self.training_client.list_models(f"ml.models.list.{token}")

    def _submit_dataset(self) -> None:
        precision = {
            "129×129": "preview",
            "257×257": "standard",
            "513×513": "high",
            # 兼容旧界面保存值。
            "预览": "preview", "标准": "standard", "高精度": "high",
        }.get(self.dataset_precision.currentText(), "standard")
        target = canonical_metric_name(
            {
                "耦合损耗(dB)": "coupling_loss_db",
                "耦合效率": "coupling_efficiency",
                "RMS 光斑": "rms_spot_radius_um",
                "Strehl": "strehl_estimate_marechal",
            }[self.dataset_target.currentText()]
        )
        project_payload = self._current_dataset_project_payload()
        parameters = build_dataset_parameters(project_payload)
        if not parameters:
            self._set_info(
                self.dataset_status,
                "任务状态",
                "当前项目没有可采样的曲率或空气间隔参数",
            )
            return
        validation = self.validation_split.value()
        test = min(0.15, max(0.05, validation))
        train = 1.0 - validation - test
        payload = {
            "dataset_name": f"frontend-{uuid4().hex[:8]}",
            "base_project": project_payload,
            "parameters": parameters,
            "targets": [target],
            "sample_count": self.dataset_count.value(),
            "sampling_method": "latin_hypercube" if self.sampling.currentIndex() == 0 else "sobol",
            "train_ratio": train,
            "validation_ratio": validation,
            "test_ratio": test,
            "random_seed": self.dataset_seed.value(),
            "precision": precision,
        }
        if hasattr(self, "dataset_progress"):
            # 提交请求期间尚未收到可量化的后台工作量，不伪造百分比。
            self.dataset_progress.setRange(0, 0)
            self.dataset_progress.setFormat("正在提交后台…")
        self.dataset_client.submit("ml.dataset.submit", payload)
        self._set_info(self.dataset_status, "任务状态", "正在提交数据集任务")

    def _submit_training(self) -> None:
        dataset_id = self.training_dataset.currentData() or self.training_dataset.currentText()
        if not dataset_id:
            self._set_info(self.training_status, "任务状态", "请先刷新并选择数据集")
            if hasattr(self, "training_submit_button"):
                self.training_submit_button.set_task_state("error", "请先选择数据集")
                from PySide6.QtCore import QTimer
                QTimer.singleShot(1400, lambda: self.training_submit_button.reset_task_state("开始训练"))
            return
        model_type = str(self.model_type.currentData() or "random_forest")
        hyperparameters = {"n_estimators": self.training_epochs.value()}
        if model_type == "xgboost_physics_residual" and bool(self.training_early_stop.isChecked()):
            hyperparameters["early_stopping_rounds"] = int(self.training_patience.value())
        payload = {
            "dataset_id": str(dataset_id),
            "model_type": model_type,
            "target_names": [],
            "hyperparameters": hyperparameters,
            "random_seed": self.training_seed.value(),
        }
        token = self.lifecycle.generations.next("ml-training-preflight")
        self._pending_training[f"{token}:{dataset_id}"] = payload
        if hasattr(self, "training_progress"):
            self.training_progress.setRange(0, 0)
            self.training_progress.setFormat("正在检查数据…")
        if hasattr(self, "training_submit_button"):
            self.training_submit_button.set_task_state("submitted", "正在检查数据")
        self.headless_client.download_manifest(
            f"ml.training.preflight.{token}.{dataset_id}", str(dataset_id)
        )
        self._set_info(self.training_status, "任务状态", "正在检查数据集有效样本")

    def _api_completed(self, key: str, body: object) -> None:
        data = body if isinstance(body, dict) else {}
        if key.startswith("ml.datasets.list."):
            token = int(key.rsplit(".", 1)[-1])
            if self.lifecycle.generations.is_current(token, "ml-datasets-list"):
                self._set_datasets(data)
        elif key.startswith("ml.models.list."):
            token = int(key.rsplit(".", 1)[-1])
            if self.lifecycle.generations.is_current(token, "ml-models-list"):
                self._set_models(data)
        elif key in {"ml.dataset.submit", "ml.training.submit"}:
            job_id = str(data.get("job_id", ""))
            kind = "dataset" if key == "ml.dataset.submit" else "training"
            if not job_id:
                self._api_failed(key, "响应缺少 job_id")
                return
            task = self.context.tasks.add(
                "后端生成数据集" if kind == "dataset" else "后端训练代理模型",
                "机器学习",
                "等待后端",
                0,
                f"job_id: {job_id}",
                page="machine_learning",
                job_id=job_id,
            )
            self._jobs[job_id] = {
                "kind": kind,
                "task_id": str(task["id"]),
                "result_requested": False,
            }
            if kind == "dataset":
                tracker = getattr(self, "_dataset_progress_tracker", None)
                if tracker is not None:
                    tracker.reset(job_id)
                self._active_dataset_job_id = job_id
                if hasattr(self, "dataset_progress"):
                    self.dataset_progress.setRange(0, 100)
                    self.dataset_progress.setValue(0)
                    self.dataset_progress.setFormat("等待后台进度 · 0%")
            elif kind == "training":
                tracker = getattr(self, "_training_progress_tracker", None)
                if tracker is not None:
                    tracker.reset(job_id)
                self._active_training_job_id = job_id
                if hasattr(self, "training_progress"):
                    self.training_progress.setRange(0, 100)
                    self.training_progress.setValue(0)
                    self.training_progress.setFormat("等待后台进度 · 0%")
            self.job_watcher.subscribe(job_id)
            if not self._centralized_polling:
                self._poll_timer.start()
            self._set_job_status(kind, f"已提交 job {job_id}")
        elif key.startswith("ml.status."):
            self._handle_status(key.rsplit(".", 1)[-1], data)
        elif key.startswith("ml.result."):
            self._handle_result_response(key, data)
        elif key.startswith("ml.dataset.detail."):
            parsed = self._parse_generation_key(key, "ml.dataset.detail")
            if parsed is not None:
                token, dataset_id = parsed
                if self.lifecycle.generations.is_current(token, "ml-dataset-detail"):
                    self._show_dataset_detail(data, expected_dataset_id=dataset_id)
        elif key == "ml.coupling.submit":
            job_id = str(data.get("job_id", ""))
            self._set_info(
                self.coupling_status,
                "耦合任务",
                f"已提交: {job_id[:12]}" if job_id else "后端未返回 job_id",
            )
        elif key.startswith("ml.predict."):
            parsed = self._parse_generation_key(key, "ml.predict")
            if parsed is None:
                return
            token, model_id = parsed
            if not self.lifecycle.generations.is_current(token, "ml-predict"):
                return
            predictions = data.get("predictions", {}) if isinstance(data, dict) else {}
            if predictions:
                summary = "，".join(f"{metric_label(name)}={value:.4g}" for name, value in predictions.items())
                self._set_info(self.pred_result_label, "预测结果", summary)
                if hasattr(self, "prediction_button"):
                    self.prediction_button.set_task_state("success", "预测完成")
                if hasattr(self, "prediction_progress_panel"):
                    self.prediction_progress.setRange(0, 100)
                    self.prediction_progress.setValue(100)
                    self.prediction_progress_label.setText("预测完成 · 可解释预测或进行正式仿真验证")
            else:
                self._set_info(self.pred_result_label, "预测结果", f"后端返回空结果: {model_id[:12]}")
                if hasattr(self, "prediction_button"):
                    self.prediction_button.set_task_state("error", "预测无结果")
                if hasattr(self, "prediction_progress_panel"):
                    self.prediction_progress.setRange(0, 100)
                    self.prediction_progress.setValue(0)
                    self.prediction_progress_label.setText("代理模型未返回预测值")

    def _api_failed(self, key: str, message: str) -> None:
        if not key.startswith("ml."):
            return
        if key.startswith("ml.training.preflight."):
            suffix = key.removeprefix("ml.training.preflight.")
            token_text, _, dataset_id = suffix.partition(".")
            pending_key = f"{token_text}:{dataset_id}"
            self._pending_training.pop(pending_key, None)
            try:
                token = int(token_text)
            except ValueError:
                token = -1
            if self.lifecycle.generations.is_current(token, "ml-training-preflight"):
                if hasattr(self, "training_progress"):
                    self.training_progress.setRange(0, 100)
                    self.training_progress.setValue(0)
                    self.training_progress.setFormat("检查失败")
                self._set_info(self.training_status, "任务状态", f"无法检查数据集：{message}")
                if hasattr(self, "training_submit_button"):
                    self.training_submit_button.set_task_state("error", "检查失败")
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(1400, lambda: self.training_submit_button.reset_task_state("开始训练"))
        elif key.startswith("ml.status."):
            self._finish_job(key.rsplit(".", 1)[-1], "失败", message)
        elif key.startswith("ml.result."):
            self._handle_result_failure(key, message)
        elif key.startswith("ml.datasets.list."):
            self.context.registry.refresh_failed("datasets")
            if hasattr(self, "dataset_status"):
                self._set_info(self.dataset_status, "任务状态", f"不能读取数据集：{message}")
        elif key.startswith("ml.models.list."):
            self.context.registry.refresh_failed("models")
            if hasattr(self, "model_detail"):
                self._set_info(self.model_detail, "模型列表", f"读取失败：{message}")
        elif key.startswith("ml.predict."):
            parsed = self._parse_generation_key(key, "ml.predict")
            if parsed and self.lifecycle.generations.is_current(parsed[0], "ml-predict"):
                self._set_info(self.pred_result_label, "预测结果", f"请求失败：{message}")
                if hasattr(self, "prediction_button"):
                    self.prediction_button.set_task_state("error", "预测失败")
                if hasattr(self, "prediction_progress_panel"):
                    self.prediction_progress.setRange(0, 100)
                    self.prediction_progress.setValue(0)
                    self.prediction_progress_label.setText(f"预测失败：{message}")
                    self.prediction_progress_panel.show()
        elif key == "ml.coupling.submit":
            self._set_info(self.coupling_status, "耦合任务", f"提交失败：{message}")
        else:
            self._set_job_status("dataset" if "dataset" in key else "training", f"请求失败：{message}")

    def _set_datasets(self, data: object, *, publish: bool = True) -> None:
        records = data.get("items", data) if isinstance(data, dict) else data
        dataset_records = [item for item in (records or []) if isinstance(item, dict)]
        if publish:
            self.context.registry.set_datasets(dataset_records)

        current_id = self.context.registry.current_dataset_id
        datasets_table = getattr(self, "datasets_table", None)
        training_dataset = getattr(self, "training_dataset", None)
        if training_dataset is not None:
            training_dataset.blockSignals(True)
            training_dataset.clear()

        rows: list[list[object]] = []
        tooltips: list[list[str]] = []
        total = 0
        known_feature_counts: list[int] = []
        known_target_counts: list[int] = []
        selected_row = -1
        for row, item in enumerate(dataset_records):
            dataset_id = self._record_id(item, "dataset")
            samples = int(item.get("sample_count", 0) or 0)
            features = item.get("feature_names") or item.get("feature_paths")
            targets = item.get("target_names") or (
                [item.get("target_column")] if item.get("target_column") else None
            )
            feature_display = len(features) if isinstance(features, (list, tuple)) else "—"
            target_display = "、".join(metric_label(value) for value in targets) if isinstance(targets, (list, tuple)) else "—"
            if isinstance(features, (list, tuple)):
                known_feature_counts.append(len(features))
            if isinstance(targets, (list, tuple)):
                known_target_counts.append(len(targets))
            total += samples
            name = readable_dataset_name(item, row, aliases=getattr(self, "registry_aliases", None))
            if training_dataset is not None:
                training_dataset.addItem(f"{name} · {samples} 样本", dataset_id)
            values = [
                name,
                samples,
                target_display,
                self._dataset_status_text(item.get("status", "未知")),
                self._short_datetime(item.get("created_at", "")),
                dataset_id,
            ]
            rows.append(values)
            tooltips.append([
                f"{name}\nID: {dataset_id}",
                f"{samples} 条样本",
                f"目标：{target_display}；特征数：{feature_display}",
                str(values[3]),
                str(item.get("created_at", "—")),
                dataset_id,
            ])
            if dataset_id == current_id:
                selected_row = row

        if datasets_table is not None:
            datasets_table.set_rows(
                rows,
                tooltips=tooltips,
                align_columns=(1, 3, 4),
            )
        if training_dataset is not None:
            training_dataset.blockSignals(False)
            if current_id:
                index = training_dataset.findData(current_id)
                if index >= 0:
                    training_dataset.setCurrentIndex(index)
        if hasattr(self, "dataset_summary_label"):
            self.dataset_summary_label.setText(f"{len(dataset_records)}个数据集 · {total}条样本")
        if datasets_table is not None:
            if selected_row >= 0:
                datasets_table.selectRow(selected_row)
            elif dataset_records:
                datasets_table.selectRow(0)
                self._load_dataset_detail(0)

    def _set_models(self, data: object, *, publish: bool = True) -> None:
        records = data.get("models", data.get("items", data)) if isinstance(data, dict) else data
        model_records = [item for item in (records or []) if isinstance(item, dict)]
        if publish:
            self.context.registry.set_models(model_records)
        models_table = getattr(self, "models_table", None)
        if models_table is None:
            return
        rows: list[list[object]] = []
        tooltips: list[list[str]] = []
        selected_row = -1
        current_id = self.context.registry.current_model_id
        for row, item in enumerate(model_records):
            # Model selection and SHAP reliability are based on the independent
            # test set.  Show the same metrics here so the list never appears to
            # contradict the current-model summary.  Fall back to validation only
            # for older model records that do not yet contain test metrics.
            metrics = item.get("test_metrics", {})
            metrics = metrics if isinstance(metrics, dict) else {}
            metric_source = "独立测试"
            if not metrics:
                metrics = item.get("validation_metrics", {})
                metrics = metrics if isinstance(metrics, dict) else {}
                metric_source = "验证集"
            model_id = self._record_id(item, "model")
            values = [
                readable_model_name(item, row, aliases=getattr(self, "registry_aliases", None)),
                model_type_label(item.get("model_type", "")),
                readable_dataset_name(
                    next((dataset for dataset in self.context.registry.datasets if self._record_id(dataset, "dataset") == str(item.get("dataset_id", ""))), {"dataset_id": item.get("dataset_id", "")}),
                    aliases=getattr(self, "registry_aliases", None),
                ),
                metrics.get("r2", metrics.get("R2", "—")),
                metrics.get("mae", "—"),
                metrics.get("rmse", "—"),
                self._short_datetime(item.get("created_at", "")),
                model_id,
            ]
            rows.append(values)
            tooltips.append([
                f"{values[0]}\nID: {model_id}",
                str(values[1]),
                f"训练数据集：{values[2]}",
                f"{metric_source} R²={values[3]}",
                f"{metric_source} MAE={values[4]}",
                f"{metric_source} RMSE={values[5]}",
                str(item.get("created_at", "—")),
                model_id,
            ])
            if model_id == current_id:
                selected_row = row
        models_table.set_rows(
            rows,
            tooltips=tooltips,
            align_columns=(1, 3, 4, 5, 6),
        )
        if model_records:
            selected_row = selected_row if selected_row >= 0 else 0
            models_table.selectRow(selected_row)
            self._on_model_selected(selected_row)

    def _load_dataset_detail(self, row: int, *_args) -> None:
        datasets = self.context.registry.datasets
        if not 0 <= row < len(datasets):
            return
        dataset_id = self._record_id(datasets[row], "dataset")
        self.context.registry.set_current_dataset(dataset_id)
        token = self.lifecycle.generations.next("ml-dataset-detail")
        self.headless_client.get_dataset(
            f"ml.dataset.detail.{token}.{dataset_id}", dataset_id
        )

    def _show_dataset_detail(self, data: dict, *, expected_dataset_id: str = "") -> None:
        actual_id = self._record_id(data, "dataset")
        if expected_dataset_id and actual_id and actual_id != expected_dataset_id:
            return
        if expected_dataset_id and self.context.registry.current_dataset_id not in {"", expected_dataset_id}:
            return
        name = readable_dataset_name(data, aliases=getattr(self, "registry_aliases", None))
        samples = data.get("sample_count", "—")
        features = data.get("feature_names") or data.get("feature_paths") or []
        targets = data.get("target_names") or []
        detail = f"{name} / {samples} 样本"
        if features or targets:
            detail += f" / {len(features)} 输入 / {len(targets)} 目标"
        self._set_info(self.dataset_detail, "数据集", detail)
        self.context.registry.merge_dataset(data)

    def _selected_dataset_id(self) -> str:
        row = self.datasets_table.currentRow()
        datasets = self.context.registry.datasets
        if 0 <= row < len(datasets):
            return self._record_id(datasets[row], "dataset")
        return ""

    def _download_manifest(self) -> None:
        dataset_id = self._selected_dataset_id()
        if dataset_id:
            self.headless_client.download_manifest(f"ml.download.manifest.{dataset_id}", dataset_id)

    def _download_samples_flat(self) -> None:
        dataset_id = self._selected_dataset_id()
        if dataset_id:
            self.headless_client.download_samples_flat(f"ml.download.flat.{dataset_id}", dataset_id)

    def _download_samples_jsonl(self) -> None:
        dataset_id = self._selected_dataset_id()
        if dataset_id:
            self.headless_client.download_samples_jsonl(f"ml.download.jsonl.{dataset_id}", dataset_id)

    def _submit_coupling_dataset(self) -> None:
        payload = {
            "project": self._current_dataset_project_payload(),
            "analyses": ["coupling"],
            "precision": "standard",
            "random_seed": 42,
        }
        self.headless_client.submit_coupling("ml.coupling.submit", payload)
        self._set_info(self.coupling_status, "耦合任务", "正在提交")

    @staticmethod
    def _decode_manifest_bytes(data: bytes) -> dict:
        value = json.loads(data.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("数据集 manifest 不是对象")
        return value

    @staticmethod
    def _write_download(path: Path, data: bytes) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def _start_background_worker(self, worker: FunctionWorker) -> None:
        self._background_workers.add(worker)
        self.lifecycle.manage_worker(worker)
        worker.signals.finished.connect(
            lambda current=worker: (self._background_workers.discard(current), self.lifecycle.release_worker(current))
        )
        QThreadPool.globalInstance().start(worker)

    def _binary_completed(self, key: str, data: bytes) -> None:
        if key.startswith("ml.training.preflight."):
            suffix = key.removeprefix("ml.training.preflight.")
            token_text, _, dataset_id = suffix.partition(".")
            try:
                token = int(token_text)
            except ValueError:
                return
            payload = self._pending_training.pop(f"{token}:{dataset_id}", None)
            if payload is None or not self.lifecycle.generations.is_current(token, "ml-training-preflight"):
                return
            worker = FunctionWorker(self._decode_manifest_bytes, bytes(data))
            worker.signals.result.connect(
                lambda manifest, ds=dataset_id, request=payload: self._manifest_decoded(
                    ds, request, manifest
                )
            )
            worker.signals.error.connect(
                lambda message: self._set_info(
                    self.training_status,
                    "任务状态",
                    f"无法解析数据集 manifest：{message}",
                )
            )
            self._start_background_worker(worker)
            return

        downloads = {
            "ml.download.manifest.": ("manifest.json", "清单文件"),
            "ml.download.flat.": ("samples.csv", "CSV 文件"),
            "ml.download.jsonl.": ("samples.jsonl", "JSON 文件"),
        }
        for prefix, (suffix, label) in downloads.items():
            if not key.startswith(prefix):
                continue
            dataset_id = key.removeprefix(prefix)
            path = Path.cwd() / "downloads" / f"{dataset_id}-{suffix}"
            worker = FunctionWorker(self._write_download, path, bytes(data))
            worker.signals.result.connect(
                lambda saved_path, output_label=label: self._set_info(
                    self.dataset_detail, output_label, str(saved_path)
                )
            )
            worker.signals.error.connect(
                lambda message, output_label=label: self._set_info(
                    self.dataset_detail, output_label, f"写入失败：{message}"
                )
            )
            self._start_background_worker(worker)
            return

    def _manifest_decoded(self, dataset_id: str, payload: dict, manifest: dict) -> None:
        splits = (
            manifest.get("train_ids", []),
            manifest.get("validation_ids", []),
            manifest.get("test_ids", []),
        )
        if not manifest.get("valid_sample_count", 0) or not all(splits):
            if hasattr(self, "training_progress"):
                self.training_progress.setRange(0, 100)
                self.training_progress.setValue(0)
                self.training_progress.setFormat("数据不可用")
            self._set_info(
                self.training_status,
                "任务状态",
                "数据集没有可用于训练的有效样本；请检查数据集任务详情中的失败原因。",
            )
            if hasattr(self, "training_submit_button"):
                self.training_submit_button.set_task_state("error", "数据不可用")
                from PySide6.QtCore import QTimer
                QTimer.singleShot(1400, lambda: self.training_submit_button.reset_task_state("开始训练"))
            return
        self.context.registry.merge_dataset(manifest)
        if hasattr(self, "training_progress"):
            self.training_progress.setRange(0, 0)
            self.training_progress.setFormat("正在提交后台…")
        self.training_client.submit("ml.training.submit", payload)
        if hasattr(self, "training_submit_button"):
            self.training_submit_button.set_task_state("running", "训练中")
        self._set_info(self.training_status, "任务状态", "正在提交训练任务")


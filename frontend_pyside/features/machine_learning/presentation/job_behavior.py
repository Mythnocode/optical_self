from __future__ import annotations

from PySide6.QtCore import QTimer

from frontend_pyside.shared.task_display import friendly_job_stage, progress_fraction, progress_percent, stable_progress_text

from frontend_pyside.shared.components.basic import InfoRow


_TERMINAL = {"已完成", "失败", "已取消", "未收敛"}


def _friendly_ml_job_message(message: object) -> str:
    text = str(message or "").strip()
    low = text.lower()
    if "im(1/q)" in low or "q 参数无效" in text:
        return "采样参数使高斯光束传播状态无效。请缩小曲率或空气间隔范围后重新提交。"
    if "半口径超出" in text or "conic sag" in low:
        return "采样后的曲率与镜片口径不匹配，已超出曲面有效范围。"
    if "no valid" in low and "sample" in low:
        return "本次数据集中没有可用于训练的有效样本，请检查曲率、间隔和仿真收敛设置。"
    if "timeout" in low or "timed out" in low:
        return "任务运行超时。请减少样本数、降低仿真精度或检查后端是否繁忙。"
    return text or "任务失败，请在任务中心查看详细日志。"


class MachineLearningJobMixin:


    @staticmethod
    def _ml_kind_from_task(task: dict) -> str:
        text = " ".join(str(task.get(key, "")) for key in ("name", "kind", "note"))
        return "training" if any(token in text for token in ("训练", "模型")) and "数据集" not in text else "dataset"

    def _restore_ml_jobs(self) -> None:
        loaded = getattr(self, "_loaded_ml_results", None)
        if loaded is None:
            loaded = self._loaded_ml_results = set()
        latest: dict[str, dict] = {}
        for task in self.context.tasks.tasks:
            if not isinstance(task, dict):
                continue
            job_id = str(task.get("job_id", ""))
            if not job_id:
                continue
            if str(task.get("page", "")) != "machine_learning" and str(task.get("kind", "")) != "机器学习":
                continue
            kind = self._ml_kind_from_task(task)
            if str(task.get("status", "")) == "已完成" and job_id in loaded:
                continue
            latest[kind] = task
        for kind, task in latest.items():
            job_id = str(task.get("job_id", ""))
            info = self._jobs.setdefault(job_id, {})
            info.update(
                {
                    "kind": kind,
                    "task_id": str(task.get("id", "")),
                    "result_requested": bool(info.get("result_requested", False)),
                }
            )

    def _sync_task_context(self, _tasks: object = None) -> None:
        self._restore_ml_jobs()
        for job_id, info in list(self._jobs.items()):
            task = self.context.tasks.find_by_job_id(job_id)
            if not task:
                continue
            info["task_id"] = str(task.get("id", info.get("task_id", "")))
            status = str(task.get("status", ""))
            progress = progress_percent(task.get("progress", 0))
            tracker = getattr(
                self,
                "_dataset_progress_tracker" if info["kind"] == "dataset" else "_training_progress_tracker",
                None,
            )
            if tracker is not None:
                progress = tracker.value(job_id, status, progress)
            self.context.registry.merge_training_task(
                {
                    "job_id": job_id,
                    "training_task_id": str(task.get("id", "")),
                    "kind": info["kind"],
                    "status": status,
                    "progress": progress,
                    "note": str(task.get("note", "")),
                }
            )
            self._set_job_status(info["kind"], f"{status} {progress}%")
            if info["kind"] == "training":
                self._update_training_progress(job_id, status, progress)
            elif info["kind"] == "dataset":
                self._update_dataset_progress(job_id, status, progress)
            if status == "已完成" and not info.get("result_requested", False):
                self._request_ml_result(job_id, info)
            elif status in {"失败", "已取消"}:
                self._finish_job(job_id, status, str(task.get("note", status)))

    def _request_ml_result(self, job_id: str, info: dict) -> None:
        kind = str(info.get("kind", "dataset"))
        token = self.lifecycle.generations.next(f"ml-result:{kind}")
        info["result_requested"] = True
        info["result_generation"] = token
        self.job_client.get_result(f"ml.result.{kind}.{token}.{job_id}", job_id)

    @staticmethod
    def _parse_ml_result_key(key: str) -> tuple[str, int, str] | None:
        parts = key.split(".", 4)
        if len(parts) != 5 or parts[:2] != ["ml", "result"]:
            return None
        try:
            return parts[2], int(parts[3]), parts[4]
        except ValueError:
            return None

    def _handle_result_response(self, key: str, data: dict) -> None:
        parsed = self._parse_ml_result_key(key)
        if parsed is None:
            return
        kind, token, job_id = parsed
        if not self.lifecycle.generations.is_current(token, f"ml-result:{kind}"):
            return
        self._handle_result(job_id, data)

    def _handle_result_failure(self, key: str, message: str) -> None:
        parsed = self._parse_ml_result_key(key)
        if parsed is None:
            return
        kind, token, job_id = parsed
        if self.lifecycle.generations.is_current(token, f"ml-result:{kind}"):
            self._finish_job(job_id, "失败", message)

    def _poll_jobs(self) -> None:
        if self._centralized_polling:
            self._poll_timer.stop()
            return
        for job_id in list(self._jobs):
            task = self.context.tasks.find_by_job_id(job_id)
            if task and str(task.get("status", "")) in _TERMINAL:
                continue
            self.job_client.get_status(f"ml.status.{job_id}", job_id)
        if not self._jobs:
            self._poll_timer.stop()

    def _ensure_ml_job(self, job_id: str) -> dict | None:
        info = self._jobs.get(job_id)
        if info:
            return info
        task = self.context.tasks.find_by_job_id(job_id)
        if not task:
            return None
        info = {
            "kind": self._ml_kind_from_task(task),
            "task_id": str(task.get("id", "")),
            "result_requested": False,
        }
        self._jobs[job_id] = info
        return info

    def _handle_status(self, job_id: str, body: dict) -> None:
        info = self._ensure_ml_job(job_id)
        if not info:
            self.context.tasks.upsert_backend_job({"job_id": job_id, **body})
            info = self._ensure_ml_job(job_id)
            if not info:
                return
        status = str(body.get("status", "queued"))
        progress = progress_fraction(body.get("progress", 0.0))
        stage = str(body.get("stage", ""))
        progress_value = round(progress * 100)
        tracker = getattr(
            self,
            "_dataset_progress_tracker" if info["kind"] == "dataset" else "_training_progress_tracker",
            None,
        )
        if tracker is not None:
            progress_value = tracker.value(job_id, status, progress)
            progress = progress_value / 100.0
        stage_display = friendly_job_stage(stage)
        self.context.tasks.update_job(
            job_id,
            status=self._status_text(status),
            progress=progress_value,
            note=stage_display or f"job_id: {job_id}",
        )
        self.context.registry.merge_training_task(
            {
                "job_id": job_id,
                "training_task_id": str(info.get("task_id", "")),
                "kind": info["kind"],
                "status": self._status_text(status),
                "progress": progress_value,
                "note": stage_display,
            }
        )
        self.context.tasks.append_log(job_id, stage_display or self._status_text(status))
        loading_result = status == "completed" and not bool(info.get("result_requested", False))
        self._set_job_status(info["kind"], stable_progress_text(status, progress, loading_result=loading_result))
        if info["kind"] == "training":
            self._update_training_progress(job_id, status, progress)
        elif info["kind"] == "dataset":
            self._update_dataset_progress(job_id, status, progress)
        if status == "completed" and not info.get("result_requested", False):
            self._request_ml_result(job_id, info)
        elif status in {"failed", "cancelled"}:
            error = body.get("error") if isinstance(body, dict) else None
            error_message = ""
            if isinstance(error, dict):
                error_message = str(error.get("message", "") or "")
            self._finish_job(
                job_id,
                self._status_text(status),
                error_message or stage,
            )

    def _handle_result(self, job_id: str, data: dict) -> None:
        info = self._ensure_ml_job(job_id)
        if not info:
            return
        self.context.tasks.update_job(
            job_id,
            status="已完成",
            progress=100,
            note="后端任务已完成",
            result_available=True,
        )
        self.context.tasks.set_result(job_id, data)
        self.context.tasks.append_log(job_id, "机器学习任务结果已加载")
        self.context.registry.merge_training_task(
            {
                "job_id": job_id,
                "training_task_id": str(info.get("task_id", "")),
                "kind": info["kind"],
                "status": "已完成",
                "progress": 100,
                "result": dict(data or {}),
            }
        )
        if info["kind"] == "dataset":
            self._update_dataset_progress(job_id, "completed", 1.0)
            if isinstance(data, dict) and (data.get("dataset_id") or data.get("id")):
                self.context.registry.merge_dataset(data)
                self.context.registry.set_current_dataset(
                    str(data.get("dataset_id", data.get("id", "")))
                )
            self._set_job_status("dataset", "数据集任务完成")
            self.context.registry.invalidate("datasets")
            self.refresh_remote(force=True)
            # Background completion must not steal the user's current ML stage.
            # The visible workflow bar is the navigation authority; data refreshes
            # in place and the user decides when to inspect it.
        else:
            metrics = data.get("validation_metrics", {})
            metrics = dict(metrics) if isinstance(metrics, dict) else {}
            self._update_training_progress(job_id, "completed", 1.0)
            if hasattr(self, "training_progress"):
                def _fmt_metric(value):
                    try:
                        return f"{float(value):.3f}"
                    except (TypeError, ValueError):
                        return "—"
                self.training_r2.set_value(_fmt_metric(metrics.get("r2", metrics.get("R2"))))
                self.training_mae.set_value(_fmt_metric(metrics.get("mae")))
                self.training_rmse.set_value(_fmt_metric(metrics.get("rmse")))
                try:
                    elapsed_ms = float(data.get("training_elapsed_ms"))
                    self.training_time.set_value(f"{elapsed_ms:.0f}")
                except (TypeError, ValueError):
                    self.training_time.set_value("—")
                model_type = str(data.get("model_type", ""))
                metadata = dict(data.get("metadata") or {})
                history = data.get("training_history") or metadata.get("training_history")
                if isinstance(history, dict) and history:
                    
                    
                    
                    train_values = list(history.get("train", history.get("training", [])) or [])
                    validation_values = list(history.get("validation", history.get("valid", [])) or [])
                    # XGBoost exposes nested evals_result_ such as
                    # {"validation_0": {"rmse": [...]}}. Use the real validation curve
                    # instead of treating the nested structure as “no history”.
                    if not train_values and not validation_values:
                        for dataset_name, metrics_map in history.items():
                            if not isinstance(metrics_map, dict):
                                continue
                            for metric_name, values in metrics_map.items():
                                if isinstance(values, (list, tuple)) and values:
                                    validation_values = list(values)
                                    break
                            if validation_values:
                                break
                    count = max(len(train_values), len(validation_values))
                    series = []
                    if train_values:
                        series.append({"label": "训练集", "y": train_values})
                    if validation_values:
                        series.append({"label": "验证集", "y": validation_values})
                    if series:
                        self.training_result.set_result(0, "训练诊断", {
                            "kind": "line_multi", "x": list(range(1, count + 1)), "series": series,
                            "title": "真实训练历史", "x_label": "训练轮次", "y_label": "验证误差",
                            "source": "后端训练历史",
                        })
                    else:
                        history = {}
                else:
                    evaluation = dict(metadata.get("evaluation") or {})
                    actual = evaluation.get("actual") or []
                    predicted = evaluation.get("predicted") or []
                    # Single-target regression is the normal coupling use case. Flatten one-element rows.
                    def _flat(values):
                        out = []
                        for value in values:
                            if isinstance(value, (list, tuple)) and value:
                                value = value[0]
                            try:
                                out.append(float(value))
                            except (TypeError, ValueError):
                                pass
                        return out
                    actual_flat, predicted_flat = _flat(actual), _flat(predicted)
                    if actual_flat and len(actual_flat) == len(predicted_flat):
                        self.training_result.set_result(0, "训练诊断", {
                            "kind": "validation_scatter",
                            "actual": actual_flat,
                            "predicted": predicted_flat,
                            "title": "预测值与真实值",
                            "x_label": "真实值",
                            "y_label": "预测值",
                            "source": "独立测试集",
                        })
                    else:
                        self.training_result.set_result(0, "训练诊断", {
                            "kind": "empty",
                            "message": "当前模型没有逐轮历史；后端也未返回可绘制的独立测试样本。",
                        })
                summary = dict(metadata.get("training_summary") or {})
                if hasattr(self, "training_run_summary"):
                    if model_type == "random_forest":
                        trees = int(summary.get("actual_units", summary.get("requested_units", 0)) or 0)
                        self.training_run_summary.setText(f"随机森林为非迭代模型 · 实际构建 {trees or '—'} 棵树 · 早停/收敛轮次不适用")
                    else:
                        requested = int(summary.get("requested_units", 0) or 0)
                        actual_units = int(summary.get("actual_units", 0) or 0)
                        best = summary.get("best_iteration")
                        early = bool(summary.get("early_stopped"))
                        convergence = "早停收敛" if early else "达到最大训练预算，需结合验证曲线判断收敛"
                        self.training_run_summary.setText(
                            f"计划最大轮数 {requested or '—'} · 实际训练 {actual_units or '—'} · "
                            f"最佳轮次 {best or '—'} · 早停 {'是' if early else '否'} · {convergence}"
                        )
            model_record = data.get("model") if isinstance(data.get("model"), dict) else data
            if isinstance(model_record, dict) and (
                model_record.get("model_id") or model_record.get("id")
            ):
                self.context.registry.merge_model(model_record)
                self.context.registry.set_recent_model(
                    str(model_record.get("model_id", model_record.get("id", "")))
                )
                if hasattr(self, "training_adopt_button"):
                    self.training_adopt_button.setEnabled(True)
                if hasattr(self, "training_adopt_note"):
                    self.training_adopt_note.setText("新模型已训练完成，但尚未设为当前模型。请检查指标后再决定是否采用。")
            self._set_job_status("training", "模型训练完成")
            if hasattr(self, "training_submit_button"):
                self.training_submit_button.set_task_state("success", "训练完成")
                QTimer.singleShot(1400, lambda: self.training_submit_button.reset_task_state("开始训练"))
            self.context.registry.invalidate("models")
            self.refresh_remote(force=True)
            # Do not asynchronously jump from prediction/data to model comparison.
            # This used to race with real clicks during GUI acceptance.
        self._loaded_ml_results.add(job_id)
        self._jobs.pop(job_id, None)
        if not self._jobs:
            self._poll_timer.stop()

    def _finish_job(self, job_id: str, status: str, message: str) -> None:
        info = self._ensure_ml_job(job_id)
        display_message = _friendly_ml_job_message(message) if status == "失败" else (str(message or "").strip() or status)
        if info:
            self.context.tasks.update_job(job_id, status=status, note=display_message)
            self.context.tasks.append_log(job_id, str(message or display_message), level="ERROR")
            self.context.registry.merge_training_task(
                {
                    "job_id": job_id,
                    "training_task_id": str(info.get("task_id", "")),
                    "kind": info["kind"],
                    "status": status,
                    "note": display_message,
                }
            )
            self.lifecycle.generations.invalidate(f"ml-result:{info['kind']}")
            self._set_job_status(
                info["kind"],
                f"{status}：{display_message}" if status == "失败" else display_message,
            )
            if info["kind"] == "dataset":
                self._update_dataset_progress(job_id, status, 0.0)
            elif info["kind"] == "training":
                self._update_training_progress(job_id, status, 0.0)
                if hasattr(self, "training_submit_button"):
                    if status == "失败":
                        self.training_submit_button.set_task_state("error", "训练失败")
                    else:
                        self.training_submit_button.set_task_state("pending", "训练已取消")
                    QTimer.singleShot(1500, lambda: self.training_submit_button.reset_task_state("开始训练"))
            self._jobs.pop(job_id, None)
        if not self._jobs:
            self._poll_timer.stop()

    def _update_dataset_progress(self, job_id: str, status: object, progress: object) -> None:
        """Only render progress reported by the backend for the active dataset job."""
        state = str(status or "").strip().lower()
        active = str(getattr(self, "_active_dataset_job_id", "") or "")
        if not active and state in {"running", "运行中", "queued", "等待后端", "等待中"}:
            self._active_dataset_job_id = str(job_id)
            active = str(job_id)
            tracker = getattr(self, "_dataset_progress_tracker", None)
            if tracker is not None:
                tracker.reset(job_id)
        if str(job_id) != active:
            return
        tracker = getattr(self, "_dataset_progress_tracker", None)
        percent = tracker.value(job_id, status, progress) if tracker is not None else progress_percent(progress)
        bar = getattr(self, "dataset_progress", None)
        if bar is not None:
            bar.setRange(0, 100)
            bar.setValue(percent)
            if state in {"completed", "已完成"}:
                bar.setFormat("已完成 · 100%")
            elif state in {"failed", "失败"}:
                bar.setFormat("任务失败")
            elif state in {"cancelled", "已取消"}:
                bar.setFormat("已取消")
            else:
                bar.setFormat("%p%")
        if state in {"completed", "已完成", "failed", "失败", "cancelled", "已取消"}:
            self._active_dataset_job_id = ""
            if tracker is not None:
                tracker.forget(job_id)

    def _update_training_progress(self, job_id: str, status: object, progress: object) -> None:
        state = str(status or "").strip().lower()
        active = str(getattr(self, "_active_training_job_id", "") or "")
        if not active and state in {"running", "运行中", "queued", "等待后端", "等待中"}:
            self._active_training_job_id = str(job_id); active = str(job_id)
            tracker = getattr(self, "_training_progress_tracker", None)
            if tracker is not None: tracker.reset(job_id)
        if str(job_id) != active:
            return
        tracker = getattr(self, "_training_progress_tracker", None)
        percent = tracker.value(job_id, status, progress) if tracker is not None else progress_percent(progress)
        bar = getattr(self, "training_progress", None)
        if hasattr(self, "training_submit_button") and state not in {"completed", "已完成", "failed", "失败", "cancelled", "已取消"}:
            if self.training_submit_button.property("taskState") not in {"running", "submitted"}:
                self.training_submit_button.set_task_state("running", "训练中")
        if bar is not None:
            bar.setRange(0, 100)
            bar.setValue(percent)
            if state in {"completed", "已完成"}:
                bar.setFormat("已完成 · 100%")
            elif state in {"failed", "失败"}:
                bar.setFormat("任务失败")
            elif state in {"cancelled", "已取消"}:
                bar.setFormat("已取消")
            else:
                bar.setFormat("%p%")
        if state in {"completed", "已完成", "failed", "失败", "cancelled", "已取消"}:
            self._active_training_job_id = ""
            if tracker is not None: tracker.forget(job_id)

    def _on_ws_progress(self, job_id: str, progress: float, stage: str) -> None:
        info = self._ensure_ml_job(job_id)
        if not info:
            return
        if progress > 1.0:
            progress /= 100.0
        percent = round(progress * 100)
        tracker = getattr(
            self,
            "_dataset_progress_tracker" if info["kind"] == "dataset" else "_training_progress_tracker",
            None,
        )
        if tracker is not None:
            percent = tracker.value(job_id, "running", progress)
            progress = percent / 100.0
        stage_display = friendly_job_stage(stage)
        self.context.tasks.update_job(
            job_id,
            status="运行中",
            progress=percent,
            note=stage_display,
        )
        message = stage_display if stage_display in {"正在保存结果", "正在整理结果"} else stable_progress_text("running", progress)
        if stage_display in {"正在保存结果", "正在整理结果"}:
            message = f"{stage_display} · {percent}%"
        self._set_job_status(info["kind"], message)
        if info["kind"] == "training":
            self._update_training_progress(job_id, "running", progress)
        elif info["kind"] == "dataset":
            self._update_dataset_progress(job_id, "running", progress)

    def _on_ws_completed(self, job_id: str, status: str, _metrics: dict) -> None:
        info = self._ensure_ml_job(job_id)
        if not info:
            return
        if status == "completed" and not info.get("result_requested", False):
            self.context.tasks.update_job(
                job_id, status="已完成", progress=100, note="任务已完成，结果可读取", result_available=True
            )
            self._request_ml_result(job_id, info)
        elif status == "cancelled":
            self._finish_job(job_id, "已取消", "任务已取消")

    def _on_ws_failed(self, job_id: str, message: str) -> None:
        self._finish_job(job_id, "失败", message)

    def _refresh_models(self) -> None:
        self.context.registry.invalidate("models")
        self.refresh_remote(force=True)

    def _set_job_status(self, kind: str, message: str) -> None:
        target = getattr(self, "dataset_status", None) if kind == "dataset" else getattr(self, "training_status", None)
        if target is not None:
            self._set_info(target, "任务状态", message)

    @staticmethod
    def _set_info(widget: InfoRow, label: str, value: str) -> None:
        layout = widget.layout()
        if layout and layout.count() >= 2:
            layout.itemAt(0).widget().setText(label)
            layout.itemAt(1).widget().setText(value)

    @staticmethod
    def _status_text(status: str) -> str:
        return {
            "queued": "等待后端",
            "running": "运行中",
            "completed": "已完成",
            "failed": "失败",
            "cancelled": "已取消",
        }.get(status, status)

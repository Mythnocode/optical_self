from __future__ import annotations

from frontend_pyside.shared.task_display import progress_fraction, progress_percent, stable_progress_text

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
            if info["kind"] == "training" and hasattr(self, "training_progress"):
                self.training_progress.setValue(progress)
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
        self.context.tasks.update_job(
            job_id,
            status=self._status_text(status),
            progress=round(progress * 100),
            note=stage or f"job_id: {job_id}",
        )
        self.context.registry.merge_training_task(
            {
                "job_id": job_id,
                "training_task_id": str(info.get("task_id", "")),
                "kind": info["kind"],
                "status": self._status_text(status),
                "progress": round(progress * 100),
                "note": stage,
            }
        )
        self.context.tasks.append_log(job_id, stage or self._status_text(status))
        self._set_job_status(info["kind"], stable_progress_text(status, progress))
        if info["kind"] == "training" and hasattr(self, "training_progress"):
            self.training_progress.setValue(round(progress * 100))
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
            if isinstance(data, dict) and (data.get("dataset_id") or data.get("id")):
                self.context.registry.merge_dataset(data)
                self.context.registry.set_current_dataset(
                    str(data.get("dataset_id", data.get("id", "")))
                )
            self._set_job_status("dataset", "数据集任务完成")
            self.context.registry.invalidate("datasets")
            self.refresh_remote(force=True)
            if getattr(self, "advanced_section", None) is not None and self.advanced_section.is_expanded():
                self._set_workflow_step(0)
        else:
            metrics = data.get("validation_metrics", {})
            metrics = dict(metrics) if isinstance(metrics, dict) else {}
            if hasattr(self, "training_progress"):
                self.training_progress.setValue(100)
                self.training_r2.set_value(metrics.get("r2", metrics.get("R2", "—")))
                self.training_mae.set_value(metrics.get("mae", "—"))
                self.training_rmse.set_value(metrics.get("rmse", "—"))
                self.training_time.set_value(data.get("training_elapsed_ms", "—"))
                model_type = str(data.get("model_type", ""))
                history = data.get("training_history")
                if isinstance(history, dict) and history:
                    
                    
                    
                    train_values = list(history.get("train", history.get("training", [])) or [])
                    validation_values = list(history.get("validation", history.get("valid", [])) or [])
                    count = max(len(train_values), len(validation_values))
                    series = []
                    if train_values:
                        series.append({"label": "训练集", "y": train_values})
                    if validation_values:
                        series.append({"label": "验证集", "y": validation_values})
                    self.training_result.set_result(0, "模型训练", {
                        "kind": "line_multi", "x": list(range(1, count + 1)), "series": series,
                        "title": "真实训练历史", "x_label": "迭代轮次", "y_label": "评估误差",
                        "source": "后端训练历史",
                    })
                else:
                    self.training_result.set_result(0, "模型训练", {
                        "kind": "text",
                        "text": f"模型：{model_type or '—'}\n后端未返回逐轮评估历史。\n随机森林等非迭代模型不绘制伪训练曲线；质量请查看上方 R²、MAE 和 RMSE。",
                        "title": "模型训练信息", "source": "后端训练",
                    })
            model_record = data.get("model") if isinstance(data.get("model"), dict) else data
            if isinstance(model_record, dict) and (
                model_record.get("model_id") or model_record.get("id")
            ):
                self.context.registry.merge_model(model_record)
                self.context.registry.set_current_model(
                    str(model_record.get("model_id", model_record.get("id", "")))
                )
            self._set_job_status("training", "模型训练完成")
            self.context.registry.invalidate("models")
            self.refresh_remote(force=True)
            if getattr(self, "advanced_section", None) is not None and self.advanced_section.is_expanded():
                self._set_workflow_step(2)
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
            self._jobs.pop(job_id, None)
        if not self._jobs:
            self._poll_timer.stop()

    def _on_ws_progress(self, job_id: str, progress: float, stage: str) -> None:
        info = self._ensure_ml_job(job_id)
        if not info:
            return
        if progress > 1.0:
            progress /= 100.0
        self.context.tasks.update_job(
            job_id,
            status="运行中",
            progress=round(progress * 100),
            note=stage,
        )
        self._set_job_status(info["kind"], stable_progress_text("running", progress))

    def _on_ws_completed(self, job_id: str, status: str, _metrics: dict) -> None:
        info = self._ensure_ml_job(job_id)
        if not info:
            return
        if status == "completed" and not info.get("result_requested", False):
            self.context.tasks.update_job(job_id, status="已完成", progress=100)
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

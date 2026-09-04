from __future__ import annotations

from copy import deepcopy

from frontend_pyside.features.optimization.guided_research import friendly_failure_message
from frontend_pyside.shared.task_display import friendly_job_stage, progress_percent, stable_progress_text


_TERMINAL = {"已完成", "失败", "已取消", "未收敛"}


class OptimizationJobMixin:


    @staticmethod
    def _kind_from_task(task: dict) -> str:
        text = " ".join(str(task.get(key, "")) for key in ("name", "kind", "note"))
        if "容差" in text:
            return "tolerance"
        return (
            "optimization"
            if any(token in text for token in ("自动优化", "自动调参", "优化"))
            and "扫描" not in text
            else "scan"
        )

    def _restore_jobs_from_tasks(self, tasks: object) -> None:
        records = list(tasks or []) if isinstance(tasks, (list, tuple)) else []
        loaded_results = getattr(self, "_loaded_result_jobs", None)
        if loaded_results is None:
            loaded_results = self._loaded_result_jobs = set()
        latest_by_kind: dict[str, dict] = {}
        for task in records:
            if not isinstance(task, dict):
                continue
            job_id = str(task.get("job_id", ""))
            if not job_id:
                continue
            page = str(task.get("page", ""))
            kind_text = str(task.get("kind", ""))
            name = str(task.get("name", ""))
            if page != "optimization" and kind_text != "参数研究" and not any(
                token in name for token in ("参数扫描", "自动优化", "自动调参", "容差")
            ):
                continue
            status = str(task.get("status", ""))
            if status in {"失败", "已取消", "未收敛"}:
                continue
            if status == "已完成" and job_id in loaded_results:
                continue
            latest_by_kind[self._kind_from_task(task)] = task

        for kind, task in latest_by_kind.items():
            job_id = str(task.get("job_id", ""))
            info = self._jobs.setdefault(job_id, {})
            info.update(
                {
                    "kind": kind,
                    "task_id": str(task.get("id", "")),
                    "result_requested": bool(info.get("result_requested", False)),
                    "project_revision": str(task.get("project_revision", info.get("project_revision", "")) or ""),
                }
            )

    def _sync_task_context(self, _tasks: object = None) -> None:
        records = self.context.tasks.tasks
        self._restore_jobs_from_tasks(records)
        by_job_id = {
            str(item.get("job_id", "")): item
            for item in records
            if isinstance(item, dict) and str(item.get("job_id", ""))
        }
        for job_id, info in list(self._jobs.items()):
            task = by_job_id.get(job_id)
            if not task:
                continue
            info["task_id"] = str(task.get("id", info.get("task_id", "")))
            status = str(task.get("status", ""))
            progress = progress_percent(task.get("progress", 0))
            self._set_job_info(info["kind"], stable_progress_text(status, progress))
            self._update_research_progress(job_id, status, progress)
            if status == "已完成" and not info.get("result_requested", False):
                self._request_job_result(job_id, info)
            elif status in {"失败", "已取消"}:
                self._finish_failure(
                    job_id,
                    str(task.get("note", status)),
                    status="cancelled" if status == "已取消" else "failed",
                )

    @staticmethod
    def _progress_fraction(value: object) -> float:
        try:
            progress = float(value or 0.0)
        except (TypeError, ValueError):
            progress = 0.0
        if progress > 1.0:
            progress /= 100.0
        return max(0.0, min(1.0, progress))

    def _request_job_result(self, job_id: str, info: dict) -> None:
        kind = str(info.get("kind", "scan"))
        token = self.lifecycle.generations.next(f"optimization-result:{kind}")
        info["result_requested"] = True
        info["result_generation"] = token
        self.job_client.get_result(
            f"optimization.result.{kind}.{token}.{job_id}", job_id
        )

    @staticmethod
    def _parse_result_key(key: str) -> tuple[str, int, str] | None:
        parts = key.split(".", 4)
        if len(parts) != 5 or parts[:2] != ["optimization", "result"]:
            return None
        try:
            return parts[2], int(parts[3]), parts[4]
        except ValueError:
            return None

    def _api_completed(self, key: str, body: object) -> None:
        if key == "structure.models":
            handler = getattr(self, "_structure_models_completed", None)
            if callable(handler):
                handler(body)
            return
        if key == "structure.candidates":
            handler = getattr(self, "_structure_candidates_completed", None)
            if callable(handler):
                handler(body)
            return
        if key == "validation.run":
            handler = getattr(self, "_validation_platform_completed", None)
            if callable(handler):
                handler(body)
            return
        if not key.startswith("optimization."):
            return

        if key == "optimization.jobs.refresh":
            payload = body if isinstance(body, dict) else {}
            jobs = body if isinstance(body, list) else payload.get("items", payload.get("jobs", []))
            if not isinstance(jobs, list):
                jobs = []
            self.context.tasks.reconcile_backend_jobs(
                [item for item in jobs if isinstance(item, dict)]
            )
            return

        data = body if isinstance(body, dict) else {}
        if key in {"optimization.scan.submit", "optimization.auto.submit", "optimization.tolerance.submit"}:
            job_id = str(data.get("job_id", ""))
            if not job_id:
                self._api_failed(key, "响应缺少 job_id")
                return
            if key.endswith("scan.submit"):
                kind = "scan"
            elif key.endswith("tolerance.submit"):
                kind = "tolerance"
            else:
                kind = "optimization"
            existing_task = next(
                (item for item in self.context.tasks.tasks if str(item.get("job_id", "")) == job_id),
                None,
            )
            reused_existing = existing_task is not None
            if existing_task is None:
                task = self.context.tasks.add(
                    "后端参数扫描" if kind == "scan" else ("参数容差分析" if kind == "tolerance" else "后端自动优化"),
                    "参数研究",
                    "等待后端",
                    0,
                    f"job_id: {job_id}",
                    page="optimization",
                    job_id=job_id,
                )
            else:
                task = existing_task
            project_revision = str(getattr(self.context.project, "design_revision", "") or getattr(self.context.project, "revision", "") or "")
            if project_revision:
                self.context.tasks.update_task(str(task["id"]), project_revision=project_revision)
            self._jobs[job_id] = {
                "kind": kind,
                "task_id": str(task["id"]),
                "result_requested": False,
                "project_revision": project_revision,
            }
            self._active_research_job_id = job_id
            if hasattr(self, "_progress_tracker"):
                self._progress_tracker.reset(job_id)
            if kind == "tolerance" and hasattr(self, "tolerance_progress"):
                # 收到 job_id 后才切换到可量化的真实后台进度。
                if hasattr(self, "tolerance_progress_panel"):
                    self.tolerance_progress_panel.setVisible(True)
                if hasattr(self, "tolerance_progress_label"):
                    self.tolerance_progress_label.setText("容差任务已接收 · 等待后台进度")
                self.tolerance_progress.setRange(0, 100)
                self.tolerance_progress.setValue(0)
                self.tolerance_progress.setFormat("等待后台进度 · 0%")
                self.tolerance_progress.setTextVisible(True)
            elif hasattr(self, "research_progress"):
                # 收到 job_id 后才切换到可量化的真实后台进度。
                self.research_progress.setRange(0, 100)
                self.research_progress.setValue(0)
                self.research_progress.setFormat("等待后台进度 · 0%")
            self.context.tasks.append_log(
                str(task["id"]),
                "后端返回了已有相同任务，已复用原 job_id" if reused_existing else "任务已提交到后端",
            )
            if kind == "scan":
                self._scan_refinement_pending = False
                self._scan_refinement_parameter = ""
            self.job_watcher.subscribe(job_id)
            if not self._centralized_polling:
                self._poll_timer.start()
            self._set_job_info(kind, f"已复用已有 job {job_id}" if reused_existing else f"已提交 job {job_id}")
            self._refresh_history()
            return

        if key.startswith("optimization.status."):
            self._handle_status(key.rsplit(".", 1)[-1], data)
            return

        parsed = self._parse_result_key(key)
        if parsed:
            kind, token, job_id = parsed
            if not self.lifecycle.generations.is_current(
                token, f"optimization-result:{kind}"
            ):
                return
            self._schedule_result_render(job_id, kind, token, data)

    @staticmethod
    def _validation_error_text(error: object) -> str:
        context = getattr(error, "context", {}) if error is not None else {}
        errors = list(context.get("errors", []) or []) if isinstance(context, dict) else []
        rows: list[str] = []
        for item in errors[:4]:
            if not isinstance(item, dict):
                continue
            loc = [str(value) for value in list(item.get("loc", []) or []) if str(value) not in {"body"}]
            field = ".".join(loc) or "请求参数"
            msg = str(item.get("msg") or "参数无效")
            rows.append(f"{field}：{msg}")
        return "；".join(rows)

    def _api_failed_detail(self, key: str, error: object) -> None:
        code = str(getattr(error, "code", "") or "")
        base = str(getattr(error, "user_message", lambda: "请求失败")() or "请求失败")
        details = self._validation_error_text(error) if code == "INVALID_REQUEST" else ""
        message = f"参数校验失败：{details}" if details else base
        self._api_failed(key, message)

    def _api_failed(self, key: str, message: str) -> None:
        if key == "structure.models":
            handler = getattr(self, "_structure_models_failed", None)
            if callable(handler):
                handler(message)
            return
        if key == "structure.candidates":
            handler = getattr(self, "_structure_candidates_failed", None)
            if callable(handler):
                handler(message)
            return
        if key == "validation.run":
            handler = getattr(self, "_validation_platform_failed", None)
            if callable(handler):
                handler(message)
            return
        if not key.startswith("optimization."):
            return
        if key == "optimization.jobs.refresh":
            self.context.tasks.mark_backend_refresh_failed()
            return
        if key in {"optimization.scan.submit", "optimization.auto.submit", "optimization.tolerance.submit"}:
            target = "scan" if ".scan." in key else ("tolerance" if ".tolerance." in key else "optimization")
            # A 4xx submit failure means no backend job exists.  Restore the page
            # immediately instead of leaving the primary action disabled/spinning.
            if hasattr(self, "start_research_button") and target != "tolerance":
                self.start_research_button.setEnabled(True)
            if hasattr(self, "research_progress") and target != "tolerance":
                self.research_progress.setRange(0, 100)
                self.research_progress.setValue(0)
                self.research_progress.setFormat("%p%")
                self.research_progress.setVisible(False)
            if hasattr(self, "header_state"):
                self.header_state.set_value("待检查")
            display = f"请求未创建：{message}。请修正设置后重新提交；上方已完成结果仍然有效。"
            self._set_job_info(target, display)
            if target == "tolerance" and hasattr(self, "tolerance_run_button"):
                self.tolerance_run_button.setEnabled(True)
                if hasattr(self, "tolerance_result_panel"):
                    self.tolerance_result_panel.setVisible(True)
                if hasattr(self, "tolerance_notice"):
                    self.tolerance_notice.setText(display)
                    self.tolerance_notice.setVisible(True)
                if hasattr(self, "tolerance_status"):
                    self._set_info(self.tolerance_status, "状态", display)
            return
        if key.startswith("optimization.status."):
            self._finish_failure(key.rsplit(".", 1)[-1], message)
            return
        parsed = self._parse_result_key(key)
        if parsed:
            kind, token, job_id = parsed
            if self.lifecycle.generations.is_current(
                token, f"optimization-result:{kind}"
            ):
                self._finish_failure(job_id, message)
            return
        target = "scan" if ".scan." in key else ("tolerance" if ".tolerance." in key else "optimization")
        self._set_job_info(target, f"请求失败：{message}")
        if target == "tolerance" and hasattr(self, "tolerance_run_button"):
            self.tolerance_run_button.setEnabled(True)
            if hasattr(self, "tolerance_result_panel"):
                self.tolerance_result_panel.setVisible(True)
            if hasattr(self, "tolerance_notice"):
                self.tolerance_notice.setText(f"容差请求失败：{message}。参数没有被修改，可以修正连接或设置后重新开始分析。")
                self.tolerance_notice.setVisible(True)
            if hasattr(self, "tolerance_status"):
                self._set_info(self.tolerance_status, "状态", f"请求失败：{message}")

    def _schedule_result_render(
        self, job_id: str, kind: str, token: int, body: dict
    ) -> None:
        
        
        self._prepared_result_jobs[(kind, token)] = job_id
        self._result_preparer.submit(
            f"optimization-result:{kind}",
            token,
            lambda payload=deepcopy(body): self._prepare_result_payload(payload),
        )

    @staticmethod
    def _prepare_result_payload(payload: dict) -> dict:
        result = dict(payload or {})
        for key in ("parameter_grid", "history"):
            value = result.get(key)
            if value is not None and not isinstance(value, list):
                try:
                    result[key] = list(value)
                except TypeError:
                    result[key] = []
        return result

    def _prepared_result_ready(self, channel: str, token: int, payload: object) -> None:
        if not channel.startswith("optimization-result:"):
            return
        kind = channel.split(":", 1)[1]
        if not self.lifecycle.generations.is_current(token, channel):
            return
        job_id = self._prepared_result_jobs.pop((kind, token), "")
        if job_id:
            self._handle_result(job_id, dict(payload or {}))

    def _prepared_result_failed(self, channel: str, token: int, message: str) -> None:
        if not channel.startswith("optimization-result:"):
            return
        kind = channel.split(":", 1)[1]
        if not self.lifecycle.generations.is_current(token, channel):
            return
        job_id = self._prepared_result_jobs.pop((kind, token), "")
        if job_id:
            self._finish_failure(job_id, f"结果准备失败：{message}")

    def _poll_jobs(self) -> None:
        if self._centralized_polling:
            self._poll_timer.stop()
            return
        for job_id in list(self._jobs):
            task = self.context.tasks.find_by_job_id(job_id)
            if task and str(task.get("status", "")) in _TERMINAL:
                continue
            self.job_client.get_status(f"optimization.status.{job_id}", job_id)
        if not self._jobs:
            self._poll_timer.stop()

    def _ensure_job_info(self, job_id: str) -> dict | None:
        info = self._jobs.get(job_id)
        if info:
            return info
        task = self.context.tasks.find_by_job_id(job_id)
        if not task:
            return None
        info = {
            "kind": self._kind_from_task(task),
            "task_id": str(task.get("id", "")),
            "result_requested": False,
            "project_revision": str(task.get("project_revision", "") or ""),
        }
        self._jobs[job_id] = info
        return info

    def _handle_status(self, job_id: str, body: dict) -> None:
        info = self._ensure_job_info(job_id)
        if not info:
            
            self.context.tasks.upsert_backend_job({"job_id": job_id, **body})
            info = self._ensure_job_info(job_id)
            if not info:
                return
        status = str(body.get("status", "queued"))
        progress = self._progress_fraction(body.get("progress", 0.0))
        stage = str(body.get("stage", ""))
        tracker = getattr(self, "_progress_tracker", None)
        percent = tracker.value(job_id, status, progress) if tracker is not None else progress_percent(progress)
        progress = percent / 100.0
        stage_display = friendly_job_stage(stage)
        self.context.tasks.update_job(
            job_id,
            status=self._status_text(status),
            progress=percent,
            note=stage_display or f"job_id: {job_id}",
            result_available=bool(body.get("result_available", False)),
        )
        self.context.tasks.append_log(job_id, stage_display or self._status_text(status))
        loading_result = status == "completed" and not bool(info.get("result_requested", False))
        message = stable_progress_text(status, progress, loading_result=loading_result)
        if status == "running" and stage_display in {"正在保存结果", "正在整理结果"}:
            message = f"{stage_display} · {percent}%"
        self._set_job_info(info["kind"], message)
        self._update_research_progress(job_id, status, progress)
        if status == "completed" and not info.get("result_requested", False):
            self._request_job_result(job_id, info)
        elif status in {"failed", "cancelled"}:
            self._finish_failure(job_id, stage or self._status_text(status), status=status)

    def _handle_result(self, job_id: str, body: dict) -> None:
        info = self._ensure_job_info(job_id)
        if not info:
            return
        self.context.tasks.update_job(
            job_id, status="已完成", progress=100, note="后端任务已完成", result_available=True
        )
        body = dict(body or {})
        metadata = dict(body.get("metadata", {}) or {})
        if info.get("project_revision") and not metadata.get("project_revision"):
            metadata["project_revision"] = str(info.get("project_revision"))
        metadata.setdefault("source_job_id", str(job_id))
        body["metadata"] = metadata
        self.context.tasks.set_result(job_id, body)
        self.context.tasks.append_log(job_id, "正式结果已加载")
        loaded_results = getattr(self, "_loaded_result_jobs", None)
        if loaded_results is None:
            loaded_results = self._loaded_result_jobs = set()
        loaded_results.add(job_id)
        ensure_workspace = getattr(self, "_ensure_result_workspace", None)
        if callable(ensure_workspace):
            ensure_workspace(info["kind"])
        if info["kind"] == "scan":
            self._render_scan_result(body)
        elif info["kind"] == "tolerance":
            self._render_tolerance_result(body)
        else:
            self._render_optimization_result(body)
        self._update_research_progress(job_id, "completed", 1.0)
        if str(getattr(self, "_active_research_job_id", "")) == str(job_id):
            self._active_research_job_id = ""
        if hasattr(self, "_progress_tracker"):
            self._progress_tracker.forget(job_id)
        self._jobs.pop(job_id, None)
        self._refresh_history()
        if not self._jobs:
            self._poll_timer.stop()

    def _finish_failure(self, job_id: str, message: str, status: str = "failed") -> None:
        info = self._ensure_job_info(job_id)
        if not info:
            return
        text = self._status_text(status)
        raw_message = str(message)
        display_message = friendly_failure_message(raw_message)
        self.context.tasks.update_job(job_id, status=text, note=display_message)
        self.context.tasks.append_log(job_id, raw_message, level="ERROR")
        self.lifecycle.generations.invalidate(f"optimization-result:{info['kind']}")
        self._jobs.pop(job_id, None)
        self._set_job_info(info["kind"], stable_progress_text(text, 0.99))
        if hasattr(self, "start_research_button"):
            if hasattr(self.start_research_button, "set_task_state"):
                self.start_research_button.set_task_state("error", "任务失败")
                from PySide6.QtCore import QTimer
                QTimer.singleShot(1500, lambda: self.start_research_button.reset_task_state())
            else:
                self.start_research_button.setEnabled(True)
        if info.get("kind") == "tolerance" and hasattr(self, "tolerance_run_button"):
            self.tolerance_run_button.setEnabled(True)
            if hasattr(self, "tolerance_result_panel"):
                self.tolerance_result_panel.setVisible(True)
            if hasattr(self, "tolerance_notice"):
                self.tolerance_notice.setText(f"容差任务失败：{display_message}。请根据任务日志修正后重新运行；按钮已恢复可用。")
                self.tolerance_notice.setVisible(True)
            if hasattr(self, "tolerance_status"):
                self._set_info(self.tolerance_status, "状态", f"失败：{display_message}")
        if hasattr(self, "header_state"):
            self.header_state.set_value(text)
        if hasattr(self, "activity_label"):
            self.activity_label.setText(stable_progress_text(text, 0.99))
            self.activity_label.setToolTip(display_message)
        self._update_research_progress(job_id, text, 0.99)
        if str(getattr(self, "_active_research_job_id", "")) == str(job_id):
            self._active_research_job_id = ""
        self._refresh_history()
        if not self._jobs:
            self._poll_timer.stop()

    def _update_research_progress(self, job_id: str, status: object, progress: object) -> None:
        """Render progress for one active backend job without regressions or cross-job overwrite."""
        state = str(status or "").strip().lower()
        active = str(getattr(self, "_active_research_job_id", "") or "")
        if not active and state in {"running", "运行中", "submitting", "queued", "等待后端", "等待中"}:
            self._active_research_job_id = str(job_id)
            active = str(job_id)
        if str(job_id) != active:
            return
        tracker = getattr(self, "_progress_tracker", None)
        percent = tracker.value(job_id, status, progress) if tracker is not None else progress_percent(progress)
        info = dict(getattr(self, "_jobs", {}).get(str(job_id), {}) or {})
        is_tolerance = str(info.get("kind", "")) == "tolerance"
        bar = getattr(self, "tolerance_progress", None) if is_tolerance else getattr(self, "research_progress", None)
        if bar is None:
            return
        if is_tolerance:
            panel = getattr(self, "tolerance_progress_panel", None)
            if panel is not None:
                panel.setVisible(True)
            sync_height = getattr(self, "_sync_task_content_height", None)
            if callable(sync_height):
                sync_height()
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, sync_height)
            label = getattr(self, "tolerance_progress_label", None)
            if label is not None and state not in {"completed", "已完成", "failed", "失败", "cancelled", "已取消"}:
                label.setText("正在运行容差样本 · 结果将在下方原位更新")
            button = getattr(self, "tolerance_run_button", None)
        else:
            button = getattr(self, "start_research_button", None)
        if button is not None and hasattr(button, "set_task_state") and state not in {"completed", "已完成", "failed", "失败", "cancelled", "已取消", "not_converged", "未收敛"}:
            if not button.property("taskState") in {"running", "submitted"}:
                label_text = "分析中" if is_tolerance else (self._task_state_label("running") if hasattr(self, "_task_state_label") else "任务运行中")
                button.set_task_state("running", label_text)
        terminal = state in {"completed", "已完成", "failed", "失败", "cancelled", "已取消", "not_converged", "未收敛"}
        # 失败/取消时也保留最后进度和明确状态，避免进度条突然消失造成“跳回0/未运行”的错觉。
        bar.setVisible(True)
        bar.setRange(0, 100)
        bar.setValue(percent)
        if state in {"completed", "已完成"}:
            bar.setFormat("已完成 · 100%")
            if is_tolerance and hasattr(self, "tolerance_progress_label"):
                self.tolerance_progress_label.setText("容差分析完成")
        elif state in {"failed", "失败", "not_converged", "未收敛"}:
            bar.setFormat("任务失败")
            if is_tolerance and hasattr(self, "tolerance_progress_label"):
                self.tolerance_progress_label.setText("容差分析失败 · 请查看下方原因")
        elif state in {"cancelled", "已取消"}:
            bar.setFormat("已取消")
            if is_tolerance and hasattr(self, "tolerance_progress_label"):
                self.tolerance_progress_label.setText("容差分析已取消")
        else:
            bar.setFormat("%p%")

    def _on_ws_progress(self, job_id: str, progress: float, stage: str) -> None:
        info = self._ensure_job_info(job_id)
        if not info:
            return
        progress = self._progress_fraction(progress)
        tracker = getattr(self, "_progress_tracker", None)
        percent = tracker.value(job_id, "running", progress) if tracker is not None else progress_percent(progress)
        progress = percent / 100.0
        stage_display = friendly_job_stage(stage)
        self.context.tasks.update_job(
            job_id,
            status="运行中",
            progress=percent,
            note=stage_display or "后端正在处理",
        )
        message = stable_progress_text("running", progress)
        if stage_display in {"正在保存结果", "正在整理结果"}:
            message = f"{stage_display} · {percent}%"
        self._set_job_info(info["kind"], message)
        self._update_research_progress(job_id, "running", progress)

    def _on_ws_completed(self, job_id: str, status: str, _metrics: dict) -> None:
        info = self._ensure_job_info(job_id)
        if not info:
            return
        if status == "completed":
            self.context.tasks.update_job(
                job_id, status="已完成", progress=100, note="任务已完成，结果可读取", result_available=True
            )
            if not info.get("result_requested", False):
                self._request_job_result(job_id, info)
        elif status == "cancelled":
            self._finish_failure(job_id, "任务已取消", status=status)

    def _on_ws_failed(self, job_id: str, message: str) -> None:
        self._finish_failure(job_id, message)

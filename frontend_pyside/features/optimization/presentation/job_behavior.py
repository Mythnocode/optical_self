from __future__ import annotations

from copy import deepcopy

from frontend_pyside.features.optimization.guided_research import friendly_failure_message
from frontend_pyside.shared.task_display import progress_percent, stable_progress_text


_TERMINAL = {"已完成", "失败", "已取消", "未收敛"}


class OptimizationJobMixin:


    @staticmethod
    def _kind_from_task(task: dict) -> str:
        text = " ".join(str(task.get(key, "")) for key in ("name", "kind", "note"))
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
                token in name for token in ("参数扫描", "自动优化", "自动调参")
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
            if hasattr(self, "research_progress"):
                self.research_progress.setValue(max(0, min(100, progress)))
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
        if key in {"optimization.scan.submit", "optimization.auto.submit"}:
            job_id = str(data.get("job_id", ""))
            if not job_id:
                self._api_failed(key, "响应缺少 job_id")
                return
            kind = "scan" if key.endswith("scan.submit") else "optimization"
            task = self.context.tasks.add(
                "后端参数扫描" if kind == "scan" else "后端自动优化",
                "参数研究",
                "等待后端",
                0,
                f"job_id: {job_id}",
                page="optimization",
                job_id=job_id,
            )
            self._jobs[job_id] = {
                "kind": kind,
                "task_id": str(task["id"]),
                "result_requested": False,
            }
            self.context.tasks.append_log(str(task["id"]), "任务已提交到后端")
            self.job_watcher.subscribe(job_id)
            if not self._centralized_polling:
                self._poll_timer.start()
            self._set_job_info(kind, f"已提交 job {job_id}")
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

    def _api_failed(self, key: str, message: str) -> None:
        if not key.startswith("optimization."):
            return
        if key == "optimization.jobs.refresh":
            self.context.tasks.mark_backend_refresh_failed()
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
        target = "scan" if ".scan." in key else "optimization"
        self._set_job_info(target, f"请求失败：{message}")

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
        self.context.tasks.update_job(
            job_id,
            status=self._status_text(status),
            progress=round(progress * 100),
            note=stage or f"job_id: {job_id}",
        )
        self.context.tasks.append_log(job_id, stage or self._status_text(status))
        self._set_job_info(info["kind"], stable_progress_text(status, progress))
        if hasattr(self, "research_progress"):
            self.research_progress.setValue(round(progress * 100))
        if status == "completed" and not info.get("result_requested", False):
            self._request_job_result(job_id, info)
        elif status in {"failed", "cancelled"}:
            self._finish_failure(job_id, stage or self._status_text(status), status=status)

    def _handle_result(self, job_id: str, body: dict) -> None:
        info = self._ensure_job_info(job_id)
        if not info:
            return
        self.context.tasks.update_job(
            job_id, status="已完成", progress=100, note="后端任务已完成"
        )
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
        else:
            self._render_optimization_result(body)
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
            self.start_research_button.setEnabled(True)
        if hasattr(self, "header_state"):
            self.header_state.set_value(text)
        if hasattr(self, "activity_label"):
            self.activity_label.setText(stable_progress_text(text, 0.99))
            self.activity_label.setToolTip(display_message)
        if hasattr(self, "research_progress"):
            self.research_progress.setValue(0)
        self._refresh_history()
        if not self._jobs:
            self._poll_timer.stop()

    def _on_ws_progress(self, job_id: str, progress: float, stage: str) -> None:
        info = self._ensure_job_info(job_id)
        if not info:
            return
        progress = self._progress_fraction(progress)
        self.context.tasks.update_job(
            job_id,
            status="运行中",
            progress=round(progress * 100),
            note=stage or "后端正在处理",
        )
        self._set_job_info(info["kind"], stable_progress_text("running", progress))
        if hasattr(self, "research_progress"):
            self.research_progress.setValue(round(progress * 100))

    def _on_ws_completed(self, job_id: str, status: str, _metrics: dict) -> None:
        info = self._ensure_job_info(job_id)
        if not info:
            return
        if status == "completed":
            self.context.tasks.update_job(job_id, status="已完成", progress=100)
            if not info.get("result_requested", False):
                self._request_job_result(job_id, info)
        elif status == "cancelled":
            self._finish_failure(job_id, "任务已取消", status=status)

    def _on_ws_failed(self, job_id: str, message: str) -> None:
        self._finish_failure(job_id, message)

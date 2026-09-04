from __future__ import annotations

import re

from frontend_pyside.infrastructure.api.errors import ApiError


class TaskRemoteMixin:


    @staticmethod
    def _job_id(task: dict) -> str:
        value = str(task.get("job_id", ""))
        if value:
            return value
        match = re.search(r"job_id:\s*([^\s,]+)", str(task.get("note", "")))
        return match.group(1) if match else ""

    @staticmethod
    def _status_text(status: str) -> str:
        return {
            "queued": "等待后端",
            "running": "运行中",
            "completed": "已完成",
            "failed": "失败",
            "cancelled": "已取消",
        }.get(status, status or "未知")

    def refresh(self, tasks=None):
        
        self._all_tasks = self.context.tasks.tasks
        statuses = [self._normalized_status(task) for task in self._all_tasks]
        running = sum(status == "运行中" for status in statuses)
        waiting = sum(status == "等待中" for status in statuses)
        failed = sum(status == "失败" for status in statuses)
        paused = sum(status == "已暂停" for status in statuses)
        unfinished = running + waiting + paused
        history_count = sum(status in {"已完成", "已取消", "失败"} for status in statuses)

        self.unfinished_metric.set_value(unfinished, "个")
        self.running_metric.set_value(running, "个")
        self.waiting_metric.set_value(waiting, "个")
        self.failed_metric.set_value(failed, "个")
        if hasattr(self, "task_summary_bar"):
            completed_count = sum(status == "已完成" for status in statuses)
            self.task_summary_bar.set_items((("运行", running), ("等待", waiting), ("失败", failed), ("完成", completed_count)))
        self.queue_label.setText(
            "当前没有未完成任务"
            if unfinished == 0
            else f"{running} 运行 · {waiting} 等待 · {failed} 失败"
        )
        if hasattr(self, "status_donut"):
            self.status_donut.set_values(running=running, waiting=waiting, failed=0, paused=paused)
        if hasattr(self, "history_section"):
            self.history_section.header.setText(f"任务历史　{history_count} 个")
        self._apply_filter()

    def _request_remote_jobs(self, force: bool = False) -> None:
        if self.api_client is None or self._remote_list_pending:
            return
        if self._remote_list_available is False and not force:
            return
        if not self.context.tasks.should_refresh_backend(force=force):
            return
        self._remote_list_pending = True
        self.remote_state.setText("正在读取后端任务")
        self.remote_state.set_tone("info")
        self.job_client.list_jobs("tasks.list", limit=200)

    def _api_completed(self, key: str, data) -> None:
        if key == "tasks.list":
            self._remote_list_pending = False
            body = data if isinstance(data, dict) else {}
            jobs = data if isinstance(data, list) else body.get("items", body.get("jobs", []))
            if not isinstance(jobs, list):
                jobs = []
            raw_jobs = [item for item in jobs if isinstance(item, dict)]
            
            
            self.context.tasks.reconcile_backend_jobs(raw_jobs)
            self._remote_list_available = True
            self.remote_state.setText(f"已同步 {len(raw_jobs)} 个后端任务")
            self.remote_state.set_tone("success")
            self.refresh()
            return

        if key.startswith("tasks.cancel."):
            job_id = key.rsplit(".", 1)[-1]
            # Cancellation must not fabricate progress.  Preserve the last real
            # backend/UI progress until the authoritative status refresh arrives.
            current = self.context.tasks.find_by_job_id(job_id) or {}
            self.context.tasks.update_job(
                job_id,
                status="已取消",
                progress=current.get("progress", 0),
                note="后端已确认取消",
            )
            self.context.tasks.append_log(job_id, "后端已确认取消任务")
            self._request_remote_jobs(force=True)
            return

        if key.startswith("tasks.result."):
            job_id = key.rsplit(".", 1)[-1]
            task_id = self.context.tasks.set_result(job_id, data)
            self.context.tasks.append_log(job_id, "后端任务结果已下载并缓存")
            selected = self._selected_task()
            if selected and str(selected.get("id", "")) == task_id:
                self.artifact_text.setText(f"后端结果已缓存。\n{str(data)[:800]}")
                # A successful “查看结果” action must visibly take the user to
                # the result, not merely fill a hidden tab in the background.
                self.detail_tabs.setCurrentIndex(2)
            return

        if key.startswith("tasks.retry."):
            original_job_id = key.rsplit(".", 1)[-1]
            body = dict(data or {}) if isinstance(data, dict) else {}
            new_job_id = str(body.get("job_id", "") or "")
            pending = getattr(self, "_pending_retries", {})
            original = pending.pop(original_job_id, None) if isinstance(pending, dict) else None
            if not new_job_id:
                self.context.tasks.append_log(original_job_id, "后端接受了重试请求，但没有返回新的 job_id", level="ERROR")
                return
            enriched = dict(body)
            if isinstance(original, dict):
                enriched.setdefault("name", f"重试：{original.get('name', '任务')}")
                enriched.setdefault("kind", original.get("kind", body.get("job_type", "其他")))
                enriched.setdefault("page", original.get("page", "tasks"))
            new_task = self.context.tasks.upsert_backend_job(enriched)
            self.context.tasks.append_log(original_job_id, f"已重新提交为新任务 {new_job_id}")
            self.context.tasks.append_log(new_job_id, f"由任务 {original_job_id} 重新运行")
            if new_task:
                self._selected_task_override = new_task
                self._show_task_detail(new_task)
            self._request_remote_jobs(force=True)
            return

    def _api_failed_detail(self, key: str, error: object) -> None:
        detail = error if isinstance(error, ApiError) else ApiError(code="REQUEST_FAILED", message=str(error or "请求失败"))
        message = detail.user_message()
        if key.startswith("tasks.retry."):
            original_job_id = key.rsplit(".", 1)[-1]
            pending = getattr(self, "_pending_retries", {})
            if isinstance(pending, dict):
                pending.pop(original_job_id, None)
            self.context.tasks.append_log(original_job_id, f"重新运行失败：{message}（{detail.code}）", level="ERROR")
            self._request_remote_jobs(force=True)
            return
        if key.startswith("tasks.result.") and detail.code == "JOB_RESULT_NOT_AVAILABLE":
            job_id = key.rsplit(".", 1)[-1]
            self.context.tasks.update_job(job_id, result_available=False)
        self._api_failed(key, message)

    def _api_failed(self, key: str, message: str) -> None:
        if key == "tasks.list":
            self._remote_list_pending = False
            self.context.tasks.mark_backend_refresh_failed()
            self._remote_list_available = False
            self.remote_state.setText("后端尚未提供批量 jobs 路由，显示共享本地任务")
            self.remote_state.set_tone("warning")
            self.refresh()
            return

        if key.startswith("tasks.cancel."):
            job_id = key.rsplit(".", 1)[-1]
            self.context.tasks.update_job(job_id, note=f"取消任务失败：{message}")
            self.context.tasks.append_log(job_id, f"取消任务失败：{message}", level="ERROR")
            return

        if key.startswith("tasks.result."):
            job_id = key.rsplit(".", 1)[-1]
            self.context.tasks.append_log(job_id, f"获取结果失败：{message}", level="ERROR")
            selected = self._selected_task()
            if selected and self._job_id(selected) == job_id:
                self.log_text.setText(f"获取任务 {job_id[:12]} 结果失败：{message}")
            return

        if key.startswith("tasks.retry."):
            original_job_id = key.rsplit(".", 1)[-1]
            self.context.tasks.append_log(original_job_id, f"重新运行失败：{message}", level="ERROR")
            return

    def _cancel_selected(self):
        task = self._selected_task()
        if not task:
            return
        job_id = self._job_id(task)
        task_id = str(task.get("id", ""))
        if job_id:
            self.job_client.cancel(f"tasks.cancel.{job_id}", job_id)
            self.context.tasks.update_task(task_id, status="取消请求中", note="正在取消后端任务…")
            self.context.tasks.append_log(task_id, "已发送取消请求")
        else:
            self.context.tasks.update_task(
                task_id,
                status="已取消",
                progress=task.get("progress", 0),
                note="本地取消（无后端任务）",
            )

    def _view_selected_result(self):
        task = self._selected_task()
        if not task:
            return
        task_id = str(task.get("id", ""))
        cached = self.context.tasks.result(task_id)
        if cached is not None:
            self.artifact_text.setText(f"共享结果缓存：\n{str(cached)[:800]}")
            self.detail_tabs.setCurrentIndex(2)
            return
        job_id = self._job_id(task)
        if job_id and bool(task.get("result_available", False)):
            self.job_client.get_result(f"tasks.result.{job_id}", job_id)
            self.context.tasks.append_log(task_id, "正在获取后端结果")
        elif job_id:
            self.artifact_text.setText("该任务没有可用的正式结果。请查看任务状态和失败原因。")
            self.detail_tabs.setCurrentIndex(2)
            self.context.tasks.append_log(task_id, "未请求结果：后端状态表明 result_available=false")
        else:
            self.log_text.setText(
                f"本地任务没有后端结果可查看。\n任务：{task.get('name', '')}\n状态：{task.get('status', '')}"
            )

    def _open_selected_log(self):
        task = self._selected_task()
        if not task:
            return
        task_id = str(task.get("id", ""))
        rows = self.context.tasks.logs(task_id)
        if rows:
            self.log_text.setText(
                "\n".join(
                    f"{item.get('time', '')} [{item.get('level', 'INFO')}] {item.get('message', '')}"
                    for item in rows[-500:]
                )
            )
        else:
            note = task.get("note", "") or "无日志"
            self.log_text.setText(
                f"任务名称：{task.get('name', '')}\n"
                f"任务类型：{task.get('kind', '')}\n"
                f"状态：{task.get('status', '')}\n"
                f"进度：{task.get('progress', 0)}%\n"
                f"说明：{note}"
            )
        self.detail_tabs.setCurrentIndex(1)

    def _export_selected_record(self):
        task = self._selected_task()
        if not task:
            return
        from pathlib import Path
        import json

        payload = dict(task)
        payload["logs"] = self.context.tasks.logs(str(task.get("id", "")))
        payload["result"] = self.context.tasks.result(str(task.get("id", "")))
        path = Path.cwd() / "exports" / f"task_{task.get('id', 'unknown')}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        self.log_text.setText(f"任务记录已导出到：{path}")

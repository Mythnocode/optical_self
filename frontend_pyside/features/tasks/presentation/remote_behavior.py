from __future__ import annotations

from collections import Counter
import re


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
        self.queue_label.setText(
            "当前没有未完成任务"
            if unfinished == 0
            else f"{running} 运行 · {waiting} 等待 · {failed} 失败"
        )
        self.status_donut.set_values(
            running=running, waiting=waiting, failed=0, paused=paused
        )
        has_active = unfinished > 0
        self.status_donut.setVisible(has_active)
        if hasattr(self, "empty_chart_text"):
            self.empty_chart_text.setVisible(not has_active)
        attention = [
            task
            for task in self._all_tasks
            if self._normalized_status(task) in {"失败", "已暂停"}
        ]
        if attention:
            lines = []
            for task in attention[:6]:
                icon = "●" if self._normalized_status(task) == "失败" else "◆"
                lines.append(
                    f"{icon} {task.get('name', '未命名任务')}\n"
                    f"   {str(task.get('note', '') or self._normalized_status(task))[:90]}"
                )
            self.attention_text.setText("\n\n".join(lines))
        else:
            self.attention_text.setText("当前没有需要处理的任务。")
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
            self.context.tasks.update_job(
                job_id,
                status="已取消",
                progress=99,
                note="后端已确认取消",
            )
            self.context.tasks.append_log(job_id, "后端已确认取消任务")
            return

        if key.startswith("tasks.result."):
            job_id = key.rsplit(".", 1)[-1]
            task_id = self.context.tasks.set_result(job_id, data)
            self.context.tasks.append_log(job_id, "后端任务结果已下载并缓存")
            selected = self._selected_task()
            if selected and str(selected.get("id", "")) == task_id:
                self.artifact_text.setText(f"后端结果已缓存。\n{str(data)[:800]}")
            return

        if key.startswith("tasks.retry."):
            job_id = key.rsplit(".", 1)[-1]
            body = data if isinstance(data, dict) else {}
            self.context.tasks.upsert_backend_job({"job_id": job_id, **body})

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
                progress=99,
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
        if job_id:
            self.job_client.get_result(f"tasks.result.{job_id}", job_id)
            self.context.tasks.append_log(task_id, "正在获取后端结果")
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

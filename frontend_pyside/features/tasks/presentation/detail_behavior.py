from __future__ import annotations

from datetime import datetime

from frontend_pyside.shared.components.basic import InfoRow
from frontend_pyside.shared.task_display import progress_percent, stable_progress_text


class TaskDetailMixin:
    @staticmethod
    def _kind_text(value: object) -> str:
        text = str(value or "其他")
        mapping = {
            "simulation": "正式仿真",
            "scan": "参数扫描",
            "optimization": "自动优化",
            "dataset": "数据集生成",
            "headless_dataset": "无界面数据集任务",
            "training": "模型训练",
            "explainability": "模型解释",
            "teaching": "教学",
            "report": "报告",
        }
        return mapping.get(text.lower(), text)

    @staticmethod
    def _format_duration(seconds) -> str:
        if seconds is None:
            return "—"
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return "—"
        if value < 1:
            return f"{value * 1000:.0f} ms"
        if value < 60:
            return f"{value:.2f} s"
        return f"{value / 60:.1f} min"

    @staticmethod
    def _format_task_time(value: object, *, detailed: bool = False) -> str:
        text = str(value or "—")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone()
            return parsed.strftime("%Y-%m-%d %H:%M:%S" if detailed else "%m-%d %H:%M")
        except (TypeError, ValueError):
            clean = text.replace("T", " ")
            return clean[:19 if detailed else 16]

    @staticmethod
    def _normalized_status(task: dict) -> str:
        status = str(task.get("status", "未知"))
        if status in {"等待后端", "排队中", "queued", "等待资源"}:
            return "等待中"
        if status in {"运行中", "running", "取消请求中"}:
            return "运行中"
        if status in {"已完成", "completed"}:
            return "已完成"
        if status in {"失败", "failed", "未收敛"}:
            return "失败"
        if status in {"已暂停", "暂停", "paused"}:
            return "已暂停"
        if status in {"已取消", "cancelled"}:
            return "已取消"
        return status

    def _matches(self, task: dict) -> bool:
        text = self.search.text().strip().lower()
        localized_kind = self._kind_text(task.get("kind", ""))
        status = self._normalized_status(task)
        haystack = " ".join(
            [
                str(task.get("name", "")),
                str(task.get("kind", "")),
                localized_kind,
                status,
                str(task.get("note", "")),
            ]
        ).lower()
        if text and text not in haystack:
            return False
        selected_type = self.type_filter.currentText()
        if selected_type != "全部类型" and selected_type not in localized_kind:
            return False
        selected_status = self.status_filter.currentText()
        if selected_status == "全部未完成":
            return status in {"运行中", "等待中", "已暂停"}
        if selected_status == "等待中":
            return status == "等待中"
        if selected_status == "已暂停":
            return status == "已暂停"
        return selected_status == status

    def _apply_filter(self, *_):
        active = [task for task in self._all_tasks if self._matches(task)]
        self._visible_tasks = active
        rows: list[list[str]] = []
        tooltips: list[list[str]] = []
        for task in active:
            status = self._normalized_status(task)
            kind = self._kind_text(task.get("kind", "其他"))
            progress = progress_percent(task.get("progress", 0))
            note = str(task.get("note", "")) or (
                "等待资源" if status == "等待中" else "正在执行" if status == "运行中" else "需要处理"
            )
            stable = stable_progress_text(task.get("status", status), progress)
            rows.append(
                [
                    str(task.get("name", "未命名任务")),
                    kind,
                    status,
                    f"{progress}%",
                    stable,
                ]
            )
            tooltips.append(
                [
                    f"{self._format_task_time(task.get('time', '—'), detailed=True)}\n{note}",
                    kind,
                    status,
                    f"进度 {progress}%",
                    note,
                ]
            )
        self.table.set_rows(rows, tooltips=tooltips, align_columns=(1, 2, 3))
        if not active:
            self._clear_detail()

        completed = [
            task
            for task in self._all_tasks
            if self._normalized_status(task) in {"已完成", "已取消", "失败"}
        ]
        self._completed_tasks = completed
        completed_rows = [
            [
                self._format_task_time(task.get("time", "—")),
                str(task.get("name", "未命名任务")),
                self._kind_text(task.get("kind", "其他")),
                self._format_duration(task.get("duration_s")),
                (
                    "查看"
                    if self._normalized_status(task) == "已完成"
                    else self._normalized_status(task)
                ),
            ]
            for task in completed
        ]
        self.completed_table.set_rows(completed_rows, align_columns=(0, 2, 3, 4), eager_rows=50)
        self.history_section.header.setText(f"任务历史　{len(completed)} 个")

    def _task_at(self, row: int) -> dict | None:
        return self._visible_tasks[row] if 0 <= row < len(self._visible_tasks) else None

    def _selected_task(self) -> dict | None:
        override = getattr(self, "_selected_task_override", None)
        if override is not None:
            return override
        return self._task_at(self.table.currentRow())

    def _show_selected(self, row, *_):
        task = self._task_at(row)
        self._selected_task_override = None
        if not task:
            self._clear_detail()
            return
        self._show_task_detail(task)

    def _show_task_detail(self, task: dict) -> None:
        task_id = str(task.get("id", ""))
        self.context.tasks.set_current_task(task_id)
        status = self._normalized_status(task)
        tone = (
            "success"
            if status == "已完成"
            else "warning"
            if status in {"等待中", "运行中", "已暂停"}
            else "danger"
            if status in {"失败", "已取消"}
            else "info"
        )
        self.detail_badge.setText(status)
        self.detail_badge.set_tone(tone)
        self._set_info(self.detail_name, "任务名称", str(task.get("name", "—")))
        self._set_info(self.detail_kind, "任务类型", self._kind_text(task.get("kind", "—")))
        self._set_info(
            self.detail_time,
            "创建时间",
            self._format_task_time(task.get("time", "—"), detailed=True),
        )
        source = (
            "本地教学/快速预览"
            if self._kind_text(task.get("kind")) == "教学"
            or "预览" in str(task.get("note", ""))
            else "FastAPI 后端任务"
        )
        self._set_info(self.detail_source, "执行来源", source)
        self._set_info(
            self.detail_duration,
            "运行耗时",
            self._format_duration(task.get("duration_s")),
        )
        self._set_info(self.detail_note, "当前信息", str(task.get("note", "—")))
        progress = progress_percent(task.get("progress", 0))
        self.progress.setValue(progress)
        logs = self.context.tasks.logs(task_id)
        if logs:
            self.log_text.setText(
                "\n".join(
                    f"{item.get('time', '')} [{item.get('level', 'INFO')}] {item.get('message', '')}"
                    for item in logs[-500:]
                )
            )
        else:
            self.log_text.setText(
                f"[{self._format_task_time(task.get('time', '—'), detailed=True)}] 任务已创建。\n"
                f"当前状态：{status}，进度 {progress}%。"
            )
        cached_result = self.context.tasks.result(task_id)
        self.artifact_text.setText(
            f"共享结果缓存：\n{str(cached_result)[:800]}"
            if cached_result is not None
            else "当前任务尚未缓存结果产物。"
        )
        if hasattr(self, "retry_button"):
            self.retry_button.setEnabled(status in {"失败", "已取消"})
        if hasattr(self, "cancel_button"):
            self.cancel_button.setEnabled(status in {"运行中", "等待中", "已暂停"})
        if hasattr(self, "detail_section"):
            self.detail_section.set_expanded(True)

    @staticmethod
    def _set_info(widget: InfoRow, label: str, value: str) -> None:
        layout = widget.layout()
        if layout and layout.count() >= 2:
            layout.itemAt(0).widget().setText(label)
            layout.itemAt(1).widget().setText(value)

    def _clear_detail(self):
        self._selected_task_override = None
        self.detail_badge.setText("未选择")
        self.detail_badge.set_tone("info")
        for widget, label in (
            (self.detail_name, "任务名称"),
            (self.detail_kind, "任务类型"),
            (self.detail_time, "创建时间"),
            (self.detail_source, "执行来源"),
            (self.detail_duration, "运行耗时"),
            (self.detail_note, "当前信息"),
        ):
            self._set_info(widget, label, "—")
        self.progress.setValue(0)
        self.log_text.setText("选择任务后显示关键日志。")
        if hasattr(self, "retry_button"):
            self.retry_button.setEnabled(False)
        if hasattr(self, "cancel_button"):
            self.cancel_button.setEnabled(False)

    def _retry_selected(self):
        task = self._selected_task()
        if not task:
            return
        job_id = self._job_id(task)
        if job_id:
            self.job_client.get_status(f"tasks.retry.{job_id}", job_id)
            self.context.tasks.add(
                f"重试：{task.get('name', '任务')}",
                task.get("kind", "其他"),
                "等待后端",
                0,
                f"重新查询 job_id: {job_id}",
                page="tasks",
            )
        else:
            self.context.tasks.add(
                f"重试：{task.get('name', '任务')}",
                task.get("kind", "其他"),
                "等待后端",
                0,
                "由任务中心创建的重试任务（无关联后端job）",
                page="tasks",
            )

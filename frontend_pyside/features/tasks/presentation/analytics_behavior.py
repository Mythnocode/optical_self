from __future__ import annotations

from PySide6.QtCore import QThreadPool

from frontend_pyside.infrastructure.workers.worker import FunctionWorker
from frontend_pyside.shared.components.basic import Card


class TaskAnalyticsMixin:
    @staticmethod
    def _chart_card(title: str):
        
        from frontend_pyside.shared.plotting.canvas import PlotCanvas

        card = Card(title, compact=True)
        canvas = PlotCanvas()
        canvas.setMinimumHeight(250)
        card.body.addWidget(canvas, 1)
        return card, canvas

    def _selected_days(self) -> int:
        return 30 if "30" in self.period.currentText() else 7

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

    def _refresh_analytics(self, *_):
        if not hasattr(self, "analytics_state"):
            return
        if getattr(self, "_analytics_pending", False):
            return
        self._analytics_pending = True
        self.analytics_state.setText("正在后台统计")
        self.analytics_state.set_tone("info")
        worker = FunctionWorker(self.usage.summary, self._selected_days())
        workers = getattr(self, "_analytics_workers", None)
        if workers is None:
            workers = self._analytics_workers = set()
        workers.add(worker)
        worker.signals.result.connect(self._apply_analytics_summary)
        worker.signals.error.connect(self._analytics_failed)
        worker.signals.finished.connect(lambda w=worker: self._analytics_finished(w))
        QThreadPool.globalInstance().start(worker)

    def _analytics_finished(self, worker) -> None:
        self._analytics_pending = False
        getattr(self, "_analytics_workers", set()).discard(worker)

    def _analytics_failed(self, message: str) -> None:
        if hasattr(self, "analytics_state"):
            self.analytics_state.setText(f"统计失败：{message}")
            self.analytics_state.set_tone("danger")

    def _apply_analytics_summary(self, summary: dict) -> None:
        if not hasattr(self, "analytics_state"):
            return
        has_data = bool(summary.get("has_real_data"))
        self.analytics_state.setText("真实本地统计" if has_data else "暂无真实统计")
        self.analytics_state.set_tone("success" if has_data else "warning")

        self.today_card.set_value(summary.get("today_tasks", 0), "条", note="本机真实任务记录")
        rate = summary.get("completion_rate")
        self.rate_card.set_value("—" if rate is None else f"{rate:.1f}", "" if rate is None else "%", note="最近统计周期")
        average = summary.get("average_duration_s")
        self.average_card.set_value(self._format_duration(average), note="仅统计已记录耗时的任务")
        self.failed_card.set_value(summary.get("failures", 0), "条", note="不含取消任务")
        self.active_card.set_value(summary.get("active", 0), "条", note="运行、排队或等待后端")
        self.week_card.set_value(self._format_duration(summary.get("total_duration_s")), note=f"最近 {self._selected_days()} 天")
        compact = getattr(self, "task_compact_summary", None)
        if compact is not None:
            compact.setText(
                f"活动任务 {summary.get('active', 0)} · "
                f"失败任务 {summary.get('failures', 0)} · "
                f"今日任务 {summary.get('today_tasks', 0)}"
            )

        if not has_data:
            empty = {"kind": "empty", "message": "暂无真实统计\n完成任务后自动生成"}
            for _, canvas in (self.trend_chart, self.module_chart, self.status_chart, self.duration_chart):
                canvas.set_plot(empty)
            self.failure_text.setText("暂无真实失败记录。")
            self.duration_text.setText("暂无可统计的真实耗时记录。")
            self.page_text.setText("进入页面后开始记录本机页面访问次数。")
            return

        labels = summary.get("daily_labels", [])
        daily = summary.get("daily_task_counts", [])
        self.trend_chart[1].set_plot({"kind": "bar", "labels": labels, "values": daily, "title": f"最近 {self._selected_days()} 天任务数量", "x_label": "日期", "y_label": "任务数"})
        kinds = summary.get("kind_counts", {})
        self.module_chart[1].set_plot({"kind": "bar", "labels": list(kinds), "values": list(kinds.values()), "title": "各模块任务使用次数", "x_label": "任务类型", "y_label": "次数"} if kinds else {"kind": "empty", "message": "暂无模块任务记录"})
        statuses = summary.get("status_counts", {})
        self.status_chart[1].set_plot({"kind": "donut", "labels": list(statuses), "values": list(statuses.values()), "title": "任务状态占比"} if statuses else {"kind": "empty", "message": "暂无任务状态记录"})
        duration_by_kind = summary.get("average_duration_by_kind", {})
        max_duration_by_kind = summary.get("max_duration_by_kind", {})
        ordered_duration = sorted(duration_by_kind.items(), key=lambda item: item[1], reverse=True)
        duration_labels = [item[0] for item in ordered_duration]
        self.duration_chart[1].set_plot({"kind": "bar_grouped", "labels": duration_labels, "series": [{"label": "平均耗时", "values": [duration_by_kind[label] for label in duration_labels]}, {"label": "最长耗时", "values": [max_duration_by_kind.get(label, duration_by_kind[label]) for label in duration_labels]}], "title": "各模块平均与最长运行时间", "x_label": "任务类型", "y_label": "秒"} if ordered_duration else {"kind": "empty", "message": "尚无真实耗时记录"})

        errors = summary.get("error_counts", {})
        if errors:
            ordered = sorted(errors.items(), key=lambda item: item[1], reverse=True)
            self.failure_text.setText("\n".join(f"{index + 1}. {name}：{count} 次" for index, (name, count) in enumerate(ordered[:6])))
        else:
            self.failure_text.setText("当前统计周期内没有真实失败记录。")
        if ordered_duration:
            self.duration_text.setText("\n".join(f"{index + 1}. {kind}：平均 {self._format_duration(value)}，最长 {self._format_duration(max_duration_by_kind.get(kind))}" for index, (kind, value) in enumerate(ordered_duration[:6])))
        else:
            self.duration_text.setText("暂无可统计的真实耗时记录。")

        pages = summary.get("page_counts", {})
        if pages:
            page_names = {"home": "首页工作台", "simulation": "仿真系统", "optimization": "参数研究与优化", "machine_learning": "机器学习", "explainability": "模型解释", "teaching": "教学中心", "tasks": "任务中心"}
            ordered_pages = sorted(pages.items(), key=lambda item: item[1], reverse=True)
            self.page_text.setText("\n".join(f"{page_names.get(name, name)}：{count} 次" for name, count in ordered_pages[:8]))
        else:
            self.page_text.setText("暂无页面访问记录。")

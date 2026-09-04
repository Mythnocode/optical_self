from __future__ import annotations


class SimulationModeMixin:


    def set_work_mode(self, _mode: str = "unified") -> None:

        self._work_mode = "unified"

    def _enable_multipath_mode(self) -> None:
        if hasattr(self, "multipath_toggle"):
            self.multipath_toggle.setChecked(True)

    def _set_multipath_enabled(self, checked: bool) -> None:
        self.multipath_mode = bool(checked)
        self.settings.setValue("simulation/multipath_enabled", bool(checked))
        if checked:
            self.model_badge.setText("多路径正式计算")
            self.model_badge.set_tone("info")
            self.results.set_status(
                "已启用多路径高级模式；下一次提交将走多路径后端。",
                tone="info",
            )
        else:
            self.model_badge.setText("正式仿真由后端执行")
            self.model_badge.set_tone("info")
            self.results.set_status("已使用普通正式仿真模式。", tone="info")
        self._refresh_submission_state()

    def _remember_splitter(self, *_args) -> None:
        sizes = [int(value) for value in self.main_splitter.sizes()]
        if len(sizes) == 2 and sizes[0] >= 300 and sizes[1] >= 420:
            
            
            self.settings.setValue("simulation/unified_splitter_sizes", sizes)
            self.workspace_state.save_splitter("main", self.main_splitter)
            self._main_splitter_initialized = True

    def _auto_preview_toggled(self, checked: bool) -> None:
        self.settings.setValue("simulation/auto_preview", bool(checked))
        if checked:
            self.preview_state.setText("自动快速预览已开启")
            self.preview_state.set_tone("success")
            if self._manual_preview_requested:
                self.preview_scheduler.schedule(high_quality=True)
        else:
            self.preview_scheduler.cancel()
            self.preview_state.setText("快速预览需手动刷新")
            self.preview_state.set_tone("info")

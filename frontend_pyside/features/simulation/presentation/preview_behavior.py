from __future__ import annotations

from copy import deepcopy
from time import perf_counter

from frontend_pyside.features.simulation.result_adapter import preview_result_to_plots


class SimulationPreviewMixin:
    @staticmethod
    def _apply_candidate_changes_to_snapshot(project, changes: dict) -> None:
        for path, raw in dict(changes or {}).items():
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if path == "source.wavelength_nm":
                project.wavelength_nm = value
            elif path == "receiver.mode_field_diameter_x_um":
                project.receiver_mfd_um = value
            elif path.startswith("surfaces["):
                try:
                    index = int(path.split("[", 1)[1].split("]", 1)[0])
                    field = path.split("].", 1)[1]
                except (ValueError, IndexError):
                    continue
                if 0 <= index < len(project.surfaces):
                    if field == "distance_to_next_mm":
                        project.surfaces[index].thickness_mm = value
                    elif field == "radius_mm":
                        project.surfaces[index].radius_mm = value



    def _geometry_changed(self) -> None:
        try:
            signature = self._current_geometry_signature()
            if signature and signature == self._last_geometry_signature:
                return
            self._last_geometry_signature = signature
        except Exception:
            pass
        self._update_instant_efficiency_cards()
        self.session.mark_geometry()
        self._publish_active_simulation_project()
        self.schedule_preview()
        self._refresh_submission_state()

    def _form_changed(self) -> None:
        try:
            state = self.params.collect_state()
            signature = self._current_form_signature(state)
            if signature and signature == self._last_form_signature:
                return
            self._last_form_signature = signature
        except Exception:
            state = None
        self._update_instant_efficiency_cards()
        try:
            if state is None:
                state = self.params.collect_state()
            self.session.mark_form(state)
            self._publish_active_simulation_project(state)
        except Exception:
            self.session.mark_geometry()
            self._publish_active_simulation_project()
        self.schedule_preview()
        self._refresh_submission_state()

    def schedule_preview(self) -> None:
        self._manual_preview_requested = True
        self.preview_state.setText("参数已修改")
        self.preview_state.set_tone("warning")
        if self.auto_preview.isChecked():
            self.preview_state.setText("先更新二维截面，随后更新三维预览")
            self.preview_scheduler.schedule(high_quality=True)

    def _manual_preview(self) -> None:
        self._record_preview_usage = True
        self._manual_preview_requested = True
        self.preview_scheduler.request_now(high_quality=True)

    def run_preview(self) -> None:
        
        self._manual_preview()

    def _prepare_preview_stage(self, generation: int, quality: str) -> None:
        if not self.preview_scheduler.is_current(generation):
            return
        self.preview_state.setText(
            "正在更新二维截面"
            if quality == "section"
            else "正在更新简化三维"
            if quality == "interactive"
            else "正在更新高质量预览"
        )
        self.preview_state.set_tone("warning")
        project_snapshot = deepcopy(self.context.project.project)
        candidate_changes = deepcopy(dict(getattr(self, "_candidate_preview_changes", {}) or {}))
        if candidate_changes:
            self._apply_candidate_changes_to_snapshot(project_snapshot, candidate_changes)
        profile = self.context.services.ui_preferences.render_profile
        ray_limit = int(profile.representative_rays)

        def prepare():
            started = perf_counter()
            data = self.preview_workflow.run(project=project_snapshot, quality=quality, parameter_changes=candidate_changes)
            self._limit_preview_rays(data, ray_limit)
            return data, max(0.0, perf_counter() - started)

        self.preview_preparer.submit(f"simulation-preview:{quality}", generation, prepare)

    @staticmethod
    def _limit_preview_rays(data: dict, limit: int) -> None:
        limit = max(1, int(limit))
        for record in data.values():
            if not isinstance(record, dict):
                continue
            rays = list(record.get("rays", []) or [])
            if len(rays) <= limit:
                continue
            indices = sorted(
                set(
                    round(index * (len(rays) - 1) / max(1, limit - 1))
                    for index in range(limit)
                )
            )
            record["full_ray_count"] = len(rays)
            record["rays"] = [rays[index] for index in indices]
            record["display_ray_count"] = len(indices)

    def _preview_prepared(self, channel: str, generation: int, payload: object) -> None:
        if not bool(getattr(self, "_page_active", True)):
            return
        if not channel.startswith("simulation-preview:"):
            return
        if not self.preview_scheduler.is_current(generation):
            return
        quality = channel.split(":", 1)[1]
        data, elapsed_s = payload if isinstance(payload, tuple) and len(payload) == 2 else ({}, 0.0)
        data = dict(data or {})
        metrics = dict(data.pop("__metrics__", {}) or {})
        data.pop("__quality__", None)
        if metrics:
            if dict(getattr(self, "_candidate_preview_changes", {}) or {}):
                setter = getattr(self, "_set_candidate_preview_metrics", None)
                if callable(setter):
                    setter(metrics)
            else:
                self.context.project.update_metrics(metrics)

        plots = preview_result_to_plots(data)
        for index, plot in enumerate(plots.values()):
            plot.setdefault("render_key", f"preview:{quality}:{generation}:{index}")
            if quality != "high":
                plot.setdefault("render_quality", "interactive")

        if quality == "section":
            self.results.merge_results(plots)
            self.results.set_status("二维光路已更新。", tone="info")
            return
        if quality == "interactive":
            self.results.merge_results(plots)
            self.results.set_status("简化三维预览已更新；当前视图保持不变。", tone="info")
            return
        self._display_preview(data, float(elapsed_s))

    def _preview_prepare_failed(self, channel: str, generation: int, message: str) -> None:
        if channel.startswith("simulation-preview:") and self.preview_scheduler.is_current(generation):
            self._preview_failed(message)

    def _display_preview(self, data: dict, elapsed_s: float) -> None:
        metrics = dict(data.pop("__metrics__", {}) or {}) if isinstance(data, dict) else {}
        if metrics:
            if dict(getattr(self, "_candidate_preview_changes", {}) or {}):
                setter = getattr(self, "_set_candidate_preview_metrics", None)
                if callable(setter):
                    setter(metrics)
            else:
                self.context.project.update_metrics(metrics)
        plots = preview_result_to_plots(data)
        for index, plot in enumerate(plots.values()):
            plot.setdefault("render_key", f"preview:high:{index}:{elapsed_s:.9f}")
        self.results.set_results(plots)
        self.results.set_status("高质量快速预览已更新；它不会提交正式任务。", tone="info")

        project = self.context.project.project
        self._update_instant_efficiency_cards()
        preview_efficiency = project.metrics.get("coupling_efficiency")
        if preview_efficiency is not None:
            self.cards["coupling_eff"].set_value(
                f"{100.0 * float(preview_efficiency):.2f}", "%", note="快速预览"
            )
        if dict(getattr(self, "_candidate_preview_changes", {}) or {}):
            self.preview_state.setText("候选预览已同步 · 待正式验证")
            self.preview_state.set_tone("warning")
            self.results.set_status("候选快速预览已同步；尚未写入当前系统。", tone="warning")
        else:
            self.preview_state.setText("预览已同步")
            self.preview_state.set_tone("success")
        self._manual_preview_requested = False

        if self._record_preview_usage:
            self.context.tasks.add(
                "多透镜系统快速预览",
                "仿真",
                "已完成",
                100,
                "手动快速预览，不作为正式研究数据",
                page="simulation",
                duration_s=float(elapsed_s),
            )
        self._record_preview_usage = False

    def _preview_failed(self, message: str) -> None:
        self.results.set_status(f"快速预览失败：{message}", tone="danger")
        self.preview_state.setText("预览失败")
        self.preview_state.set_tone("danger")
        self.cards["coupling_eff"].set_value("—", "%", note="预览失败")
        self._record_preview_usage = False

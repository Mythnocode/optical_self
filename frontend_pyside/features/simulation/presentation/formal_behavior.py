from __future__ import annotations

import logging
from time import perf_counter

from PySide6.QtCore import QThreadPool, QTimer

from frontend_pyside.shared.task_display import extract_error_message, stable_progress_text
from frontend_pyside.shared.performance import record_perf
from frontend_pyside.infrastructure.workers.worker import FunctionWorker

from frontend_pyside.features.simulation.alignment import (
    alignment_solution_from_result,
    alignment_summary,
)
from frontend_pyside.features.simulation.formal_result_store import FormalResultStore
from frontend_pyside.features.simulation.result_adapter import formal_result_diagnostics


_logger = logging.getLogger(__name__)


def _estimated_dense_elements(body: dict) -> int:

    arrays = body.get("arrays") if isinstance(body, dict) else None
    if not isinstance(arrays, dict):
        return 0
    total = 0
    for value in arrays.values():
        shape = getattr(value, "shape", None)
        size = getattr(value, "size", None)
        if isinstance(size, (int, float)):
            total += int(size)
            continue
        if isinstance(value, list):
            rows = len(value)
            cols = len(value[0]) if rows and isinstance(value[0], list) else 1
            depth = len(value[0][0]) if rows and cols and isinstance(value[0], list) and value[0] and isinstance(value[0][0], list) else 1
            total += rows * max(1, cols) * max(1, depth)
        elif shape:
            product = 1
            for item in shape:
                product *= int(item)
            total += product
    return total


def _materialize_formal_result(body: dict, submitted_project: dict, section_options: dict, visible: tuple[str, ...]):
    started = perf_counter()
    store = FormalResultStore(body, submitted_project, section_options=section_options)
    plots = store.ensure(visible)
    return store, plots, (perf_counter() - started) * 1000.0


class SimulationFormalMixin:
    def submit_formal(self) -> None:
        self.controller.mark_user_submit()
        self._partial_plot_rendered = False
        try:
            state = self.params.collect_state()
        except Exception as exc:
            self._formal_failed("form", f"参数读取失败：{exc}")
            return
        submitted = self.controller.submit(
            self.context.project.project,
            state,
            visible_views=self.results.visible_result_keys(),
            multipath=self.multipath_mode,
        )
        if submitted:
            self.results.set_busy(True)
            self._set_coupling_note("正在准备正式计算")
            self.model_badge.setText("按需正式计算")
            self.model_badge.set_tone("warning")

    def _display_partial_result(self, payload: dict) -> None:

        if not isinstance(payload, dict):
            return
        metrics = payload.get("metrics")
        if isinstance(metrics, dict) and metrics:
            self.context.project.update_metrics(dict(metrics))
            self._update_formal_metric_cards(dict(metrics))

        preview = payload.get("preview_result")
        if (
            bool(getattr(self, "_page_active", True))
            and isinstance(preview, dict)
            and isinstance(preview.get("arrays"), dict)
            and preview.get("arrays")
        ):
            
            
            
            expected_fingerprint = str(
                getattr(self.controller, "_pending_fingerprint", "") or ""
            )
            QTimer.singleShot(
                0,
                lambda preview_body=dict(preview), analysis=str(payload.get("analysis", "") or ""), expected=expected_fingerprint:
                self._apply_partial_preview(preview_body, analysis, expected),
            )

        if not isinstance(metrics, dict) or not metrics:
            return
        stage = str(payload.get("stage", "") or "")
        self._set_coupling_note(
            "核心数值已返回，图表继续生成"
            if not bool(getattr(self, "_partial_plot_rendered", False))
            else "核心数值与当前图表预览已返回"
        )
        self.model_badge.setText("核心结果已返回")
        self.model_badge.set_tone("warning")
        self.model_badge.setToolTip(stage or "后端继续生成正式图表与诊断结果")

    def _apply_partial_preview(
        self, preview: dict, analysis: str = "", expected_fingerprint: str = ""
    ) -> None:
        if not bool(getattr(self, "_page_active", True)):
            return
        
        
        
        if bool(getattr(self.controller, "_live_result_displayed", False)):
            return
        if not bool(getattr(self.controller, "is_running", False)):
            return
        current_fingerprint = str(
            getattr(self.controller, "_pending_fingerprint", "") or ""
        )
        if expected_fingerprint and expected_fingerprint != current_fingerprint:
            return
        try:
            visible = tuple(self.results.visible_result_keys())
            preview_store = FormalResultStore(
                preview,
                dict(self.controller.last_project_payload or {}),
                section_options=self.results.section_options(),
            )
            plots = preview_store.ensure(visible)
            if not plots:
                return
            self.results.merge_results(plots)
            if not bool(getattr(self, "_partial_plot_rendered", False)):
                self._partial_plot_rendered = True
                record_perf(
                    "simulation_click_to_first_preview_plot",
                    self.controller.elapsed_since_submit_ms(),
                    views=sorted(plots),
                    analysis=str(analysis or ""),
                )
        except Exception:
            
            
            _logger.debug("正式结果预览绘制失败，等待完整结果。", exc_info=True)

    def _formal_plot_rendered(self, key: str, render_key: str) -> None:
        started = float(getattr(self, "_formal_result_received_perf", 0.0) or 0.0)
        if started <= 0.0:
            return
        elapsed_ms = (perf_counter() - started) * 1000.0
        self._formal_result_received_perf = 0.0
        record_perf(
            "simulation_frontend_received_to_plot_rendered",
            elapsed_ms,
            view=str(key),
            render_key=str(render_key),
        )
        record_perf(
            "simulation_click_to_plot_rendered",
            self.controller.elapsed_since_submit_ms(),
            view=str(key),
        )

    def _formal_state_changed(self, status: str, progress: float, note: str) -> None:
        display = stable_progress_text(status, progress)
        self._set_coupling_note(display)
        self.model_badge.setText(display)
        self.model_badge.set_tone(
            "warning" if status in {"submitting", "queued", "running", "cancelled"}
            else ("danger" if status == "failed" else "success")
        )
        
        
        self.model_badge.setToolTip(str(note or ""))
        if status in {"failed", "cancelled"} and note:
            self.results.set_status(
                str(note), tone="warning" if status == "cancelled" else "danger"
            )

    def _display_formal_result(self, body: dict, submitted_project: dict) -> None:
        body = dict(body or {})
        prebuilt = body.pop("__frontend_materialized__", None)
        if prebuilt is None:
            self._formal_result_received_perf = perf_counter()
        if not bool(getattr(self, "_page_active", True)):
            self._pending_formal_result = (body, dict(submitted_project or {}))
            return
        status = str(body.get("status", "failed"))
        if status != "completed":
            self.results.set_busy(False)
            message = extract_error_message(
                body,
                "任务已取消" if status == "cancelled" else "仿真内部失败",
            )
            self._formal_store = None
            self._formal_failed(status, message)
            return
        converged = bool(body.get("converged", False))
        metrics = dict(body.get("metrics", {})) if isinstance(body.get("metrics"), dict) else {}
        if metrics:
            self.context.project.update_metrics(metrics)
            self._update_formal_metric_cards(metrics)

        visible = tuple(self.results.visible_result_keys())
        if prebuilt is None and _estimated_dense_elements(body) >= 100_000:
            self.results.set_status("核心数值已显示，正在后台准备当前图表。", tone="info")
            worker = FunctionWorker(
                _materialize_formal_result,
                body,
                dict(submitted_project or {}),
                dict(self.results.section_options()),
                visible,
            )
            self._formal_workers.add(worker)

            def apply_materialized(value, *, _worker=worker, _body=body, _project=dict(submitted_project or {})):
                store, plots, elapsed_ms = value
                record_perf(
                    "simulation_result_materialization_worker",
                    elapsed_ms,
                    views=list(visible),
                )
                payload = dict(_body)
                payload["__frontend_materialized__"] = (store, plots)
                self._display_formal_result(payload, _project)

            worker.signals.result.connect(apply_materialized)
            worker.signals.error.connect(lambda message: self._formal_failed("frontend_render", message))
            worker.signals.finished.connect(lambda _worker=worker: self._formal_workers.discard(_worker))
            QThreadPool.globalInstance().start(worker)
            return

        self.results.set_busy(False)
        if prebuilt is not None:
            self._formal_store, plots = prebuilt
        else:
            self._formal_store = FormalResultStore(
                body,
                submitted_project,
                section_options=self.results.section_options(),
            )
            plots = self._formal_store.ensure(visible)
        self.results.set_results(plots)
        missing_visible = [key for key in visible if key not in plots]
        auto_retry_missing = False
        if missing_visible:
            retry_key: tuple[str, tuple[str, ...]] | None = None
            try:
                current_state = self.params.collect_state()
                fingerprint = self.controller.invalidate_views(
                    self.context.project.project, current_state, missing_visible
                )
                retry_key = (fingerprint, tuple(sorted(missing_visible)))
            except Exception:
                _logger.warning("无法生成缺失分析的重试指纹，自动补算已跳过。", exc_info=True)
                retry_key = None
            if retry_key is not None and retry_key not in self._missing_plot_retry_keys:
                self._missing_plot_retry_keys.add(retry_key)
                auto_retry_missing = True
                message = (
                    "正式任务已完成，但当前分析没有返回可绘制数组；系统将只补算："
                    + "、".join(missing_visible)
                )
            else:
                message = (
                    "自动补算后仍未返回可绘制数组："
                    + "、".join(missing_visible)
                    + "。请查看任务日志或手动重新计算。"
                )
            self.results.set_result_pending(message)
        else:
            self._missing_plot_retry_keys.clear()

        diagnostics = formal_result_diagnostics(body)
        metadata = dict(body.get("metadata", {}) or {})
        cache_status = str(metadata.get("frontend_cache_status", ""))
        if cache_status:
            diagnostics += f"\n前端缓存：{cache_status}；已具备分析：" + "、".join(
                metadata.get("frontend_cached_analyses", []) or []
            )
        self._alignment_solution = alignment_solution_from_result(body)
        self.apply_alignment_button.setVisible(
            bool(self._alignment_solution and self._alignment_solution.accepted)
        )
        if self._alignment_solution is not None:
            diagnostics = f"{diagnostics}\n{alignment_summary(self._alignment_solution)}"
        self.diagnostic_text.setText(diagnostics)

        try:
            accepted_state = self.params.collect_state()
            self.session.accept(accepted_state)
            self._last_form_signature = self._current_form_signature(accepted_state)
            self._last_geometry_signature = self._current_geometry_signature()
        except Exception:
            _logger.warning("正式结果已返回，但会话状态同步失败。", exc_info=True)
        self._refresh_submission_state()

        if status == "completed":
            sampling = ""
            if isinstance(metadata.get("sampling"), dict):
                sampling = " / ".join(f"{key}={value}" for key, value in metadata["sampling"].items())
            self.results.set_result_valid(
                version=str(getattr(self.context.project.project, "version", "")),
                generated_at=str(metadata.get("completed_at", metadata.get("generated_at", "")) or "") or None,
                algorithm=str(metadata.get("engine_version", metadata.get("engine_name", "")) or ""),
                sampling=sampling,
                converged=converged,
            )
            tone = "success" if converged else "warning"
            self._set_coupling_note("正式仿真完成" if converged else "完成但未收敛")
            self.model_badge.setText("正式结果" if converged else "正式结果·未收敛")
            self.model_badge.set_tone(tone)
            note = (
                "当前分析缺少可绘制数组，正在自动补算。"
                if missing_visible else "当前可见结果已从正式缓存同步。"
            )
            if cache_status == "hit":
                note = "相同参数已直接复用缓存，没有重新运行后端。"
            elif metadata.get("frontend_submitted_analyses"):
                note = "本次仅补算：" + "、".join(metadata["frontend_submitted_analyses"])
            self.results.set_status(note, tone=tone)
            if not missing_visible or auto_retry_missing:
                self._schedule_auto_submit_visible()
            return

    def _visible_results_changed(self, keys: object) -> None:
        if self._formal_store is not None:
            plots = self._formal_store.ensure(tuple(keys or ()))
            if plots:
                self.results.merge_results(plots)
        self._refresh_submission_state()
        self._schedule_auto_submit_visible()

    def _schedule_auto_submit_visible(self) -> None:

        if not bool(getattr(self, "_page_active", True)):
            return
        if self.controller.is_running or self._auto_submit_scheduled:
            return
        try:
            state = self.params.collect_state()
            planned = set(
                self.controller.planned_analyses(
                    state, self.results.visible_result_keys()
                )
            )
            cached = set(
                self.controller.cached_analyses(
                    self.context.project.project,
                    state,
                    self.results.visible_result_keys(),
                )
            )
        except Exception:
            _logger.warning("无法判断可见分析是否需要补算。", exc_info=True)
            return
        if not self.session.dirty.is_dirty and not (planned - cached):
            return
        self._auto_submit_scheduled = True
        QTimer.singleShot(0, self._auto_submit_visible)

    def _auto_submit_visible(self) -> None:
        self._auto_submit_scheduled = False
        if not self.controller.is_running:
            self.submit_formal()

    def _section_options_changed(self, options: dict) -> None:
        if self._formal_store is None or self._formal_store.ray_dataset is None:
            return
        visible = self.results.visible_result_keys()
        plots = self._formal_store.update_section(
            options, requested_keys=visible
        )
        if plots:
            self.results.merge_results(plots)
        self.results.set_status(
            "二维截面与三维截面平面已从同一份正式光线缓存更新；未访问后端。",
            tone="success",
        )

    def _apply_alignment_solution(self) -> None:
        solution = self._alignment_solution
        if solution is None or not solution.accepted:
            self.results.set_status("当前正式结果没有可应用的五轴最优值。", tone="warning")
            return
        self.params.apply_alignment_solution(solution)
        if hasattr(self.params, "expand_section"):
            self.params.expand_section("fiber")
        self.apply_alignment_button.setVisible(False)
        self.results.set_status("五轴最优值已写回；只需重新计算耦合相关结果。", tone="success")

    def _formal_failed(self, category: str, message: str) -> None:
        self.results.set_busy(False)
        self._alignment_solution = None
        self.apply_alignment_button.setVisible(False)
        cancelled = category == "cancelled"
        self._set_coupling_note("正式仿真已取消" if cancelled else "正式仿真失败")
        self.model_badge.setText("正式任务已取消" if cancelled else "后端任务失败")
        self.model_badge.set_tone("warning" if cancelled else "danger")
        self.results.set_status(message, tone="warning" if cancelled else "danger")
        self.results.set_result_error(message)
        self.diagnostic_text.setText(f"错误类别：{category}\n{message}")
        self._refresh_submission_state()

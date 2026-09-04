
from __future__ import annotations

from time import perf_counter
from typing import Any, Iterable
import logging

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from frontend_pyside.shared.task_display import extract_error_message, friendly_job_stage, terminal_progress
from frontend_pyside.shared.lifecycle import safe_single_shot
from frontend_pyside.shared.performance import record_perf
from frontend_pyside.infrastructure.local_array_transport import materialize_local_arrays
from frontend_pyside.infrastructure.workers.worker import FunctionWorker

from frontend_pyside.features.simulation.analysis_planner import plan_analyses
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.features.simulation.execution_policy import is_layout_only, state_for_analyses
from frontend_pyside.features.simulation.payloads import build_multipath_payload, build_simulation_payload
from frontend_pyside.features.simulation.request_fingerprint import physical_fingerprint
from frontend_pyside.features.simulation.result_cache import SimulationResultCache
from frontend_pyside.features.simulation.incremental_preview import (
    dependency_keys_for_payload,
    receiver_field_preview,
)





_SHARED_FORMAL_RESULT_CACHE = SimulationResultCache(max_entries=24)
_logger = logging.getLogger(__name__)
from frontend_pyside.infrastructure.api.clients import JobClient, MultiPathClient, SimulationClient


class SimulationController(QObject):
    previewReady = Signal(object, float)
    previewFailed = Signal(str)
    stateChanged = Signal(str, float, str)
    partialResultReady = Signal(object)
    formalResultReady = Signal(object, object)
    formalFailed = Signal(str, str)
    jobChanged = Signal(str)

    def __init__(self, context, preview_workflow, parent=None):
        super().__init__(parent)
        self.context = context
        self.preview_workflow = preview_workflow
        self.api_client = context.api_client
        self.simulation_client = SimulationClient(self.api_client)
        self.multipath_client = MultiPathClient(self.api_client)
        self.job_client = JobClient(self.api_client)
        self.job_watcher = context.services.job_watcher
        self._centralized_polling = bool(getattr(self.job_watcher, "centralized_polling", False))
        self.result_cache = _SHARED_FORMAL_RESULT_CACHE

        self.current_job_id = ""
        self.current_task_id = ""
        self.last_project_payload: dict[str, Any] = {}
        self._multipath = False
        self._polling_allowed = True
        self._submission_pending = False
        self._pending_fingerprint = ""
        self._pending_submitted_analyses: frozenset[str] = frozenset()
        self._pending_requested_analyses: frozenset[str] = frozenset()
        self._perf_click_started = 0.0
        self._perf_submission_accepted = 0.0
        self._perf_job_started = 0.0
        self._perf_result_requested = 0.0
        self._perf_result_received = 0.0
        self._last_progress_signature: tuple[int, str] | None = None
        self._last_partial_version = 0
        self._result_request_job_id = ""
        self._analysis_result_requested = ""
        self._analysis_result_fallback_used = False
        self._pending_options: dict[str, Any] = {}
        self._local_result_requested_job_id = ""
        self._live_result_displayed = False
        self._live_result_body: dict[str, Any] | None = None
        self._terminal_completed_job_id = ""
        self._surrogate_request_fingerprint = ""
        self._surrogate_request_id = ""
        self._submission_request_id = ""
        
        
        
        self._preview_quality_rank = 0
        self._fast_workers: set[object] = set()

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1000)
        self.poll_timer.timeout.connect(self._poll_job)

        self.api_client.completed.connect(self._api_completed)
        self.api_client.failed.connect(self._api_failed)
        self.job_watcher.job_progress.connect(self._on_ws_progress)
        if hasattr(self.job_watcher, "job_partial"):
            self.job_watcher.job_partial.connect(self._on_ws_partial)
        self.job_watcher.job_completed.connect(self._on_ws_completed)
        self.job_watcher.job_failed.connect(self._on_ws_failed)

    @property
    def is_running(self) -> bool:
        return self._submission_pending or bool(self.current_job_id)

    def mark_user_submit(self) -> None:

        self._perf_click_started = perf_counter()
        self._perf_submission_accepted = 0.0
        self._perf_job_started = 0.0
        self._perf_result_requested = 0.0
        self._perf_result_received = 0.0
        self._last_progress_signature = None
        self._last_partial_version = 0
        self._result_request_job_id = ""
        self._analysis_result_requested = ""
        self._analysis_result_fallback_used = False
        self._pending_options = {}
        self._local_result_requested_job_id = ""
        self._live_result_displayed = False
        self._live_result_body = None
        self._terminal_completed_job_id = ""
        self._surrogate_request_fingerprint = ""
        self._surrogate_request_id = ""
        self._submission_request_id = ""
        self._preview_quality_rank = 0

    def elapsed_since_submit_ms(self) -> float:
        if self._perf_click_started <= 0.0:
            return 0.0
        return max(0.0, (perf_counter() - self._perf_click_started) * 1000.0)

    def run_preview(self) -> None:
        started = perf_counter()
        try:
            data = self.preview_workflow.run()
        except Exception as exc:
            self.previewFailed.emit(str(exc))
            return
        self.previewReady.emit(data, max(0.0, perf_counter() - started))

    def planned_analyses(
        self,
        state: SimulationFormState,
        visible_views: Iterable[str],
    ) -> tuple[str, ...]:
        return plan_analyses(
            state.calculation.analyses,
            visible_views,
            visible_only=state.calculation.only_visible_results,
        )

    def cached_analyses(
        self,
        project: Any,
        state: SimulationFormState,
        visible_views: Iterable[str],
    ) -> frozenset[str]:
        planned = self.planned_analyses(state, visible_views)
        planned_state = state_for_analyses(state, planned)
        payload = build_simulation_payload(project, planned_state, request_id="fingerprint")
        return self.result_cache.available_analyses(physical_fingerprint(payload))

    def restore_cached(
        self,
        project: Any,
        state: SimulationFormState,
        visible_views: Iterable[str],
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:

        planned = self.planned_analyses(state, visible_views)
        if not planned:
            return None
        planned_state = state_for_analyses(state, planned)
        try:
            payload = build_simulation_payload(project, planned_state, request_id="cache-restore")
        except Exception:
            return None
        fingerprint = physical_fingerprint(payload)
        cached = self.result_cache.get_covering(fingerprint, frozenset(planned))
        if cached is None:
            return None
        cached.setdefault("metadata", {})
        cached["metadata"]["frontend_cache_status"] = "restore"
        cached["metadata"]["frontend_requested_analyses"] = sorted(planned)
        return cached, _project_from_payload(payload)

    def submit(
        self,
        project: Any,
        state: SimulationFormState,
        *,
        visible_views: Iterable[str] = (),
        multipath: bool = False,
    ) -> bool:
        if self.is_running:
            self.stateChanged.emit("running", 0.0, "已有正式任务正在运行")
            return False
        if self._perf_click_started <= 0.0:
            self.mark_user_submit()

        self._multipath = bool(multipath)
        planned = self.planned_analyses(state, visible_views)
        requested = frozenset(planned)
        planned_state = state_for_analyses(state, planned)

        try:
            full_payload = (
                build_multipath_payload(project, planned_state)
                if self._multipath
                else build_simulation_payload(project, planned_state)
            )
        except Exception as exc:
            self.formalFailed.emit("request", str(exc))
            return False

        self.last_project_payload = _project_from_payload(full_payload)
        fingerprint = physical_fingerprint(full_payload)

        
        
        
        if not self._multipath:
            cached = self.result_cache.get_covering(fingerprint, requested)
            if cached is not None:
                cached.setdefault("metadata", {})
                cached["metadata"]["frontend_requested_analyses"] = sorted(requested)
                self.stateChanged.emit("cached", 1.0, "相同物理参数与分析已命中前端结果缓存")
                record_perf(
                    "simulation_click_to_cached_result",
                    self.elapsed_since_submit_ms(),
                    analyses=sorted(requested),
                )
                safe_single_shot(
                    self,
                    0,
                    lambda body=cached, project_payload=dict(self.last_project_payload):
                    self.formalResultReady.emit(body, project_payload),
                )
                return True

            missing = self.result_cache.missing_analyses(fingerprint, requested)
        else:
            missing = requested

        submitted_state = state_for_analyses(state, tuple(sorted(missing)))
        payload = (
            build_multipath_payload(project, submitted_state)
            if self._multipath
            else build_simulation_payload(project, submitted_state)
        )
        self.last_project_payload = _project_from_payload(payload)
        self._pending_fingerprint = fingerprint
        self._pending_requested_analyses = requested
        self._pending_submitted_analyses = frozenset(missing)
        self._pending_options = dict(payload.get("options") or {})
        self._submission_request_id = str(payload.get("request_id", "") or "")
        self._submission_pending = True

        if self._multipath:
            self.multipath_client.submit(
                f"simulation.multipath.submit:{self._submission_request_id}", payload
            )
        else:
            
            
            
            
            
            if "coupling" in requested:
                self._schedule_compatible_receiver_preview(payload, fingerprint)
                self._surrogate_request_fingerprint = fingerprint
                self._surrogate_request_id = self._submission_request_id
                self.simulation_client.surrogate_preview(
                    f"simulation.surrogate_preview:{self._surrogate_request_id}", payload
                )
            self.simulation_client.submit(
                f"simulation.submit:{self._submission_request_id}", payload
            )

        if missing != requested:
            note = "复用已有正式结果，仅补算：" + "、".join(sorted(missing))
        elif is_layout_only(missing):
            note = (
                "正在提交稀疏正式布局光路："
                f"{submitted_state.calculation.pupil_sample_count}×"
                f"{submitted_state.calculation.pupil_sample_count} 入瞳采样；"
                "未运行 PSF、MTF、波前、耦合或五轴寻优"
            )
        else:
            note = "正在提交正式仿真：" + "、".join(sorted(missing))
        self.stateChanged.emit("submitting", 0.0, note)
        return True

    def invalidate_views(
        self, project: Any, state: SimulationFormState, visible_views: Iterable[str]
    ) -> str:

        planned = frozenset(self.planned_analyses(state, visible_views))
        planned_state = state_for_analyses(state, tuple(sorted(planned)))
        payload = build_simulation_payload(project, planned_state, request_id="fingerprint")
        fingerprint = physical_fingerprint(payload)
        self.result_cache.invalidate_analyses(fingerprint, planned)
        return fingerprint

    def set_polling_allowed(self, allowed: bool) -> None:
        self._polling_allowed = bool(allowed)
        if self._polling_allowed and self.current_job_id and not self._centralized_polling:
            self.poll_timer.start()
        elif not self._polling_allowed:
            self.poll_timer.stop()

    def _poll_job(self) -> None:
        if self._centralized_polling:
            self.poll_timer.stop()
            return
        if self.current_job_id:
            self.job_client.get_status(
                f"simulation.status:{self.current_job_id}", self.current_job_id
            )

    def _api_completed(self, key: str, body: object) -> None:
        base_key, _, token = str(key).partition(":")
        if base_key not in {
            "simulation.submit",
            "simulation.multipath.submit",
            "simulation.status",
            "simulation.result",
            "simulation.result.analysis",
            "simulation.result.local_live",
            "simulation.surrogate_preview",
        }:
            return
        data = body if isinstance(body, dict) else {}
        if base_key in {"simulation.submit", "simulation.multipath.submit"}:
            if token and self._submission_request_id and token != self._submission_request_id:
                return
            self._accept_submission(data)
        elif base_key == "simulation.status":
            if token and self.current_job_id and token != self.current_job_id:
                return
            self._update_job_status(data)
        elif base_key == "simulation.surrogate_preview":
            if token and self._surrogate_request_id and token != self._surrogate_request_id:
                return
            self._accept_surrogate_preview(data)
        elif base_key == "simulation.result.local_live":
            metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
            transport_job_id = str(
                metadata.get("transport_job_id", "") or token
                or self._local_result_requested_job_id
            )
            self._materialize_local_result(data, transport_job_id)
        else:
            if token and self.current_job_id and token.split(":", 1)[0] != self.current_job_id:
                return
            self._accept_result(data)

    def _accept_submission(self, data: dict[str, Any]) -> None:
        response_request_id = str(data.get("request_id", "") or "")
        if (
            response_request_id
            and self._submission_request_id
            and response_request_id != self._submission_request_id
        ):
            _logger.warning(
                "忽略过期仿真提交响应：response_request_id=%s current_request_id=%s",
                response_request_id,
                self._submission_request_id,
            )
            return
        self._submission_pending = False
        job_id = str(data.get("job_id", ""))
        if not job_id:
            self._fail("submission", "响应缺少 job_id")
            return
        self.current_job_id = job_id
        self._perf_submission_accepted = perf_counter()
        if self._perf_click_started > 0.0:
            record_perf(
                "simulation_click_to_job_created",
                (self._perf_submission_accepted - self._perf_click_started) * 1000.0,
                job_id=job_id,
            )
        task = self.context.tasks.add(
            "多路径正式仿真" if self._multipath else "正式光学仿真",
            "仿真",
            "等待后端",
            0,
            f"job_id: {job_id}",
            page="simulation",
            job_id=job_id,
        )
        self.current_task_id = str(task["id"])
        self.job_watcher.subscribe(job_id)
        if self._polling_allowed and not self._centralized_polling:
            self.poll_timer.start()
        self.jobChanged.emit(job_id)
        self.stateChanged.emit("queued", 0.0, f"任务已创建：{job_id}")

    def _update_job_status(self, body: dict[str, Any]) -> None:
        response_job_id = str(body.get("job_id", "") or "")
        if response_job_id and self.current_job_id and response_job_id != self.current_job_id:
            _logger.warning(
                "忽略过期任务状态响应：response_job_id=%s current_job_id=%s",
                response_job_id,
                self.current_job_id,
            )
            return
        status = str(body.get("status", "queued"))
        progress = float(body.get("progress", 0.0) or 0.0)
        if status in {"failed", "cancelled"}:
            note = extract_error_message(
                body, "任务已取消" if status == "cancelled" else "仿真任务失败"
            )
        elif status == "completed":
            note = "正在加载结果"
        else:
            note = friendly_job_stage(body.get("stage", "")) or "后端正在处理"
        self._update_task(
            status,
            progress,
            note,
            result_available=bool(body.get("result_available", False)),
        )
        self.stateChanged.emit(status, progress, note)
        if status == "completed":
            self.poll_timer.stop()
            self._handle_completed_signal(self.current_job_id)
        elif status in {"failed", "cancelled"}:
            self.poll_timer.stop()
            self._finish_without_result(status, note)

    def _accept_result(self, body: dict[str, Any]) -> None:
        self.poll_timer.stop()
        self._perf_result_received = perf_counter()
        if self._perf_result_requested > 0.0:
            record_perf(
                "simulation_result_request_to_frontend_received",
                (self._perf_result_received - self._perf_result_requested) * 1000.0,
                job_id=self.current_job_id,
            )
        if self._perf_click_started > 0.0:
            record_perf(
                "simulation_click_to_frontend_result_received",
                (self._perf_result_received - self._perf_click_started) * 1000.0,
                job_id=self.current_job_id,
            )
        status = str(body.get("status", "failed"))
        emitted = dict(body)
        if status == "completed" and not self._multipath:
            emitted = self.result_cache.merge(
                self._pending_fingerprint,
                self._pending_submitted_analyses,
                body,
                self.last_project_payload,
                self._pending_options,
            )
            emitted.setdefault("metadata", {})
            emitted["metadata"]["frontend_requested_analyses"] = sorted(
                self._pending_requested_analyses
            )
            emitted["metadata"]["frontend_submitted_analyses"] = sorted(
                self._pending_submitted_analyses
            )

        previous_project = dict(self.last_project_payload)
        if status == "completed":
            converged = bool(body.get("converged", False))
            terminal_status = "completed" if converged else "not_converged"
            terminal_note = "正式仿真结果已返回" if converged else "结果已返回，但未通过收敛判定"
            self._update_task(
                terminal_status,
                1.0,
                terminal_note,
                result_available=bool(converged),
            )
            # Result delivery through the persisted/analysis endpoint used to clear
            # the job and emit only ``formalResultReady``.  The page therefore
            # received the data but never received the terminal state transition,
            # leaving PrimaryButton's spinner active forever.  WebSocket/local-live
            # delivery already emits this terminal state; keep both paths identical.
            self.stateChanged.emit(terminal_status, 1.0, terminal_note)
            self._clear_job()
            self.formalResultReady.emit(emitted, previous_project)
            return

        note = extract_error_message(
            body, "任务已取消" if status == "cancelled" else "仿真内部失败"
        )
        self._update_task(status, body.get("progress", 0.0), note)
        self._clear_job()
        self.formalFailed.emit(status, note)

    def _api_failed(self, key: str, message: str) -> None:
        base_key, _, token = str(key).partition(":")
        
        
        
        if base_key in {"simulation.submit", "simulation.multipath.submit"}:
            if token and self._submission_request_id and token != self._submission_request_id:
                return
        elif base_key == "simulation.status":
            if token and self.current_job_id and token != self.current_job_id:
                return
        elif base_key in {"simulation.result", "simulation.result.analysis", "simulation.result.local_live"}:
            response_job_id = token.split(":", 1)[0] if token else ""
            if response_job_id and self.current_job_id and response_job_id != self.current_job_id:
                return
        elif base_key == "simulation.surrogate_preview":
            if token and self._surrogate_request_id and token != self._surrogate_request_id:
                return

        
        
        if base_key in {"simulation.result.local_live", "simulation.surrogate_preview"}:
            if base_key == "simulation.result.local_live":
                self._local_result_requested_job_id = ""
            return
        if base_key == "simulation.result.analysis" and self.current_job_id:
            if not self._analysis_result_fallback_used:
                self._analysis_result_fallback_used = True
                self.job_client.get_result(
                    f"simulation.result:{self.current_job_id}", self.current_job_id
                )
                return
        if base_key.startswith("simulation."):
            self._fail("api", message)

    def _on_ws_progress(self, job_id: str, progress: float, stage: str) -> None:
        if job_id != self.current_job_id:
            return
        if self._live_result_displayed and float(progress) < 1.0:
            return
        note = friendly_job_stage(stage) or "后端运行中"
        signature = (int(max(0.0, min(1.0, float(progress))) * 100.0), note)
        if signature == self._last_progress_signature:
            return
        self._last_progress_signature = signature
        if self._perf_job_started <= 0.0:
            self._perf_job_started = perf_counter()
            if self._perf_click_started > 0.0:
                record_perf(
                    "simulation_click_to_backend_started",
                    (self._perf_job_started - self._perf_click_started) * 1000.0,
                    job_id=job_id,
                    stage=note,
                )
        self._update_task("running", progress, note)
        self.stateChanged.emit("running", progress, note)

    def _on_ws_partial(self, job_id: str, payload: dict) -> None:
        if job_id != self.current_job_id or not isinstance(payload, dict):
            return
        if self._live_result_displayed:
            return
        if bool(payload.get("live_result_available", False)):
            self._request_local_result(job_id)
        version = int(payload.get("result_version", 0) or 0)
        if version and version <= self._last_partial_version:
            return
        self._last_partial_version = max(self._last_partial_version, version)
        metrics = payload.get("metrics")
        if isinstance(metrics, dict) and metrics:
            self._preview_quality_rank = max(self._preview_quality_rank, 3)
            if self._perf_click_started > 0.0:
                record_perf(
                    "simulation_click_to_core_metrics",
                    self.elapsed_since_submit_ms(),
                    job_id=job_id,
                    stage=str(payload.get("stage", "") or ""),
                )
            self.partialResultReady.emit(dict(payload))

    def _track_fast_worker(self, worker: FunctionWorker) -> None:
        self._fast_workers.add(worker)
        worker.signals.finished.connect(
            lambda _worker=worker: self._fast_workers.discard(_worker)
        )
        QThreadPool.globalInstance().start(worker)

    def _schedule_compatible_receiver_preview(
        self, payload: dict[str, Any], fingerprint: str
    ) -> None:
        try:
            keys = dependency_keys_for_payload(payload)
            compatible = self.result_cache.find_receiver_field_compatible(
                str(keys.get("receiver_field", ""))
            )
        except Exception:
            return
        if compatible is None:
            return
        cached_result, cached_project = compatible
        worker = FunctionWorker(
            receiver_field_preview, cached_result, cached_project, dict(payload)
        )

        def apply_preview(value, *, expected=str(fingerprint)):
            if not isinstance(value, dict) or not value:
                return
            if (
                expected != self._pending_fingerprint
                or not self._submission_pending
                or self._live_result_displayed
                or self._preview_quality_rank >= 2
            ):
                return
            self._preview_quality_rank = 2
            record_perf(
                "simulation_click_to_compatible_receiver_preview",
                self.elapsed_since_submit_ms(),
                preview_elapsed_ms=float(
                    ((value.get("preview_result") or {}).get("metadata") or {}).get(
                        "preview_elapsed_ms", 0.0
                    )
                    or 0.0
                ),
            )
            self.partialResultReady.emit(dict(value))

        worker.signals.result.connect(apply_preview)
        worker.signals.error.connect(
            lambda message: _logger.warning(
                "兼容端面场预览失败，已回退正式计算：%s", message
            )
        )
        self._track_fast_worker(worker)

    def _accept_surrogate_preview(self, data: dict[str, Any]) -> None:
        if not bool(data.get("available", False)):
            return
        response_request_id = str(data.get("request_id", "") or "")
        if (
            not (self._submission_pending or self.current_job_id)
            or self._live_result_displayed
            or self._preview_quality_rank >= 1
            or not self._surrogate_request_fingerprint
            or self._surrogate_request_fingerprint != self._pending_fingerprint
            or (
                response_request_id
                and self._surrogate_request_id
                and response_request_id != self._surrogate_request_id
            )
        ):
            return
        self._preview_quality_rank = 1
        metrics = data.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            return
        payload = {
            "status": "running",
            "stage": "surrogate.preview",
            "metrics": dict(metrics),
            "metadata": {
                "preview_only": True,
                "preview_source": "bounded_surrogate",
                "model_id": str(data.get("model_id", "")),
                "in_training_domain": bool(data.get("in_training_domain", False)),
                "preview_elapsed_ms": float(data.get("elapsed_ms", 0.0) or 0.0),
            },
        }
        record_perf(
            "simulation_click_to_surrogate_preview",
            self.elapsed_since_submit_ms(),
            model_id=str(data.get("model_id", "")),
        )
        self.partialResultReady.emit(payload)

    def _request_local_result(self, job_id: str) -> None:
        job_id = str(job_id or "")
        if not job_id or self._local_result_requested_job_id == job_id:
            return
        self._local_result_requested_job_id = job_id
        self.job_client.get_live_result_local(
            f"simulation.result.local_live:{job_id}", job_id
        )

    def _materialize_local_result(
        self, data: dict[str, Any], job_id: str
    ) -> None:
        job_id = str(job_id or self.current_job_id or "")
        if not job_id or job_id != self.current_job_id:
            return
        started = perf_counter()
        worker = FunctionWorker(materialize_local_arrays, dict(data))

        def accept(value, *, expected_job=job_id, started_at=started):
            record_perf(
                "simulation_local_descriptor_to_memmap",
                (perf_counter() - started_at) * 1000.0,
                job_id=expected_job,
            )
            self._accept_live_result(value, expected_job)

        worker.signals.result.connect(accept)

        def failed(message: str, *, expected_job=job_id) -> None:
            _logger.warning(
                "本地数组映射失败，回退持久化结果：job_id=%s error=%s",
                expected_job,
                message,
            )
            if expected_job != self.current_job_id:
                return
            self._local_result_requested_job_id = ""
            if self._terminal_completed_job_id == expected_job:
                self._request_result_once(expected_job)

        worker.signals.error.connect(failed)
        self._track_fast_worker(worker)

    def _accept_live_result(self, body: object, job_id: str) -> None:
        if job_id != self.current_job_id or not isinstance(body, dict):
            return
        status = str(body.get("status", "completed") or "completed")
        if status != "completed":
            return
        emitted = dict(body)
        emitted.setdefault("status", "completed")
        emitted.setdefault("metadata", {})
        if isinstance(emitted["metadata"], dict):
            emitted["metadata"].update(
                {
                    "frontend_delivery": "local_numpy_memmap",
                    "frontend_authoritative": True,
                    "frontend_requested_analyses": sorted(
                        self._pending_requested_analyses
                    ),
                    "frontend_submitted_analyses": sorted(
                        self._pending_submitted_analyses
                    ),
                }
            )
        if not self._multipath:
            emitted = self.result_cache.merge(
                self._pending_fingerprint,
                self._pending_submitted_analyses,
                emitted,
                self.last_project_payload,
                self._pending_options,
            )
        self._preview_quality_rank = 4
        self._live_result_displayed = True
        self._live_result_body = emitted
        previous_project = dict(self.last_project_payload)
        record_perf(
            "simulation_click_to_local_exact_result",
            self.elapsed_since_submit_ms(),
            job_id=job_id,
        )
        self._update_task("running", 0.995, "正式精确结果已显示，后台完成存档")
        self.stateChanged.emit("running", 0.995, "正式精确结果已显示，后台完成存档")
        self.formalResultReady.emit(emitted, previous_project)
        if self._terminal_completed_job_id == job_id:
            self._finalize_after_live_result(job_id)

    def _handle_completed_signal(self, job_id: str) -> None:
        job_id = str(job_id or "")
        if not job_id or job_id != self.current_job_id:
            return
        self._terminal_completed_job_id = job_id
        if self._live_result_displayed:
            self._finalize_after_live_result(job_id)
            return
        if self._local_result_requested_job_id == job_id:
            
            
            
            safe_single_shot(
                self, 80, lambda expected=job_id: self._request_result_after_local_grace(expected)
            )
            return
        self._request_result_once(job_id)

    def _request_result_after_local_grace(self, job_id: str) -> None:
        if job_id != self.current_job_id or self._live_result_displayed:
            return
        self._request_result_once(job_id)

    def _finalize_after_live_result(self, job_id: str) -> None:
        if job_id != self.current_job_id:
            return
        body = self._live_result_body or {}
        converged = bool(body.get("converged", True))
        self._update_task(
            "completed" if converged else "not_converged",
            1.0,
            "正式仿真结果已返回" if converged else "结果已返回，但未通过收敛判定",
            result_available=bool(converged),
        )
        self.stateChanged.emit(
            "completed" if converged else "not_converged",
            1.0,
            "正式仿真结果已返回" if converged else "结果已返回，但未通过收敛判定",
        )
        self._clear_job()

    def _request_result_once(self, job_id: str) -> None:
        job_id = str(job_id or "")
        if not job_id or self._result_request_job_id == job_id:
            return
        self._result_request_job_id = job_id
        self._perf_result_requested = perf_counter()
        if not self._multipath and len(self._pending_submitted_analyses) == 1:
            analysis = next(iter(self._pending_submitted_analyses))
            self._analysis_result_requested = analysis
            self.job_client.get_result_analysis(
                f"simulation.result.analysis:{job_id}:{analysis}", job_id, analysis
            )
        else:
            self.job_client.get_result(f"simulation.result:{job_id}", job_id)

    def _on_ws_completed(self, job_id: str, status: str, metrics: dict) -> None:
        if job_id != self.current_job_id:
            return
        if status == "completed":
            self.poll_timer.stop()
            self._handle_completed_signal(job_id)
        elif status in {"cancelled", "failed"}:
            self.job_client.get_status(f"simulation.status:{job_id}", job_id)

    def _on_ws_failed(self, job_id: str, message: str) -> None:
        if job_id == self.current_job_id:
            self.job_client.get_status(f"simulation.status:{job_id}", job_id)

    def _finish_without_result(self, status: str, note: str) -> None:
        self._update_task(status, 0.99, note)
        self._clear_job()
        self.formalFailed.emit(status, note)

    def _fail(self, category: str, message: str) -> None:
        self.poll_timer.stop()
        self._update_task("failed", 0.99, str(message))
        self._clear_job()
        self.formalFailed.emit(category, str(message))

    def _update_task(
        self,
        status: str,
        progress: float,
        note: str,
        *,
        result_available: bool | None = None,
    ) -> None:
        if not self.current_task_id:
            return
        labels = {
            "queued": "等待后端",
            "submitting": "正在提交",
            "running": "运行中",
            "completed": "已完成",
            "not_converged": "未收敛",
            "failed": "失败",
            "cancelled": "已取消",
        }
        changes = {
            "status": labels.get(status, status),
            "progress": terminal_progress(status, progress),
            "note": note,
            "stage": status if status in {"completed", "not_converged", "failed", "cancelled"} else "",
            "error_message": note if status in {"failed", "not_converged"} else "",
        }
        if result_available is not None:
            changes["result_available"] = bool(result_available)
        self.context.tasks.update_task(self.current_task_id, **changes)

    def _clear_job(self) -> None:
        old_job_id = self.current_job_id
        if old_job_id and hasattr(self.job_watcher, "unsubscribe"):
            try:
                self.job_watcher.unsubscribe(old_job_id)
            except Exception:
                pass
        self.current_job_id = ""
        self.current_task_id = ""
        self._submission_pending = False
        self._pending_fingerprint = ""
        self._pending_submitted_analyses = frozenset()
        self._pending_requested_analyses = frozenset()
        self._result_request_job_id = ""
        self._analysis_result_requested = ""
        self._analysis_result_fallback_used = False
        self._pending_options = {}
        self._local_result_requested_job_id = ""
        self._live_result_displayed = False
        self._live_result_body = None
        self._terminal_completed_job_id = ""
        self._surrogate_request_fingerprint = ""
        self._surrogate_request_id = ""
        self._submission_request_id = ""
        self._preview_quality_rank = 0
        self._last_progress_signature = None
        self._last_partial_version = 0
        self.jobChanged.emit("")

    def dispose(self) -> None:

        self.poll_timer.stop()
        if self.current_job_id and hasattr(self.job_watcher, "unsubscribe"):
            try:
                self.job_watcher.unsubscribe(self.current_job_id)
            except Exception:
                pass
        for signal, slot in (
            (self.api_client.completed, self._api_completed),
            (self.api_client.failed, self._api_failed),
            (self.job_watcher.job_progress, self._on_ws_progress),
            *(([(self.job_watcher.job_partial, self._on_ws_partial)]) if hasattr(self.job_watcher, "job_partial") else []),
            (self.job_watcher.job_completed, self._on_ws_completed),
            (self.job_watcher.job_failed, self._on_ws_failed),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._clear_job()



def _project_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    project = payload.get("project")
    if isinstance(project, dict):
        return dict(project)
    paths = payload.get("paths", []) or []
    if paths and isinstance(paths[0], dict):
        path_project = paths[0].get("project")
        if isinstance(path_project, dict):
            return dict(path_project)
    return {}


__all__ = ["SimulationController"]

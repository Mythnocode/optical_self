"""Non-blocking computation controller with stale-result protection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from frontend_pyside.infrastructure.workers.worker import FunctionWorker

from .coordinates import DEFAULT_TRANSFORM, FrameTransform
from .model import ResultKind, SceneSnapshot, SceneStore
from .physics import (
    FormalTeachingGateway,
    PhysicsGateway,
    PhysicsRequest,
    PhysicsResult,
    canonicalize_analysis,
    compute_geometry_preview,
    ray_segment_to_dict,
)


class TaskState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    MISSED = "missed"
    FAILED = "failed"
    BLOCKED = "blocked"
    STALE = "stale"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class _Job:
    request: PhysicsRequest
    gateway: PhysicsGateway
    cancelled: threading.Event


class ComputationController(QObject):
    """Coordinates cheap previews and explicit formal calculations.

    Scene edits only invalidate results.  Wave-optics work starts solely from
    ``request_formal`` (the visible Calculate button), and a worker result is
    applied only if its scene revision still matches the store.
    """

    stateChanged = Signal(str, str)
    resultReady = Signal(str, object)
    previewReady = Signal(object)

    def __init__(
        self,
        store: SceneStore,
        gateway: PhysicsGateway | None = None,
        *,
        transform: FrameTransform = DEFAULT_TRANSFORM,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.gateway = gateway or FormalTeachingGateway()
        self.transform = transform
        self._cancelled = threading.Event()
        self._running_revision: int | None = None
        self._request_token = 0
        self._workers: set[FunctionWorker] = set()
        self._pending_preview: SceneSnapshot | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        # 30 FPS is visually continuous for the teaching ray overlay while
        # leaving time for mouse, layout and Quick3D event processing.
        self._preview_timer.setInterval(33)
        self._preview_timer.timeout.connect(self._flush_preview)
        self.store.sceneChanged.connect(self._on_scene_changed)

    def request_preview(self, snapshot: SceneSnapshot | None = None) -> PhysicsResult:
        scene = snapshot or self.store.snapshot()
        result = compute_geometry_preview(scene, self.transform)
        self.store.apply_result(
            ResultKind.GEOMETRY,
            {
                "source": result.source,
                "status": result.status,
                "metrics": result.metrics,
                "rays": [ray_segment_to_dict(ray) for ray in result.rays],
            },
            source_revision=scene.revision,
        )
        self.previewReady.emit(result)
        if self._running_revision is None:
            self.stateChanged.emit(TaskState.COMPLETED.value, "光路示意已随拖动更新")
        return result

    def request_formal(self, analysis: str = "raytrace") -> None:
        analysis = canonicalize_analysis(analysis)
        scene = self.store.snapshot()
        report = self.gateway.inspect(scene, analysis)
        if not report.allowed:
            self.stateChanged.emit(TaskState.BLOCKED.value, "；".join(report.messages))
            return
        self.cancel()
        self._cancelled = threading.Event()
        self._running_revision = scene.revision
        self._request_token += 1
        request_token = self._request_token
        names = {
            "raytrace": "光线追迹",
            "spot": "光斑",
            "field": "端面场",
            "coupling": "耦合",
            "wavefront": "波前",
        }
        self.stateChanged.emit(TaskState.RUNNING.value, f"正在计算{names.get(analysis, analysis)}，界面仍可继续操作")
        job = _Job(PhysicsRequest(scene, str(analysis), self.transform), self.gateway, self._cancelled)
        # Formal wave-optics work can take seconds.  Use the same QRunnable
        # mechanism as the simulation workspace so the GUI can keep showing an
        # honest indeterminate progress bar and remains responsive.
        worker = FunctionWorker(self._compute_job, job)
        self._workers.add(worker)
        worker.signals.result.connect(
            lambda result, name=str(analysis), token=request_token: self._on_finished(name, result, token)
        )
        worker.signals.error.connect(
            lambda message, name=str(analysis), token=request_token, request=job.request: self._on_finished(
                name,
                PhysicsResult(
                    False,
                    request.analysis,
                    request.scene.revision,
                    "formal_engine",
                    TaskState.FAILED.value,
                    errors=(str(message),),
                ),
                token,
            )
        )
        worker.signals.finished.connect(lambda current=worker: self._workers.discard(current))
        QThreadPool.globalInstance().start(worker)

    @staticmethod
    def _compute_job(job: _Job) -> PhysicsResult:
        if job.cancelled.is_set():
            return PhysicsResult(
                False,
                job.request.analysis,
                job.request.scene.revision,
                "formal_engine",
                TaskState.CANCELLED.value,
            )
        try:
            return job.gateway.compute(job.request)
        except Exception as exc:
            return PhysicsResult(
                False,
                job.request.analysis,
                job.request.scene.revision,
                "formal_engine",
                TaskState.FAILED.value,
                errors=(repr(exc),),
            )

    def cancel(self) -> None:
        if self._running_revision is not None:
            self._cancelled.set()
            self._request_token += 1
            self.stateChanged.emit(TaskState.CANCELLED.value, "已取消计算")
            self._running_revision = None

    def _on_scene_changed(self, snapshot: SceneSnapshot, _reason: str) -> None:
        self._pending_preview = snapshot
        if not self._preview_timer.isActive():
            self._preview_timer.start()
        if self._running_revision is not None and int(snapshot.revision) != int(self._running_revision):
            self.stateChanged.emit(TaskState.STALE.value, "场景已改；算完后不会覆盖现在的光路")

    def _flush_preview(self) -> None:
        snapshot = self._pending_preview
        self._pending_preview = None
        if snapshot is not None:
            self.request_preview(snapshot)

    def _on_finished(self, analysis: str, result: PhysicsResult, request_token: int) -> None:
        running_revision = self._running_revision
        if int(request_token) != int(self._request_token):
            return
        self._running_revision = None
        if running_revision is None:
            return
        if int(result.scene_revision) != int(self.store.revision):
            self.stateChanged.emit(TaskState.STALE.value, "这是改场景之前的结果，已丢弃；需要请再点光学计算")
            return
        artifacts = dict(result.artifacts or {})
        if not artifacts:
            artifacts = {
                str(analysis): {
                    "source": result.source,
                    "status": result.status,
                    "metrics": result.metrics,
                    "warnings": list(result.warnings),
                    "errors": list(result.errors),
                    "rays": [ray_segment_to_dict(ray) for ray in result.rays],
                }
            }
        if "raytrace" in artifacts and result.rays and not artifacts["raytrace"].get("rays"):
            artifacts["raytrace"]["rays"] = [ray_segment_to_dict(ray) for ray in result.rays]
        for kind, artifact in artifacts.items():
            if str(kind) == ResultKind.GEOMETRY.value:
                continue
            self.store.apply_result(kind, artifact, source_revision=result.scene_revision)
        if result.status == TaskState.MISSED.value:
            state = TaskState.MISSED
            message = next(
                (note for note in result.warnings if "位置失配" in note),
                "光束未击中器件。这是位置失配，不是计算失败。",
            )
        elif result.success:
            state = TaskState.COMPLETED
            message = "光学计算完成"
        else:
            state = TaskState.FAILED
            message = "；".join(result.errors) or "光学计算失败"
        self.stateChanged.emit(state.value, message)
        self.resultReady.emit(str(analysis), result)


__all__ = ["ComputationController", "TaskState"]

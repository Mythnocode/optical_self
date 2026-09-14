"""画布 L1/L2 刷新控制器（M3）。

三级更新链路（与 §6 更新策略对齐）：

- L0：编辑即算（lens_node 摘要、scene 脏传播）——不经过本控制器；
- L1 增量缓存：payload 物理指纹 → SimulationResultCache.get_covering；
  命中直接回放（不打引擎）；部分命中则只向后端提交缺失的分析项，
  结果 merge 回同一缓存条目（按分析增量积累）；
- L2 HTTP 任务：SimulationClient.submit → 共享 CentralJobMonitor 订阅
  （WebSocket 优先、1s HTTP 轮询兜底）→ 完成后 /jobs/{id}/result →
  merge 入缓存 → 分发；后端不可达（连接失败）时本会话一次性降级为
  进程内 EngineBridge（离线可用）。

节流合并：运行中收到新请求 → 合并为“最新待跑”；L2 在途任务先 cancel
再补跑最新版本。resultReady 载荷与 EngineBridge 契约兼容（version 字段
供 UI 丢弃过期结果），另附 level 字段（"L1"/"L2"/"fallback"）。
"""

from __future__ import annotations

from typing import Any, Iterable
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, Signal

from frontend_pyside.features.simulation.request_fingerprint import physical_fingerprint
from frontend_pyside.features.simulation.result_cache import SimulationResultCache

from .engine_bridge import EngineBridge, build_payload, restrict_payload

_SUBMIT_KEY = "canvas.simulation.submit"
_RESULT_KEY = "canvas.simulation.result"
_CANCEL_KEY = "canvas.simulation.cancel"

# chart_kind → 引擎分析名（节点级增量刷新的请求范围）
CHART_ANALYSES: dict[str, frozenset[str]] = {
    "mtf": frozenset({"mtf"}),
    "intensity": frozenset({"coupling"}),
    "phase": frozenset({"coupling"}),
    "mode": frozenset({"coupling"}),
    "psf": frozenset({"psf"}),
    "spot": frozenset({"spot"}),
    "layout": frozenset({"raytrace"}),
    "propagation": frozenset({"raytrace"}),
    "catalogue": frozenset(),  # 指标目录依赖全量分析 → 空集表示“全量”
}


def chart_analyses(chart_kind: str) -> frozenset[str] | None:
    """节点刷新所需的分析集合；None/空集 = 全量。"""
    return CHART_ANALYSES.get(str(chart_kind)) or None


class RefreshController(QObject):
    """画布刷新的统一入口：request_refresh(surface_rows, analyses=None)。

    - analyses=None → 全量分析；传入子集 → 节点级增量刷新；
    - resultReady(dict)：{version, status, arrays, metrics, warnings,
      errors, elapsed_ms, level, note}；
    - stateChanged(level, note)：L2 提交 / L1 命中 / 回退等过程提示。
    """

    resultReady = Signal(dict)
    stateChanged = Signal(str, str)

    def __init__(
        self,
        api_client=None,
        simulation_client=None,
        job_client=None,
        job_watcher=None,
        cache: SimulationResultCache | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._api = api_client
        self._simulation_client = simulation_client
        self._job_client = job_client
        self._job_watcher = job_watcher
        self._cache = cache if cache is not None else SimulationResultCache(max_entries=4)

        # 进程内回退引擎（后端不可达 / 无 API 句柄时使用）
        self._bridge = EngineBridge(self)
        self._bridge.resultReady.connect(self._on_bridge_result)

        self._version = 0
        self._stopped = False
        self._pending_rows: list[dict[str, Any]] | None = None
        self._pending_analyses: frozenset[str] | None = None
        self._active: dict[str, Any] | None = None
        self._http_disabled = api_client is None or simulation_client is None

        # 无共享 job_watcher 时的独立轮询（1s，与 CentralJobMonitor 兜底同频）
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll_active_job)

        if self._api is not None:
            self._api.completed.connect(self._on_api_completed)
            self._api.failed.connect(self._on_api_failed)
        if self._job_watcher is not None:
            self._job_watcher.job_completed.connect(self._on_job_completed)
            self._job_watcher.job_failed.connect(self._on_job_failed)

    # ---- 主线程接口 ----------------------------------------------------------

    def request_refresh(
        self,
        surface_rows: list[dict[str, Any]],
        analyses: Iterable[str] | None = None,
    ) -> int:
        """请求一次刷新，返回请求版本号；运行中合并为最新待跑。"""
        if self._stopped:
            return self._version
        self._version += 1
        self._pending_rows = list(surface_rows)
        self._pending_analyses = frozenset(analyses) if analyses else None
        if self._active is not None:
            self._supersede_active()
        if self._active is None:
            self._dispatch_next()
        return self._version

    def latest_version(self) -> int:
        return self._version

    def retry_backend(self) -> None:
        """重新允许 L2 提交（用户手动重试后端连接时调用）。"""
        if self._http_disabled and self._api is not None and self._simulation_client is not None:
            self._http_disabled = False
            self.stateChanged.emit("L2", "已恢复后端任务提交通道")

    def is_running(self) -> bool:
        return self._active is not None

    def shutdown(self) -> None:
        """窗口关闭：停掉轮询与进程内引擎线程，避免向已销毁对象发信号。"""
        self._stopped = True
        self._pending_rows = None
        self._pending_analyses = None
        self._active = None
        self._poll_timer.stop()
        try:
            self.blockSignals(True)
        except RuntimeError:
            pass
        self._bridge.stop()

    # ---- 调度 ---------------------------------------------------------------

    def _dispatch_next(self) -> None:
        if self._stopped:
            return
        rows, analyses = self._pending_rows, self._pending_analyses
        self._pending_rows = None
        self._pending_analyses = None
        if rows is None:
            return
        version = self._version
        # request_id 全局唯一：后端按 simulation:{request_id} 幂等去重，
        # 跨会话/跨控制器实例复用同一 ID 会拿到旧的已取消/已完成任务
        payload = build_payload(rows, f"canvas-{version}-{uuid4().hex[:8]}")
        if analyses:
            payload = restrict_payload(payload, analyses)
        requested = frozenset(str(item) for item in payload.get("analyses", ()) or ())
        active = {
            "version": version,
            "rows": rows,
            "payload": payload,
            "fingerprint": physical_fingerprint(payload),
            "requested": requested,
            "transport": None,  # "http" | "inprocess"
            "job_id": "",
            "superseded": False,
        }
        self._active = active

        # ---- L1：增量缓存 -----------------------------------------------------
        cached = self._cache.get_covering(active["fingerprint"], requested)
        if cached is not None:
            self._emit_result(active, cached, "L1", "L1 缓存命中（未打引擎）")
            self._finish_active()
            return

        missing = self._cache.missing_analyses(active["fingerprint"], requested)
        submit_payload = payload
        if missing and missing < requested:
            # 部分命中：只提交缺失分析（结果 merge 回同一缓存条目）
            submit_payload = restrict_payload(payload, missing)

        # ---- L2：HTTP 任务 ----------------------------------------------------
        if not self._http_disabled:
            active["transport"] = "http"
            names = sorted(missing or requested)
            self.stateChanged.emit("L2", f"L2 已提交后端仿真任务（{len(names)} 项分析）")
            self._simulation_client.submit(f"{_SUBMIT_KEY}:{version}", submit_payload)
            return

        # ---- 回退：进程内引擎 --------------------------------------------------
        self._run_inprocess(active, "后端不可用 → 进程内引擎直算")

    def _supersede_active(self) -> None:
        """新请求到达：在途 L2 任务取消（异步），完成后补跑最新待跑。"""
        active = self._active
        if active is None or active.get("superseded"):
            return
        active["superseded"] = True
        job_id = str(active.get("job_id") or "")
        if active.get("transport") == "http" and job_id and self._job_client is not None:
            self._job_client.cancel(f"{_CANCEL_KEY}:{job_id}", job_id)

    def _finish_active(self) -> None:
        self._active = None
        self._poll_timer.stop()
        if self._pending_rows is not None:
            self._dispatch_next()

    def _run_inprocess(self, active: dict[str, Any], note: str) -> None:
        active["transport"] = "inprocess"
        self.stateChanged.emit("fallback", note)
        # 保留节点级请求的分析集合；否则增量刷新会退化成全量计算，
        # 既浪费算力，也会让未请求的结果被意外覆盖。
        active["bridge_version"] = self._bridge.run_async(
            active["rows"], active.get("requested")
        )

    # ---- HTTP 回调 -----------------------------------------------------------

    def _on_api_completed(self, key: str, data) -> None:
        active = self._active
        if active is None:
            return
        base, _, token = str(key).partition(":")
        if base == _SUBMIT_KEY:
            if token and token != str(active["version"]):
                return
            job_id = str(data.get("job_id", "") or "") if isinstance(data, dict) else ""
            if not job_id:
                self._fallback(active, "后端未返回任务 ID")
                return
            active["job_id"] = job_id
            if active["superseded"]:
                # 取代发生在提交响应之前：取消孤儿任务，直接补跑最新待跑
                if self._job_client is not None:
                    self._job_client.cancel(f"{_CANCEL_KEY}:{job_id}", job_id)
                self._finish_active()
                return
            if self._job_watcher is not None:
                self._job_watcher.subscribe(job_id)
            else:
                self._poll_timer.start()
                self._poll_active_job()
        elif base == _RESULT_KEY:
            if token and token != str(active["job_id"]):
                return
            if active["superseded"]:
                self._finish_active()
                return
            self._accept_http_result(active, data)
        elif base == "job_monitor.status":
            # 无共享 job_watcher 时的独立轮询分支
            if token and token != str(active["job_id"]):
                return
            if active["superseded"]:
                return
            if not isinstance(data, dict):
                return
            status = str(data.get("status", "") or "").lower()
            if status == "completed":
                self._poll_timer.stop()
                self._job_client.get_result(f"{_RESULT_KEY}:{active['job_id']}", active["job_id"])
            elif status in {"failed", "cancelled"}:
                self._poll_timer.stop()
                error = data.get("error") or {}
                message = error.get("message", "") if isinstance(error, dict) else ""
                self._fallback(active, f"后端任务{status}：{message or status}")

    def _on_api_failed(self, key: str, message: str) -> None:
        active = self._active
        if active is None:
            return
        base, _, token = str(key).partition(":")
        if base == _SUBMIT_KEY:
            if token and token != str(active["version"]):
                return
            self._http_disabled = True  # 连接失败：本会话内不再尝试 HTTP
            self._run_inprocess(active, f"后端不可用（{message}）→ 进程内引擎直算")
        elif base == _RESULT_KEY:
            if token and token != str(active["job_id"]):
                return
            if active["superseded"]:
                self._finish_active()
                return
            self._fallback(active, f"结果获取失败：{message}")

    def _poll_active_job(self) -> None:
        active = self._active
        job_id = str(active.get("job_id") or "") if active else ""
        if not job_id or self._job_watcher is not None or active.get("transport") != "http":
            self._poll_timer.stop()
            return
        self._api.get(f"job_monitor.status.{job_id}", f"/jobs/{job_id}")

    def _on_job_completed(self, job_id: str, status: str, metrics: dict) -> None:
        active = self._active
        if active is None or str(job_id) != str(active.get("job_id")):
            return
        if active["superseded"]:
            self._finish_active()
            return
        if status == "completed":
            self._job_client.get_result(f"{_RESULT_KEY}:{job_id}", job_id)
        else:
            self._fallback(active, f"后端任务{status}")

    def _on_job_failed(self, job_id: str, message: str) -> None:
        active = self._active
        if active is None or str(job_id) != str(active.get("job_id")):
            return
        if active["superseded"]:
            self._finish_active()
            return
        self._fallback(active, f"后端任务失败：{message}")

    def _accept_http_result(self, active: dict[str, Any], body) -> None:
        result = dict(body or {})
        status = str(result.get("status", "") or "")
        # 空响应/缺失状态不是成功：直接合并会把旧缓存标成最新，
        # 用户只会看到“完成”却拿不到有效结果。
        if status != "completed":
            self._fallback(active, f"后端任务{status or '返回状态缺失'}")
            return
        merged = self._cache.merge(
            active["fingerprint"],
            active["requested"],
            result,
            active["payload"].get("project") or {},
            active["payload"].get("options") or {},
        )
        self._emit_result(active, merged, "L2", "L2 后端任务完成")
        self._finish_active()

    # ---- 进程内回调 -----------------------------------------------------------

    def _on_bridge_result(self, payload: dict) -> None:
        active = self._active
        if active is None or active.get("transport") != "inprocess":
            return
        if payload.get("version") != active.get("bridge_version"):
            return
        result = dict(payload)
        if str(result.get("status", "")) == "completed":
            result = self._cache.merge(
                active["fingerprint"],
                active["requested"],
                result,
                active["payload"].get("project") or {},
                active["payload"].get("options") or {},
            )
        self._emit_result(active, result, "fallback", "进程内引擎直算完成")
        self._finish_active()

    def _fallback(self, active: dict[str, Any], reason: str) -> None:
        """L2 失败 → 同步回退进程内引擎（本会话禁用 HTTP）。"""
        self._http_disabled = True
        self._run_inprocess(active, f"{reason} → 进程内引擎直算")

    # ---- 输出 ---------------------------------------------------------------

    def _emit_result(
        self,
        active: dict[str, Any],
        body: dict[str, Any],
        level: str,
        note: str,
    ) -> None:
        metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        analyses = metadata.get("frontend_cached_analyses") or sorted(active["requested"])
        self.resultReady.emit(
            {
                "version": int(active["version"]),
                "status": str(body.get("status", "completed") or "completed"),
                "arrays": dict(body.get("arrays", {}) or {}),
                "metrics": dict(body.get("metrics", {}) or {}),
                "warnings": list(body.get("warnings", []) or []),
                "errors": list(body.get("errors", []) or []),
                "elapsed_ms": int(float(body.get("elapsed_ms", 0) or 0)),
                "level": level,
                "note": note,
                "analyses": list(analyses),
            }
        )


__all__ = ["CHART_ANALYSES", "RefreshController", "chart_analyses"]

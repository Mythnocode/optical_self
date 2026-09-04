from __future__ import annotations

import time
from collections import OrderedDict
from threading import RLock
from contextlib import contextmanager

import numpy as np
from collections.abc import Sequence
from typing import Any

from shared_contracts.simulation import SimulationRequest, SimulationResult
from shared_ports.progress import CancellationTokenPort, ProgressReporterPort
from shared_ports.simulation import SimulationPort

from .analysis_mapper import normalize_analyses
from .analysis_registry import AnalysisCategory, DEFAULT_ANALYSIS_REGISTRY
from .geometric_pipeline import GeometricPipeline
from .hybrid_pipeline import HybridPipeline
from .request_compiler import compile_simulation_context
from .result_builder import build_completed_result, build_failed_result
from .result_merger import EnginePartialResult
from .task_graph import build_task_graph
from .wave_pipeline import WavePipeline



def _compact_metrics(metrics: dict[str, Any], *, max_items: int = 96) -> dict[str, Any]:

    compact: dict[str, Any] = {}
    for key, value in metrics.items():
        if len(compact) >= max_items:
            break
        if value is None or isinstance(value, (str, bool, int, float, np.generic)):
            compact[str(key)] = value.item() if isinstance(value, np.generic) else value
        elif isinstance(value, dict) and len(value) <= 16:
            nested = {
                str(k): (v.item() if isinstance(v, np.generic) else v)
                for k, v in value.items()
                if v is None or isinstance(v, (str, bool, int, float, np.generic))
            }
            if nested:
                compact[str(key)] = nested
        elif isinstance(value, (list, tuple)) and len(value) <= 16 and all(
            item is None or isinstance(item, (str, bool, int, float, np.generic))
            for item in value
        ):
            compact[str(key)] = [
                item.item() if isinstance(item, np.generic) else item for item in value
            ]
    return compact


def _emit_partial(progress: Any, payload: dict[str, Any], *, stage: str) -> None:
    publisher = getattr(progress, "partial", None)
    if callable(publisher):
        publisher(payload, stage=stage)


def _preview_array_payload(
    arrays: dict[str, Any],
    *,
    max_side: int = 129,
    max_arrays: int = 10,
    max_points: int = 120_000,
) -> dict[str, Any]:

    preview: dict[str, Any] = {}
    used_points = 0
    for key, raw in dict(arrays or {}).items():
        if len(preview) >= max_arrays:
            break
        name = str(key)
        lowered = name.lower()
        if any(token in lowered for token in (
            "raytrace_path", "path_offsets", "termination", "status_codes"
        )):
            continue
        try:
            value = np.asarray(raw)
        except Exception:
            continue
        if value.dtype.kind not in "biufc" or value.ndim == 0:
            continue
        
        
        if value.ndim == 2 and value.shape[1] <= 4 and value.shape[0] > max_side:
            continue
        if value.ndim == 1:
            indices = np.linspace(
                0, max(0, value.shape[0] - 1), min(value.shape[0], max_side * 4),
                dtype=np.int64,
            )
            reduced = value[indices]
        elif value.ndim == 2:
            y_idx = np.linspace(
                0, max(0, value.shape[0] - 1), min(value.shape[0], max_side),
                dtype=np.int64,
            )
            x_idx = np.linspace(
                0, max(0, value.shape[1] - 1), min(value.shape[1], max_side),
                dtype=np.int64,
            )
            reduced = value[np.ix_(y_idx, x_idx)]
        else:
            continue
        if np.iscomplexobj(reduced):
            
            
            continue
        points = int(reduced.size)
        if used_points + points > max_points:
            continue
        used_points += points
        preview[name] = np.asarray(reduced, dtype=np.float32).tolist()
    return preview


class ByteBoundLRUCache:


    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max(0, int(max_bytes))
        self._items: OrderedDict[str, tuple[Any, int]] = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._lock = RLock()
        self._key_locks: dict[str, tuple[RLock, int]] = {}

    @staticmethod
    def _estimate_bytes(value: Any) -> int:
        seen: set[int] = set()
        total = 0
        stack = [value]
        while stack:
            item = stack.pop()
            identifier = id(item)
            if identifier in seen:
                continue
            seen.add(identifier)
            if isinstance(item, np.ndarray):
                total += int(item.nbytes)
            elif isinstance(item, dict):
                stack.extend(item.keys())
                stack.extend(item.values())
            elif isinstance(item, (list, tuple, set)):
                stack.extend(item)
            else:
                slots = getattr(type(item), "__slots__", ())
                if isinstance(slots, str):
                    slots = (slots,)
                for name in slots:
                    if hasattr(item, name):
                        stack.append(getattr(item, name))
        return max(total, 1)

    def get(self, key: str) -> Any | None:
        if self.max_bytes <= 0:
            return None
        with self._lock:
            item = self._items.pop(str(key), None)
            if item is None:
                self._misses += 1
                return None
            self._items[str(key)] = item
            self._hits += 1
            return item[0]

    def put(self, key: str, value: Any) -> None:
        if self.max_bytes <= 0:
            return
        size = self._estimate_bytes(value)
        if size > self.max_bytes:
            return
        with self._lock:
            old = self._items.pop(str(key), None)
            if old is not None:
                self._bytes -= old[1]
            self._items[str(key)] = (value, size)
            self._bytes += size
            while self._bytes > self.max_bytes and self._items:
                _, (_, removed_size) = self._items.popitem(last=False)
                self._bytes -= removed_size

    @contextmanager
    def key_lock(self, key: str):

        token = str(key)
        with self._lock:
            entry = self._key_locks.get(token)
            if entry is None:
                lock, users = RLock(), 0
            else:
                lock, users = entry
            self._key_locks[token] = (lock, users + 1)
        try:
            with lock:
                yield
        finally:
            with self._lock:
                current = self._key_locks.get(token)
                if current is not None and current[0] is lock:
                    remaining = current[1] - 1
                    if remaining <= 0:
                        self._key_locks.pop(token, None)
                    else:
                        self._key_locks[token] = (lock, remaining)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0
            self._key_locks.clear()

    def info(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self._hits, "misses": self._misses,
                "entries": len(self._items), "bytes": self._bytes,
                "max_bytes": self.max_bytes,
            }



_TraceLRUCache = ByteBoundLRUCache


class AnalysisNotImplementedError(RuntimeError):
    code = "ANALYSIS_NOT_IMPLEMENTED"
    stage = "optical_runtime.analysis"
    retryable = False

    def __init__(self, analyses: list[str]) -> None:
        self.context = {"analyses": analyses}
        super().__init__("Unsupported optical analysis: " + ", ".join(analyses))


class OpticalSimulationEngine(SimulationPort):


    name = "headless"
    version = "native-optical-core-v3.2"
    algorithm_version = "coupling-research-task-graph-v5-unpolarized-fresnel"

    def __init__(
        self,
        *,
        trace_cache_max_bytes: int = 512 * 1024**2,
        shared_trace_cache: ByteBoundLRUCache | None = None,
    ) -> None:
        self.geometric_pipeline = GeometricPipeline()
        self.wave_pipeline = WavePipeline()
        self.hybrid_pipeline = HybridPipeline()
        self._shared_trace_cache = (
            shared_trace_cache
            if shared_trace_cache is not None
            else ByteBoundLRUCache(trace_cache_max_bytes)
        )

    def clear_prepared_coupling_cache(self) -> None:
        """Release dense prepared-coupling state without discarding the ray cache.

        Long parameter scans can visit hundreds of unique receiver offsets.  A
        PreparedCouplingProblem intentionally caches generated receiver modes and
        evaluations for interactive reuse, but those dense 2-D fields are not
        useful once a scan batch has reduced them to scalar response metrics.
        Clearing only this runtime cache keeps scan memory bounded while preserving
        the shared geometric trace cache and does not change any optical calculation.
        """
        self.hybrid_pipeline.clear_caches()

    def clear_caches(self) -> None:
        self._shared_trace_cache.clear()
        self.clear_prepared_coupling_cache()
        try:
            from optical_core.physics.wave.solvers.advanced_propagation import clear_all_propagation_caches
            clear_all_propagation_caches()
        except ImportError:
            pass
        try:
            from optical_core.physics.hybrid.solvers.cartesian_pupil_propagation import (
                clear_cartesian_pupil_caches,
            )
            clear_cartesian_pupil_caches()
        except ImportError:
            pass
        try:
            from optical_core.physics.wave.solvers.sampling_advisor import clear_sampling_advice_cache
            clear_sampling_advice_cache()
        except ImportError:
            pass
        try:
            from optical_core.physics.hybrid.solvers.fiber_coupling import clear_global_fiber_mode_cache
            clear_global_fiber_mode_cache()
        except ImportError:
            pass

    def cache_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "trace": self._shared_trace_cache.info(),
            "prepared_coupling": self.hybrid_pipeline.cache_info(),
        }
        try:
            from optical_core.physics.hybrid.solvers.cartesian_pupil_propagation import (
                cartesian_pupil_cache_info,
            )
            info["cartesian_pupil"] = cartesian_pupil_cache_info()
        except ImportError:
            pass
        try:
            from optical_core.physics.wave.solvers.advanced_propagation import (
                propagation_spectrum_cache_info,
            )
            info["propagation"] = propagation_spectrum_cache_info()
        except ImportError:
            pass
        try:
            from optical_core.physics.wave.solvers.sampling_advisor import sampling_advice_cache_info
            info["sampling_advice"] = sampling_advice_cache_info()
        except ImportError:
            pass
        try:
            from optical_core.physics.hybrid.solvers.fiber_coupling import global_fiber_mode_cache_info
            info["fiber_mode"] = global_fiber_mode_cache_info()
        except ImportError:
            pass
        return info

    def evaluate(
        self,
        request: SimulationRequest,
        cancellation: CancellationTokenPort | None = None,
        progress: ProgressReporterPort | None = None,
    ) -> SimulationResult:
        started_at = time.perf_counter()
        stage_timings_ms: dict[str, float] = {}

        def add_timing(name: str, since: float) -> None:
            stage_timings_ms[name] = round(
                stage_timings_ms.get(name, 0.0)
                + (time.perf_counter() - since) * 1000.0,
                3,
            )

        try:
            if self._is_multi_path_request(request):
                return self._evaluate_multi_path(
                    request=request,
                    cancellation=cancellation,
                    progress=progress,
                    started_at=started_at,
                )

            if self._is_cancelled(cancellation):
                partial = EnginePartialResult.empty()
                partial.converged = False
                partial.metadata["cancelled"] = True
                return build_completed_result(
                    request=request,
                    engine_name=self.name,
                    engine_version=self.version,
                    algorithm_version=self.algorithm_version,
                    started_at=started_at,
                    partial=partial,
                )

            if progress is not None:
                progress.update(0.03, "optical_engine.compile")

            compile_started = time.perf_counter()
            context = compile_simulation_context(request)
            context.shared_trace_cache = self._shared_trace_cache
            analyses = normalize_analyses(request)
            add_timing("参数校验与编译", compile_started)
            if progress is not None:
                progress.update(0.07, "optical_engine.compiled")
            unsupported = [spec.name for spec in analyses if DEFAULT_ANALYSIS_REGISTRY.get(spec.name) is None]
            if unsupported:
                raise AnalysisNotImplementedError(unsupported)

            
            
            
            
            if any(DEFAULT_ANALYSIS_REGISTRY.resolve(spec.name).requires_complex_field for spec in analyses):
                geometric_options = context.scene.options.setdefault("geometric", {})
                hybrid_options = context.scene.options.setdefault("hybrid", {})
                geometric_options["record_surfaces"] = True
                hybrid_options["record_surfaces"] = True
                
                
                
                geometric_options.setdefault("sampling_role", "complex_field_dense")
                hybrid_options.setdefault("sampling_role", "complex_field_dense")
                context.metadata["surface_history_recorded_for_complex_field_roles"] = True
                
                context.metadata["surface_history_recorded_for_shared_trace"] = True

            graph_started = time.perf_counter()
            graph = build_task_graph(analyses, context)
            ordered = graph.topological_order()
            add_timing("任务图构建", graph_started)
            if progress is not None:
                progress.update(0.10, "optical_engine.graph_ready")
            final = EnginePartialResult.empty()
            analysis_nodes = [node for node in ordered if node.kind == "analysis"]
            completed_analyses = 0

            for node in ordered:
                if self._is_cancelled(cancellation):
                    final.converged = False
                    final.metadata["cancelled"] = True
                    break

                if node.kind == "scene":
                    continue
                if node.kind == "trace":
                    if progress is not None:
                        progress.update(0.14, "optical_engine.trace.running")
                    trace_started = time.perf_counter()
                    if progress is not None:
                        context.trace_progress_callback = lambda fraction: progress.update(
                            0.14 + 0.28 * max(0.0, min(1.0, float(fraction))),
                            "optical_engine.trace.running",
                        )
                    try:
                        context.get_or_create_trace(dict(node.payload or {}))
                    finally:
                        context.trace_progress_callback = None
                    add_timing("光线追迹", trace_started)
                    if progress is not None:
                        progress.update(0.42, "optical_engine.trace.completed")
                    continue
                if node.kind != "analysis":
                    raise RuntimeError(f"unknown optical task kind: {node.kind!r}")

                spec = node.payload
                definition = DEFAULT_ANALYSIS_REGISTRY.resolve(spec.name)
                if progress is not None:
                    analysis_start_fraction = 0.42 + 0.48 * completed_analyses / max(1, len(analysis_nodes))
                    progress.update(analysis_start_fraction, f"optical_engine.analysis.{spec.name}.running")
                analysis_started = time.perf_counter()
                if definition.category is AnalysisCategory.GEOMETRIC:
                    partial = self.geometric_pipeline.evaluate(
                        system=context.scene.system,
                        analyses=[spec],
                        global_options=context.scene.options,
                        context=context,
                    )
                elif definition.category is AnalysisCategory.WAVE:
                    partial = self.wave_pipeline.evaluate(
                        system=context.scene.system,
                        analyses=[spec],
                        global_options=context.scene.options,
                    )
                else:
                    partial = self.hybrid_pipeline.evaluate(
                        system=context.scene.system,
                        analyses=[spec],
                        global_options=context.scene.options,
                        context=context,
                        cancellation=cancellation,
                    )

                final.merge(partial, namespace=spec.name, on_conflict="namespace")
                if definition.category is AnalysisCategory.WAVE:
                    timing_name = "波动传播"
                elif definition.category is AnalysisCategory.HYBRID and spec.name in {
                    "coupling", "fiber_coupling", "mode_overlap", "alignment_5axis"
                }:
                    timing_name = "耦合计算"
                elif definition.category is AnalysisCategory.HYBRID:
                    timing_name = "混合分析"
                else:
                    timing_name = "几何分析"
                add_timing(timing_name, analysis_started)
                completed_analyses += 1
                fraction = (
                    0.42 + 0.48 * completed_analyses / len(analysis_nodes)
                    if analysis_nodes else 0.90
                )
                if progress is not None:
                    progress.update(fraction, f"optical_engine.analysis.{spec.name}.completed")
                    preview_arrays = _preview_array_payload(partial.arrays)
                    preview_result = None
                    if preview_arrays:
                        preview_result = {
                            "request_id": str(getattr(request, "request_id", "")),
                            "status": "completed",
                            "metrics": _compact_metrics(final.metrics),
                            "arrays": preview_arrays,
                            "warnings": [],
                            "errors": [],
                            "elapsed_ms": round(
                                (time.perf_counter() - started_at) * 1000.0, 3
                            ),
                            "converged": bool(final.converged),
                            "metadata": {
                                "analysis": str(spec.name),
                                "preview_only": True,
                                "preview_max_side": 129,
                            },
                        }
                    _emit_partial(
                        progress,
                        {
                            "analysis": str(spec.name),
                            "available_analyses": [
                                str(item.payload.name)
                                for item in analysis_nodes[:completed_analyses]
                            ],
                            "metrics": _compact_metrics(final.metrics),
                            "stage_timings_ms": dict(stage_timings_ms),
                            "converged": bool(final.converged),
                            **(
                                {"preview_result": preview_result}
                                if preview_result is not None else {}
                            ),
                        },
                        stage=f"optical_engine.partial.{spec.name}",
                    )

            final.warnings.extend(context.warnings)
            final.metadata.update(context.metadata)
            final.metadata.update(
                {
                    "execution_model": "request_scoped_task_graph",
                    "task_graph_node_count": len(ordered),
                    "task_graph_order": [node.node_id for node in ordered],
                    "analysis_registry": "DEFAULT_ANALYSIS_REGISTRY",
                    "shared_trace_build_count": context.trace_build_count,
                    "formal_complex_field_chain": "cartesian_exit_pupil",
                    "engine_trace_cache": self._shared_trace_cache.info(),
                    "stage_timings_ms": dict(stage_timings_ms),
                    "progressive_result_delivery": True,
                    "requested_analyses": [str(spec.name) for spec in analyses],
                }
            )

            stage_timings_ms["后端计算总计"] = round(
                (time.perf_counter() - started_at) * 1000.0, 3
            )
            final.metadata["stage_timings_ms"] = dict(stage_timings_ms)
            if progress is not None:
                progress.update(0.94, "optical_engine.finalizing")

            return build_completed_result(
                request=request,
                engine_name=self.name,
                engine_version=self.version,
                algorithm_version=self.algorithm_version,
                started_at=started_at,
                partial=final,
            )
        except Exception as exc:
            return build_failed_result(
                request=request,
                engine_name=self.name,
                engine_version=self.version,
                algorithm_version=self.algorithm_version,
                started_at=started_at,
                error=exc,
            )

    def _evaluate_multi_path(
        self,
        *,
        request: Any,
        cancellation: Any = None,
        progress: Any = None,
        started_at: float,
    ):
        from .multi_path_pipeline import MultiPathPipeline

        if self._is_cancelled(cancellation):
            partial = EnginePartialResult.empty()
            partial.converged = False
            partial.metadata.update({"cancelled": True, "multipath_mode": "independent"})
            return build_completed_result(
                request=request,
                engine_name=self.name,
                engine_version=self.version,
                algorithm_version=self.algorithm_version,
                started_at=started_at,
                partial=partial,
            )

        if progress is not None:
            progress.update(0.05, "optical_engine.multipath.start")
        pipeline = MultiPathPipeline(
            single_path_evaluator=lambda single_request: self.evaluate(
                single_request,
                cancellation=cancellation,
                progress=None,
            )
        )
        partial = pipeline.evaluate(request)
        if progress is not None:
            progress.update(0.94, "optical_engine.multipath.finalizing")
        return build_completed_result(
            request=request,
            engine_name=self.name,
            engine_version=self.version,
            algorithm_version=self.algorithm_version,
            started_at=started_at,
            partial=partial,
        )

    def _is_multi_path_request(self, request: Any) -> bool:
        simulation_type = str(getattr(request, "simulation_type", "") or "").strip().lower()
        if simulation_type in {"multi_path", "multipath"}:
            return True
        if isinstance(request, dict):
            simulation_type = str(request.get("simulation_type", "") or "").strip().lower()
            return simulation_type in {"multi_path", "multipath"} or "paths" in request
        return hasattr(request, "paths") and not hasattr(request, "project")

    def batch_evaluate(
        self,
        requests: Sequence[SimulationRequest],
        cancellation: CancellationTokenPort | None = None,
        progress: ProgressReporterPort | None = None,
        *,
        max_workers: int = 1,
        worker_pool: Any | None = None,
    ) -> list[SimulationResult]:

        if worker_pool is not None:
            return list(
                worker_pool.map(
                    requests,
                    cancellation=cancellation,
                    progress=progress,
                    stage="batch.evaluate",
                )
            )
        if int(max_workers) <= 1:
            items = tuple(requests)
            results: list[SimulationResult] = []
            for index, request in enumerate(items):
                results.append(
                    self.evaluate(request, cancellation=cancellation, progress=None)
                )
                if progress is not None and items:
                    progress.update(
                        (index + 1) / len(items),
                        "batch.evaluate",
                        completed_items=index + 1,
                        total_items=len(items),
                    )
            return results
        from .worker_pool import OpticalWorkerPool
        with OpticalWorkerPool(
            max_workers=int(max_workers),
            trace_cache_max_bytes=self._shared_trace_cache.max_bytes,
        ) as pool:
            return pool.map(
                requests,
                cancellation=cancellation,
                progress=progress,
                stage="batch.evaluate",
            )

    @staticmethod
    def _is_cancelled(cancellation: CancellationTokenPort | Any | None) -> bool:


        if cancellation is None:
            return False
        value = getattr(cancellation, "is_cancelled", False)
        if callable(value):
            value = value()
        return bool(value)

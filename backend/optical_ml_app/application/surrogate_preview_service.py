
from __future__ import annotations

from threading import RLock
from collections import OrderedDict
import os
from time import perf_counter
from typing import Any, Mapping
import numpy as np


class SurrogatePreviewService:


    def __init__(self, model_registry) -> None:
        self.registry = model_registry
        self._lock = RLock()
        self._max_loaded = max(1, int(os.getenv("OPTICAL_SURROGATE_PREVIEW_CACHE_MODELS", "3")))
        self._loaded: OrderedDict[str, tuple[Any, Any, dict]] = OrderedDict()

    def preview(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        started = perf_counter()
        record = self._select_model()
        if record is None:
            return self._unavailable(started, "no_compatible_bounded_model")
        model_id = str(record.get("model_id", ""))
        try:
            model, preprocessing, manifest = self._load(model_id)
            paths = list(manifest.get("feature_paths") or record.get("feature_paths") or [])
            if not paths:
                return self._unavailable(started, "model_has_no_feature_paths")
            project_data = dict(payload.get("project") or {})
            values = self._feature_values(project_data, paths, manifest)
            bounds = self._bounds(manifest, record)
            if not bounds or any(path not in bounds for path in paths):
                return self._unavailable(started, "training_bounds_missing")
            for path, value in values.items():
                lo, hi = bounds[path]
                if not np.isfinite(value) or value < lo or value > hi:
                    return self._unavailable(started, f"outside_training_domain:{path}")
            X = np.asarray([[values[path] for path in paths]], dtype=float)
            scaled = np.asarray(model.predict(preprocessing.transform_features(X)))
            if scaled.ndim == 1:
                scaled = scaled.reshape(1, -1)
            predicted = preprocessing.inverse_targets(scaled)[0]
            targets = list(manifest.get("target_names") or record.get("target_names") or [])
            raw = {str(name): float(value) for name, value in zip(targets, predicted)}
            metrics = self._coupling_metrics(raw)
            if not metrics:
                return self._unavailable(started, "coupling_target_missing")
            return {
                "available": True,
                "model_id": model_id,
                "in_training_domain": True,
                "metrics": metrics,
                "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
            }
        except Exception as exc:
            return self._unavailable(started, f"preview_error:{type(exc).__name__}")

    def _select_model(self) -> dict | None:
        for record in reversed(list(self.registry.list_models())):
            if str(record.get("status", "available")) != "available":
                continue
            text = " ".join(str(record.get(key, "")) for key in ("model_type", "algorithm", "name")).lower()
            targets = [str(item).lower() for item in record.get("target_names", [])]
            if not any("coupling" in item or "efficiency" in item or "loss" in item for item in targets):
                continue
            if text and not any(token in text for token in ("forest", "xgboost", "residual", "surrogate")):
                continue
            if self._bounds(record, record):
                return record
        return None

    def _load(self, model_id: str):
        with self._lock:
            cached = self._loaded.get(model_id)
            if cached is None:
                cached = self.registry.load(model_id)
                self._loaded[model_id] = cached
                while len(self._loaded) > self._max_loaded:
                    self._loaded.popitem(last=False)
            else:
                self._loaded.move_to_end(model_id)
            return cached

    @staticmethod
    def _bounds(manifest: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, tuple[float, float]]:
        raw = manifest.get("feature_ranges") or manifest.get("training_ranges") or manifest.get("feature_bounds")
        if not isinstance(raw, Mapping):
            raw = record.get("feature_ranges") or record.get("training_ranges") or record.get("feature_bounds")
        result: dict[str, tuple[float, float]] = {}
        if not isinstance(raw, Mapping):
            return result
        for key, value in raw.items():
            try:
                if isinstance(value, Mapping):
                    lo = value.get("min", value.get("low")); hi = value.get("max", value.get("high"))
                else:
                    lo, hi = value[0], value[1]
                lo = float(lo); hi = float(hi)
                if np.isfinite(lo) and np.isfinite(hi) and hi >= lo:
                    result[str(key)] = (lo, hi)
            except Exception:
                continue
        return result

    @staticmethod
    def _feature_values(project_data: dict, paths: list[str], manifest: Mapping[str, Any]) -> dict[str, float]:
        from shared_contracts.project import ProjectSnapshot
        from machine_learning.features.coupling_physics import enrich_candidate_features

        values: dict[str, float] = {}
        overrides = dict(manifest.get("default_features") or {})
        for path in paths:
            value: Any = project_data
            for part in str(path).split("."):
                if isinstance(value, Mapping) and part in value:
                    value = value[part]
                else:
                    value = overrides.get(path)
                    break
            if value is not None:
                try:
                    values[path] = float(value)
                except Exception:
                    pass
        try:
            project = ProjectSnapshot.model_validate(project_data)
            values = enrich_candidate_features(project, values)
        except Exception:
            pass
        missing = [path for path in paths if path not in values]
        if missing:
            raise ValueError("missing features: " + ", ".join(missing))
        return values

    @staticmethod
    def _coupling_metrics(raw: Mapping[str, float]) -> dict[str, float]:
        metrics = dict(raw)
        eta = None
        for key, value in raw.items():
            lowered = key.lower()
            if "coupling" in lowered and "efficiency" in lowered:
                eta = float(value); break
            if lowered in {"eta", "efficiency"}:
                eta = float(value); break
        if eta is None:
            for key, value in raw.items():
                if "loss" in key.lower() and "db" in key.lower():
                    eta = 10.0 ** (-float(value) / 10.0); break
        if eta is None:
            return {}
        eta = float(np.clip(eta, 0.0, 1.0))
        metrics.setdefault("coupling_efficiency", eta)
        metrics.setdefault("total_coupling_efficiency", eta)
        metrics.setdefault("loss_db", float(-10.0 * np.log10(max(eta, 1e-15))))
        return metrics

    @staticmethod
    def _unavailable(started: float, reason: str) -> dict[str, Any]:
        return {
            "available": False,
            "reason": reason,
            "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
        }

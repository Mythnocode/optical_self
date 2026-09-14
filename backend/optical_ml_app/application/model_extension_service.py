

from __future__ import annotations

import logging
import threading
import hashlib
import json
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from backend.optical_ml_app.domain.errors import BackendApplicationError
from machine_learning.datasets.storage import FileDatasetStore
from machine_learning.registry.model_registry import FileModelRegistry
from machine_learning.explainability.linkage_metadata import (
    enrich_local_formula_values,
    formula_consistency_record,
    formula_linkage_for_feature,
    infer_target_unit,
    target_supports_additive_formula_comparison,
)
from machine_learning.explainability.physics_features import PHYSICS_FEATURES

_logger = logging.getLogger(__name__)
_SHAP_CACHE_SCHEMA_VERSION = 5


def _default_display_feature_paths(
    feature_paths: Sequence[str],
    manifest: Mapping[str, Any],
) -> list[str]:
    """Return truthful, user-facing design features in model order.

    Derived physics features remain available to the estimator, but the main
    explanation ranks the radius/thickness/conic variables selected when the
    dataset was created.  Older manifests are supported by a conservative path
    inference; if no design feature can be identified we retain all inputs.
    """
    available = [str(path) for path in feature_paths]
    declared = [
        str(path)
        for path in list(manifest.get("design_variable_paths") or [])
        if str(path) in available
    ]
    if declared:
        return declared
    inferred = [
        path
        for path in available
        if path.endswith((".radius_mm", ".thickness_mm", ".distance_to_next_mm", ".conic"))
    ]
    return inferred or available


def _resolve_display_feature_paths(
    feature_paths: Sequence[str],
    manifest: Mapping[str, Any],
    requested: Sequence[str] | None,
    *,
    model_id: str,
) -> list[str]:
    available = [str(path) for path in feature_paths]
    defaults = _default_display_feature_paths(available, manifest)
    values = [str(path) for path in list(requested or [])]
    if not values:
        return defaults
    unknown = [path for path in values if path not in available]
    if unknown:
        raise BackendApplicationError(
            code="SHAP_DISPLAY_FEATURE_SCHEMA_MISMATCH",
            stage="model.shap",
            message="One or more requested explanation features were not used to train the model",
            context={
                "model_id": model_id,
                "unknown_feature_paths": unknown,
                "model_feature_paths": available,
            },
        )
    requested_set = set(values)
    ordered = [path for path in available if path in requested_set]
    if not ordered:
        raise BackendApplicationError(
            code="SHAP_DISPLAY_FEATURES_EMPTY",
            stage="model.shap",
            message="No valid design variables were selected for explanation",
            context={"model_id": model_id},
        )
    return ordered


def _to_dict(payload: Any) -> dict[str, Any]:

    if hasattr(payload, "model_dump"):
        return dict(payload.model_dump())
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _request_feature_array(
    features: Any,
    feature_paths: Sequence[str],
    *,
    model_id: str,
) -> Any:
    """Build a SHAP request row without inventing missing feature values."""
    import numpy as np

    if not isinstance(features, Mapping):
        raise BackendApplicationError(
            code="SHAP_FEATURE_SCHEMA_MISMATCH",
            stage="model.shap",
            message="SHAP request must provide a mapping for every model feature",
            context={"model_id": model_id, "feature_paths": list(feature_paths)},
        )
    missing = [path for path in feature_paths if path not in features]
    if missing:
        raise BackendApplicationError(
            code="SHAP_FEATURE_SCHEMA_MISMATCH",
            stage="model.shap",
            message="SHAP request is missing one or more trained features",
            context={
                "model_id": model_id,
                "missing_feature_paths": missing,
                "feature_paths": list(feature_paths),
            },
        )
    try:
        array = np.asarray(
            [[float(features[path]) for path in feature_paths]],
            dtype=float,
        )
    except (TypeError, ValueError) as exc:
        raise BackendApplicationError(
            code="SHAP_FEATURE_VALUES_INVALID",
            stage="model.shap",
            message="Request feature values must be finite numbers",
            context={"model_id": model_id},
        ) from exc
    if not np.all(np.isfinite(array)):
        raise BackendApplicationError(
            code="SHAP_FEATURE_VALUES_INVALID",
            stage="model.shap",
            message="Request feature values must be finite numbers",
            context={"model_id": model_id},
        )
    return array


def shap_dependence_map(
    feature_paths: Sequence[str],
    feature_values: Any,
    shap_matrix: Any,
) -> dict[str, dict[str, Any]]:
    """Pair each feature's raw values with its SHAP contributions."""
    import numpy as np

    values = np.asarray(feature_values, dtype=float)
    matrix = np.asarray(shap_matrix, dtype=float)
    dependence: dict[str, dict[str, Any]] = {}
    if values.ndim != 2 or matrix.ndim != 2:
        return dependence
    count = min(len(feature_paths), values.shape[1], matrix.shape[1])
    for feature_index in range(count):
        feature = str(feature_paths[feature_index])
        xs = values[:, feature_index].tolist()
        ys = matrix[:, feature_index].tolist()
        dependence[feature] = {
            "feature": feature,
            "x": xs,
            "feature_value": xs,
            "y": ys,
            "shap_value": ys,
        }
    return dependence


def _load_shap_module():

    try:
        import shap
    except Exception as exc:  
        _logger.warning("SHAP extension is unavailable: %s", exc)
        raise BackendApplicationError(
            code="SHAP_BACKEND_NOT_CONFIGURED",
            stage="model.shap",
            message="SHAP dependency is not available or failed to initialise",
            context={"package": "shap", "error_type": type(exc).__name__},
        ) from exc
    return shap


def _as_2d_predictions(values: Any, *, sample_count: int) -> Any:
    import numpy as np

    array = np.asarray(values, dtype=float)
    if array.ndim == 1:
        array = array.reshape(-1, 1)
    if array.ndim != 2 or array.shape[0] != sample_count:
        raise ValueError(f"unexpected prediction shape {array.shape}")
    return array


def _normalise_shap_outputs(
    values: Any,
    *,
    sample_count: int,
    feature_count: int,
    target_count: int,
) -> list[Any]:

    import numpy as np

    if isinstance(values, list):
        outputs = [np.asarray(item, dtype=float) for item in values]
    else:
        array = np.asarray(values, dtype=float)
        if array.ndim == 2:
            outputs = [array]
        elif array.ndim == 3 and array.shape[:2] == (sample_count, feature_count):
            outputs = [array[:, :, index] for index in range(array.shape[2])]
        elif array.ndim == 3 and array.shape[1:] == (sample_count, feature_count):
            outputs = [array[index, :, :] for index in range(array.shape[0])]
        else:
            raise ValueError(f"unexpected SHAP value shape {array.shape}")

    checked: list[Any] = []
    for matrix in outputs:
        matrix = np.asarray(matrix, dtype=float)
        if matrix.ndim == 1 and sample_count == 1 and matrix.size == feature_count:
            matrix = matrix.reshape(1, feature_count)
        if matrix.shape != (sample_count, feature_count):
            raise ValueError(f"unexpected per-target SHAP shape {matrix.shape}")
        checked.append(matrix)

    if len(checked) == 1 and target_count > 1:
        
        
        return checked
    return checked[:target_count]


def _normalise_expected_values(values: Any, *, target_count: int) -> list[float]:
    import numpy as np

    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size == 0:
        return [0.0] * target_count
    if array.size == 1:
        return [float(array[0])] * target_count
    return [float(item) for item in array[:target_count]]


class ModelExtensionService:


    def __init__(
        self,
        model_registry: FileModelRegistry,
        dataset_store: FileDatasetStore | None = None,
    ) -> None:
        self.model_registry = model_registry
        self.dataset_store = dataset_store
        
        
        self._shap_gate = threading.Semaphore(1)
        self._shap_cache_lock = threading.RLock()
        self._tree_explainer_cache: OrderedDict[tuple[str, str], Any] = OrderedDict()
        self._dataset_rows_cache: OrderedDict[tuple[Any, ...], tuple[Any, dict[str, dict]]] = OrderedDict()
        self._dataset_rows_cache_size = 4
        # Content digests make packaged SHAP caches stable across ZIP extraction.
        # Runtime mtime remains part of this *in-memory* digest cache key, so changed
        # files are rehashed immediately; the persisted SHAP key itself is based on
        # file contents and therefore survives copy/extract timestamp changes.
        self._content_digest_cache: OrderedDict[tuple[str, int, int], str] = OrderedDict()
        self._content_digest_cache_size = 32
        self._shap_result_cache_dir = (
            Path(self.model_registry.root).parent / "cache" / "shap"
        )
        self._shap_result_cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _mtime_ns(path: Path) -> int:
        try:
            return int(path.stat().st_mtime_ns)
        except OSError:
            return -1

    def _stable_file_digest(self, path: Path) -> str:
        try:
            stat = path.stat()
        except OSError:
            return "missing"
        key = (str(path.resolve()), int(stat.st_size), int(stat.st_mtime_ns))
        with self._shap_cache_lock:
            cached = self._content_digest_cache.pop(key, None)
            if cached is not None:
                self._content_digest_cache[key] = cached
                return cached
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            value = digest.hexdigest()
        except OSError:
            value = "missing"
        with self._shap_cache_lock:
            # Remove stale entries for the same path before inserting the current
            # content fingerprint.  This keeps update invalidation deterministic.
            for old_key in tuple(self._content_digest_cache):
                if old_key[0] == key[0] and old_key != key:
                    self._content_digest_cache.pop(old_key, None)
            self._content_digest_cache[key] = value
            while len(self._content_digest_cache) > self._content_digest_cache_size:
                self._content_digest_cache.popitem(last=False)
        return value

    def _dataset_signature(self, dataset_id: str | None) -> tuple[Any, ...]:
        if not dataset_id or self.dataset_store is None:
            return (str(dataset_id or ""), "missing", "missing")
        root = Path(self.dataset_store.root) / str(dataset_id)
        return (
            str(dataset_id),
            self._stable_file_digest(root / "manifest.json"),
            self._stable_file_digest(root / "samples.jsonl"),
        )

    def _model_shap_signature(self, model_id: str) -> tuple[str, str, str, str]:
        root = Path(self.model_registry.root) / str(model_id)
        return (
            str(model_id),
            self._stable_file_digest(root / "model.joblib"),
            self._stable_file_digest(root / "preprocessing.joblib"),
            self._stable_file_digest(root / "manifest.json"),
        )

    def _shap_cache_key(self, model_id: str, dataset_id: str | None, body: dict[str, Any]) -> str:
        signature = {
            "schema": _SHAP_CACHE_SCHEMA_VERSION,
            "model": list(self._model_shap_signature(model_id)),
            "dataset": list(self._dataset_signature(dataset_id)),
            "request": body,
        }
        encoded = json.dumps(
            signature,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _read_shap_cache(self, cache_key: str) -> dict[str, Any] | None:
        path = self._shap_result_cache_dir / f"{cache_key}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        result = dict(payload)
        result["cache_hit"] = True
        result["elapsed_ms"] = 0.0
        return result

    def _write_shap_cache(self, cache_key: str, payload: dict[str, Any]) -> None:
        path = self._shap_result_cache_dir / f"{cache_key}.json"
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp.replace(path)
        except (OSError, TypeError, ValueError):
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            _logger.debug("SHAP result cache write skipped", exc_info=True)

    # ------------------------------------------------------------------
    
    # ------------------------------------------------------------------

    def _tree_explainer(self, shap_module: Any, model_id: str, model: Any, manifest: dict[str, Any]):
        key = (
            str(model_id),
            repr(self.model_registry.artifact_signature(model_id)),
        )
        with self._shap_cache_lock:
            cached = self._tree_explainer_cache.pop(key, None)
            if cached is not None:
                self._tree_explainer_cache[key] = cached
                return cached
        explainer = shap_module.TreeExplainer(model)
        with self._shap_cache_lock:
            self._tree_explainer_cache[key] = explainer
            while len(self._tree_explainer_cache) > 4:
                self._tree_explainer_cache.popitem(last=False)
        return explainer

    def _load_registered_rows(
        self,
        *,
        dataset_id: str,
        feature_paths: Sequence[str],
        sample_ids: Sequence[str],
        max_samples: int,
        background_sample_count: int,
        random_seed: int,
    ) -> tuple[Any, list[str], Any, list[str]]:

        import numpy as np

        if self.dataset_store is None:
            raise BackendApplicationError(
                code="SHAP_DATASET_STORE_NOT_CONFIGURED",
                stage="model.shap",
                message="Dataset-backed SHAP requires a configured dataset store",
                context={"dataset_id": dataset_id},
            )
        signature = self._dataset_signature(dataset_id) + (tuple(feature_paths),)
        with self._shap_cache_lock:
            cached = self._dataset_rows_cache.pop(signature, None)
            if cached is not None:
                self._dataset_rows_cache[signature] = cached
        try:
            if cached is not None:
                manifest, by_id = cached
            else:
                manifest = self.dataset_store.load_manifest(dataset_id)
                records = [
                    record
                    for record in self.dataset_store.iter_samples(dataset_id)
                    if bool(record.get("valid", True))
                ]
                by_id = {
                    str(record.get("sample_id")): record
                    for record in records
                    if record.get("sample_id") is not None
                }
                with self._shap_cache_lock:
                    self._dataset_rows_cache[signature] = (manifest, by_id)
                    while len(self._dataset_rows_cache) > self._dataset_rows_cache_size:
                        self._dataset_rows_cache.popitem(last=False)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise BackendApplicationError(
                code="SHAP_DATASET_NOT_FOUND",
                stage="model.shap",
                message=f"Dataset {dataset_id} could not be loaded",
                context={"dataset_id": dataset_id, "error_type": type(exc).__name__},
            ) from exc

        if not by_id:
            raise BackendApplicationError(
                code="SHAP_DATASET_EMPTY",
                stage="model.shap",
                message=f"Dataset {dataset_id} contains no valid samples",
                context={"dataset_id": dataset_id},
            )

        if sample_ids:
            missing = [sample_id for sample_id in sample_ids if sample_id not in by_id]
            if missing:
                raise BackendApplicationError(
                    code="SHAP_SAMPLE_NOT_FOUND",
                    stage="model.shap",
                    message="One or more requested SHAP samples do not exist",
                    context={"dataset_id": dataset_id, "missing_sample_ids": missing[:20]},
                )
            explain_ids = list(dict.fromkeys(sample_ids))[:max_samples]
        else:
            preferred = list(manifest.test_ids) + list(manifest.validation_ids) + list(manifest.train_ids)
            explain_ids = [sample_id for sample_id in preferred if sample_id in by_id]
            if not explain_ids:
                explain_ids = sorted(by_id)
            explain_ids = explain_ids[:max_samples]

        def matrix(ids: Iterable[str]) -> Any:
            rows: list[list[float]] = []
            for sample_id in ids:
                values = by_id[sample_id].get("feature_values", {})
                try:
                    rows.append([float(values[path]) for path in feature_paths])
                except (KeyError, TypeError, ValueError) as exc:
                    raise BackendApplicationError(
                        code="SHAP_FEATURE_SCHEMA_MISMATCH",
                        stage="model.shap",
                        message="Dataset sample does not match the trained model feature schema",
                        context={
                            "dataset_id": dataset_id,
                            "sample_id": sample_id,
                            "feature_paths": list(feature_paths),
                        },
                    ) from exc
            array = np.asarray(rows, dtype=float)
            if array.ndim != 2 or array.shape[1] != len(feature_paths) or not np.all(np.isfinite(array)):
                raise BackendApplicationError(
                    code="SHAP_FEATURE_VALUES_INVALID",
                    stage="model.shap",
                    message="SHAP input contains non-finite or malformed feature values",
                    context={"dataset_id": dataset_id},
                )
            return array

        train_ids = [sample_id for sample_id in manifest.train_ids if sample_id in by_id]
        if not train_ids:
            train_ids = sorted(by_id)
        rng = np.random.default_rng(random_seed)
        if len(train_ids) > background_sample_count:
            positions = rng.choice(len(train_ids), size=background_sample_count, replace=False)
            background_ids = [train_ids[int(index)] for index in positions]
        else:
            background_ids = train_ids[:background_sample_count]

        return matrix(explain_ids), explain_ids, matrix(background_ids), background_ids

    def explain_shap(self, model_id: str, request_body: Any) -> dict[str, Any]:

        import time

        import numpy as np

        body = _to_dict(request_body)
        shap = _load_shap_module()
        started = time.perf_counter()

        try:
            model, preprocessing, manifest = self.model_registry.load(model_id)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise BackendApplicationError(
                code="MODEL_NOT_FOUND",
                stage="model.shap",
                message=f"Model {model_id} could not be loaded",
                context={"model_id": model_id, "error_type": type(exc).__name__},
            ) from exc

        target_names = list(manifest.get("target_names") or ["target"])
        feature_paths = list(manifest.get("feature_paths") or [])
        if not feature_paths:
            raise BackendApplicationError(
                code="MODEL_FEATURE_SCHEMA_MISSING",
                stage="model.shap",
                message="The model manifest does not define feature paths",
                context={"model_id": model_id},
            )
        display_feature_paths = _resolve_display_feature_paths(
            feature_paths,
            manifest,
            body.get("display_feature_paths"),
            model_id=model_id,
        )
        display_feature_set = set(display_feature_paths)
        display_feature_indices = [
            index for index, path in enumerate(feature_paths) if path in display_feature_set
        ]

        requested_dataset_id = body.get("dataset_id")
        model_dataset_id = manifest.get("dataset_id")
        dataset_id = str(requested_dataset_id or model_dataset_id or "") or None
        features = body.get("features")
        try:
            requested_top_k = int(body.get("top_k", 10))
            max_samples = int(body.get("max_samples", 100))
            background_sample_count = int(body.get("background_sample_count", 100))
            random_seed = int(body.get("random_seed", 42))
        except (TypeError, ValueError) as exc:
            raise BackendApplicationError(
                code="SHAP_REQUEST_INVALID",
                stage="model.shap",
                message="SHAP request limits must be integers",
                context={"model_id": model_id},
            ) from exc
        if requested_top_k < 1 or max_samples < 1 or background_sample_count < 1:
            raise BackendApplicationError(
                code="SHAP_REQUEST_INVALID",
                stage="model.shap",
                message="SHAP request limits must be positive",
                context={"model_id": model_id},
            )
        top_k = min(requested_top_k, len(display_feature_paths))
        requested_sample_ids = [str(item) for item in body.get("sample_ids", [])]

        if requested_dataset_id and model_dataset_id and str(requested_dataset_id) != str(model_dataset_id):
            raise BackendApplicationError(
                code="SHAP_DATASET_MODEL_MISMATCH",
                stage="model.shap",
                message="Requested dataset does not match the dataset used to train the model",
                context={
                    "model_id": model_id,
                    "model_dataset_id": model_dataset_id,
                    "requested_dataset_id": requested_dataset_id,
                },
            )

        cache_key = self._shap_cache_key(model_id, dataset_id, body)
        cached_result = self._read_shap_cache(cache_key)
        if cached_result is not None:
            return cached_result

        synthetic_samples = False
        data_source = "registered_dataset"
        if features is not None:
            X_raw = _request_feature_array(features, feature_paths, model_id=model_id)
            sample_ids = ["request-sample-0"]
            background_raw = X_raw.copy()
            background_ids = list(sample_ids)
            data_source = "request_features"
        elif dataset_id is not None:
            X_raw, sample_ids, background_raw, background_ids = self._load_registered_rows(
                dataset_id=dataset_id,
                feature_paths=feature_paths,
                sample_ids=requested_sample_ids,
                max_samples=max_samples,
                background_sample_count=background_sample_count,
                random_seed=random_seed,
            )
        else:
            raise BackendApplicationError(
                code="SHAP_DATASET_REQUIRED",
                stage="model.shap",
                message="SHAP needs the training dataset or explicit current-system features; synthetic samples are disabled",
                context={"model_id": model_id},
            )

        try:
            X = np.asarray(preprocessing.transform_features(X_raw), dtype=float)
            background = np.asarray(preprocessing.transform_features(background_raw), dtype=float)
        except Exception as exc:
            raise BackendApplicationError(
                code="SHAP_PREPROCESSING_FAILED",
                stage="model.shap",
                message="Model preprocessing failed for SHAP inputs",
                context={"model_id": model_id, "error_type": type(exc).__name__},
            ) from exc
        if not np.all(np.isfinite(X)) or not np.all(np.isfinite(background)):
            raise BackendApplicationError(
                code="SHAP_PREPROCESSING_NON_FINITE",
                stage="model.shap",
                message="Model preprocessing produced non-finite values",
                context={"model_id": model_id},
            )

        def predict_scaled(values: Any) -> Any:
            return _as_2d_predictions(model.predict(values), sample_count=len(values))

        def predict_original(values: Any) -> Any:
            scaled = predict_scaled(values)
            return np.asarray(preprocessing.inverse_targets(scaled), dtype=float)

        explainer_name = "KernelExplainer"
        output_scale = np.ones(len(target_names), dtype=float)
        output_offset = np.zeros(len(target_names), dtype=float)
        self._shap_gate.acquire()
        try:
            model_type = str(manifest.get("model_type", "")).lower()
            is_tree_model = model_type in {
                "random_forest",
                "gradient_boosting",
                "extra_trees",
                "xgboost",
                "lightgbm",
            } or hasattr(model, "estimators_")
            if is_tree_model:
                explainer = self._tree_explainer(shap, model_id, model, manifest)
                shap_values_raw = explainer.shap_values(X)
                expected_raw = explainer.expected_value
                explainer_name = "TreeExplainer"
                scaler = getattr(preprocessing, "y_scaler", None)
                scale = getattr(scaler, "scale_", None)
                mean = getattr(scaler, "mean_", None)
                if scale is not None:
                    output_scale = np.asarray(scale, dtype=float).reshape(-1)
                if mean is not None:
                    output_offset = np.asarray(mean, dtype=float).reshape(-1)
                predictions = predict_original(X)
            else:
                kernel_predict = lambda values: predict_original(values)  
                explainer = shap.KernelExplainer(kernel_predict, background)
                shap_values_raw = explainer.shap_values(
                    X,
                    nsamples=min(200, max(50, 2 * len(feature_paths) + 1)),
                )
                expected_raw = explainer.expected_value
                predictions = predict_original(X)
        except BackendApplicationError:
            raise
        except Exception as exc:
            _logger.exception("SHAP computation failed for model %s", model_id)
            raise BackendApplicationError(
                code="SHAP_COMPUTATION_FAILED",
                stage="model.shap",
                message="SHAP computation failed for this model or dataset",
                context={"model_id": model_id, "error_type": type(exc).__name__},
            ) from exc
        finally:
            self._shap_gate.release()

        matrices = _normalise_shap_outputs(
            shap_values_raw,
            sample_count=len(X),
            feature_count=len(feature_paths),
            target_count=len(target_names),
        )
        explained_target_count = len(matrices)
        explained_target_names = target_names[:explained_target_count]
        base_values_raw = _normalise_expected_values(expected_raw, target_count=explained_target_count)

        target_results: list[dict[str, Any]] = []
        global_top_features: list[dict[str, Any]] = []
        base_values: dict[str, float] = {}
        primary_contributions: list[dict[str, Any]] = []
        primary_formula_consistency: list[dict[str, Any]] = []
        formula_dependence: dict[str, dict[str, Any]] = {}
        shap_dependence: dict[str, dict[str, Any]] = {}
        formula_warnings: list[str] = []
        primary_target_name = ""
        primary_target_unit = ""
        primary_additivity_error: float | None = None
        formula_comparison_enabled = False

        for target_index, (target_name, matrix) in enumerate(zip(explained_target_names, matrices)):
            scale = float(output_scale[target_index]) if target_index < output_scale.size else 1.0
            offset = float(output_offset[target_index]) if target_index < output_offset.size else 0.0
            matrix_original = matrix * scale if explainer_name == "TreeExplainer" else matrix
            base_value = (
                float(base_values_raw[target_index]) * scale + offset
                if explainer_name == "TreeExplainer"
                else float(base_values_raw[target_index])
            )
            base_values[target_name] = base_value
            target_unit = infer_target_unit(target_name, manifest)
            target_formula_comparison = target_supports_additive_formula_comparison(
                target_name, target_unit
            )

            mean_shap = np.mean(matrix_original, axis=0)
            mean_abs_shap = np.mean(np.abs(matrix_original), axis=0)
            ranking = sorted(
                display_feature_indices,
                key=lambda feature_index: float(mean_abs_shap[feature_index]),
                reverse=True,
            )[:top_k]
            top_features: list[dict[str, Any]] = []
            displayed_total = float(
                sum(float(mean_abs_shap[index]) for index in display_feature_indices)
            )
            for index in ranking:
                feature_index = int(index)
                feature = feature_paths[feature_index]
                linkage = formula_linkage_for_feature(feature)
                item = {
                    "target": target_name,
                    "feature": feature,
                    "mean_shap": float(mean_shap[feature_index]),
                    "mean_abs_shap": float(mean_abs_shap[feature_index]),
                    "std_shap": float(np.std(matrix_original[:, feature_index])),
                    "relative_importance": (
                        float(mean_abs_shap[feature_index]) / displayed_total
                        if displayed_total > 0.0
                        else 0.0
                    ),
                    "sample_count": int(len(X)),
                }
                item.update(linkage.to_dict())
                top_features.append(item)

            if not global_top_features:
                primary_target_name = target_name
                primary_target_unit = target_unit
                formula_comparison_enabled = target_formula_comparison
                global_top_features = top_features
                all_dependence = shap_dependence_map(feature_paths, X_raw, matrix_original)
                shap_dependence = {
                    feature: all_dependence[feature]
                    for feature in display_feature_paths
                    if feature in all_dependence
                }
                primary_contributions = []
                for index in ranking:
                    feature_index = int(index)
                    feature = feature_paths[feature_index]
                    shap_value = float(matrix_original[0, feature_index])
                    linkage = formula_linkage_for_feature(feature)
                    contribution = {
                        "target": target_name,
                        "feature": feature,
                        "value": float(X_raw[0, feature_index]),
                        "shap_value": shap_value,
                        "abs_shap_value": float(abs(shap_value)),
                    }
                    contribution.update(
                        enrich_local_formula_values(
                            linkage,
                            feature_value=float(X_raw[0, feature_index]),
                            background_values=background_raw[:, feature_index],
                            shap_value=shap_value,
                            comparison_enabled=target_formula_comparison,
                        )
                    )
                    primary_contributions.append(contribution)

                primary_additivity_error = float(
                    base_value
                    + float(np.sum(matrix_original[0]))
                    - float(predictions[0, target_index])
                )

                if target_formula_comparison:
                    for feature_index, feature in enumerate(feature_paths):
                        consistency = formula_consistency_record(
                            feature,
                            X_raw[:, feature_index],
                            matrix_original[:, feature_index],
                        )
                        if consistency is not None:
                            primary_formula_consistency.append(consistency)

                        definition = PHYSICS_FEATURES.get(feature)
                        if definition is None:
                            continue
                        raw_values = np.asarray(X_raw[:, feature_index], dtype=float)
                        finite_values = raw_values[np.isfinite(raw_values)]
                        if finite_values.size < 2:
                            continue
                        x_curve = np.linspace(
                            float(np.min(finite_values)),
                            float(np.max(finite_values)),
                            min(160, max(40, len(finite_values))),
                        )
                        background_values = np.asarray(
                            background_raw[:, feature_index], dtype=float
                        )
                        background_values = background_values[np.isfinite(background_values)]
                        background_mean = float(
                            np.mean(
                                [definition.loss_db(float(value)) for value in background_values]
                            )
                        )
                        formula_curve = [
                            float(definition.loss_db(float(value)) - background_mean)
                            for value in x_curve
                        ]
                        formula_dependence[feature] = {
                            "feature": feature,
                            "formula_x": x_curve.tolist(),
                            "formula_centered_contribution": formula_curve,
                            "target_unit": "dB",
                        }
                elif any(
                    formula_linkage_for_feature(feature).mapping_level == "直接"
                    for feature in feature_paths
                ):
                    formula_warnings.append(
                        "当前输出不是dB损失，解析公式可以显示，但不与SHAP贡献作加性残差比较。"
                    )

            sample_shap_values = []
            for sample_index, sample_id in enumerate(sample_ids):
                visible_feature_values = {
                    feature: float(X_raw[sample_index, feature_index])
                    for feature_index, feature in enumerate(feature_paths)
                    if feature in display_feature_set
                }
                visible_shap_values = {
                    feature: float(matrix_original[sample_index, feature_index])
                    for feature_index, feature in enumerate(feature_paths)
                    if feature in display_feature_set
                }
                hidden_feature_contribution = float(
                    sum(
                        float(matrix_original[sample_index, feature_index])
                        for feature_index, feature in enumerate(feature_paths)
                        if feature not in display_feature_set
                    )
                )
                if len(display_feature_paths) < len(feature_paths):
                    # Keep the local waterfall additive without exposing every
                    # derived physics input as if it were an adjustable variable.
                    visible_shap_values["__other_model_features__"] = hidden_feature_contribution
                sample_shap_values.append(
                    {
                        "sample_id": sample_id,
                        "prediction": float(predictions[sample_index, target_index]),
                        "feature_values": visible_feature_values,
                        "shap_values": visible_shap_values,
                        "hidden_feature_contribution": hidden_feature_contribution,
                        "additivity_error": float(
                            base_value
                            + sum(visible_shap_values.values())
                            - float(predictions[sample_index, target_index])
                        ),
                    }
                )

            target_results.append(
                {
                    "target": target_name,
                    "target_name": target_name,
                    "target_unit": target_unit,
                    "base_value": base_value,
                    "top_features": top_features,
                    "sample_shap_values": sample_shap_values,
                }
            )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        response = {
            "explanation_run_id": f"shap-{cache_key[:12]}",
            "model_id": model_id,
            "dataset_id": dataset_id,
            "data_source": data_source,
            "synthetic_samples": synthetic_samples,
            "explainer": explainer_name,
            "target_name": primary_target_name,
            "target_unit": primary_target_unit,
            "target_names": explained_target_names,
            "model_feature_paths": feature_paths,
            "display_feature_paths": display_feature_paths,
            "hidden_feature_count": len(feature_paths) - len(display_feature_paths),
            "base_values": base_values,
            "feature_contributions": primary_contributions,
            "top_features": global_top_features,
            "formula_consistency": primary_formula_consistency,
            "formula_dependence": formula_dependence,
            "shap_dependence": shap_dependence,
            "formula_comparison_enabled": formula_comparison_enabled,
            "formula_comparison_domain": "dB损失" if formula_comparison_enabled else "仅展示公式",
            "additivity_error": primary_additivity_error,
            "warnings": formula_warnings,
            "targets": target_results,
            "sample_ids": sample_ids,
            "background_sample_ids": background_ids,
            "sample_count": len(X),
            "background_sample_count": len(background),
            "elapsed_ms": round(elapsed_ms, 1),
            "cache_hit": False,
        }
        self._write_shap_cache(cache_key, response)
        return response



from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Iterable, Sequence
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


def _to_dict(payload: Any) -> dict[str, Any]:

    if hasattr(payload, "model_dump"):
        return dict(payload.model_dump())
    if isinstance(payload, dict):
        return dict(payload)
    return {}


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

    # ------------------------------------------------------------------
    
    # ------------------------------------------------------------------

    def _tree_explainer(self, shap_module: Any, model_id: str, model: Any, manifest: dict[str, Any]):
        key = (str(model_id), str(manifest.get("created_at", manifest.get("dataset_id", ""))))
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
        try:
            manifest = self.dataset_store.load_manifest(dataset_id)
            records = [
                record
                for record in self.dataset_store.iter_samples(dataset_id)
                if bool(record.get("valid", True))
            ]
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise BackendApplicationError(
                code="SHAP_DATASET_NOT_FOUND",
                stage="model.shap",
                message=f"Dataset {dataset_id} could not be loaded",
                context={"dataset_id": dataset_id, "error_type": type(exc).__name__},
            ) from exc

        by_id = {
            str(record.get("sample_id")): record
            for record in records
            if record.get("sample_id") is not None
        }
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

        requested_dataset_id = body.get("dataset_id")
        model_dataset_id = manifest.get("dataset_id")
        dataset_id = str(requested_dataset_id or model_dataset_id or "") or None
        features = body.get("features")
        top_k = min(int(body.get("top_k", 10)), len(feature_paths))
        max_samples = int(body.get("max_samples", 100))
        background_sample_count = int(body.get("background_sample_count", 100))
        random_seed = int(body.get("random_seed", 42))
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

        synthetic_samples = False
        data_source = "registered_dataset"
        if features is not None:
            try:
                X_raw = np.asarray(
                    [[float(features.get(path, 0.0)) for path in feature_paths]],
                    dtype=float,
                )
            except (TypeError, ValueError) as exc:
                raise BackendApplicationError(
                    code="SHAP_FEATURE_VALUES_INVALID",
                    stage="model.shap",
                    message="Request feature values must be finite numbers",
                    context={"model_id": model_id},
                ) from exc
            if not np.all(np.isfinite(X_raw)):
                raise BackendApplicationError(
                    code="SHAP_FEATURE_VALUES_INVALID",
                    stage="model.shap",
                    message="Request feature values must be finite numbers",
                    context={"model_id": model_id},
                )
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
            
            
            rng = np.random.default_rng(random_seed)
            count = max(2, min(max_samples, max(background_sample_count, top_k)))
            X_raw = rng.normal(0.0, 1.0, (count, len(feature_paths)))
            background_raw = X_raw[: min(background_sample_count, count)]
            sample_ids = [f"synthetic-{index}" for index in range(count)]
            background_ids = sample_ids[: len(background_raw)]
            synthetic_samples = True
            data_source = "synthetic_fallback"

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
            ranking = np.argsort(mean_abs_shap)[::-1][:top_k]
            top_features: list[dict[str, Any]] = []
            for index in ranking:
                feature_index = int(index)
                feature = feature_paths[feature_index]
                linkage = formula_linkage_for_feature(feature)
                item = {
                    "target": target_name,
                    "feature": feature,
                    "mean_shap": float(mean_shap[feature_index]),
                    "mean_abs_shap": float(mean_abs_shap[feature_index]),
                }
                item.update(linkage.to_dict())
                top_features.append(item)

            if not global_top_features:
                primary_target_name = target_name
                primary_target_unit = target_unit
                formula_comparison_enabled = target_formula_comparison
                global_top_features = top_features
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
                sample_shap_values.append(
                    {
                        "sample_id": sample_id,
                        "prediction": float(predictions[sample_index, target_index]),
                        "feature_values": {
                            feature: float(X_raw[sample_index, feature_index])
                            for feature_index, feature in enumerate(feature_paths)
                        },
                        "shap_values": {
                            feature: float(matrix_original[sample_index, feature_index])
                            for feature_index, feature in enumerate(feature_paths)
                        },
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
        return {
            "model_id": model_id,
            "dataset_id": dataset_id,
            "data_source": data_source,
            "synthetic_samples": synthetic_samples,
            "explainer": explainer_name,
            "target_name": primary_target_name,
            "target_unit": primary_target_unit,
            "target_names": explained_target_names,
            "base_values": base_values,
            "feature_contributions": primary_contributions,
            "top_features": global_top_features,
            "formula_consistency": primary_formula_consistency,
            "formula_dependence": formula_dependence,
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
        }

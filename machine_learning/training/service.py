from __future__ import annotations

import time
import uuid

from shared_contracts.training import TrainingResult


def _random_forest_oob_curve(model, X_train, y_train, preprocessing):
    """Calculate cumulative OOB RMSE so RF has a truthful learning chart.

    RandomForestRegressor is fitted in one call and has no validation-iteration
    history.  Its bootstrap samples do, however, define an out-of-bag estimate
    for every prefix of the forest.  The chart is therefore labelled OOB RMSE,
    not presented as a made-up validation curve.
    """
    import numpy as np

    estimators = list(getattr(model, "estimators_", ()) or ())
    samples_by_tree = getattr(model, "estimators_samples_", None)
    if not estimators or samples_by_tree is None:
        return []
    X = np.asarray(X_train, dtype=float)
    actual = np.asarray(y_train, dtype=float)
    if actual.ndim == 1:
        actual = actual.reshape(-1, 1)
    if X.ndim != 2 or len(X) != len(actual):
        return []

    sums = np.zeros_like(actual, dtype=float)
    counts = np.zeros(len(actual), dtype=int)
    curve: list[float] = []
    for estimator, samples in zip(estimators, samples_by_tree):
        indices = np.asarray(samples, dtype=int).reshape(-1)
        oob = np.ones(len(actual), dtype=bool)
        oob[indices[(indices >= 0) & (indices < len(actual))]] = False
        if np.any(oob):
            predictions = np.asarray(estimator.predict(X[oob]), dtype=float)
            if predictions.ndim == 1:
                predictions = predictions.reshape(-1, 1)
            if predictions.shape != sums[oob].shape:
                return []
            sums[oob] += predictions
            counts[oob] += 1
        eligible = counts > 0
        if not np.any(eligible):
            continue
        mean_scaled = sums[eligible] / counts[eligible, None]
        predicted = np.asarray(preprocessing.inverse_targets(mean_scaled), dtype=float)
        error = predicted - actual[eligible]
        curve.append(float(np.sqrt(np.mean(error * error))))
    return curve


class TrainingService:
    def __init__(self, dataset_store, model_registry):
        self.dataset_store = dataset_store
        self.model_registry = model_registry

    def train(self, request, cancellation=None, progress=None):
        
        
        
        import numpy as np
        from machine_learning.datasets.splitter import resolve_training_splits, too_few_samples_message
        from machine_learning.evaluation.metrics import regression_metrics
        from machine_learning.features.coupling_physics import resolve_stored_target
        from machine_learning.models.factory import create_model
        from machine_learning.preprocessing.pipeline import PreprocessingPipeline
        from shared_contracts.metrics import canonical_metric_name

        started = time.perf_counter()
        manifest = self.dataset_store.load_manifest(request.dataset_id)
        records = [
            record
            for record in self.dataset_store.iter_samples(request.dataset_id)
            if record.get("valid")
        ]
        by_id = {record["sample_id"]: record for record in records}

        targets = [canonical_metric_name(name) for name in (request.target_names or manifest.target_names)]
        all_feature_paths = list(manifest.feature_paths)
        design_feature_paths = list(
            getattr(manifest, "design_variable_paths", None)
            or manifest.metadata.get("design_variable_paths", [])
        )
        # 随机森林与 XGBoost 都使用完整特征向量（设计变量 + 物理失配特征）。
        # 物理特征（尺寸失配、光束半径、横向/角向/轴向/曲率失配）本质上是
        # 耦合效率的解析公式因子；随机森林只用 8 个设计变量时 R² 约 -0.9，
        # 补上物理特征后 R² 提升到约 0.95。代价：SHAP 解释会包含非用户直接
        # 可控的派生特征，不再是纯"设计空间"。
        feature_paths = all_feature_paths
        unit_by_path = {
            str(path): str(manifest.feature_units[index])
            for index, path in enumerate(all_feature_paths)
            if index < len(manifest.feature_units)
        }
        feature_units = [unit_by_path.get(str(path), "") for path in feature_paths]

        if request.model_type == "xgboost_physics_residual":
            if targets == ["coupling_efficiency"]:
                targets = ["coupling_loss_db"]
            elif targets != ["coupling_loss_db"]:
                raise ValueError(
                    "XGBoost物理残差模型只接受单目标 coupling_loss_db；"
                    "请在数据生成阶段同时保存解析失配特征和dB损耗。"
                )

        def matrix(ids):
            try:
                X = np.array(
                    [[by_id[sample_id]["feature_values"][path] for path in feature_paths] for sample_id in ids],
                    dtype=float,
                )
                y = np.array(
                    [
                        [resolve_stored_target(by_id[sample_id]["target_values"], target) for target in targets]
                        for sample_id in ids
                    ],
                    dtype=float,
                )
            except KeyError as exc:
                raise ValueError(
                    f"数据集缺少字段 {exc}。XGBoost 物理残差需要耦合损耗(dB)以及解析失配特征；"
                    "请重新生成含耦合效率的数据集。"
                ) from exc
            return X, y

        train_ids, val_ids, test_ids = resolve_training_splits(
            list(by_id),
            manifest.train_ids,
            manifest.validation_ids,
            manifest.test_ids,
            seed=int(getattr(request, "random_seed", None) or manifest.random_seed or 42),
        )
        if not train_ids or not val_ids or not test_ids:
            raise ValueError(too_few_samples_message(len(by_id)))
        X_train, y_train = matrix(train_ids)
        X_val, y_val = matrix(val_ids)
        X_test, y_test = matrix(test_ids)
        if len(X_train) == 0 or len(X_val) == 0 or len(X_test) == 0:
            raise ValueError(too_few_samples_message(len(by_id)))

        physics_residual = request.model_type == "xgboost_physics_residual"
        pipeline = PreprocessingPipeline(
            scale_features=not physics_residual,
            scale_targets=not physics_residual,
        )
        prepared = pipeline.fit_transform(
            X_train, X_val, X_test, y_train, y_val, y_test
        )
        if progress is not None:
            progress.update(0.35, "training.preprocessing")

        model = create_model(
            request.model_type,
            request.random_seed,
            request.hyperparameters,
            feature_names=feature_paths,
        )
        train_target = (
            prepared.y_train.ravel()
            if prepared.y_train.shape[1] == 1
            else prepared.y_train
        )
        if request.model_type == "xgboost_physics_residual":
            validation_target = prepared.y_validation.ravel() if prepared.y_validation.shape[1] == 1 else prepared.y_validation
            model.fit(
                prepared.X_train,
                train_target,
                X_validation=prepared.X_validation,
                y_validation=validation_target,
            )
        else:
            model.fit(prepared.X_train, train_target)
        if progress is not None:
            progress.update(0.75, "training.fit")
            progress.update(0.80, "training.evaluating")

        val_scaled = np.asarray(model.predict(prepared.X_validation))
        test_scaled = np.asarray(model.predict(prepared.X_test))
        if val_scaled.ndim == 1:
            val_scaled = val_scaled.reshape(-1, 1)
            test_scaled = test_scaled.reshape(-1, 1)
        val_pred = pipeline.inverse_targets(val_scaled)
        test_pred = pipeline.inverse_targets(test_scaled)
        validation_metrics = regression_metrics(y_val, val_pred)
        test_metrics = regression_metrics(y_test, test_pred)

        model_id = "model-" + uuid.uuid4().hex[:12]
        model_manifest = {
            "model_id": model_id,
            "dataset_id": request.dataset_id,
            "model_type": request.model_type,
            "feature_paths": feature_paths,
            "feature_units": feature_units,
            "design_variable_paths": design_feature_paths,
            "physics_feature_paths": list(getattr(manifest, "physics_feature_paths", None) or manifest.metadata.get("physics_feature_paths", [])),
            "variable_scheme_id": getattr(manifest, "variable_scheme_id", None) or manifest.metadata.get("variable_scheme_id"),
            "target_names": targets,
            "engine_name": manifest.engine_name,
            "engine_version": manifest.engine_version,
            "validation_metrics": validation_metrics,
            "test_metrics": test_metrics,
            "physics_baseline": "analytic_coupling_mismatch"
            if physics_residual
            else None,
            "training_role": "physics_residual_surrogate"
            if physics_residual
            else "random_forest_baseline",
            "source_project": manifest.metadata.get("source_project"),
            "analytic_coupling_baseline": bool(
                manifest.metadata.get("analytic_coupling_baseline", False)
            ),
            
            
            
            "evaluation": {
                "sample_ids": [str(value) for value in manifest.test_ids],
                "actual": np.asarray(y_test, dtype=float).tolist(),
                "predicted": np.asarray(test_pred, dtype=float).tolist(),
                "residual": np.asarray(test_pred - y_test, dtype=float).tolist(),
            },
        }
        history = getattr(model, "history_", None) or getattr(model, "evals_result_", None)
        if isinstance(history, dict) and history:
            model_manifest["training_history"] = history
        requested_units = int(request.hyperparameters.get("n_estimators", 0) or 0)
        best_iteration = getattr(model, "best_iteration_", None)
        actual_units = requested_units
        if isinstance(history, dict) and history:
            lengths: list[int] = []
            stack = list(history.values())
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    stack.extend(value.values())
                elif isinstance(value, (list, tuple)):
                    lengths.append(len(value))
            if lengths:
                actual_units = max(lengths)
        early_stopped = bool(requested_units and actual_units and actual_units < requested_units)
        oob_curve = getattr(model, "oob_error_curve_", None)
        if oob_curve is None and request.model_type == "random_forest":
            oob_curve = _random_forest_oob_curve(
                model,
                prepared.X_train,
                y_train,
                pipeline,
            )
        if oob_curve is not None:
            values = [float(value) for value in np.asarray(oob_curve, dtype=float).reshape(-1) if np.isfinite(value)]
            if values:
                model_manifest["oob_error_curve"] = values

        curve_available = bool(
            (isinstance(history, dict) and history)
            or model_manifest.get("oob_error_curve")
        )
        curve_label = (
            "OOB RMSE"
            if model_manifest.get("oob_error_curve") and request.model_type == "random_forest"
            else "验证误差"
        )
        training_summary = {
            "requested_units": requested_units,
            "actual_units": actual_units,
            "best_iteration": int(best_iteration) if best_iteration is not None else None,
            "early_stopped": early_stopped,
            "early_stopping_rounds": int(request.hyperparameters.get("early_stopping_rounds", 0) or 0),
            "convergence": ("early_stopped" if early_stopped else ("not_applicable" if request.model_type == "random_forest" else "max_budget_reached")),
            "training_curve_status": "available" if curve_available else "unavailable",
            "training_curve_type": "oob_rmse" if model_manifest.get("oob_error_curve") else ("iteration" if history else "none"),
        }
        model_manifest["training_summary"] = training_summary
        model_manifest["training_curve_label"] = curve_label
        model_manifest["training_curve_description"] = (
            "随机森林按累计树数计算袋外 RMSE；它不是逐轮验证损失。"
            if model_manifest.get("oob_error_curve") and request.model_type == "random_forest"
            else "模型返回的逐轮验证误差。"
        ) if curve_available else "该模型没有可用的逐轮训练记录。"
        test_r2 = test_metrics.get("r2")
        prediction_usable = True
        quality_reason = ""
        if test_r2 is not None:
            try:
                score = float(test_r2)
            except (TypeError, ValueError):
                score = float("nan")
            if not np.isfinite(score) or score <= 0.0:
                prediction_usable = False
                quality_reason = f"测试 R²={score:.4g}，低于 0，不能用于当前镜头预测。"
        model_quality = {
            "prediction_usable": prediction_usable,
            "test_r2": test_r2,
            "reason": quality_reason,
        }
        model_manifest["model_quality"] = model_quality
        model_manifest["feature_paths"] = feature_paths
        model_manifest["feature_units"] = feature_units
        model_manifest["target_names"] = targets
        model_manifest["training_curve_status"] = "available" if curve_available else "unavailable"
        self.model_registry.save(model_id, model, pipeline, model_manifest)
        if progress is not None:
            progress.update(1.0, "training.completed")
        return TrainingResult(
            model_id=model_id,
            dataset_id=request.dataset_id,
            model_type=request.model_type,
            validation_metrics=validation_metrics,
            test_metrics=test_metrics,
            training_elapsed_ms=(time.perf_counter() - started) * 1000.0,
            metadata={
                "training_role": model_manifest["training_role"],
                "physics_residual": physics_residual,
                "training_summary": training_summary,
                "evaluation": model_manifest["evaluation"],
                "training_history": model_manifest.get("training_history", {}),
                "oob_error_curve": model_manifest.get("oob_error_curve", []),
                "training_curve_status": model_manifest["training_curve_status"],
                "training_curve_label": model_manifest["training_curve_label"],
                "training_curve_description": model_manifest["training_curve_description"],
                "feature_paths": feature_paths,
                "feature_units": feature_units,
                "design_variable_paths": design_feature_paths,
                "physics_feature_paths": model_manifest["physics_feature_paths"],
                "variable_scheme_id": model_manifest["variable_scheme_id"],
                "target_names": targets,
                "model_quality": model_quality,
            },
        )

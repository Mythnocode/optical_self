from __future__ import annotations

import time
import uuid

from shared_contracts.training import TrainingResult


class TrainingService:
    def __init__(self, dataset_store, model_registry):
        self.dataset_store = dataset_store
        self.model_registry = model_registry

    def train(self, request, cancellation=None, progress=None):
        
        
        
        import numpy as np
        from machine_learning.evaluation.metrics import regression_metrics
        from machine_learning.models.factory import create_model
        from machine_learning.preprocessing.pipeline import PreprocessingPipeline

        started = time.perf_counter()
        manifest = self.dataset_store.load_manifest(request.dataset_id)
        records = [
            record
            for record in self.dataset_store.iter_samples(request.dataset_id)
            if record.get("valid")
        ]
        by_id = {record["sample_id"]: record for record in records}
        targets = request.target_names or manifest.target_names
        feature_paths = list(manifest.feature_paths)

        if request.model_type == "xgboost_physics_residual":
            if targets != ["coupling_loss_db"]:
                raise ValueError(
                    "XGBoost物理残差模型只接受单目标 coupling_loss_db；"
                    "请在数据生成阶段同时保存解析失配特征和dB损耗。"
                )

        def matrix(ids):
            X = np.array(
                [[by_id[sample_id]["feature_values"][path] for path in feature_paths] for sample_id in ids],
                dtype=float,
            )
            y = np.array(
                [[by_id[sample_id]["target_values"][target] for target in targets] for sample_id in ids],
                dtype=float,
            )
            return X, y

        X_train, y_train = matrix(manifest.train_ids)
        X_val, y_val = matrix(manifest.validation_ids)
        X_test, y_test = matrix(manifest.test_ids)
        if len(X_train) == 0 or len(X_val) == 0 or len(X_test) == 0:
            raise ValueError("数据集切分后至少需要非空 train/validation/test")

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
            "feature_units": manifest.feature_units,
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
        oob_curve = getattr(model, "oob_error_curve_", None)
        if oob_curve is not None:
            model_manifest["oob_error_curve"] = np.asarray(oob_curve, dtype=float).tolist()
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
            },
        )

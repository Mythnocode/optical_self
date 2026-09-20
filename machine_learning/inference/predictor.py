from shared_contracts.prediction import PredictionResult


class Predictor:
    def __init__(self, registry):
        self.registry = registry

    def predict(self, request):
        import numpy as np
        from machine_learning.features.coupling_physics import (
            PHYSICS_RESIDUAL_FEATURE_PATHS,
            enrich_candidate_features,
        )
        from shared_contracts.project import ProjectSnapshot

        model, preprocessing, manifest = self.registry.load(request.model_id)
        paths = list(manifest["feature_paths"])
        features = {str(key): float(value) for key, value in request.features.items()}
        warnings: list[str] = []

        test_metrics = manifest.get("test_metrics")
        if isinstance(test_metrics, dict) and test_metrics.get("r2") is not None:
            try:
                test_r2 = float(test_metrics["r2"])
            except (TypeError, ValueError):
                test_r2 = float("nan")
            if not np.isfinite(test_r2) or test_r2 <= 0.0:
                raise ValueError(
                    f"模型测试 R²={test_r2:.4g}，低于 0，不能用于当前镜头预测"
                )

        missing_physics = [
            path
            for path in paths
            if path in PHYSICS_RESIDUAL_FEATURE_PATHS and path not in features
        ]
        if missing_physics:
            source_project = manifest.get("source_project")
            if source_project:
                project = ProjectSnapshot.model_validate(source_project)
                features = enrich_candidate_features(project, features)
                warnings.append("解析耦合特征已由训练数据源项目自动计算")

        missing = [path for path in paths if path not in features]
        if missing:
            raise ValueError("缺少特征: %s" % ", ".join(missing))
        if not all(np.isfinite(value) for value in features.values()):
            raise ValueError("模型输入包含非有限特征值")
        X = np.array([[features[path] for path in paths]], dtype=float)
        scaled = model.predict(preprocessing.transform_features(X))
        scaled = np.asarray(scaled)
        if scaled.ndim == 1:
            scaled = scaled.reshape(1, -1)
        values = preprocessing.inverse_targets(scaled)[0]
        predictions = dict(
            zip(manifest["target_names"], [float(value) for value in values])
        )
        # XGBoost 物理残差模型输出耦合损耗(dB)，附加转换为耦合效率，
        # 与随机森林模型的输出口径一致（η = 10^(-loss_db/10)）。
        if "coupling_loss_db" in predictions and "coupling_efficiency" not in predictions:
            predictions["coupling_efficiency"] = float(
                np.power(10.0, -predictions["coupling_loss_db"] / 10.0)
            )
        return PredictionResult(
            model_id=request.model_id,
            predictions=predictions,
            warnings=warnings,
        )

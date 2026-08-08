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
        X = np.array([[features[path] for path in paths]], dtype=float)
        scaled = model.predict(preprocessing.transform_features(X))
        scaled = np.asarray(scaled)
        if scaled.ndim == 1:
            scaled = scaled.reshape(1, -1)
        values = preprocessing.inverse_targets(scaled)[0]
        predictions = dict(
            zip(manifest["target_names"], [float(value) for value in values])
        )
        return PredictionResult(
            model_id=request.model_id,
            predictions=predictions,
            warnings=warnings,
        )


from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from machine_learning.datasets.storage import FileDatasetStore
from machine_learning.features.coupling_physics import (
    PHYSICS_RESIDUAL_FEATURE_PATHS,
    coupling_loss_db,
    derive_coupling_physics_features,
)
from machine_learning.features.resolver import FeatureResolver
from shared_contracts.project import ProjectSnapshot


def append_verified_result(
    dataset_root: str | Path,
    dataset_id: str,
    *,
    request_id: str,
    project: ProjectSnapshot,
    feature_values: Mapping[str, float] | None = None,
    target_values: Mapping[str, float],
    engine_name: str,
    engine_version: str,
    elapsed_ms: float = 0.0,
    metadata: Mapping[str, Any] | None = None,
) -> str:

    store = FileDatasetStore(Path(dataset_root))
    manifest = store.load_manifest(dataset_id)
    sample_id = "feedback-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    resolver = FeatureResolver()
    overrides = {str(key): float(value) for key, value in dict(feature_values or {}).items()}

    physics_features: dict[str, float] = {}
    if set(manifest.feature_paths) & set(PHYSICS_RESIDUAL_FEATURE_PATHS):
        physics_features = derive_coupling_physics_features(project, target_values)

    resolved_features: dict[str, float] = {}
    for path in manifest.feature_paths:
        if path in overrides:
            resolved_features[path] = overrides[path]
        elif path in physics_features:
            resolved_features[path] = physics_features[path]
        else:
            resolved_features[path] = resolver.get_value(project, path)

    resolved_targets = {str(key): float(value) for key, value in target_values.items() if isinstance(value, (int, float))}
    if "coupling_loss_db" in manifest.target_names and "coupling_loss_db" not in resolved_targets:
        loss = coupling_loss_db(target_values)
        if loss is not None:
            resolved_targets["coupling_loss_db"] = loss
    missing_targets = sorted(set(manifest.target_names) - set(resolved_targets))
    if missing_targets:
        raise ValueError("优化结果无法回填：缺少数据集目标 " + ", ".join(missing_targets))

    sample = {
        "sample_id": sample_id,
        "split": "train",
        "request_id": request_id,
        "project_fingerprint": project.fingerprint,
        "feature_values": {
            path: float(resolved_features[path]) for path in manifest.feature_paths
        },
        "target_values": {
            name: float(resolved_targets[name]) for name in manifest.target_names
        },
        "valid": True,
        "failure_code": "",
        "failure_message": "",
        "engine_name": engine_name,
        "engine_version": engine_version,
        "elapsed_ms": float(elapsed_ms),
        "converged": True,
        "metadata": {
            "source": "formal_optimization_feedback",
            "coupling_physics_features": physics_features,
            **dict(metadata or {}),
        },
    }
    store.append_sample(dataset_id, sample)
    manifest.sample_count += 1
    manifest.valid_sample_count += 1
    manifest.train_ids.append(sample_id)
    manifest.metadata["feedback_sample_count"] = int(
        manifest.metadata.get("feedback_sample_count", 0)
    ) + 1
    store.save_manifest(manifest)
    return sample_id

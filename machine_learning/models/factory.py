from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from machine_learning.models.random_forest import create_random_forest
from machine_learning.models.xgboost_physics_residual import (
    XGBoostPhysicsResidualRegressor,
)

SUPPORTED_MODEL_TYPES = ("random_forest", "xgboost_physics_residual")


def create_model(
    model_type: str,
    seed: int,
    hyperparameters: Mapping[str, Any] | None,
    *,
    feature_names: Sequence[str] = (),
):
    if model_type == "random_forest":
        return create_random_forest(seed, hyperparameters)
    if model_type == "xgboost_physics_residual":
        return XGBoostPhysicsResidualRegressor(
            feature_names=feature_names,
            random_seed=seed,
            hyperparameters=hyperparameters,
        )
    raise ValueError(
        f"不支持的模型类型: {model_type}; 可选值: {', '.join(SUPPORTED_MODEL_TYPES)}"
    )

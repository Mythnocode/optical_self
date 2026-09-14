
from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from machine_learning.explainability.physics_residual import (
    FORMULA_FEATURES,
    RESIDUAL_FEATURES,
    augment_residual_features,
    emphasis_weights,
    formula_baseline_db,
)

_REQUIRED_FEATURES = tuple(
    dict.fromkeys(
        [
            *FORMULA_FEATURES,
            "size_log_signed",
            "size_ratio",
            "fiber_mode_radius_um",
            "beam_radius_at_receiver_um",
        ]
    )
)


class XGBoostPhysicsResidualRegressor:


    def __init__(
        self,
        *,
        feature_names: Sequence[str],
        random_seed: int = 42,
        hyperparameters: Mapping[str, Any] | None = None,
    ) -> None:
        self.feature_names = tuple(str(name) for name in feature_names)
        self.random_seed = int(random_seed)
        self.hyperparameters = dict(hyperparameters or {})
        self.residual_model: Any | None = None
        self.required_feature_names = _REQUIRED_FEATURES
        self.residual_feature_names = RESIDUAL_FEATURES

    def _frame(self, X: Any) -> pd.DataFrame:
        if isinstance(X, pd.DataFrame):
            frame = X.copy()
            if tuple(frame.columns) != self.feature_names:
                frame = frame.loc[:, list(self.feature_names)]
        else:
            values = np.asarray(X, dtype=float)
            if values.ndim == 1:
                values = values.reshape(1, -1)
            if values.ndim != 2 or values.shape[1] != len(self.feature_names):
                raise ValueError(
                    "XGBoost物理残差模型输入维度不匹配: "
                    f"expected={len(self.feature_names)}, actual={values.shape}"
                )
            frame = pd.DataFrame(values, columns=self.feature_names)

        missing = sorted(set(self.required_feature_names) - set(frame.columns))
        if missing:
            raise ValueError(
                "XGBoost物理残差模型缺少解析耦合特征: " + ", ".join(missing)
            )
        return frame

    def _create_xgb(self):
        try:
            from xgboost import XGBRegressor
        except ImportError as exc:  
            raise RuntimeError(
                "训练XGBoost物理残差模型需要安装xgboost"
            ) from exc

        allowed = {
            "n_estimators",
            "max_depth",
            "learning_rate",
            "min_child_weight",
            "subsample",
            "colsample_bytree",
            "reg_alpha",
            "reg_lambda",
            "gamma",
            "max_leaves",
            "n_jobs",
            "tree_method",
            "early_stopping_rounds",
        }
        params: dict[str, Any] = {
            "n_estimators": 500,
            "max_depth": 4,
            "learning_rate": 0.05,
            "min_child_weight": 2.0,
            "subsample": 0.9,
            "colsample_bytree": 0.95,
            "reg_alpha": 0.01,
            "reg_lambda": 3.0,
            "objective": "reg:squarederror",
            "random_state": self.random_seed,
            "n_jobs": -1,
            "tree_method": "hist",
        }
        params.update(
            {key: value for key, value in self.hyperparameters.items() if key in allowed}
        )
        if int(params.get("early_stopping_rounds") or 0) <= 0:
            params.pop("early_stopping_rounds", None)
        return XGBRegressor(**params)

    def fit(self, X: Any, y: Any, *, X_validation: Any | None = None, y_validation: Any | None = None):
        frame = self._frame(X)
        target = np.asarray(y, dtype=float).reshape(-1)
        if len(target) != len(frame):
            raise ValueError("X与y样本数不一致")
        if not np.all(np.isfinite(target)):
            raise ValueError("coupling_loss_db目标必须为有限数")

        baseline = formula_baseline_db(frame)
        residual_target = target - baseline
        residual_x = augment_residual_features(frame)
        self.residual_model = self._create_xgb()
        fit_kwargs: dict[str, Any] = {"sample_weight": emphasis_weights(target)}
        if X_validation is not None and y_validation is not None:
            validation_frame = self._frame(X_validation)
            validation_target = np.asarray(y_validation, dtype=float).reshape(-1)
            validation_baseline = formula_baseline_db(validation_frame)
            validation_residual = validation_target - validation_baseline
            fit_kwargs["eval_set"] = [(augment_residual_features(validation_frame), validation_residual)]
            fit_kwargs["verbose"] = False
        self.residual_model.fit(residual_x, residual_target, **fit_kwargs)
        try:
            self.evals_result_ = dict(self.residual_model.evals_result())
        except Exception:
            self.evals_result_ = {}
        best = getattr(self.residual_model, "best_iteration", None)
        self.best_iteration_ = (int(best) + 1) if best is not None else None
        return self

    def predict(self, X: Any) -> np.ndarray:
        if self.residual_model is None:
            raise RuntimeError("XGBoost物理残差模型尚未训练")
        frame = self._frame(X)
        baseline = formula_baseline_db(frame)
        residual = np.asarray(
            self.residual_model.predict(augment_residual_features(frame)), dtype=float
        ).reshape(-1)
        return baseline + residual

    def predict_parts(self, X: Any) -> pd.DataFrame:
        frame = self._frame(X)
        prediction = self.predict(frame)
        baseline = formula_baseline_db(frame)
        return pd.DataFrame(
            {
                "formula_baseline_db": baseline,
                "ml_residual_db": prediction - baseline,
                "prediction_db": prediction,
            },
            index=frame.index,
        )

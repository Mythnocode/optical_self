
from __future__ import annotations

from dataclasses import dataclass
from math import log10
from typing import Iterable, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

FORMULA_FEATURES: tuple[str, ...] = (
    "size_log_mismatch",
    "lateral_mismatch",
    "angular_mismatch",
    "axial_mismatch",
    "curvature_mismatch",
)

RESIDUAL_FEATURES: tuple[str, ...] = (
    "size_log_mismatch",
    "size_log_signed",
    "size_ratio",
    "fiber_mode_radius_um",
    "beam_radius_at_receiver_um",
    "lateral_mismatch",
    "angular_mismatch",
    "axial_mismatch",
    "curvature_mismatch",
    "formula_size_loss_db",
    "formula_lateral_loss_db",
    "formula_angular_loss_db",
    "formula_axial_loss_db",
    "formula_curvature_loss_db",
    "formula_total_loss_db",
    "interaction_axial_curvature",
    "interaction_lateral_angular",
    "interaction_size_axial",
    "interaction_lateral_curvature",
    "interaction_size_lateral",
    "lateral_squared",
    "angular_squared",
    "axial_squared",
    "curvature_squared",
)

DB_PER_NEPER = 10.0 / np.log(10.0)


def formula_components_db(frame: pd.DataFrame) -> pd.DataFrame:

    us = frame["size_log_mismatch"].to_numpy(dtype=float)
    ur = frame["lateral_mismatch"].to_numpy(dtype=float)
    ut = frame["angular_mismatch"].to_numpy(dtype=float)
    uz = frame["axial_mismatch"].to_numpy(dtype=float)
    uR = frame["curvature_mismatch"].to_numpy(dtype=float)

    return pd.DataFrame(
        {
            "formula_size_loss_db": 20.0 * np.log10(np.cosh(us)),
            "formula_lateral_loss_db": DB_PER_NEPER * ur**2,
            "formula_angular_loss_db": DB_PER_NEPER * ut**2,
            "formula_axial_loss_db": 10.0 * np.log10(1.0 + (uz / 2.0) ** 2),
            "formula_curvature_loss_db": 10.0 * np.log10(1.0 + uR**2),
        },
        index=frame.index,
    )


def formula_baseline_db(frame: pd.DataFrame) -> np.ndarray:
    return formula_components_db(frame).sum(axis=1).to_numpy(dtype=float)


def augment_residual_features(frame: pd.DataFrame) -> pd.DataFrame:

    required = set(FORMULA_FEATURES) | {
        "size_log_signed",
        "size_ratio",
        "fiber_mode_radius_um",
        "beam_radius_at_receiver_um",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing physical features: {missing}")

    out = frame.loc[:, list(required)].copy()
    us = frame["size_log_mismatch"].to_numpy(dtype=float)
    ur = frame["lateral_mismatch"].to_numpy(dtype=float)
    ut = frame["angular_mismatch"].to_numpy(dtype=float)
    uz = frame["axial_mismatch"].to_numpy(dtype=float)
    uR = frame["curvature_mismatch"].to_numpy(dtype=float)

    components = formula_components_db(frame)
    for column in components.columns:
        out[column] = components[column].to_numpy(dtype=float)
    out["formula_total_loss_db"] = components.sum(axis=1).to_numpy(dtype=float)

    out["interaction_axial_curvature"] = np.abs(uz * uR)
    out["interaction_lateral_angular"] = np.abs(ur * ut)
    out["interaction_size_axial"] = us * np.abs(uz)
    out["interaction_lateral_curvature"] = ur**2 * np.abs(uR)
    out["interaction_size_lateral"] = us * ur
    out["lateral_squared"] = ur**2
    out["angular_squared"] = ut**2
    out["axial_squared"] = uz**2
    out["curvature_squared"] = uR**2
    return out.loc[:, list(RESIDUAL_FEATURES)]


def regression_metrics(y_true: Sequence[float], y_pred: Sequence[float]) -> dict[str, float]:
    truth = np.asarray(y_true, dtype=float)
    pred = np.asarray(y_pred, dtype=float)
    err = pred - truth
    return {
        "r2": float(r2_score(truth, pred)),
        "mae_db": float(mean_absolute_error(truth, pred)),
        "rmse_db": float(np.sqrt(mean_squared_error(truth, pred))),
        "p95_abs_error_db": float(np.quantile(np.abs(err), 0.95)),
        "max_abs_error_db": float(np.max(np.abs(err))),
        "bias_db": float(np.mean(err)),
    }


def emphasis_weights(loss_db: Sequence[float]) -> np.ndarray:

    y = np.asarray(loss_db, dtype=float)
    return 1.0 + 3.0 * np.exp(-y / 1.25) + 2.0 * np.exp(-np.abs(y - 1.0) / 0.30)


@dataclass
class PhysicsResidualModel:
    residual_model: object
    residual_feature_names: tuple[str, ...] = RESIDUAL_FEATURES
    target_name: str = "coupling_loss_db"
    target_unit: str = "dB"
    metadata: dict[str, object] | None = None

    def predict(self, physics_features: pd.DataFrame) -> np.ndarray:
        baseline = formula_baseline_db(physics_features)
        residual_x = augment_residual_features(physics_features)
        residual = np.asarray(self.residual_model.predict(residual_x), dtype=float)
        return baseline + residual

    def predict_parts(self, physics_features: pd.DataFrame) -> pd.DataFrame:
        components = formula_components_db(physics_features)
        residual_x = augment_residual_features(physics_features)
        components["ml_residual_db"] = np.asarray(
            self.residual_model.predict(residual_x), dtype=float
        )
        components["prediction_db"] = components.sum(axis=1)
        return components

    def save(self, path: str) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: str) -> "PhysicsResidualModel":
        model = joblib.load(path)
        if not isinstance(model, PhysicsResidualModel):
            raise TypeError("joblib file does not contain PhysicsResidualModel")
        return model

    def shap_values(self, physics_features: pd.DataFrame):

        import shap

        residual_x = augment_residual_features(physics_features)
        explainer = shap.TreeExplainer(self.residual_model)
        explanation = explainer(residual_x)
        values = np.asarray(explanation.values, dtype=float)
        base_values = np.asarray(explanation.base_values, dtype=float).reshape(-1)
        residual_prediction = np.asarray(
            self.residual_model.predict(residual_x), dtype=float
        )
        residual_reconstructed = base_values + values.sum(axis=1)
        formula = formula_baseline_db(physics_features)
        total_prediction = formula + residual_prediction
        total_reconstructed = formula + residual_reconstructed
        return {
            "explanation": explanation,
            "feature_frame": residual_x,
            "formula_baseline_db": formula,
            "residual_prediction_db": residual_prediction,
            "total_prediction_db": total_prediction,
            "residual_additivity_error_db": residual_reconstructed - residual_prediction,
            "total_additivity_error_db": total_reconstructed - total_prediction,
        }

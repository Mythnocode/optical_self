from __future__ import annotations

import numpy as np
import pytest

from backend.optical_ml_app.application.model_extension_service import (
    _default_display_feature_paths,
    _request_feature_array,
    _resolve_display_feature_paths,
)
from backend.optical_ml_app.domain.errors import BackendApplicationError


def test_shap_request_does_not_turn_missing_features_into_zero():
    with pytest.raises(BackendApplicationError) as exc_info:
        _request_feature_array(
            {"surfaces[0].radius_mm": 5.0},
            ["surfaces[0].radius_mm", "source.wavelength_nm"],
            model_id="model-1",
        )

    error = exc_info.value
    assert error.code == "SHAP_FEATURE_SCHEMA_MISMATCH"
    assert error.context["missing_feature_paths"] == ["source.wavelength_nm"]


def test_shap_request_preserves_feature_order_and_rejects_non_finite_values():
    values = _request_feature_array(
        {"b": 2.0, "a": 1.0},
        ["a", "b"],
        model_id="model-1",
    )
    assert np.array_equal(values, np.array([[1.0, 2.0]]))

    with pytest.raises(BackendApplicationError) as exc_info:
        _request_feature_array({"a": float("nan")}, ["a"], model_id="model-1")
    assert exc_info.value.code == "SHAP_FEATURE_VALUES_INVALID"


def test_shap_dependence_map_pairs_values_with_contributions():
    from backend.optical_ml_app.application.model_extension_service import shap_dependence_map

    dependence = shap_dependence_map(
        ["a", "b"],
        np.array([[1.0, 2.0], [3.0, 4.0]]),
        np.array([[0.1, -0.2], [0.3, -0.4]]),
    )
    assert dependence["a"]["feature_value"] == [1.0, 3.0]
    assert dependence["a"]["shap_value"] == [0.1, 0.3]
    assert dependence["b"]["x"] == [2.0, 4.0]
    assert dependence["b"]["y"] == [-0.2, -0.4]


def test_shap_defaults_to_all_model_features():
    features = [
        "surfaces[0].radius_mm",
        "surfaces[0].distance_to_next_mm",
        "size_log_mismatch",
    ]
    assert _default_display_feature_paths(features) == features


def test_shap_rejects_display_variables_not_used_by_model():
    with pytest.raises(BackendApplicationError) as exc_info:
        _resolve_display_feature_paths(
            ["surfaces[0].radius_mm"],
            ["surfaces[2].conic"],
            model_id="model-1",
        )
    assert exc_info.value.code == "SHAP_DISPLAY_FEATURE_SCHEMA_MISMATCH"

from __future__ import annotations

import math
from types import SimpleNamespace

from frontend_pyside.features.canvas.dataset_node import QUICK_LOOP_SAMPLE_COUNT
from frontend_pyside.features.canvas.prediction_compare import (
    baseline_for_target,
    build_forward_compare,
    compare_rows,
)


def test_compare_rows_show_lens_prediction_and_residual():
    result = build_forward_compare(
        {
            "model_name": "demo-rf",
            "predictions": {"coupling_efficiency": 0.42},
            "features": {
                "source.wavelength_nm": 808.0,
                "surfaces[0].radius_mm": 51.68,
            },
        },
        extra_metrics={"coupling_efficiency": 0.40},
    )
    rows = dict(compare_rows(result))
    assert "808" in rows["当前透镜"]
    assert rows["预测 耦合效率"] == "42.00 %"
    assert rows["正式基线"] == "40.00 %"
    assert rows["残差"] == "+2.00 %"
    assert abs(result["residuals"]["coupling_efficiency"] - 0.02) < 1e-9


def test_compare_rows_hide_residual_without_formal_baseline():
    rows = dict(compare_rows(build_forward_compare({
        "model_id": "m1",
        "predictions": {"coupling_efficiency": 0.33},
        "features": {"source.wavelength_nm": 780.0},
    })))
    assert rows["正式基线"] == "尚未正式计算"
    assert "残差" not in rows
    assert "780" in rows["当前透镜"]


def test_loss_db_baseline_converts_from_efficiency():
    eta = 0.5
    expected = -10.0 * math.log10(eta)
    assert abs(baseline_for_target("coupling_loss_db", {"coupling_efficiency": eta}) - expected) < 1e-9


def test_build_forward_compare_reads_project_metrics():
    context = SimpleNamespace(
        project=SimpleNamespace(
            project=SimpleNamespace(metrics={"coupling_efficiency": 0.31}),
            formal_result=None,
        )
    )
    result = build_forward_compare(
        {"predictions": {"coupling_efficiency": 0.28}, "features": {}},
        context=context,
    )
    assert result["matched_baseline"]["coupling_efficiency"] == 0.31
    assert abs(result["residuals"]["coupling_efficiency"] - (-0.03)) < 1e-9


def test_quick_loop_sample_count_is_short():
    assert QUICK_LOOP_SAMPLE_COUNT == 16

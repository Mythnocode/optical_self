from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from backend.optical_ml_app.application.prediction_service import PredictionApplicationService
from backend.optical_ml_app.domain.errors import BackendApplicationError
from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.workbench_jobs import (
    model_prediction_status,
    opt_chart_payload,
    scan_curve_payload,
    train_chart_payload,
    train_chart_unavailable_message,
)
from frontend_pyside.app.workbench_shell import (
    OptimizationDocument,
    WorkbenchShell,
    _coerce_feature_units,
    _optimization_status_label,
)
from frontend_pyside.features.machine_learning.feature_adapter import features_from_project


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_frontend_project_builds_exact_physics_model_features():
    context = create_app_context()
    paths = [
        "surfaces[0].radius_mm",
        "surfaces[1].distance_to_next_mm",
        "source.wavelength_nm",
        "size_log_mismatch",
        "fiber_mode_radius_um",
        "lateral_mismatch",
    ]
    values = features_from_project(context.project.project, paths)
    assert list(values) == paths
    assert values["source.wavelength_nm"] == pytest.approx(780.0)
    assert values["fiber_mode_radius_um"] > 0.0


def test_training_result_accepts_positional_feature_units():
    paths = ["source.wavelength_nm", "surfaces[0].radius_mm", "target"]
    assert _coerce_feature_units(["nm", "mm", "1"], paths) == {
        "source.wavelength_nm": "nm",
        "surfaces[0].radius_mm": "mm",
        "target": "1",
    }
    assert _coerce_feature_units({"source.wavelength_nm": "nm"}, paths) == {
        "source.wavelength_nm": "nm",
    }
    assert _coerce_feature_units("nm", paths) == {}


def test_training_finished_callback_commits_positional_feature_units():
    app = _app()
    shell = WorkbenchShell(create_app_context())
    shell._request_train_shap = lambda _model_id: None
    try:
        shell._on_workbench_job_finished(
            "train",
            {
                "model_id": "model-units-list",
                "feature_paths": ["source.wavelength_nm", "surfaces[0].radius_mm"],
                "feature_units": ["nm", "mm"],
                "target_names": ["coupling_loss_db"],
            },
        )
        record = next(item for item in shell._trained_models if item["id"] == "model-units-list")
        assert record["feature_units"] == {
            "source.wavelength_nm": "nm",
            "surfaces[0].radius_mm": "mm",
        }
        assert shell._widgets["model:train_result"]._trained is True
    finally:
        shell.close()
        app.processEvents()


def test_bad_model_is_not_exposed_as_predictor():
    usable, reason = model_prediction_status({"test_metrics": {"r2": -0.25}})
    assert usable is False
    assert "测试 R²" in reason


def test_training_curve_and_optimization_charts_use_explicit_sources():
    result = {
        "metadata": {
            "oob_error_curve": [0.4, 0.2],
            "training_curve_label": "OOB RMSE",
            "training_curve_status": "available",
        },
        "candidates": [
            {"label": "方案A", "metrics": {"coupling_efficiency": 0.91}},
        ],
        "history": [
            {"metrics": {"coupling_efficiency": 0.11}, "merit": 0.8},
        ],
    }
    curve = train_chart_payload(result, "验证误差曲线")
    assert curve is not None
    assert curve["y"] == [0.4, 0.2]
    assert curve["y_label"] == "OOB RMSE"
    candidates = opt_chart_payload(result, "候选对照")
    assert candidates is not None
    assert candidates["values"] == [0.91]
    assert "正式评价" in candidates["description"]
    assert "没有逐轮" in train_chart_unavailable_message(
        {"metadata": {"training_summary": {"convergence": "not_applicable"}}},
        "验证误差曲线",
    )


def test_two_dimensional_scan_is_rendered_as_a_real_heatmap() -> None:
    payload = scan_curve_payload(
        {
            "parameter_grid": [[0.0, 10.0], [0.0, 20.0], [1.0, 10.0], [1.0, 20.0]],
            "response_values": {"coupling_efficiency": [0.1, 0.2, 0.3, 0.4]},
        },
        "耦合效率",
    )
    assert payload is not None
    assert payload["kind"] == "heatmap"
    assert payload["z"] == [[0.1, 0.3], [0.2, 0.4]]


def test_optimization_result_has_real_apply_action():
    app = _app()
    context = create_app_context()
    document = OptimizationDocument("opt_result", context, set())
    current = float(context.project.project.surfaces[0].radius_mm)
    document.apply_opt_result(
        {
            "candidates": [
                {
                    "label": "方案A",
                    "variables": {"surfaces[0].radius_mm": current + 0.1},
                    "metrics": {"coupling_efficiency": 0.95},
                    "verification_status": "formal_simulation",
                }
            ]
        }
    )
    document.table.selectRow(0)
    assert document.apply_button.isEnabled()
    document.apply_button.click()
    assert context.project.project.surfaces[0].radius_mm == pytest.approx(current + 0.1)
    document.close()
    app.processEvents()


def test_applying_candidate_requests_formal_validation_with_baseline():
    app = _app()
    context = create_app_context()
    context.project.set_formal_result({"metrics": {"coupling_efficiency": 0.81}})
    document = OptimizationDocument("opt_result", context, set())
    current = float(context.project.project.surfaces[0].radius_mm)
    requests = []
    document.applyAndVerifyRequested.connect(
        lambda variables, label, baseline: requests.append((variables, label, baseline))
    )
    document.apply_opt_result(
        {
            "candidates": [
                {
                    "label": "方案A",
                    "variables": {"surfaces[0].radius_mm": current + 0.1},
                    "metrics": {"coupling_efficiency": 0.95},
                    "verification_status": "formal_simulation",
                }
            ]
        }
    )
    document.table.selectRow(0)
    document.apply_button.click()
    assert len(requests) == 1
    assert requests[0][0]["surfaces[0].radius_mm"] == pytest.approx(current + 0.1)
    assert requests[0][1] == "方案A"
    assert requests[0][2] == pytest.approx(0.81)
    assert "正在正式验证" in document.apply_status.text()
    document.close()
    app.processEvents()


def test_optimization_status_is_readable_in_result_table():
    assert _optimization_status_label("formal_simulation") == "正式评价"
    assert _optimization_status_label("surrogate") == "代理模型筛选"


def test_prediction_service_returns_structured_quality_error():
    class Registry:
        def load(self, _model_id):
            return object(), object(), {
                "feature_paths": ["source.wavelength_nm"],
                "target_names": ["coupling_loss_db"],
                "test_metrics": {"r2": -1.0},
            }

    from shared_contracts.prediction import PredictionRequest

    service = PredictionApplicationService(
        __import__("machine_learning.inference.predictor", fromlist=["Predictor"]).Predictor(Registry())
    )
    with pytest.raises(BackendApplicationError) as exc_info:
        service.predict(
            PredictionRequest(
                model_id="model-bad",
                features={"source.wavelength_nm": 780.0},
            )
        )
    assert exc_info.value.code == "MODEL_QUALITY_REJECTED"


def test_prediction_service_converts_unexpected_runtime_error_to_structured_failure():
    class Registry:
        def load(self, _model_id):
            raise RuntimeError("predictor state is incomplete")

    from machine_learning.inference.predictor import Predictor
    from shared_contracts.prediction import PredictionRequest

    service = PredictionApplicationService(Predictor(Registry()))
    with pytest.raises(BackendApplicationError) as exc_info:
        service.predict(
            PredictionRequest(
                model_id="model-runtime-error",
                features={"source.wavelength_nm": 780.0},
            )
        )
    assert exc_info.value.code == "MODEL_PREDICTION_FAILED"
    assert "模型预测失败" in exc_info.value.message

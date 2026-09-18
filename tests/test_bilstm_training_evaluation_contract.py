from pathlib import Path


def test_bilstm_artifact_persists_point_level_evaluation_contract():
    source = Path("machine_learning/neural_networks/bilstm.py").read_text(encoding="utf-8")
    service = Path(
        "backend/optical_ml_app/application/structure_model_service.py"
    ).read_text(encoding="utf-8")

    assert '"evaluation": evaluation' in source
    assert '"actual": test_truth.tolist()' in source
    assert '"predicted": test_prediction.tolist()' in source
    assert '"residual": (test_prediction - test_truth).tolist()' in source
    assert '"evaluation": artifact["evaluation"]' in service
    assert '"training_history": artifact["history"]' in service
    assert '"training_curve_label": "验证 MSE（标准化）"' in service


def test_training_result_exposes_reference_charts_and_shap_distribution():
    jobs = Path("frontend_pyside/app/workbench_jobs.py").read_text(encoding="utf-8")
    model_document = Path("frontend_pyside/modules/model/documents.py").read_text(encoding="utf-8")
    explainability = Path("frontend_pyside/modules/explainability/documents.py").read_text(encoding="utf-8")

    assert '"kind": "validation_scatter"' in jobs
    assert '"kind": "residual"' in jobs
    assert '"kind": "histogram"' in jobs
    assert '"reference_y": test_metrics.get("rmse")' in jobs
    assert '"残差分布"' in model_document
    assert '"SHAP分布图"' in explainability

"""Render the real FastAPI job results inside the PySide workbench.

This is an acceptance/diagnostic script only. It does not submit jobs or
change product state; it reads the latest completed live jobs from the local
backend and injects their returned payloads into the corresponding widgets.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="optical-live-ui-"))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="optical-live-ui-appdata-")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.features.machine_learning.feature_adapter import features_from_project
from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.simulation.form_state import SimulationFormState


BASE = "http://127.0.0.1:8000/api/v1"


def api_data(response: httpx.Response):
    response.raise_for_status()
    body = response.json()
    if body.get("code") != "OK":
        raise RuntimeError(json.dumps(body, ensure_ascii=False))
    return body.get("data")


def latest_jobs(client: httpx.Client) -> dict[str, dict]:
    items = api_data(client.get(f"{BASE}/jobs?limit=80", timeout=30))
    result: dict[str, dict] = {}
    for item in items or []:
        if not isinstance(item, dict) or item.get("status") != "completed":
            continue
        kind = str(item.get("job_type") or "")
        if kind and kind not in result:
            result[kind] = item
    return result


def job_result(client: httpx.Client, item: dict) -> dict:
    return dict(api_data(client.get(f"{BASE}/jobs/{item['job_id']}/result", timeout=180)) or {})


def wait(ms: int = 220) -> None:
    QTest.qWait(ms)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def shot(widget: QWidget, out: Path, name: str) -> str:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    if not widget.grab().save(str(path)):
        raise RuntimeError(f"failed to save screenshot: {path}")
    return str(path)


def click_teaching_equipment(teaching, kind: str) -> None:
    """Place one device through the visible equipment popup controls."""
    teaching._toolbar_action("equipment")
    wait(120)
    popup = teaching.equipment_popup
    if popup is None:
        raise RuntimeError("teaching equipment popup missing")
    button = next(
        (item for item in popup._kind_buttons if str(item.property("kindKey") or "") == kind),
        None,
    )
    if button is None:
        raise RuntimeError(f"teaching equipment button missing: {kind}")
    button.click()
    wait(120)
    if popup.apply_preset.isVisible():
        popup.preset_box.setCurrentIndex(0)
        popup.apply_preset.click()
        wait(120)


def click_teaching_analysis(teaching) -> tuple[object, str]:
    """Open 成像与耦合 and run its visible calculate button.

    The merged window runs both formal analyses (spot, then coupling) from one
    button, so the harness waits for the whole run instead of one analysis.
    """
    teaching._toolbar_action("analysis")
    wait(150)
    popup = teaching.analysis_popup
    if popup is None:
        raise RuntimeError("teaching analysis popup missing")
    popup.run_button.click()
    # The first formal engine call in a fresh worker may spend tens of seconds
    # initializing numerical backends; keep the UI in its explicit running
    # state until a real result arrives.
    deadline = 120000
    while deadline > 0:
        wait(250)
        status = str(popup.status.text() or "")
        if "正式计算完成" in status or "未完成" in status or "未命中" in status:
            break
        deadline -= 250
    status = str(popup.status.text() or "")
    if "正式计算完成" not in status:
        raise RuntimeError(f"teaching imaging/coupling did not complete: {status}")
    return popup, status


def main() -> int:
    out = ROOT / "acceptance" / "live_e2e_20260913"
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client() as client:
        jobs = latest_jobs(client)
        required = {"dataset", "training", "simulation", "optimization"}
        missing = sorted(required - set(jobs))
        if missing:
            raise RuntimeError(f"no completed live jobs: {missing}")
        results = {kind: job_result(client, item) for kind, item in jobs.items() if kind in required}
        train = results["training"]
        primary = dict(train.get("xgboost") or train)
        model_id = str(train.get("primary_model_id") or primary.get("model_id") or "")
        dataset_id = str(train.get("dataset_id") or "")
        models = api_data(client.get(f"{BASE}/models", timeout=30))
        model_record = next(
            (item for item in (models.get("models") or []) if str(item.get("model_id") or item.get("id")) == model_id),
            {},
        )
        feature_paths = list(model_record.get("feature_paths") or primary.get("metadata", {}).get("feature_paths") or [])
        # Use the same adapter as the product UI: users provide only the optical
        # project; derived residual features are computed internally.
        from frontend_pyside.state.project_context import default_project
        project_payload = serialize_project(default_project(), SimulationFormState())
        features = features_from_project(project_payload, feature_paths)
        target_name = str(list(primary.get("metadata", {}).get("target_names") or ["coupling_loss_db"])[0])
        prediction = api_data(client.post(
            f"{BASE}/models/{model_id}/predict",
            json={"model_id": model_id, "features": features},
            timeout=60,
        ))
        shap = api_data(client.post(
            f"{BASE}/models/{model_id}/shap/explain",
            json={"dataset_id": dataset_id, "target_name": target_name, "display_feature_paths": list(primary.get("metadata", {}).get("design_variable_paths") or []), "top_k": 6, "max_samples": 48},
            timeout=180,
        ))

    app = QApplication.instance() or QApplication([])
    apply_application_theme(app)
    window = create_main_window()
    window.resize(1366, 768)
    window.show()
    wait(350)
    paths: list[str] = []
    try:
        # Training charts are rendered from the actual training result bundle.
        window.navigate("model")
        window.workbench.open_document("model", "train_result")
        wait()
        train_doc = window.workbench._widgets["model:train_result"]
        train_doc.mark_trained(primary)
        for name, filename in (("残差图", "01_train_residual"), ("学习曲线", "02_train_curve"), ("实测对照", "03_train_actual_predicted")):
            train_doc.show_train_chart(name)
            wait(120)
            paths.append(shot(window, out, filename))

        # Model prediction page receives the real /predict response.
        window.workbench.open_document("model", "predict")
        wait()
        predict_doc = window.workbench._widgets["model:predict"]
        predict_doc.set_trained_models([{
            "id": model_id,
            "title": f"{primary.get('model_type', '模型')} · {model_id[-8:]}",
            "family": primary.get("model_type", "模型"),
            "target": target_name,
            "feature_paths": feature_paths,
            "design_variable_paths": list(primary.get("metadata", {}).get("design_variable_paths") or []),
            "feature_units": list(primary.get("metadata", {}).get("feature_units") or []),
            "test_r2": float((primary.get("test_metrics") or {}).get("r2", 0.0)),
        }])
        predicted = dict(prediction.get("predictions") or {})
        predicted_value = next(iter(predicted.values()), None)
        predict_doc.show_predict_result([
            ("输出", "—" if predicted_value is None else f"{float(predicted_value):.4g}"),
            ("目标", target_name),
            ("模型", predict_doc.predict_model.currentText()),
            ("光学仿真", "尚未对照仿真"),
        ])
        wait(120)
        paths.append(shot(window, out, "04_model_prediction"))

        # SHAP is the real backend response, not a preview payload.
        window.navigate("explainability")
        window.workbench.open_document("explainability", "global_contrib")
        wait()
        explain_doc = window.workbench._widgets["explainability:global_contrib"]
        explain_doc.set_trained_models([{
            "id": model_id,
            "title": f"{primary.get('model_type', '模型')} · {model_id[-8:]}",
            "family": primary.get("model_type", "模型"),
            "feature_paths": list(primary.get("metadata", {}).get("feature_paths") or []),
            "design_variable_paths": list(primary.get("metadata", {}).get("design_variable_paths") or []),
        }])
        explain_doc._render_shap(dict(shap))
        wait(180)
        paths.append(shot(window, out, "05_explain_global_shap"))

        # Establish the baseline through the same visible formal-calculation
        # controller that candidate validation uses.  Injecting a result created
        # with different numerical settings would make the before/after values
        # incomparable and would hide a broken closure behind a pretty label.
        window.navigate("simulation")
        window.workbench.open_document("simulation", "coupling")
        wait()
        window.workbench.run_formal_calculation()
        deadline = 120000
        while deadline > 0 and window.workbench.context.project.formal_result is None:
            wait(250)
            deadline -= 250
        if window.workbench.context.project.formal_result is None:
            raise RuntimeError("visible formal baseline did not complete")
        wait(220)
        paths.append(shot(window, out, "06_simulation_coupling"))

        # Optimization result table and apply action are checked separately.
        window.navigate("optimization")
        window.workbench.open_document("optimization", "opt_result")
        wait()
        opt_doc = window.workbench._widgets["optimization:opt_result"]
        opt_doc.apply_opt_result(results["optimization"])
        wait(180)
        paths.append(shot(window, out, "07_optimization_candidates"))
        # The optimizer sorts the best changed candidate first.  Selecting row
        # zero proves the product's apply -> formal verification transition;
        # a baseline-equivalent row should correctly remain a no-op.
        selected_row = 0
        if opt_doc.table.rowCount():
            opt_doc.table.selectRow(selected_row)
            wait(120)
        if opt_doc.apply_button.isEnabled():
            opt_doc.apply_button.click()
            deadline = 120000
            while deadline > 0 and "正在正式验证" in str(opt_doc.apply_status.text() or ""):
                wait(250)
                deadline -= 250
        paths.append(shot(window, out, "08_optimization_apply_enabled"))

        # Place a valid teaching scene through the visible equipment buttons.
        # The analysis buttons below then invoke the formal local optical engine.
        window.navigate("teaching")
        wait(250)
        teaching = window.teaching
        # The teaching bench starts with a standard demo scene.  Clear that
        # demo scene so the following visible clicks create exactly one laser,
        # one lens and one fiber/CCD, matching the user acceptance flow.
        for component_id in list(teaching.store.components):
            teaching.store.remove_component(component_id)
        wait(180)
        for kind in ("laser", "lens", "fiber", "ccd"):
            click_teaching_equipment(teaching, kind)
        analysis_popup, analysis_status = click_teaching_analysis(teaching)
        paths.append(shot(analysis_popup, out, "09_teaching_imaging_coupling"))
        teaching_metrics = {
            "analysis_status": analysis_status,
            "imaging_summary": str(analysis_popup.imaging_summary.text() or ""),
            "coupling_pills": {
                key: str(label.text() or "") for key, label in analysis_popup.coupling_pills.items()
            },
            "coupling_detail": str(analysis_popup.coupling_detail.text() or ""),
            "component_kinds": [item.kind for item in teaching.store.components.values()],
        }

        report = {
            "status": "PASS",
            "backend": BASE,
            "jobs": {kind: item.get("job_id") for kind, item in jobs.items() if kind in required},
            "model_id": model_id,
            "dataset_id": dataset_id,
            "shap_data_source": shap.get("data_source"),
            "optimization_status": results["optimization"].get("status"),
            "optimization_candidate_count": len(results["optimization"].get("candidates") or []),
            "optimization_history_count": len(results["optimization"].get("history") or []),
            "optimization_table_row_count": int(opt_doc.table.rowCount()),
            "optimization_selected_row": selected_row,
            "apply_button_enabled_after_row_selection": bool(opt_doc.apply_button.isEnabled()),
            "apply_status": opt_doc.apply_status.text(),
            "teaching": teaching_metrics,
            "teaching_note": "教学设备与计算按钮通过真实界面点击；指标来自教学模块正式光学引擎。其余截图来自真实 FastAPI 后端任务结果。",
            "screenshots": paths,
        }
    finally:
        window.close()
        wait(80)
    (out / "live_ui_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

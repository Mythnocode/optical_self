from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.features.machine_learning.feature_adapter import features_from_project
from frontend_pyside.state.project_context import default_project

BASE = "http://127.0.0.1:8000/api/v1"


def data(response: httpx.Response):
    response.raise_for_status()
    body = response.json()
    if body.get("code") != "OK":
        raise RuntimeError(json.dumps(body, ensure_ascii=False))
    return body.get("data")


def wait_job(client: httpx.Client, job_id: str, timeout: float = 900.0):
    start = time.monotonic()
    last = None
    while True:
        status = data(client.get(f"{BASE}/jobs/{job_id}", timeout=30))
        marker = (status.get("status"), status.get("progress"), status.get("stage"), status.get("completed_items"))
        if marker != last:
            print("JOB", job_id, marker, flush=True)
            last = marker
        if status.get("status") == "completed":
            return data(client.get(f"{BASE}/jobs/{job_id}/result", timeout=120))
        if status.get("status") in {"failed", "cancelled"}:
            try:
                result = client.get(f"{BASE}/jobs/{job_id}/result", timeout=60).json()
            except Exception:
                result = {}
            raise RuntimeError(json.dumps({"status": status, "result": result}, ensure_ascii=False))
        if time.monotonic() - start > timeout:
            raise TimeoutError(job_id)
        time.sleep(0.8)


def submit_job(client: httpx.Client, path: str, payload: dict, timeout: float = 900.0):
    body = data(client.post(f"{BASE}{path}", json=payload, timeout=60))
    job_id = str(body["job_id"])
    return job_id, wait_job(client, job_id, timeout=timeout)


def main() -> int:
    with httpx.Client() as client:
        print("HEALTH", data(client.get(f"{BASE}/health", timeout=30)), flush=True)
        project = serialize_project(default_project(), SimulationFormState())
        stamp = uuid4().hex[:8]
        dataset_payload = {
            "dataset_name": f"live-e2e-{stamp}",
            "base_project": project,
            "parameters": [
                {"name": "第1面曲率半径", "path": "surfaces[0].radius_mm", "unit": "mm", "lower_bound": 5.04, "upper_bound": 5.18},
                {"name": "第1片透镜厚度", "path": "surfaces[0].distance_to_next_mm", "unit": "mm", "lower_bound": 2.92, "upper_bound": 3.08},
                {"name": "第1面圆锥系数", "path": "surfaces[0].conic", "unit": "1", "lower_bound": -1.13, "upper_bound": -1.01},
            ],
            "targets": ["coupling_efficiency"],
            # Structural perturbations can legitimately fail optical edge/energy
            # checks.  Keep those checks strict and generate enough candidates so
            # joint training still receives the required valid population.
            "sample_count": 48,
            "sampling_method": "latin_hypercube",
            "train_ratio": 0.7,
            "validation_ratio": 0.15,
            "test_ratio": 0.15,
            "random_seed": 42,
            "precision": "preview",
            "engine": "headless",
            "include_derived_physics_features": True,
            "variable_scheme_id": "asphere_1_lens",
            "lens_count": 1,
            "design_variable_paths": [
                "surfaces[0].radius_mm",
                "surfaces[0].distance_to_next_mm",
                "surfaces[0].conic",
            ],
        }
        dataset_job, dataset = submit_job(client, "/dataset/jobs", dataset_payload)
        print("DATASET", json.dumps({"job_id": dataset_job, **dataset}, ensure_ascii=False), flush=True)
        dataset_id = str(dataset.get("dataset_id") or dataset.get("training_dataset_id"))

        train_job, trained = submit_job(client, "/training/joint/jobs", {
            "dataset_id": dataset_id,
            "random_forest_hyperparameters": {"n_estimators": 24, "max_depth": 6},
            "xgboost_hyperparameters": {"n_estimators": 40, "max_depth": 4},
            "random_seed": 42,
        })
        print("TRAIN", json.dumps({"job_id": train_job, **trained}, ensure_ascii=False), flush=True)
        if str(trained.get("status") or "completed") != "completed":
            raise RuntimeError("joint training did not complete")
        rf_result = dict(trained["random_forest"])
        xgb_result = dict(trained["xgboost"])
        model_id = str(trained["primary_model_id"])

        models = data(client.get(f"{BASE}/models", timeout=30))
        model = next((item for item in models.get("models", []) if str(item.get("model_id") or item.get("id")) == model_id), {})
        feature_paths = list(model.get("feature_paths") or rf_result.get("metadata", {}).get("feature_paths") or [])
        features = features_from_project(project, feature_paths)
        prediction = data(client.post(f"{BASE}/models/{model_id}/predict", json={"model_id": model_id, "features": features}, timeout=60))
        print("PREDICT", json.dumps(prediction, ensure_ascii=False), flush=True)

        try:
            display_paths = list(dataset_payload["design_variable_paths"])
            shap = data(client.post(f"{BASE}/models/{model_id}/shap/explain", json={"dataset_id": dataset_id, "target_name": "coupling_efficiency", "display_feature_paths": display_paths, "top_k": 6, "max_samples": 48}, timeout=180))
            returned = [str(item.get("feature")) for item in list(shap.get("top_features") or [])]
            if not returned or not set(returned).issubset(set(display_paths)):
                raise RuntimeError(f"SHAP leaked non-design features: {returned}")
            local = dict(list(shap.get("targets") or [])[0]).get("sample_shap_values", [])[0]
            if abs(float(local.get("additivity_error") or 0.0)) > 1e-6:
                raise RuntimeError(f"SHAP additivity failed: {local.get('additivity_error')}")
            print("SHAP", json.dumps({"explanation_run_id": shap.get("explanation_run_id"), "display_feature_paths": shap.get("display_feature_paths"), "hidden_feature_count": shap.get("hidden_feature_count"), "additivity_error": local.get("additivity_error")}, ensure_ascii=False), flush=True)
        except httpx.HTTPStatusError as exc:
            print("SHAP_ERROR", exc.response.status_code, exc.response.text, flush=True)

        sim_payload = {
            "schema_version": "1.0",
            "request_id": f"live-e2e-sim-{stamp}",
            "project": project,
            "analyses": ["coupling", "psf", "mtf"],
            "parameter_changes": [],
            "precision": "preview",
            "random_seed": 42,
            "engine": "headless",
            "options": {"hybrid": {"grid_size": 129, "output_grid_size": 129, "output_extent_x_mm": 0.024, "output_extent_y_mm": 0.024, "pupil_sample_count": 25, "result_array_policy": "field_only"}},
        }
        sim_job, simulation = submit_job(client, "/simulation/jobs", sim_payload,)
        print("SIMULATION", json.dumps({"job_id": sim_job, "status": simulation.get("status"), "metrics": simulation.get("metrics"), "array_keys": list((simulation.get("arrays") or {}).keys())}, ensure_ascii=False), flush=True)

        opt_payload = {
            **sim_payload,
            "request_id": f"live-e2e-opt-{stamp}",
            "analyses": ["coupling"],
            "opt_optimizer": "auto",
            "opt_variables": [{"path": "surfaces[0].radius_mm", "label": "第1面曲率半径", "unit": "mm", "lower_bound": 5.04, "upper_bound": 5.18, "initial_value": float(project["surfaces"][0]["radius_mm"]), "enabled": True}],
            "opt_objectives": [{"metric": "coupling_efficiency", "weight": 1.0, "goal": "maximize"}],
            "opt_constraints": [],
            "opt_max_iterations": 2,
            "opt_max_evaluations": 12,
            "opt_convergence_tolerance": 1e-3,
            "opt_options": {},
        }
        opt_job, optimization = submit_job(client, "/optimization/jobs", opt_payload, timeout=1200.0)
        print("OPTIMIZATION", json.dumps({"job_id": opt_job, "status": optimization.get("status"), "best_metrics": optimization.get("best_metrics"), "candidate_count": len(optimization.get("candidates") or []), "history_count": len(optimization.get("history") or [])}, ensure_ascii=False), flush=True)

        candidates = [item for item in list(optimization.get("candidates") or []) if isinstance(item, dict)]
        if not candidates:
            raise RuntimeError("optimization returned no applicable candidate")
        candidate = candidates[0]
        raw_candidate_variables = candidate.get("variables")
        if isinstance(raw_candidate_variables, dict):
            candidate_variables = {str(path): float(value) for path, value in raw_candidate_variables.items()}
        elif isinstance(raw_candidate_variables, (list, tuple)):
            active_paths = [str(path) for path in list(dict(optimization.get("metadata") or {}).get("active_variables") or [])]
            candidate_variables = {
                path: float(value) for path, value in zip(active_paths, raw_candidate_variables)
            }
        else:
            candidate_variables = {}
        if not candidate_variables:
            raise RuntimeError("optimization candidate has no variables")
        verify_payload = dict(sim_payload)
        verify_payload["request_id"] = f"live-e2e-verify-{stamp}"
        verify_payload["analyses"] = ["coupling"]
        verify_payload["parameter_changes"] = [
            {"path": path, "value": value, "unit": "mm" if path.endswith("_mm") else "1"}
            for path, value in candidate_variables.items()
        ]
        verify_job, verified = submit_job(client, "/simulation/jobs", verify_payload)
        print("VERIFY", json.dumps({"job_id": verify_job, "candidate": candidate.get("label"), "variables": candidate_variables, "coupling_efficiency": dict(verified.get("metrics") or {}).get("coupling_efficiency")}, ensure_ascii=False), flush=True)
        print("CLOSED_LOOP", json.dumps({"dataset_id": dataset_id, "random_forest_model_id": rf_result.get("model_id"), "xgboost_model_id": xgb_result.get("model_id"), "primary_model_id": model_id, "explanation_run_id": shap.get("explanation_run_id"), "optimization_job_id": opt_job, "verification_job_id": verify_job}, ensure_ascii=False), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

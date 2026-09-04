from __future__ import annotations

"""离线生成真实演示资产。

用途：在目标机器/答辩机器空闲时，通过正在运行的正式后端一次性生成数据集、
训练模型并预计算 SHAP。脚本不会伪造结果，也不会把生成的资产设为“当前方案”
或“当前模型”。完整模式可能耗时数小时，应显式使用 --mode full。
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.state.project_context import default_project
from frontend_pyside.features.simulation.form_state import SimulationFormState


DEFAULT_PARAMETERS = [
    {
        "name": "光纤横向位置 X",
        "path": "receiver.offset_x_mm",
        "unit": "mm",
        "lower_bound": -0.002,
        "upper_bound": 0.002,
        "distribution": "uniform",
    },
    {
        "name": "光纤轴向位置",
        "path": "receiver.axial_offset_z_mm",
        "unit": "mm",
        "lower_bound": -0.05,
        "upper_bound": 0.05,
        "distribution": "uniform",
    },
]


FULL_PROFILES = [
    ("示例·780 nm 四透镜-耦合损耗", ["coupling_loss_db"], 300),
    ("示例·780 nm 四透镜-耦合效率", ["coupling_efficiency"], 300),
    ("示例·780 nm 四透镜-RMS 光斑", ["rms_spot_radius_um"], 200),
    ("示例·780 nm 四透镜-Strehl", ["strehl_estimate_marechal"], 200),
    ("示例·780 nm 四透镜-大样本耦合", ["coupling_efficiency"], 500),
    ("示例·780 nm 四透镜-正式耦合流程", ["coupling_efficiency"], 200),
]

QUICK_PROFILES = [
    ("内置演示·780 nm 四透镜 X/Z 耦合数据", ["coupling_efficiency"], 128),
]


def _data(response: requests.Response) -> Any:
    response.raise_for_status()
    body = response.json()
    if body.get("code") != "OK":
        raise RuntimeError(body)
    return body.get("data")


def _wait_job(base_url: str, job_id: str, timeout_s: float) -> dict[str, Any]:
    start = time.perf_counter()
    last = None
    while True:
        status = _data(requests.get(f"{base_url}/jobs/{job_id}", timeout=15))
        marker = (
            status.get("status"),
            round(float(status.get("progress", 0.0) or 0.0), 4),
            status.get("completed_items"),
            status.get("total_items"),
            status.get("stage"),
        )
        if marker != last:
            print(f"  {job_id}: {marker}", flush=True)
            last = marker
        state = str(status.get("status", ""))
        if state == "completed":
            return _data(requests.get(f"{base_url}/jobs/{job_id}/result", timeout=60))
        if state in {"failed", "cancelled"}:
            raise RuntimeError(f"job {job_id} -> {state}: {status}")
        if time.perf_counter() - start > timeout_s:
            raise TimeoutError(f"job {job_id} exceeded {timeout_s:.0f}s")
        time.sleep(0.8)


def _submit_dataset(base_url: str, project: dict, name: str, targets: list[str], count: int, precision: str, timeout_s: float):
    payload = {
        "dataset_name": name,
        "base_project": project,
        "parameters": DEFAULT_PARAMETERS,
        "targets": targets,
        "sample_count": count,
        "sampling_method": "latin_hypercube",
        "train_ratio": 0.7,
        "validation_ratio": 0.15,
        "test_ratio": 0.15,
        "random_seed": 42,
        "precision": precision,
        "engine": "headless",
        "include_derived_physics_features": False if "X/Z" in name else True,
    }
    job = _data(requests.post(f"{base_url}/dataset/jobs", json=payload, timeout=30))["job_id"]
    result = _wait_job(base_url, job, timeout_s)
    return job, result


def _train(base_url: str, dataset_id: str, model_type: str, target: str, timeout_s: float):
    hyper = {"n_estimators": 300, "max_depth": 12} if model_type == "random_forest" else {}
    payload = {
        "dataset_id": dataset_id,
        "model_type": model_type,
        "target_names": [target],
        "hyperparameters": hyper,
        "random_seed": 42,
    }
    job = _data(requests.post(f"{base_url}/training/jobs", json=payload, timeout=30))["job_id"]
    return job, _wait_job(base_url, job, timeout_s)




def _video_research_options() -> dict[str, Any]:
    """Formal numerical strategy used by the 3-minute video workflow.

    Keep research tasks numerically identical to the simulation workbench.  The
    options intentionally contain only numerical controls; design variables such as
    Fiber X/Z must stay in the project/parameter change path so scan and optimisation
    cannot be accidentally overridden by a stale value in ``options``.
    """
    return {
        "geometric": {"pupil_sample_count": 49},
        "hybrid": {
            "pupil_sample_count": 49,
            "grid_size": 257,
            "output_grid_size": 257,
            "output_extent_x_mm": 0.024,
            "output_extent_y_mm": 0.024,
            "propagation_model": "scaled_fresnel",
            "zero_padding_factor": 2.0,
            "precision_mode": "balanced",
            "convergence_enabled": True,
            "sampling_convergence_enabled": True,
            "auto_expand_output": True,
            "wavefront_fit_order": 4,
            "include_diagnostic_arrays": False,
            "result_array_policy": "field_only",
        },
    }

def _submit_scan(base_url: str, project: dict, precision: str, timeout_s: float):
    payload = {
        "schema_version": "1.0",
        "request_id": "demo-assets-fiber-z-scan-31",
        "project": project,
        "analyses": ["coupling"],
        "parameter_changes": [],
        "precision": precision,
        "random_seed": 42,
        "engine": "headless",
        "options": _video_research_options(),
        "scan_mode": "line_1d",
        "scan_parameters": [{
            "path": "receiver.axial_offset_z_mm",
            "label": "光纤轴向位置",
            "unit": "mm",
            "start": -0.05,
            "stop": 0.05,
            "points": 31,
        }],
        "scan_response_metrics": ["coupling_efficiency"],
        "scan_options": {},
    }
    job = _data(requests.post(f"{base_url}/scan/jobs", json=payload, timeout=30))["job_id"]
    return job, _wait_job(base_url, job, timeout_s)


def _submit_tolerance(base_url: str, project: dict, precision: str, sample_count: int, timeout_s: float):
    specs = [
        ("receiver.offset_x_mm", 0.0, "mm", 0.001),
        ("receiver.offset_y_mm", 0.0, "mm", 0.001),
        ("receiver.axial_offset_z_mm", float(project["receiver"].get("axial_offset_z_mm", 0.0) or 0.0), "mm", 0.005),
        ("receiver.tilt_x_deg", 0.0, "deg", 0.01),
        ("receiver.tilt_y_deg", 0.0, "deg", 0.01),
    ]
    params = [
        {
            "path": path,
            "nominal": nominal,
            "unit": unit,
            "distribution": {"name": "normal", "sigma": sigma},
            "enabled": True,
        }
        for path, nominal, unit, sigma in specs
    ]
    payload = {
        "schema_version": "1.0",
        "request_id": f"demo-assets-tolerance-{sample_count}",
        "project": project,
        "analyses": ["coupling"],
        "parameter_changes": [],
        "precision": precision,
        "random_seed": 42,
        "engine": "headless",
        "options": _video_research_options(),
        "tolerance_parameters": params,
        "tolerance_sampling_method": "lhs",
        "tolerance_sample_count": int(sample_count),
        "tolerance_threshold_efficiency": 0.80,
        "tolerance_threshold_loss_db": None,
        "tolerance_confidence_level": 0.95,
        "tolerance_correlation_matrix": None,
        "tolerance_options": {},
    }
    job = _data(requests.post(f"{base_url}/tolerance/jobs", json=payload, timeout=30))["job_id"]
    return job, _wait_job(base_url, job, timeout_s)


def _submit_optimization(base_url: str, project: dict, precision: str, timeout_s: float):
    initial_x = float(project["receiver"].get("offset_x_mm", 0.0) or 0.0)
    initial_z = float(project["receiver"].get("axial_offset_z_mm", 0.0) or 0.0)
    payload = {
        "schema_version": "1.0",
        "request_id": "demo-assets-fiber-xz-optimization",
        "project": project,
        "analyses": ["coupling"],
        "parameter_changes": [],
        "precision": precision,
        "random_seed": 42,
        "engine": "headless",
        "options": _video_research_options(),
        "opt_optimizer": "auto",
        "opt_variables": [
            {"path": "receiver.offset_x_mm", "label": "光纤 X 偏移", "unit": "mm", "lower_bound": -0.002, "upper_bound": 0.002, "initial_value": initial_x, "enabled": True},
            {"path": "receiver.axial_offset_z_mm", "label": "光纤轴向位置", "unit": "mm", "lower_bound": -0.05, "upper_bound": 0.05, "initial_value": initial_z, "enabled": True},
        ],
        "opt_objectives": [{"metric": "coupling_efficiency", "weight": 1.0, "goal": "maximize"}],
        "opt_constraints": [],
        "opt_max_iterations": 300,
        "opt_max_evaluations": 48 if precision != "high" else 80,
        "opt_convergence_tolerance": 1e-6,
        "opt_options": {"multistart_count": 8},
    }
    job = _data(requests.post(f"{base_url}/optimization/jobs", json=payload, timeout=30))["job_id"]
    return job, _wait_job(base_url, job, timeout_s)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成平台真实演示数据/模型/SHAP；不会自动采用这些资产。")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    parser.add_argument("--precision", choices=["preview", "standard", "high"], default=None)
    parser.add_argument("--timeout-hours", type=float, default=12.0)
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    health = _data(requests.get(f"{base_url}/health", timeout=10))
    print("backend:", health)

    profiles = QUICK_PROFILES if args.mode == "quick" else FULL_PROFILES
    precision = args.precision or "standard"
    if args.mode == "full":
        print("警告：full 会真实生成 1700 个标准精度样本，在部分机器上可能需要数小时。")

    project = serialize_project(default_project(), SimulationFormState())
    # 数据集服务使用 ProjectSnapshot：波长必须同时保存在 source，禁止静默回退到 1550 nm。
    assert float(project["source"]["wavelength_nm"]) == 780.0

    report: dict[str, Any] = {
        "mode": args.mode,
        "precision": precision,
        "generated_by_real_pipeline": True,
        "wavelength_nm": 780.0,
        "datasets": [],
        "models": [],
        "shap": [],
        "research_results": [],
        "started_at_epoch": time.time(),
    }
    timeout_s = args.timeout_hours * 3600

    for name, targets, count in profiles:
        print(f"\n生成数据集: {name} ({count})")
        t0 = time.perf_counter()
        job_id, result = _submit_dataset(base_url, project, name, targets, count, precision, timeout_s)
        elapsed = time.perf_counter() - t0
        dataset_id = str(result.get("dataset_id") or result.get("training_dataset_id") or "")
        if not dataset_id:
            raise RuntimeError(f"dataset id missing: {result}")
        row = {"job_id": job_id, "dataset_id": dataset_id, "name": name, "targets": targets, "sample_count": count, "elapsed_s": elapsed}
        report["datasets"].append(row)
        print("  完成:", row)

        # 只给两个最适合演示智能分析的数据集训练模型，避免为所有目标制造无意义模型。
        target = targets[0]
        model_type = None
        if target == "coupling_loss_db" and args.mode == "full":
            model_type = "xgboost_physics_residual"
        elif target == "coupling_efficiency" and (args.mode == "quick" or count == 300):
            model_type = "random_forest"
        if model_type:
            print(f"  训练 {model_type}")
            mt0 = time.perf_counter()
            train_job, trained = _train(base_url, dataset_id, model_type, target, timeout_s)
            model_id = str(trained.get("model_id") or "")
            model_row = {
                "job_id": train_job,
                "model_id": model_id,
                "dataset_id": dataset_id,
                "model_type": model_type,
                "test_metrics": trained.get("test_metrics", {}),
                "elapsed_s": time.perf_counter() - mt0,
            }
            report["models"].append(model_row)
            print("  模型:", model_row)
            if model_id:
                shap_request = {
                    "dataset_id": dataset_id,
                    "target_name": target,
                    "top_k": 12,
                    "max_samples": min(100, count),
                    "background_sample_count": min(64, max(16, count // 3)),
                    "random_seed": 42,
                }
                st0 = time.perf_counter()
                shap_result = _data(requests.post(f"{base_url}/models/{model_id}/shap/explain", json=shap_request, timeout=600))
                report["shap"].append({
                    "model_id": model_id,
                    "dataset_id": dataset_id,
                    "cache_hit": bool(shap_result.get("cache_hit")),
                    "elapsed_s": time.perf_counter() - st0,
                })

    # 预制研究结果同样来自真实任务管线。它们只写入报告/任务历史，
    # 不会自动覆盖用户当前方案。完整模式使用 200 个容差样本；快速模式用 64 个。
    print("\n生成参数扫描 / 容差" + (" / 优化" if args.mode == "full" else "") + "示例结果")
    research_jobs = [
        ("fiber_z_scan_31", lambda: _submit_scan(base_url, project, precision, timeout_s)),
        ("tolerance", lambda: _submit_tolerance(base_url, project, precision, 64 if args.mode == "quick" else 200, timeout_s)),
    ]
    # 优化搜索可能显著增加离线构建时间，只在 full 标准演示包中生成。
    if args.mode == "full":
        research_jobs.append(("optimization", lambda: _submit_optimization(base_url, project, precision, timeout_s)))
    for kind, submitter in research_jobs:
        rt0 = time.perf_counter()
        job_id, result = submitter()
        report["research_results"].append({
            "kind": kind,
            "job_id": job_id,
            "elapsed_s": time.perf_counter() - rt0,
            "result": result,
        })

    report["finished_at_epoch"] = time.time()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print("\n" + text)
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

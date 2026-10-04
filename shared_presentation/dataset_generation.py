"""Original Workbench dataset request construction, without Qt dependencies."""
from machine_learning.datasets.variable_schemes import resolve_lens_bindings, resolve_variable_scheme
from machine_learning.features.coupling_physics import paired_coupling_targets
from shared_presentation.dataset_configuration import build_dataset_parameters

TARGETS = {"耦合损耗(dB)": "coupling_loss_db", "耦合效率": "coupling_efficiency", "RMS 光斑": "rms_spot_radius_um", "Strehl": "strehl_estimate_marechal"}
SAMPLING = {"Latin Hypercube": "latin_hypercube", "Sobol低差异采样": "sobol"}
PRECISION = {"129×129": "preview", "257×257": "standard", "513×513": "high"}

def imported_dataset_mode(project: dict, simulation_options: dict | None = None) -> dict | None:
    if (project.get("receiver") or {}).get("mode_model") != "imported":
        return None
    hybrid = (simulation_options or {}).get("hybrid") or {}
    if not isinstance(hybrid, dict):
        raise ValueError("仿真复场选项无效")
    values = hybrid.get("imported_mode_values")
    if not isinstance(values, dict) or "real" not in values or "imag" not in values:
        raise ValueError("导入复场模式缺少已校验的复场数据")
    return {
        "real": values["real"], "imag": values["imag"],
        "source": hybrid.get("imported_mode_source", ""),
        "output_extent_x_mm": hybrid.get("output_extent_x_mm", 0.024),
        "output_extent_y_mm": hybrid.get("output_extent_y_mm", 0.024),
    }


def generation_payload(project: dict, options: dict, simulation_options: dict | None = None) -> dict:
    family = options.get("family", "tabular")
    if family == "sequence":
        if int(options.get("sample_count", 50)) < 10:
            raise ValueError("序列数据集样本数至少为 10")
        lens_count = len(resolve_lens_bindings(project))
        paths = list(options.get("variable_paths") or [])
        if not lens_count:
            raise ValueError("当前系统没有可识别的实体镜片，无法生成序列数据集")
        if not paths:
            raise ValueError("请至少选择一个用于扰动的变量")
        scheme_id = "arbitrary_lens_sequence"
    else:
        scheme = resolve_variable_scheme(project, lens_count=options.get("lens_count", 4), include_conic=options.get("include_conic", False))
        paths = list(scheme.design_variable_paths)
        scheme_id, lens_count = scheme.scheme_id, scheme.lens_count
    parameters = build_dataset_parameters(project, explicit_paths=paths)
    if not parameters:
        raise ValueError("未选择可采样参数")
    validation = min(0.45, max(0.05, float(options.get("validation_ratio", 0.15))))
    test = min(0.15, max(0.05, validation))
    payload = {
        "dataset_name": options["dataset_name"], "base_project": project,
        "parameters": parameters, "targets": paired_coupling_targets([TARGETS[options.get("target", "耦合损耗(dB)")]]),
        "sample_count": int(options.get("sample_count", 50)), "sampling_method": SAMPLING[options.get("sampling", "Latin Hypercube")],
        "train_ratio": max(0.0, 1.0-validation-test), "validation_ratio": validation, "test_ratio": test,
        "random_seed": int(options.get("random_seed", 42)), "precision": PRECISION[options.get("precision", "257×257")],
        "variable_scheme_id": scheme_id, "lens_count": lens_count, "design_variable_paths": paths,
        "dataset_layout": "sequence_long" if family == "sequence" else "tabular",
    }
    mode = imported_dataset_mode(project, simulation_options)
    if mode is not None:
        payload["imported_mode"] = mode
    return payload

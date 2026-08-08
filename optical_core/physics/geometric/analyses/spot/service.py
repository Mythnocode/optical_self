# 点列图分析的总入口。


# 本文件不生成光线，也不重新追迹光线。对外提供单根光线的落点、方向、状态、权重以及光程数组，同一份追迹结果可同时支撑前端二维/三维可视化渲染和机器学习特征提取。

from __future__ import annotations

import numpy as np

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.geometric.analyses.spot.metrics import weighted_spot_metrics
from optical_core.physics.geometric.analyses.spot.options import SpotAnalysisOptions
from optical_core.physics.geometric.analyses.spot.result import SpotResult
from optical_core.physics.geometric.formulas.airy import (
    airy_radius_um_from_na,
    evaluate_airy_disk,
    real_ray_image_space_na,
)


def _tolist_or_none(value):
    if value is None:
        return None
    return np.asarray(value).tolist()


def evaluate_spot(trace: TraceBundle, options: SpotAnalysisOptions | None = None) -> SpotResult:
    options = options or SpotAnalysisOptions()
    positions = np.asarray(trace.final_positions_mm, dtype=float)
    directions = np.asarray(trace.final_directions, dtype=float)
    valid = np.asarray(trace.valid_mask, dtype=bool)
    weights = np.asarray(trace.integration_weights, dtype=float)

    if positions.size == 0 or positions.ndim != 2 or positions.shape[1] < 3:
        return SpotResult(
            metrics={"valid_ray_count": 0.0, "rms_spot_radius_um": float("nan")},
            warnings=["没有光线，无法计算点列图。"],
        )

    warnings = list(trace.warnings)
    if options.output_unit != "um":
        warnings.append(
            "spot analysis currently outputs micrometres only; "
            f"output_unit={options.output_unit!r} was ignored."
        )

    x_um = positions[:, 0] * 1000.0
    y_um = positions[:, 1] * 1000.0
    metrics = weighted_spot_metrics(x_um, y_um, weights, valid)
    metrics["valid_ray_count"] = float(np.count_nonzero(valid))
    metrics["total_ray_count"] = float(valid.size)
    metrics["spot_rms_method"] = "common_weighted_centroid_second_moment"
    metrics["spot_weight_semantics"] = "power_weight_times_quadrature_weight"

    
    if options.wavelength_nm is not None and (
        options.numerical_aperture is not None
        or options.f_number is not None
        or (options.focal_length_mm is not None and options.aperture_diameter_mm is not None)
    ):
        try:
            airy = evaluate_airy_disk(
                wavelength_nm=float(options.wavelength_nm),
                numerical_aperture=options.numerical_aperture,
                f_number=options.f_number,
                focal_length_mm=options.focal_length_mm,
                aperture_diameter_mm=options.aperture_diameter_mm,
                refractive_index=float(options.refractive_index),
            )
            metrics.update(airy.metrics)
            if np.isfinite(metrics.get("rms_spot_radius_um", float("nan"))):
                metrics["rms_radius_to_paraxial_airy_radius"] = float(
                    metrics["rms_spot_radius_um"] / max(airy.airy_radius_um, 1.0e-15)
                )
                
                metrics["rms_radius_to_airy_radius"] = metrics[
                    "rms_radius_to_paraxial_airy_radius"
                ]
        except Exception as exc:
            warnings.append(f"Paraxial Airy calculation skipped: {exc}")

    
    if options.include_real_ray_airy and options.wavelength_nm is not None:
        try:
            na_metrics = real_ray_image_space_na(
                directions,
                valid_mask=valid,
                pupil_coordinates_normalized=trace.pupil_coordinates_normalized,
                refractive_index=float(options.refractive_index),
            )
            metrics.update(na_metrics)
            real_na = float(na_metrics["real_ray_image_space_na"])
            if np.isfinite(real_na) and real_na > 0.0:
                metrics["real_ray_airy_radius_um"] = airy_radius_um_from_na(
                    float(options.wavelength_nm), real_na
                )
                metrics["real_ray_airy_diameter_um"] = 2.0 * metrics[
                    "real_ray_airy_radius_um"
                ]
        except Exception as exc:
            warnings.append(f"Real-ray Airy calculation skipped: {exc}")

    ray_ids = (
        np.asarray(trace.ray_ids, dtype=object)
        if trace.ray_ids is not None
        else np.asarray([f"R{i:06d}" for i in range(valid.size)], dtype=object)
    )
    statuses = (
        np.asarray(trace.status_codes, dtype=object)
        if trace.status_codes is not None
        else np.where(valid, "VALID", "INVALID")
    )

    arrays = {
        
        
        "spot_x_um": x_um.tolist(),
        "spot_y_um": y_um.tolist(),
        "spot_points_um": np.column_stack([x_um, y_um]).tolist(),
        "spot_integration_weights": weights.tolist(),
        "spot_valid_mask": valid.tolist(),
        "spot_ray_ids": ray_ids.tolist(),
        "spot_status_codes": statuses.tolist(),
        "spot_termination_reasons": list(trace.termination_reasons),
        "spot_final_directions": directions.tolist(),
        "spot_optical_paths_mm": np.asarray(trace.optical_paths_mm, dtype=float).tolist(),
        "pupil_coordinates_normalized": _tolist_or_none(trace.pupil_coordinates_normalized),
        "raytrace_path_points_mm": _tolist_or_none(trace.path_points_mm),
        "raytrace_path_offsets": _tolist_or_none(trace.path_offsets),
        "raytrace_path_surface_indices": _tolist_or_none(trace.path_surface_indices),
        "raytrace_segment_lengths_mm": _tolist_or_none(trace.segment_lengths_mm),
        "raytrace_segment_refractive_indices": _tolist_or_none(
            trace.segment_refractive_indices
        ),
        "raytrace_segment_opl_mm": _tolist_or_none(trace.segment_opl_mm),
        "raytrace_cumulative_opl_mm": _tolist_or_none(trace.cumulative_opl_mm),
    }
    arrays = {key: value for key, value in arrays.items() if value is not None}

    return SpotResult(metrics=metrics, arrays=arrays, warnings=warnings)

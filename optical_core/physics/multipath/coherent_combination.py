from __future__ import annotations

import math
from typing import Any

import numpy as np

from optical_core.physics.multipath.power_combination import (
    input_power_w_from_path,
    throughput_from_metrics,
    validate_non_negative_finite,
)

_VALID_COMBINER_NORMALIZATIONS = {
    "none",
    "power_conserving_equal_splitter",
    "custom",
}


def _read(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        for name in names:
            value = obj.get(name)
            if value is not None:
                return value
        return default
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _object_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump())
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping from path_id to numeric value")
    return dict(value)


def _finite_float_strict(value: Any, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite numeric value") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite numeric value")
    return number


def _finite_float_optional(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _as_float_array(value: Any, *, name: str, path_id: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim != 2:
        raise ValueError(f"path {path_id} coherent field array {name} must be 2-D")
    if array.size == 0:
        raise ValueError(f"path {path_id} coherent field array {name} is empty")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"path {path_id} coherent field array {name} contains non-finite values")
    return array


def _as_nonnegative_float_array(value: Any, *, name: str, path_id: str) -> np.ndarray:
    array = _as_float_array(value, name=name, path_id=path_id)
    if np.any(array < 0.0):
        raise ValueError(f"path {path_id} coherent field array {name} contains negative intensity values")
    return array


def _as_grid_array(value: Any, *, name: str, path_id: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim != 1:
        raise ValueError(f"path {path_id} coherent grid array {name} must be 1-D")
    if array.size == 0:
        raise ValueError(f"path {path_id} coherent grid array {name} is empty")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"path {path_id} coherent grid array {name} contains non-finite values")
    return array


def _same_grid(a: np.ndarray, b: np.ndarray) -> bool:
    return a.shape == b.shape and bool(np.allclose(a, b, rtol=1.0e-10, atol=1.0e-12))


def _grid_is_strictly_uniform(grid: np.ndarray, *, rtol: float = 1.0e-7, atol: float = 1.0e-12) -> bool:
    if grid.size <= 2:
        return True
    diffs = np.diff(grid)
    if not (np.all(diffs > 0.0) or np.all(diffs < 0.0)):
        return False
    return bool(np.allclose(diffs, diffs[0], rtol=rtol, atol=atol))


def _phase_offset_for_path(path: Any, path_id: str, phase_offsets: dict[str, Any]) -> float:
    if path_id in phase_offsets:
        return _finite_float_strict(
            phase_offsets[path_id],
            name=f"phase_offsets_rad_by_path[{path_id!r}]",
        )

    containers = (
        _object_to_dict(path),
        _object_to_dict(_read(path, "source", default=None)),
        _object_to_dict(_read(path, "options", default=None)),
    )
    for container_name, container in zip(("path", "source", "options"), containers):
        for key in ("coherent_phase_rad", "phase_rad", "phase_offset_rad", "optical_phase_rad"):
            if key in container:
                return _finite_float_strict(
                    container.get(key),
                    name=f"{container_name}.{key}",
                )
    return 0.0


def _amplitude_coefficient_for_path(
    path_id: str,
    amplitude_coefficients_by_path: dict[str, Any],
) -> float:
    if path_id not in amplitude_coefficients_by_path:
        return 1.0
    coefficient = _finite_float_strict(
        amplitude_coefficients_by_path[path_id],
        name=f"amplitude_coefficients_by_path[{path_id!r}]",
    )
    if coefficient < 0.0:
        raise ValueError(f"amplitude_coefficients_by_path[{path_id!r}] must be non-negative")
    return coefficient


def _normalize_field_to_power(field: np.ndarray, power_w: float) -> np.ndarray:
    field_power = float(np.sum(np.abs(field) ** 2))
    if field_power <= 0.0:
        return np.zeros_like(field, dtype=np.complex128)
    return field * math.sqrt(power_w / field_power)


def _wavelength_nm_for_path_result(path: Any, result: dict[str, Any]) -> float | None:
    metadata = dict(result.get("metadata", {}) or {})
    metrics = dict(result.get("metrics", {}) or {})
    source = _object_to_dict(_read(path, "source", default=None))
    options = _object_to_dict(_read(path, "options", default=None))
    for container in (metadata, metrics, source, options, _object_to_dict(path)):
        for key in ("wavelength_nm", "coupling_wavelength_nm", "source_wavelength_nm"):
            if key in container:
                number = _finite_float_optional(container.get(key))
                if number is not None and number > 0.0:
                    return number
    return None


def _build_mode_reference(
    mode_intensity: np.ndarray,
    mode_phase: np.ndarray | None,
) -> np.ndarray:
    if mode_phase is None:
        return np.sqrt(mode_intensity).astype(np.complex128)
    return np.sqrt(mode_intensity).astype(np.complex128) * np.exp(1j * mode_phase)


def summarize_coherent_field_sum(
    path_results: dict[str, dict[str, Any]],
    *,
    raw_arrays_by_path: dict[str, dict[str, Any]],
    paths: list[Any],
    default_input_power_w: float = 1.0e-3,
    phase_offsets_rad_by_path: dict[str, Any] | None = None,
    return_field_arrays: bool = False,
    combiner_normalization: str = "none",
    amplitude_coefficients_by_path: dict[str, Any] | None = None,
) -> dict[str, Any]:


    default_input_power_w = validate_non_negative_finite(
        default_input_power_w,
        name="default_input_power_w",
    )
    phase_offsets_rad_by_path = _require_mapping(
        phase_offsets_rad_by_path,
        "phase_offsets_rad_by_path",
    )
    amplitude_coefficients_by_path = _require_mapping(
        amplitude_coefficients_by_path,
        "amplitude_coefficients_by_path",
    )
    combiner_normalization = str(combiner_normalization or "none").strip().lower()
    if combiner_normalization not in _VALID_COMBINER_NORMALIZATIONS:
        raise ValueError(
            "combiner_normalization must be 'none', 'power_conserving_equal_splitter', or 'custom'"
        )
    if combiner_normalization == "power_conserving_equal_splitter" and amplitude_coefficients_by_path:
        raise ValueError(
            "amplitude_coefficients_by_path cannot be combined with "
            "combiner_normalization='power_conserving_equal_splitter'; use custom normalization instead"
        )

    known_path_ids = set(path_results.keys())
    unknown_phase_ids = sorted(set(phase_offsets_rad_by_path) - known_path_ids)
    if unknown_phase_ids:
        raise ValueError(
            "phase_offsets_rad_by_path contains unknown path_id values: "
            + ", ".join(unknown_phase_ids)
        )
    unknown_amplitude_ids = sorted(set(amplitude_coefficients_by_path) - known_path_ids)
    if unknown_amplitude_ids:
        raise ValueError(
            "amplitude_coefficients_by_path contains unknown path_id values: "
            + ", ".join(unknown_amplitude_ids)
        )

    path_by_id = {str(_read(path, "path_id", "id", default="")).strip(): path for path in paths}

    warnings: list[str] = []
    field_total: np.ndarray | None = None
    mode_reference: np.ndarray | None = None
    reference_shape: tuple[int, int] | None = None
    reference_grid_x: np.ndarray | None = None
    reference_grid_y: np.ndarray | None = None
    reference_wavelength_nm: float | None = None
    included_path_count = 0
    skipped_path_count = 0
    input_power_w_by_path: dict[str, float] = {}
    throughput_by_path: dict[str, float] = {}
    transmitted_power_w_by_path: dict[str, float] = {}
    phase_offset_rad_by_path: dict[str, float] = {}
    amplitude_coefficient_by_path: dict[str, float] = {}
    wavelength_nm_by_path: dict[str, float] = {}
    coherent_detail_by_path: dict[str, dict[str, Any]] = {}

    total_input_power_w = 0.0
    total_transmitted_power_w = 0.0
    grid_issue_seen = False
    grid_uniform_issue_seen = False
    mode_phase_missing_seen = False
    mode_reference_issue_seen = False
    wavelength_missing_seen = False
    wavelength_mismatch_seen = False

    for path_id, result in path_results.items():
        if result.get("status") != "completed":
            skipped_path_count += 1
            coherent_detail_by_path[path_id] = {
                "status": "skipped",
                "reason": f"path status is {result.get('status')}",
            }
            continue

        path = path_by_id.get(path_id)
        input_power_w, input_source = input_power_w_from_path(path, default_w=default_input_power_w)
        total_input_power_w += input_power_w
        input_power_w_by_path[path_id] = input_power_w

        metrics = dict(result.get("metrics", {}) or {})
        throughput, throughput_source, throughput_warnings = throughput_from_metrics(metrics, path_id=path_id)
        warnings.extend(throughput_warnings)
        transmitted_power_w = input_power_w * throughput
        throughput_by_path[path_id] = throughput
        transmitted_power_w_by_path[path_id] = transmitted_power_w
        total_transmitted_power_w += transmitted_power_w

        arrays = raw_arrays_by_path.get(path_id, {}) or {}
        required = (
            "coupling_field_intensity",
            "coupling_field_phase_rad",
            "coupling_mode_intensity",
            "coupling_grid_x_mm",
            "coupling_grid_y_mm",
        )
        missing = [key for key in required if key not in arrays]
        if missing:
            skipped_path_count += 1
            grid_issue_seen = grid_issue_seen or any(key.startswith("coupling_grid_") for key in missing)
            message = f"path {path_id} skipped in coherent field sum: missing {', '.join(missing)}"
            warnings.append(message)
            coherent_detail_by_path[path_id] = {
                "status": "skipped",
                "reason": "missing_coherent_arrays",
                "missing_arrays": missing,
                "input_power_w": input_power_w,
                "input_power_source": input_source,
                "throughput": throughput,
                "throughput_source": throughput_source,
            }
            continue

        intensity = _as_nonnegative_float_array(
            arrays["coupling_field_intensity"],
            name="coupling_field_intensity",
            path_id=path_id,
        )
        phase = _as_float_array(
            arrays["coupling_field_phase_rad"],
            name="coupling_field_phase_rad",
            path_id=path_id,
        )
        mode_intensity = _as_nonnegative_float_array(
            arrays["coupling_mode_intensity"],
            name="coupling_mode_intensity",
            path_id=path_id,
        )
        grid_x = _as_grid_array(arrays["coupling_grid_x_mm"], name="coupling_grid_x_mm", path_id=path_id)
        grid_y = _as_grid_array(arrays["coupling_grid_y_mm"], name="coupling_grid_y_mm", path_id=path_id)

        if not _grid_is_strictly_uniform(grid_x) or not _grid_is_strictly_uniform(grid_y):
            skipped_path_count += 1
            grid_issue_seen = True
            grid_uniform_issue_seen = True
            message = f"path {path_id} skipped in coherent field sum: sampled coordinate grid is not strictly uniform"
            warnings.append(message)
            coherent_detail_by_path[path_id] = {
                "status": "skipped",
                "reason": "nonuniform_grid",
                "grid_x_count": int(grid_x.size),
                "grid_y_count": int(grid_y.size),
            }
            continue

        mode_phase: np.ndarray | None = None
        if "coupling_mode_phase_rad" in arrays:
            mode_phase = _as_float_array(
                arrays["coupling_mode_phase_rad"],
                name="coupling_mode_phase_rad",
                path_id=path_id,
            )
        else:
            mode_phase_missing_seen = True
            warnings.append(
                f"path {path_id} mode phase is missing; assuming zero-phase Gaussian mode"
            )

        expected_shape = (int(grid_y.size), int(grid_x.size))
        if intensity.shape != phase.shape or intensity.shape != mode_intensity.shape:
            skipped_path_count += 1
            message = f"path {path_id} skipped in coherent field sum: field and mode array shapes do not match"
            warnings.append(message)
            coherent_detail_by_path[path_id] = {
                "status": "skipped",
                "reason": "shape_mismatch",
                "field_shape": tuple(int(v) for v in intensity.shape),
                "phase_shape": tuple(int(v) for v in phase.shape),
                "mode_shape": tuple(int(v) for v in mode_intensity.shape),
            }
            continue
        if mode_phase is not None and mode_phase.shape != intensity.shape:
            skipped_path_count += 1
            message = f"path {path_id} skipped in coherent field sum: mode phase shape does not match field shape"
            warnings.append(message)
            coherent_detail_by_path[path_id] = {
                "status": "skipped",
                "reason": "mode_phase_shape_mismatch",
                "field_shape": tuple(int(v) for v in intensity.shape),
                "mode_phase_shape": tuple(int(v) for v in mode_phase.shape),
            }
            continue
        if intensity.shape != expected_shape:
            skipped_path_count += 1
            grid_issue_seen = True
            message = (
                f"path {path_id} skipped in coherent field sum: field shape {intensity.shape} "
                f"does not match grid shape {expected_shape}"
            )
            warnings.append(message)
            coherent_detail_by_path[path_id] = {
                "status": "skipped",
                "reason": "field_grid_shape_mismatch",
                "field_shape": tuple(int(v) for v in intensity.shape),
                "grid_x_count": int(grid_x.size),
                "grid_y_count": int(grid_y.size),
                "expected_shape": expected_shape,
            }
            continue

        if reference_grid_x is None:
            reference_shape = intensity.shape
            reference_grid_x = grid_x
            reference_grid_y = grid_y
            mode_reference = _build_mode_reference(mode_intensity, mode_phase)
            field_total = np.zeros(reference_shape, dtype=np.complex128)
        else:
            assert reference_grid_x is not None and reference_grid_y is not None and reference_shape is not None
            if intensity.shape != reference_shape or not _same_grid(grid_x, reference_grid_x) or not _same_grid(grid_y, reference_grid_y):
                skipped_path_count += 1
                grid_issue_seen = True
                message = f"path {path_id} skipped in coherent field sum: sampled coordinate grid differs from reference path"
                warnings.append(message)
                coherent_detail_by_path[path_id] = {
                    "status": "skipped",
                    "reason": "common_grid_coordinate_mismatch",
                    "field_shape": tuple(int(v) for v in intensity.shape),
                    "reference_shape": tuple(int(v) for v in reference_shape),
                    "grid_x_first_last_mm": [float(grid_x[0]), float(grid_x[-1])],
                    "grid_y_first_last_mm": [float(grid_y[0]), float(grid_y[-1])],
                    "reference_grid_x_first_last_mm": [float(reference_grid_x[0]), float(reference_grid_x[-1])],
                    "reference_grid_y_first_last_mm": [float(reference_grid_y[0]), float(reference_grid_y[-1])],
                }
                continue
            candidate_mode = _build_mode_reference(mode_intensity, mode_phase)
            if mode_reference is not None and not np.allclose(candidate_mode, mode_reference, rtol=1.0e-8, atol=1.0e-10):
                skipped_path_count += 1
                mode_reference_issue_seen = True
                message = f"path {path_id} skipped in coherent field sum: fibre mode reference differs from first included path"
                warnings.append(message)
                coherent_detail_by_path[path_id] = {
                    "status": "skipped",
                    "reason": "mode_reference_mismatch",
                }
                continue

        wavelength_nm = _wavelength_nm_for_path_result(path, result)
        if wavelength_nm is None:
            wavelength_missing_seen = True
            warnings.append(
                f"path {path_id} wavelength_nm is unavailable; coherent wavelength compatibility was not fully checked"
            )
        elif reference_wavelength_nm is None:
            reference_wavelength_nm = wavelength_nm
            wavelength_nm_by_path[path_id] = wavelength_nm
        elif not math.isclose(wavelength_nm, reference_wavelength_nm, rel_tol=1.0e-9, abs_tol=1.0e-9):
            skipped_path_count += 1
            wavelength_mismatch_seen = True
            message = (
                f"path {path_id} skipped in coherent field sum: wavelength_nm {wavelength_nm} "
                f"differs from reference {reference_wavelength_nm}"
            )
            warnings.append(message)
            coherent_detail_by_path[path_id] = {
                "status": "skipped",
                "reason": "wavelength_mismatch",
                "wavelength_nm": wavelength_nm,
                "reference_wavelength_nm": reference_wavelength_nm,
            }
            continue
        else:
            wavelength_nm_by_path[path_id] = wavelength_nm

        phase_offset = _phase_offset_for_path(path, path_id, phase_offsets_rad_by_path)
        amplitude_coefficient = _amplitude_coefficient_for_path(path_id, amplitude_coefficients_by_path)
        phase_offset_rad_by_path[path_id] = phase_offset
        amplitude_coefficient_by_path[path_id] = amplitude_coefficient

        field = np.sqrt(intensity).astype(np.complex128) * np.exp(1j * (phase + phase_offset))
        field = _normalize_field_to_power(field, transmitted_power_w)
        field *= amplitude_coefficient
        assert field_total is not None
        field_total += field
        included_path_count += 1
        coherent_detail_by_path[path_id] = {
            "status": "included",
            "input_power_w": input_power_w,
            "input_power_source": input_source,
            "throughput": throughput,
            "throughput_source": throughput_source,
            "transmitted_power_w": transmitted_power_w,
            "phase_offset_rad": phase_offset,
            "amplitude_coefficient": amplitude_coefficient,
            "wavelength_nm": wavelength_nm,
            "field_shape": tuple(int(v) for v in intensity.shape),
            "grid_x_count": int(grid_x.size),
            "grid_y_count": int(grid_y.size),
        }

    if combiner_normalization == "power_conserving_equal_splitter" and field_total is not None and included_path_count > 0:
        field_total = field_total / math.sqrt(float(included_path_count))

    field_power_w = float(np.sum(np.abs(field_total) ** 2)) if field_total is not None else 0.0
    coupled_power_w: float | None = None
    overlap_efficiency: float | None = None
    overlap_abs: float | None = None
    overlap_phase_rad: float | None = None
    if field_total is not None and mode_reference is not None:
        mode_power = float(np.sum(np.abs(mode_reference) ** 2))
        if mode_power > 0.0:
            overlap = np.sum(field_total * np.conjugate(mode_reference))
            coupled_power_w = float((abs(overlap) ** 2) / mode_power)
            overlap_abs = float(abs(overlap))
            overlap_phase_rad = float(np.angle(overlap))
            overlap_efficiency = coupled_power_w / field_power_w if field_power_w > 0.0 else None

    grid_checked = included_path_count > 0 and not grid_issue_seen
    wavelength_checked = included_path_count > 0 and not wavelength_missing_seen and not wavelength_mismatch_seen
    mode_phase_checked = included_path_count > 0 and not mode_phase_missing_seen
    mode_reference_checked = included_path_count > 0 and not mode_reference_issue_seen
    propagation_plane_checked = False
    polarization_checked = False
    phase_reference_checked = False

    summary_complete = (
        skipped_path_count == 0
        and included_path_count > 0
        and grid_checked
        and wavelength_checked
        and mode_phase_checked
        and mode_reference_checked
    )
    physical_assumptions_complete = (
        summary_complete
        and propagation_plane_checked
        and polarization_checked
        and phase_reference_checked
    )
    overall_efficiency = (
        coupled_power_w / total_input_power_w
        if summary_complete and coupled_power_w is not None and total_input_power_w > 0.0
        else None
    )

    result: dict[str, Any] = {
        "mode": "coherent_field_sum",
        "power_unit": "W",
        "formula": "E_total = sum(a_i * sqrt(input_power_i * throughput_i) * E_i * exp(j*phase_i)); P_coupled = |<E_total,M>|^2/<M,M>",
        "model_note": (
            "Compatibility scalar coherent sum on a common sampled receiver plane. "
            "Use coherent_network for complex scattering ports, coatings, Jones devices, "
            "path delays, partial coherence, and branched optical-network geometry."
        ),
        "combiner_normalization": combiner_normalization,
        "combiner_normalization_note": (
            "none keeps direct mathematical field superposition and can exceed passive single-port power; "
            "power_conserving_equal_splitter scales the summed field by 1/sqrt(N) for an ideal scalar equal-splitter output "
            "and is not a full beam-combiner port model; custom uses user-supplied amplitude_coefficients_by_path."
        ),
        "coherent_summary_complete": summary_complete,
        "included_path_count": included_path_count,
        "skipped_coherent_path_count": skipped_path_count,
        "total_input_power_w": total_input_power_w,
        "total_transmitted_power_w": total_transmitted_power_w,
        "total_coherent_field_power_w": field_power_w,
        "total_coupled_power_w": coupled_power_w,
        "coherent_mode_overlap_efficiency": overlap_efficiency,
        "overall_coherent_combining_efficiency": overall_efficiency,
        "coherent_overlap_abs": overlap_abs,
        "coherent_overlap_phase_rad": overlap_phase_rad,
        "input_power_w_by_path": input_power_w_by_path,
        "throughput_by_path": throughput_by_path,
        "transmitted_power_w_by_path": transmitted_power_w_by_path,
        "phase_offset_rad_by_path": phase_offset_rad_by_path,
        "amplitude_coefficient_by_path": amplitude_coefficient_by_path,
        "wavelength_nm_by_path": wavelength_nm_by_path,
        "reference_wavelength_nm": reference_wavelength_nm,
        "reference_grid_x_mm": reference_grid_x.tolist() if reference_grid_x is not None else None,
        "reference_grid_y_mm": reference_grid_y.tolist() if reference_grid_y is not None else None,
        "coherent_detail_by_path": coherent_detail_by_path,
        "coherent_assumption_grid_checked": grid_checked,
        "coherent_assumption_wavelength_checked": wavelength_checked,
        "coherent_assumption_mode_phase_checked": mode_phase_checked,
        "coherent_assumption_mode_reference_checked": mode_reference_checked,
        "coherent_assumption_grid_uniform_checked": grid_checked and not grid_uniform_issue_seen,
        "coherent_assumption_propagation_plane_checked": propagation_plane_checked,
        "coherent_assumption_polarization_checked": polarization_checked,
        "coherent_assumption_phase_reference_checked": phase_reference_checked,
        "coherent_physical_assumptions_complete": physical_assumptions_complete,
        "warnings": warnings,
    }

    if return_field_arrays and field_total is not None:
        result["arrays"] = {
            "multipath_coherent_field_intensity": (np.abs(field_total) ** 2).tolist(),
            "multipath_coherent_field_phase_rad": np.angle(field_total).tolist(),
            "multipath_coherent_grid_x_mm": reference_grid_x.tolist() if reference_grid_x is not None else [],
            "multipath_coherent_grid_y_mm": reference_grid_y.tolist() if reference_grid_y is not None else [],
        }

    return result

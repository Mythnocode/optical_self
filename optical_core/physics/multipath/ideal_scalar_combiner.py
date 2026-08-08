from __future__ import annotations

import math
from typing import Any

import numpy as np

from optical_core.physics.multipath.coherent_combination import (
    _as_float_array,
    _as_grid_array,
    _as_nonnegative_float_array,
    _build_mode_reference,
    _finite_float_strict,
    _grid_is_strictly_uniform,
    _object_to_dict,
    _phase_offset_for_path,
    _read,
    _require_mapping,
    _same_grid,
    _wavelength_nm_for_path_result,
    _normalize_field_to_power,
)
from optical_core.physics.multipath.power_combination import (
    input_power_w_from_path,
    throughput_from_metrics,
    validate_non_negative_finite,
)


def _optional_finite(value: Any, *, name: str) -> float | None:
    if value is None:
        return None
    return _finite_float_strict(value, name=name)


def _read_number(mapping: dict[str, Any], names: tuple[str, ...], *, name: str) -> float | None:
    for key in names:
        if key in mapping and mapping.get(key) is not None:
            return _finite_float_strict(mapping.get(key), name=f"{name}.{key}")
    return None


def _resolve_coefficients(combination: dict[str, Any]) -> tuple[complex, complex, dict[str, Any]]:


    t_amp = _read_number(
        combination,
        ("transmission_amplitude", "t_amplitude", "amplitude_transmission"),
        name="combination",
    )
    r_amp = _read_number(
        combination,
        ("reflection_amplitude", "r_amplitude", "amplitude_reflection"),
        name="combination",
    )
    t_power = _read_number(
        combination,
        ("transmission_power", "power_transmission", "T"),
        name="combination",
    )
    r_power = _read_number(
        combination,
        ("reflection_power", "power_reflection", "R"),
        name="combination",
    )

    if t_amp is None:
        t_amp = math.sqrt(t_power) if t_power is not None else 1.0 / math.sqrt(2.0)
    if r_amp is None:
        r_amp = math.sqrt(r_power) if r_power is not None else 1.0 / math.sqrt(2.0)
    if t_amp < 0.0:
        raise ValueError("combination transmission amplitude must be non-negative")
    if r_amp < 0.0:
        raise ValueError("combination reflection amplitude must be non-negative")

    t_phase = _read_number(
        combination,
        ("transmission_phase_rad", "t_phase_rad", "phase_transmission_rad"),
        name="combination",
    )
    r_phase = _read_number(
        combination,
        ("reflection_phase_rad", "r_phase_rad", "phase_reflection_rad"),
        name="combination",
    )
    if t_phase is None:
        t_phase = 0.0
    if r_phase is None:
        r_phase = math.pi / 2.0

    t = complex(t_amp * math.cos(t_phase), t_amp * math.sin(t_phase))
    r = complex(r_amp * math.cos(r_phase), r_amp * math.sin(r_phase))

    coefficient_power_sum = float(abs(t) ** 2 + abs(r) ** 2)
    coefficient_cross_term = float(2.0 * np.real(t * np.conjugate(r)))
    coefficient_unitarity_error = float(
        abs(coefficient_power_sum - 1.0) + abs(coefficient_cross_term)
    )
    info = {
        "transmission_amplitude": float(t_amp),
        "reflection_amplitude": float(r_amp),
        "transmission_phase_rad": float(t_phase),
        "reflection_phase_rad": float(r_phase),
        "t_complex": [float(np.real(t)), float(np.imag(t))],
        "r_complex": [float(np.real(r)), float(np.imag(r))],
        "coefficient_power_sum": coefficient_power_sum,
        "coefficient_cross_term": coefficient_cross_term,
        "coefficient_unitarity_error": coefficient_unitarity_error,
    }
    return t, r, info


def _mode_overlap_power(field: np.ndarray, mode_reference: np.ndarray) -> tuple[float | None, float | None, float | None, float | None]:
    field_power = float(np.sum(np.abs(field) ** 2))
    mode_power = float(np.sum(np.abs(mode_reference) ** 2))
    if mode_power <= 0.0:
        return field_power, None, None, None
    overlap = np.sum(field * np.conjugate(mode_reference))
    coupled_power = float((abs(overlap) ** 2) / mode_power)
    efficiency = coupled_power / field_power if field_power > 0.0 else None
    return field_power, coupled_power, efficiency, float(np.angle(overlap))


def summarize_ideal_2x2_scalar_combiner(
    path_results: dict[str, dict[str, Any]],
    *,
    raw_arrays_by_path: dict[str, dict[str, Any]],
    paths: list[Any],
    default_input_power_w: float = 1.0e-3,
    phase_offsets_rad_by_path: dict[str, Any] | None = None,
    return_port_arrays: bool = False,
    combination_options: dict[str, Any] | None = None,
) -> dict[str, Any]:


    default_input_power_w = validate_non_negative_finite(
        default_input_power_w,
        name="default_input_power_w",
    )
    phase_offsets_rad_by_path = _require_mapping(
        phase_offsets_rad_by_path,
        "phase_offsets_rad_by_path",
    )
    combination_options = dict(combination_options or {})

    if len(paths) != 2:
        raise ValueError("ideal_2x2_scalar_combiner requires exactly two input paths")

    path_order = [str(_read(path, "path_id", "id", default=f"path_{idx + 1}")).strip() for idx, path in enumerate(paths)]
    if len(set(path_order)) != 2 or any(not path_id for path_id in path_order):
        raise ValueError("ideal_2x2_scalar_combiner requires two unique non-empty path_id values")

    unknown_phase_ids = sorted(set(phase_offsets_rad_by_path) - set(path_order))
    if unknown_phase_ids:
        raise ValueError(
            "phase_offsets_rad_by_path contains unknown path_id values: "
            + ", ".join(unknown_phase_ids)
        )

    if combination_options.get("amplitude_coefficients_by_path"):
        raise ValueError(
            "amplitude_coefficients_by_path is not supported by ideal_2x2_scalar_combiner; "
            "use t/r combiner coefficients instead"
        )

    t, r, coeff_info = _resolve_coefficients(combination_options)
    energy_tolerance = _optional_finite(
        combination_options.get("energy_conservation_tolerance"),
        name="combination.energy_conservation_tolerance",
    )
    if energy_tolerance is None:
        energy_tolerance = 1.0e-9
    if energy_tolerance < 0.0:
        raise ValueError("combination.energy_conservation_tolerance must be non-negative")

    path_by_id = {str(_read(path, "path_id", "id", default="")).strip(): path for path in paths}
    warnings: list[str] = []
    input_fields: list[np.ndarray] = []
    included_ids: list[str] = []
    mode_reference: np.ndarray | None = None
    reference_grid_x: np.ndarray | None = None
    reference_grid_y: np.ndarray | None = None
    reference_shape: tuple[int, int] | None = None
    reference_wavelength_nm: float | None = None

    input_power_w_by_path: dict[str, float] = {}
    throughput_by_path: dict[str, float] = {}
    transmitted_power_w_by_path: dict[str, float] = {}
    phase_offset_rad_by_path: dict[str, float] = {}
    wavelength_nm_by_path: dict[str, float] = {}
    port_detail_by_path: dict[str, Any] = {}

    skipped_path_count = 0
    total_input_power_w = 0.0
    total_transmitted_power_w = 0.0
    grid_issue_seen = False
    grid_uniform_issue_seen = False
    mode_phase_missing_seen = False
    mode_reference_issue_seen = False
    wavelength_missing_seen = False
    wavelength_mismatch_seen = False

    for path_id in path_order:
        result = path_results.get(path_id)
        if result is None or result.get("status") != "completed":
            skipped_path_count += 1
            port_detail_by_path[path_id] = {
                "status": "skipped",
                "reason": "path is missing or not completed",
            }
            continue

        path = path_by_id[path_id]
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
            "coupling_mode_phase_rad",
            "coupling_grid_x_mm",
            "coupling_grid_y_mm",
        )
        missing = [key for key in required if key not in arrays]
        if missing:
            skipped_path_count += 1
            if any(key.startswith("coupling_grid_") for key in missing):
                grid_issue_seen = True
            if "coupling_mode_phase_rad" in missing:
                mode_phase_missing_seen = True
            message = f"path {path_id} skipped in ideal 2x2 scalar combiner: missing {', '.join(missing)}"
            warnings.append(message)
            port_detail_by_path[path_id] = {
                "status": "skipped",
                "reason": "missing_combiner_arrays",
                "missing_arrays": missing,
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
        mode_phase = _as_float_array(
            arrays["coupling_mode_phase_rad"],
            name="coupling_mode_phase_rad",
            path_id=path_id,
        )
        grid_x = _as_grid_array(arrays["coupling_grid_x_mm"], name="coupling_grid_x_mm", path_id=path_id)
        grid_y = _as_grid_array(arrays["coupling_grid_y_mm"], name="coupling_grid_y_mm", path_id=path_id)

        if not _grid_is_strictly_uniform(grid_x) or not _grid_is_strictly_uniform(grid_y):
            skipped_path_count += 1
            grid_issue_seen = True
            grid_uniform_issue_seen = True
            message = f"path {path_id} skipped in ideal 2x2 scalar combiner: sampled coordinate grid is not strictly uniform"
            warnings.append(message)
            port_detail_by_path[path_id] = {"status": "skipped", "reason": "nonuniform_grid"}
            continue

        expected_shape = (int(grid_y.size), int(grid_x.size))
        if intensity.shape != phase.shape or intensity.shape != mode_intensity.shape or intensity.shape != mode_phase.shape:
            skipped_path_count += 1
            warnings.append(f"path {path_id} skipped in ideal 2x2 scalar combiner: field, phase, and mode shapes do not match")
            port_detail_by_path[path_id] = {
                "status": "skipped",
                "reason": "shape_mismatch",
                "field_shape": tuple(int(v) for v in intensity.shape),
            }
            continue
        if intensity.shape != expected_shape:
            skipped_path_count += 1
            grid_issue_seen = True
            warnings.append(
                f"path {path_id} skipped in ideal 2x2 scalar combiner: field shape {intensity.shape} does not match grid shape {expected_shape}"
            )
            port_detail_by_path[path_id] = {"status": "skipped", "reason": "field_grid_shape_mismatch"}
            continue

        candidate_mode = _build_mode_reference(mode_intensity, mode_phase)
        if reference_grid_x is None:
            reference_grid_x = grid_x
            reference_grid_y = grid_y
            reference_shape = intensity.shape
            mode_reference = candidate_mode
        else:
            assert reference_grid_x is not None and reference_grid_y is not None and reference_shape is not None
            if intensity.shape != reference_shape or not _same_grid(grid_x, reference_grid_x) or not _same_grid(grid_y, reference_grid_y):
                skipped_path_count += 1
                grid_issue_seen = True
                warnings.append(f"path {path_id} skipped in ideal 2x2 scalar combiner: sampled coordinate grid differs from first input path")
                port_detail_by_path[path_id] = {"status": "skipped", "reason": "common_grid_coordinate_mismatch"}
                continue
            if mode_reference is not None and not np.allclose(candidate_mode, mode_reference, rtol=1.0e-8, atol=1.0e-10):
                skipped_path_count += 1
                mode_reference_issue_seen = True
                warnings.append(f"path {path_id} skipped in ideal 2x2 scalar combiner: fibre mode reference differs from first input path")
                port_detail_by_path[path_id] = {"status": "skipped", "reason": "mode_reference_mismatch"}
                continue

        wavelength_nm = _wavelength_nm_for_path_result(path, result)
        if wavelength_nm is None:
            wavelength_missing_seen = True
            warnings.append(
                f"path {path_id} wavelength_nm is unavailable; ideal 2x2 scalar combiner wavelength compatibility was not fully checked"
            )
        elif reference_wavelength_nm is None:
            reference_wavelength_nm = wavelength_nm
            wavelength_nm_by_path[path_id] = wavelength_nm
        elif not math.isclose(wavelength_nm, reference_wavelength_nm, rel_tol=1.0e-9, abs_tol=1.0e-9):
            skipped_path_count += 1
            wavelength_mismatch_seen = True
            warnings.append(
                f"path {path_id} skipped in ideal 2x2 scalar combiner: wavelength_nm {wavelength_nm} differs from reference {reference_wavelength_nm}"
            )
            port_detail_by_path[path_id] = {"status": "skipped", "reason": "wavelength_mismatch"}
            continue
        else:
            wavelength_nm_by_path[path_id] = wavelength_nm

        phase_offset = _phase_offset_for_path(path, path_id, phase_offsets_rad_by_path)
        phase_offset_rad_by_path[path_id] = phase_offset
        field = np.sqrt(intensity).astype(np.complex128) * np.exp(1j * (phase + phase_offset))
        field = _normalize_field_to_power(field, transmitted_power_w)
        input_fields.append(field)
        included_ids.append(path_id)
        port_detail_by_path[path_id] = {
            "status": "included",
            "input_port": f"input_{len(included_ids)}",
            "input_power_w": input_power_w,
            "input_power_source": input_source,
            "throughput": throughput,
            "throughput_source": throughput_source,
            "transmitted_power_w": transmitted_power_w,
            "phase_offset_rad": phase_offset,
            "wavelength_nm": wavelength_nm,
            "field_shape": tuple(int(v) for v in intensity.shape),
        }

    included_path_count = len(input_fields)
    output_fields: dict[str, np.ndarray] = {}
    output_field_power_w_by_port: dict[str, float] = {}
    output_coupled_power_w_by_port: dict[str, float | None] = {}
    output_overlap_efficiency_by_port: dict[str, float | None] = {}
    output_overlap_phase_rad_by_port: dict[str, float | None] = {}
    best_output_port_id: str | None = None
    best_output_coupled_power_w: float | None = None

    if included_path_count == 2:
        e1, e2 = input_fields
        output_fields["output_1"] = t * e1 + r * e2
        output_fields["output_2"] = r * e1 + t * e2
        assert mode_reference is not None
        for port_id, field in output_fields.items():
            field_power, coupled_power, overlap_efficiency, overlap_phase = _mode_overlap_power(field, mode_reference)
            output_field_power_w_by_port[port_id] = field_power
            output_coupled_power_w_by_port[port_id] = coupled_power
            output_overlap_efficiency_by_port[port_id] = overlap_efficiency
            output_overlap_phase_rad_by_port[port_id] = overlap_phase
            if coupled_power is not None and (
                best_output_coupled_power_w is None or coupled_power > best_output_coupled_power_w
            ):
                best_output_coupled_power_w = coupled_power
                best_output_port_id = port_id
    elif included_path_count != 0:
        warnings.append(
            "ideal 2x2 scalar combiner requires two valid included fields; "
            f"got {included_path_count}"
        )

    total_output_field_power_w = float(sum(output_field_power_w_by_port.values()))
    total_output_coupled_power_w = float(
        sum(value for value in output_coupled_power_w_by_port.values() if value is not None)
    )
    energy_error_w = total_output_field_power_w - total_transmitted_power_w
    relative_energy_error = (
        energy_error_w / total_transmitted_power_w if total_transmitted_power_w > 0.0 else None
    )
    energy_conservation_passed = (
        relative_energy_error is not None and abs(relative_energy_error) <= energy_tolerance
    )

    coefficient_unitary_like = bool(coeff_info["coefficient_unitarity_error"] <= max(energy_tolerance, 1.0e-12))
    if not coefficient_unitary_like:
        warnings.append(
            "ideal 2x2 scalar combiner t/r coefficients are not unitary-like; "
            "output ports may not conserve passive optical power for arbitrary inputs"
        )
    if relative_energy_error is not None and abs(relative_energy_error) > energy_tolerance:
        warnings.append(
            f"ideal 2x2 scalar combiner energy conservation error {relative_energy_error:.3e} exceeds tolerance {energy_tolerance:.3e}"
        )

    grid_checked = included_path_count == 2 and not grid_issue_seen
    grid_uniform_checked = grid_checked and not grid_uniform_issue_seen
    wavelength_checked = included_path_count == 2 and not wavelength_missing_seen and not wavelength_mismatch_seen
    mode_phase_checked = included_path_count == 2 and not mode_phase_missing_seen
    mode_reference_checked = included_path_count == 2 and not mode_reference_issue_seen
    summary_complete = (
        skipped_path_count == 0
        and included_path_count == 2
        and grid_checked
        and grid_uniform_checked
        and wavelength_checked
        and mode_phase_checked
        and mode_reference_checked
    )

    result: dict[str, Any] = {
        "mode": "ideal_2x2_scalar_combiner",
        "power_unit": "W",
        "formula": "E_out1 = t*E_in1 + r*E_in2; E_out2 = r*E_in1 + t*E_in2",
        "model_note": (
            "Ideal symmetric 2x2 scalar combiner. This is a first device-level scalar model with two input "
            "ports and two output ports. It checks common grid, wavelength, mode phase, and energy balance, "
            "but still does not model vector polarization, coating physics, hardware geometry, or network ray branching."
        ),
        "ideal_2x2_summary_complete": summary_complete,
        "included_path_count": included_path_count,
        "skipped_combiner_path_count": skipped_path_count,
        "input_path_order": path_order,
        "included_path_order": included_ids,
        "total_input_power_w": total_input_power_w,
        "total_transmitted_power_w": total_transmitted_power_w,
        "total_output_field_power_w": total_output_field_power_w,
        "total_output_coupled_power_w": total_output_coupled_power_w,
        "overall_output_coupling_efficiency": (
            total_output_coupled_power_w / total_input_power_w if total_input_power_w > 0.0 and summary_complete else None
        ),
        "best_output_port_id": best_output_port_id,
        "best_output_coupled_power_w": best_output_coupled_power_w,
        "input_power_w_by_path": input_power_w_by_path,
        "throughput_by_path": throughput_by_path,
        "transmitted_power_w_by_path": transmitted_power_w_by_path,
        "phase_offset_rad_by_path": phase_offset_rad_by_path,
        "wavelength_nm_by_path": wavelength_nm_by_path,
        "reference_wavelength_nm": reference_wavelength_nm,
        "output_field_power_w_by_port": output_field_power_w_by_port,
        "output_coupled_power_w_by_port": output_coupled_power_w_by_port,
        "output_overlap_efficiency_by_port": output_overlap_efficiency_by_port,
        "output_overlap_phase_rad_by_port": output_overlap_phase_rad_by_port,
        "energy_conservation_checked": included_path_count == 2,
        "energy_conservation_passed": energy_conservation_passed,
        "energy_conservation_tolerance": energy_tolerance,
        "energy_conservation_error_w": energy_error_w,
        "relative_energy_conservation_error": relative_energy_error,
        "coefficient_unitary_like": coefficient_unitary_like,
        "coefficient_info": coeff_info,
        "combiner_detail_by_path": port_detail_by_path,
        "reference_grid_x_mm": reference_grid_x.tolist() if reference_grid_x is not None else None,
        "reference_grid_y_mm": reference_grid_y.tolist() if reference_grid_y is not None else None,
        "combiner_assumption_grid_checked": grid_checked,
        "combiner_assumption_grid_uniform_checked": grid_uniform_checked,
        "combiner_assumption_wavelength_checked": wavelength_checked,
        "combiner_assumption_mode_phase_checked": mode_phase_checked,
        "combiner_assumption_mode_reference_checked": mode_reference_checked,
        "combiner_assumption_polarization_checked": False,
        "combiner_assumption_phase_reference_checked": False,
        "warnings": warnings,
    }

    if return_port_arrays and output_fields:
        arrays: dict[str, Any] = {
            "multipath_2x2_grid_x_mm": reference_grid_x.tolist() if reference_grid_x is not None else [],
            "multipath_2x2_grid_y_mm": reference_grid_y.tolist() if reference_grid_y is not None else [],
        }
        for port_id, field in output_fields.items():
            arrays[f"multipath_2x2_{port_id}_field_intensity"] = (np.abs(field) ** 2).tolist()
            arrays[f"multipath_2x2_{port_id}_field_phase_rad"] = np.angle(field).tolist()
        result["arrays"] = arrays

    return result

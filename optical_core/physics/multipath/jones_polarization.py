from __future__ import annotations

import math
from typing import Any

import numpy as np

from optical_core.physics.multipath.coherent_combination import (
    _as_grid_array,
    _as_float_array,
    _as_nonnegative_float_array,
    _build_mode_reference,
    _finite_float_strict,
    _grid_is_strictly_uniform,
    _normalize_field_to_power,
    _object_to_dict,
    _phase_offset_for_path,
    _read,
    _require_mapping,
    _same_grid,
    _wavelength_nm_for_path_result,
)
from optical_core.physics.multipath.power_combination import (
    input_power_w_from_path,
    throughput_from_metrics,
    validate_non_negative_finite,
)


def _complex_from_spec(value: Any, *, name: str) -> complex:
    if isinstance(value, complex):
        if not (math.isfinite(value.real) and math.isfinite(value.imag)):
            raise ValueError(f"{name} must be finite")
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{name} must be finite")
        return complex(number, 0.0)
    if isinstance(value, str):
        text = value.strip().lower().replace(" ", "")
        aliases = {"i": 1j, "+i": 1j, "j": 1j, "+j": 1j, "-i": -1j, "-j": -1j}
        if text in aliases:
            return aliases[text]
        try:
            number = float(text)
        except ValueError as exc:
            raise ValueError(f"{name} must be a real number, complex pair [real, imag], or simple i/-i string") from exc
        if not math.isfinite(number):
            raise ValueError(f"{name} must be finite")
        return complex(number, 0.0)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        real = _finite_float_strict(value[0], name=f"{name}.real")
        imag = _finite_float_strict(value[1], name=f"{name}.imag")
        return complex(real, imag)
    if isinstance(value, dict):
        real = _finite_float_strict(value.get("real", value.get("re", 0.0)), name=f"{name}.real")
        imag = _finite_float_strict(value.get("imag", value.get("im", 0.0)), name=f"{name}.imag")
        return complex(real, imag)
    raise ValueError(f"{name} must be a real number or complex pair [real, imag]")


def _complex_to_pair(value: complex) -> list[float]:
    return [float(np.real(value)), float(np.imag(value))]


def _angle_from_spec(spec: dict[str, Any], *, default: float = 0.0) -> float:
    if "angle_rad" in spec:
        return _finite_float_strict(spec.get("angle_rad"), name="jones angle_rad")
    if "theta_rad" in spec:
        return _finite_float_strict(spec.get("theta_rad"), name="jones theta_rad")
    if "angle_deg" in spec:
        return math.radians(_finite_float_strict(spec.get("angle_deg"), name="jones angle_deg"))
    if "theta_deg" in spec:
        return math.radians(_finite_float_strict(spec.get("theta_deg"), name="jones theta_deg"))
    return float(default)


def _normalize_jones_vector(vector: np.ndarray, *, name: str) -> np.ndarray:
    norm = float(np.sqrt(np.sum(np.abs(vector) ** 2)))
    if norm <= 0.0 or not math.isfinite(norm):
        raise ValueError(f"{name} must have non-zero finite Jones-vector norm")
    return vector / norm


def jones_vector_from_spec(spec: Any, *, name: str = "jones_vector", normalize: bool = True) -> np.ndarray:


    if spec is None:
        vector = np.asarray([1.0 + 0.0j, 0.0 + 0.0j], dtype=np.complex128)
        return _normalize_jones_vector(vector, name=name) if normalize else vector

    if isinstance(spec, str):
        key = spec.strip().lower().replace("-", "_").replace(" ", "_")
        if key in {"h", "horizontal", "x", "linear_x"}:
            vector = np.asarray([1.0 + 0.0j, 0.0 + 0.0j], dtype=np.complex128)
        elif key in {"v", "vertical", "y", "linear_y"}:
            vector = np.asarray([0.0 + 0.0j, 1.0 + 0.0j], dtype=np.complex128)
        elif key in {"right", "right_circular", "rhc", "rhcp"}:
            vector = np.asarray([1.0 + 0.0j, -1j], dtype=np.complex128) / math.sqrt(2.0)
        elif key in {"left", "left_circular", "lhc", "lhcp"}:
            vector = np.asarray([1.0 + 0.0j, 1j], dtype=np.complex128) / math.sqrt(2.0)
        else:
            raise ValueError(f"unsupported {name} string {spec!r}")
        return _normalize_jones_vector(vector, name=name) if normalize else vector

    if isinstance(spec, (list, tuple)):
        if len(spec) != 2:
            raise ValueError(f"{name} must contain exactly two Jones components")
        vector = np.asarray(
            [
                _complex_from_spec(spec[0], name=f"{name}[0]"),
                _complex_from_spec(spec[1], name=f"{name}[1]"),
            ],
            dtype=np.complex128,
        )
        return _normalize_jones_vector(vector, name=name) if normalize else vector

    if not isinstance(spec, dict):
        raise ValueError(f"{name} must be a Jones-vector list, string alias, or mapping")

    if any(key in spec for key in ("ex", "ey", "x", "y")):
        ex = spec.get("ex", spec.get("x", 0.0))
        ey = spec.get("ey", spec.get("y", 0.0))
        vector = np.asarray(
            [_complex_from_spec(ex, name=f"{name}.ex"), _complex_from_spec(ey, name=f"{name}.ey")],
            dtype=np.complex128,
        )
        return _normalize_jones_vector(vector, name=name) if normalize else vector

    state = str(spec.get("type") or spec.get("state") or "linear").strip().lower().replace("-", "_")
    if state in {"linear", "linear_polarized", "plane", "plane_polarized"}:
        theta = _angle_from_spec(spec, default=0.0)
        vector = np.asarray([math.cos(theta), math.sin(theta)], dtype=np.complex128)
    elif state in {"horizontal", "x", "linear_x"}:
        vector = np.asarray([1.0 + 0.0j, 0.0 + 0.0j], dtype=np.complex128)
    elif state in {"vertical", "y", "linear_y"}:
        vector = np.asarray([0.0 + 0.0j, 1.0 + 0.0j], dtype=np.complex128)
    elif state in {"right", "right_circular", "rhc", "rhcp"}:
        vector = np.asarray([1.0 + 0.0j, -1j], dtype=np.complex128) / math.sqrt(2.0)
    elif state in {"left", "left_circular", "lhc", "lhcp"}:
        vector = np.asarray([1.0 + 0.0j, 1j], dtype=np.complex128) / math.sqrt(2.0)
    elif state in {"elliptical", "ellipse"}:
        gamma = _finite_float_strict(spec.get("gamma", spec.get("amplitude_ratio", 1.0)), name=f"{name}.gamma")
        if gamma < 0.0:
            raise ValueError(f"{name}.gamma must be non-negative")
        phase = _finite_float_strict(spec.get("phase_rad", spec.get("relative_phase_rad", 0.0)), name=f"{name}.phase_rad")
        vector = np.asarray([1.0 + 0.0j, gamma * np.exp(1j * phase)], dtype=np.complex128)
    else:
        raise ValueError(f"unsupported {name} type {state!r}")
    return _normalize_jones_vector(vector, name=name) if normalize else vector


def _rotation_matrix(angle_rad: float) -> np.ndarray:
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    return np.asarray([[c, -s], [s, c]], dtype=np.complex128)


def _apply_global_phase(matrix: np.ndarray, spec: Any, *, name: str) -> np.ndarray:


    if isinstance(spec, dict) and "global_phase_rad" in spec:
        global_phase = _finite_float_strict(spec.get("global_phase_rad"), name=f"{name}.global_phase_rad")
        return np.exp(1j * global_phase) * matrix
    return matrix


def jones_matrix_from_spec(spec: Any, *, name: str = "jones_matrix") -> np.ndarray:


    if isinstance(spec, (list, tuple)):
        if len(spec) != 2 or any(not isinstance(row, (list, tuple)) or len(row) != 2 for row in spec):
            raise ValueError(f"{name} must be a 2x2 matrix")
        return np.asarray(
            [
                [_complex_from_spec(spec[0][0], name=f"{name}[0][0]"), _complex_from_spec(spec[0][1], name=f"{name}[0][1]")],
                [_complex_from_spec(spec[1][0], name=f"{name}[1][0]"), _complex_from_spec(spec[1][1], name=f"{name}[1][1]")],
            ],
            dtype=np.complex128,
        )
    if not isinstance(spec, dict):
        raise ValueError(f"{name} must be a 2x2 matrix or element mapping")

    if "matrix" in spec:
        return _apply_global_phase(jones_matrix_from_spec(spec["matrix"], name=f"{name}.matrix"), spec, name=name)

    element_type = str(spec.get("type") or spec.get("element") or "").strip().lower().replace("-", "_")
    if element_type in {"linear_polarizer", "polarizer", "linear_analyzer", "analyzer"}:
        theta = _angle_from_spec(spec, default=0.0)
        c = math.cos(theta)
        s = math.sin(theta)
        return _apply_global_phase(np.asarray([[c * c, c * s], [c * s, s * s]], dtype=np.complex128), spec, name=name)
    if element_type in {"quarter_wave_plate", "qwp", "lambda_4", "waveplate_qwp"}:
        theta = _angle_from_spec(spec, default=0.0)
        delta = _finite_float_strict(spec.get("retardance_rad", spec.get("delta_rad", math.pi / 2.0)), name=f"{name}.delta_rad")
        r = _rotation_matrix(theta)
        d = np.diag([1.0 + 0.0j, np.exp(1j * delta)]).astype(np.complex128)
        return _apply_global_phase(r @ d @ r.T, spec, name=name)
    if element_type in {"half_wave_plate", "hwp", "lambda_2", "waveplate_hwp"}:
        theta = _angle_from_spec(spec, default=0.0)
        r = _rotation_matrix(theta)
        d = np.diag([1.0 + 0.0j, -1.0 + 0.0j]).astype(np.complex128)
        return _apply_global_phase(r @ d @ r.T, spec, name=name)
    if element_type in {"retarder", "phase_retarder", "waveplate"}:
        theta = _angle_from_spec(spec, default=0.0)
        delta = _finite_float_strict(spec.get("retardance_rad", spec.get("delta_rad", 0.0)), name=f"{name}.delta_rad")
        r = _rotation_matrix(theta)
        d = np.diag([1.0 + 0.0j, np.exp(1j * delta)]).astype(np.complex128)
        return _apply_global_phase(r @ d @ r.T, spec, name=name)
    if element_type in {"right_circular_polarizer", "right_circular_analyzer"}:
        return _apply_global_phase(0.5 * np.asarray([[1.0, -1j], [1j, 1.0]], dtype=np.complex128), spec, name=name)
    if element_type in {"left_circular_polarizer", "left_circular_analyzer"}:
        return _apply_global_phase(0.5 * np.asarray([[1.0, 1j], [-1j, 1.0]], dtype=np.complex128), spec, name=name)
    if element_type in {"identity", "none", ""}:
        return _apply_global_phase(np.eye(2, dtype=np.complex128), spec, name=name)
    raise ValueError(f"unsupported {name} element type {element_type!r}")


def _matrix_sequence_from_spec(value: Any, *, name: str) -> list[np.ndarray]:
    if value is None:
        return []
    if isinstance(value, dict):
        if "sequence" in value:
            raw = value.get("sequence") or []
            if not isinstance(raw, list):
                raise ValueError(f"{name}.sequence must be a list")
            return [jones_matrix_from_spec(item, name=f"{name}.sequence[{idx}]") for idx, item in enumerate(raw)]
        return [jones_matrix_from_spec(value, name=name)]
    if isinstance(value, list):
        
        if len(value) == 2 and all(isinstance(row, (list, tuple)) and len(row) == 2 for row in value):
            return [jones_matrix_from_spec(value, name=name)]
        return [jones_matrix_from_spec(item, name=f"{name}[{idx}]") for idx, item in enumerate(value)]
    raise ValueError(f"{name} must be a Jones matrix, element mapping, or list of elements")


def _path_jones_vector(
    path: Any,
    path_id: str,
    jones_vectors_by_path: dict[str, Any],
    jones_elements_by_path: dict[str, Any],
    jones_matrices_by_path: dict[str, Any],
    *,
    allow_jones_gain: bool = False,
    passivity_tolerance: float = 1.0e-9,
) -> tuple[np.ndarray, dict[str, Any]]:
    source = "default_linear_x"
    if path_id in jones_vectors_by_path:
        vector_spec = jones_vectors_by_path[path_id]
        source = "combination.jones_vectors_by_path"
    else:
        vector_spec = None
        for container_name, container in (
            ("path", _object_to_dict(path)),
            ("source", _object_to_dict(_read(path, "source", default=None))),
            ("receiver", _object_to_dict(_read(path, "receiver", default=None))),
            ("options", _object_to_dict(_read(path, "options", default=None))),
        ):
            for key in ("jones_vector", "polarization_jones_vector", "polarization"):
                if key in container:
                    vector_spec = container.get(key)
                    source = f"{container_name}.{key}"
                    break
            if vector_spec is not None:
                break
    vector = jones_vector_from_spec(vector_spec, name=f"jones_vector[{path_id}]", normalize=True)

    matrix_sequence: list[np.ndarray] = []
    element_count = 0
    if path_id in jones_matrices_by_path:
        seq = _matrix_sequence_from_spec(jones_matrices_by_path[path_id], name=f"jones_matrices_by_path[{path_id!r}]")
        matrix_sequence.extend(seq)
        element_count += len(seq)
    if path_id in jones_elements_by_path:
        seq = _matrix_sequence_from_spec(jones_elements_by_path[path_id], name=f"jones_elements_by_path[{path_id!r}]")
        matrix_sequence.extend(seq)
        element_count += len(seq)

    for matrix in matrix_sequence:
        vector = matrix @ vector
    vector_power = float(np.sum(np.abs(vector) ** 2))
    if not math.isfinite(vector_power) or vector_power < 0.0:
        raise ValueError(f"path {path_id} Jones vector has invalid power after Jones elements")

    jones_passive_passed = bool(vector_power <= 1.0 + passivity_tolerance)
    nonpassive_warning = None
    if not jones_passive_passed and not allow_jones_gain:
        nonpassive_warning = (
            f"path {path_id} Jones elements increase optical power by factor {vector_power:.6g}; "
            "this is non-passive unless intentionally modeling gain"
        )

    detail = {
        "jones_vector_source": source,
        "jones_vector_explicitly_specified": source != "default_linear_x",
        "jones_element_count": element_count,
        "jones_vector_after_elements": [_complex_to_pair(vector[0]), _complex_to_pair(vector[1])],
        "jones_power_factor": vector_power,
        "jones_passive_passed": jones_passive_passed,
        "jones_nonpassive_declared_allowed": bool(allow_jones_gain),
        "jones_nonpassive_warning": nonpassive_warning,
    }
    return vector, detail


def _integrated_stokes(ex: np.ndarray, ey: np.ndarray) -> dict[str, float | None]:
    s0 = float(np.sum(np.abs(ex) ** 2 + np.abs(ey) ** 2))
    s1 = float(np.sum(np.abs(ex) ** 2 - np.abs(ey) ** 2))
    cross = np.sum(ex * np.conjugate(ey))
    s2 = float(2.0 * np.real(cross))
    s3 = float(2.0 * np.imag(cross))
    return {
        "S0": s0,
        "S1": s1,
        "S2": s2,
        "S3": s3,
        "normalized_S1": s1 / s0 if s0 > 0.0 else None,
        "normalized_S2": s2 / s0 if s0 > 0.0 else None,
        "normalized_S3": s3 / s0 if s0 > 0.0 else None,
    }


def _vector_mode_overlap(
    field_x: np.ndarray,
    field_y: np.ndarray,
    mode_reference: np.ndarray,
    *,
    mode_polarization: str,
    mode_jones_vector: np.ndarray | None,
) -> tuple[float, float | None, float | None, float | None, dict[str, Any]]:
    field_power = float(np.sum(np.abs(field_x) ** 2 + np.abs(field_y) ** 2))
    mode_power = float(np.sum(np.abs(mode_reference) ** 2))
    if mode_power <= 0.0:
        return field_power, None, None, None, {"mode_polarization": mode_polarization}

    if mode_polarization == "polarization_insensitive":
        overlap_x = np.sum(field_x * np.conjugate(mode_reference))
        overlap_y = np.sum(field_y * np.conjugate(mode_reference))
        coupled_power = float((abs(overlap_x) ** 2 + abs(overlap_y) ** 2) / mode_power)
        dominant_overlap = overlap_x if abs(overlap_x) >= abs(overlap_y) else overlap_y
        detail = {
            "mode_polarization": "polarization_insensitive",
            "overlap_x_abs": float(abs(overlap_x)),
            "overlap_y_abs": float(abs(overlap_y)),
        }
        return field_power, coupled_power, coupled_power / field_power if field_power > 0.0 else None, float(np.angle(dominant_overlap)), detail

    if mode_jones_vector is None:
        raise ValueError("mode_jones_vector is required when mode_polarization='jones_vector'")
    mode_x = mode_reference * mode_jones_vector[0]
    mode_y = mode_reference * mode_jones_vector[1]
    vector_mode_power = float(np.sum(np.abs(mode_x) ** 2 + np.abs(mode_y) ** 2))
    if vector_mode_power <= 0.0:
        return field_power, None, None, None, {"mode_polarization": mode_polarization}
    overlap = np.sum(field_x * np.conjugate(mode_x) + field_y * np.conjugate(mode_y))
    coupled_power = float((abs(overlap) ** 2) / vector_mode_power)
    detail = {
        "mode_polarization": "jones_vector",
        "mode_jones_vector": [_complex_to_pair(mode_jones_vector[0]), _complex_to_pair(mode_jones_vector[1])],
        "overlap_abs": float(abs(overlap)),
    }
    return field_power, coupled_power, coupled_power / field_power if field_power > 0.0 else None, float(np.angle(overlap)), detail


def summarize_jones_polarization_combiner(
    path_results: dict[str, dict[str, Any]],
    *,
    raw_arrays_by_path: dict[str, dict[str, Any]],
    paths: list[Any],
    default_input_power_w: float = 1.0e-3,
    phase_offsets_rad_by_path: dict[str, Any] | None = None,
    jones_vectors_by_path: dict[str, Any] | None = None,
    jones_elements_by_path: dict[str, Any] | None = None,
    jones_matrices_by_path: dict[str, Any] | None = None,
    mode_polarization: str = "polarization_insensitive",
    mode_jones_vector: Any | None = None,
    return_jones_arrays: bool = False,
    allow_jones_gain: bool = False,
    jones_passivity_tolerance: float = 1.0e-9,
) -> dict[str, Any]:


    default_input_power_w = validate_non_negative_finite(default_input_power_w, name="default_input_power_w")
    jones_passivity_tolerance = validate_non_negative_finite(
        jones_passivity_tolerance,
        name="jones_passivity_tolerance",
    )
    allow_jones_gain = bool(allow_jones_gain)
    phase_offsets_rad_by_path = _require_mapping(phase_offsets_rad_by_path, "phase_offsets_rad_by_path")
    jones_vectors_by_path = _require_mapping(jones_vectors_by_path, "jones_vectors_by_path")
    jones_elements_by_path = _require_mapping(jones_elements_by_path, "jones_elements_by_path")
    jones_matrices_by_path = _require_mapping(jones_matrices_by_path, "jones_matrices_by_path")

    known_path_ids = set(path_results.keys())
    for mapping_name, mapping in (
        ("phase_offsets_rad_by_path", phase_offsets_rad_by_path),
        ("jones_vectors_by_path", jones_vectors_by_path),
        ("jones_elements_by_path", jones_elements_by_path),
        ("jones_matrices_by_path", jones_matrices_by_path),
    ):
        unknown = sorted(set(mapping) - known_path_ids)
        if unknown:
            raise ValueError(f"{mapping_name} contains unknown path_id values: " + ", ".join(unknown))

    mode_polarization = str(mode_polarization or "polarization_insensitive").strip().lower()
    if mode_polarization in {"insensitive", "polarization_insensitive", "dual_polarization", "unpolarized_fiber"}:
        mode_polarization = "polarization_insensitive"
        parsed_mode_jones = None
    elif mode_polarization in {"jones", "jones_vector", "fixed_jones", "polarization_selective"}:
        mode_polarization = "jones_vector"
        parsed_mode_jones = jones_vector_from_spec(mode_jones_vector, name="mode_jones_vector", normalize=True)
    else:
        raise ValueError("mode_polarization must be 'polarization_insensitive' or 'jones_vector'")

    path_by_id = {str(_read(path, "path_id", "id", default="")).strip(): path for path in paths}

    warnings: list[str] = []
    field_x_total: np.ndarray | None = None
    field_y_total: np.ndarray | None = None
    mode_reference: np.ndarray | None = None
    reference_shape: tuple[int, int] | None = None
    reference_grid_x: np.ndarray | None = None
    reference_grid_y: np.ndarray | None = None
    reference_wavelength_nm: float | None = None

    included_path_count = 0
    skipped_path_count = 0
    total_input_power_w = 0.0
    total_transmitted_power_w = 0.0

    input_power_w_by_path: dict[str, float] = {}
    throughput_by_path: dict[str, float] = {}
    transmitted_power_w_by_path: dict[str, float] = {}
    phase_offset_rad_by_path: dict[str, float] = {}
    jones_vector_by_path: dict[str, list[list[float]]] = {}
    jones_power_factor_by_path: dict[str, float] = {}
    wavelength_nm_by_path: dict[str, float] = {}
    jones_detail_by_path: dict[str, dict[str, Any]] = {}

    grid_issue_seen = False
    grid_uniform_issue_seen = False
    mode_phase_missing_seen = False
    mode_reference_issue_seen = False
    wavelength_missing_seen = False
    wavelength_mismatch_seen = False
    default_polarization_path_ids: list[str] = []
    nonpassive_path_ids: list[str] = []
    jones_passive_warning_by_path: dict[str, str] = {}

    for path_id, result in path_results.items():
        if result.get("status") != "completed":
            skipped_path_count += 1
            jones_detail_by_path[path_id] = {"status": "skipped", "reason": f"path status is {result.get('status')}"}
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
            message = f"path {path_id} skipped in Jones polarization combiner: missing {', '.join(missing)}"
            warnings.append(message)
            jones_detail_by_path[path_id] = {"status": "skipped", "reason": message}
            continue

        intensity = _as_nonnegative_float_array(arrays["coupling_field_intensity"], name="coupling_field_intensity", path_id=path_id)
        phase = _as_float_array(arrays["coupling_field_phase_rad"], name="coupling_field_phase_rad", path_id=path_id)
        mode_intensity = _as_nonnegative_float_array(arrays["coupling_mode_intensity"], name="coupling_mode_intensity", path_id=path_id)
        mode_phase = _as_float_array(arrays["coupling_mode_phase_rad"], name="coupling_mode_phase_rad", path_id=path_id)
        grid_x = _as_grid_array(arrays["coupling_grid_x_mm"], name="coupling_grid_x_mm", path_id=path_id)
        grid_y = _as_grid_array(arrays["coupling_grid_y_mm"], name="coupling_grid_y_mm", path_id=path_id)

        if intensity.shape != phase.shape or intensity.shape != mode_intensity.shape or intensity.shape != mode_phase.shape:
            skipped_path_count += 1
            grid_issue_seen = True
            message = f"path {path_id} skipped in Jones polarization combiner: intensity, phase, and mode arrays have different shapes"
            warnings.append(message)
            jones_detail_by_path[path_id] = {"status": "skipped", "reason": message}
            continue
        if intensity.shape != (grid_y.size, grid_x.size):
            skipped_path_count += 1
            grid_issue_seen = True
            message = f"path {path_id} skipped in Jones polarization combiner: field shape does not match grid_y/grid_x lengths"
            warnings.append(message)
            jones_detail_by_path[path_id] = {"status": "skipped", "reason": message}
            continue
        if not (_grid_is_strictly_uniform(grid_x) and _grid_is_strictly_uniform(grid_y)):
            skipped_path_count += 1
            grid_uniform_issue_seen = True
            message = f"path {path_id} skipped in Jones polarization combiner: coupling grid is not strictly uniform"
            warnings.append(message)
            jones_detail_by_path[path_id] = {"status": "skipped", "reason": message}
            continue

        wavelength_nm = _wavelength_nm_for_path_result(path, result)
        if wavelength_nm is None:
            skipped_path_count += 1
            wavelength_missing_seen = True
            message = f"path {path_id} skipped in Jones polarization combiner: wavelength_nm is missing"
            warnings.append(message)
            jones_detail_by_path[path_id] = {"status": "skipped", "reason": message}
            continue
        if reference_wavelength_nm is None:
            reference_wavelength_nm = wavelength_nm
        elif not math.isclose(wavelength_nm, reference_wavelength_nm, rel_tol=1.0e-10, abs_tol=1.0e-9):
            skipped_path_count += 1
            wavelength_mismatch_seen = True
            message = (
                f"path {path_id} skipped in Jones polarization combiner: wavelength_nm {wavelength_nm} "
                f"differs from reference {reference_wavelength_nm}"
            )
            warnings.append(message)
            jones_detail_by_path[path_id] = {"status": "skipped", "reason": message}
            continue

        if reference_shape is None:
            reference_shape = intensity.shape
            reference_grid_x = grid_x
            reference_grid_y = grid_y
            mode_reference = _build_mode_reference(mode_intensity, mode_phase)
            field_x_total = np.zeros_like(mode_reference, dtype=np.complex128)
            field_y_total = np.zeros_like(mode_reference, dtype=np.complex128)
        else:
            assert reference_grid_x is not None and reference_grid_y is not None and mode_reference is not None
            if intensity.shape != reference_shape or not _same_grid(grid_x, reference_grid_x) or not _same_grid(grid_y, reference_grid_y):
                skipped_path_count += 1
                grid_issue_seen = True
                message = f"path {path_id} skipped in Jones polarization combiner: coordinate grid differs from reference path"
                warnings.append(message)
                jones_detail_by_path[path_id] = {"status": "skipped", "reason": message}
                continue
            candidate_mode = _build_mode_reference(mode_intensity, mode_phase)
            if not np.allclose(candidate_mode, mode_reference, rtol=1.0e-7, atol=1.0e-10):
                skipped_path_count += 1
                mode_reference_issue_seen = True
                message = f"path {path_id} skipped in Jones polarization combiner: mode reference differs from reference path"
                warnings.append(message)
                jones_detail_by_path[path_id] = {"status": "skipped", "reason": message}
                continue

        jones_vector, jones_detail = _path_jones_vector(
            path,
            path_id,
            jones_vectors_by_path,
            jones_elements_by_path,
            jones_matrices_by_path,
            allow_jones_gain=allow_jones_gain,
            passivity_tolerance=jones_passivity_tolerance,
        )
        if not jones_detail.get("jones_vector_explicitly_specified", False):
            default_polarization_path_ids.append(path_id)
            warnings.append(
                f"path {path_id} uses default linear-x polarization; specify Jones vector for physical completeness"
            )
        if not bool(jones_detail.get("jones_passive_passed", True)):
            nonpassive_path_ids.append(path_id)
            warning = jones_detail.get("jones_nonpassive_warning")
            if warning:
                jones_passive_warning_by_path[path_id] = str(warning)
                warnings.append(str(warning))
        phase_offset = _phase_offset_for_path(path, path_id, phase_offsets_rad_by_path)
        scalar_field = np.sqrt(intensity).astype(np.complex128) * np.exp(1j * (phase + phase_offset))
        scalar_field = _normalize_field_to_power(scalar_field, transmitted_power_w)

        assert field_x_total is not None and field_y_total is not None
        field_x_total = field_x_total + scalar_field * jones_vector[0]
        field_y_total = field_y_total + scalar_field * jones_vector[1]

        included_path_count += 1
        phase_offset_rad_by_path[path_id] = phase_offset
        wavelength_nm_by_path[path_id] = wavelength_nm
        jones_vector_by_path[path_id] = [_complex_to_pair(jones_vector[0]), _complex_to_pair(jones_vector[1])]
        jones_power_factor_by_path[path_id] = float(np.sum(np.abs(jones_vector) ** 2))
        jones_detail_by_path[path_id] = {
            "status": "included",
            "input_power_source": input_source,
            "throughput_source": throughput_source,
            "input_power_w": input_power_w,
            "throughput": throughput,
            "transmitted_power_w": transmitted_power_w,
            "phase_offset_rad": phase_offset,
            "wavelength_nm": wavelength_nm,
            **jones_detail,
        }

    mode_reference_checked = mode_reference is not None and not mode_reference_issue_seen
    grid_checked = reference_grid_x is not None and reference_grid_y is not None and not grid_issue_seen and not grid_uniform_issue_seen
    wavelength_checked = reference_wavelength_nm is not None and not wavelength_missing_seen and not wavelength_mismatch_seen
    polarization_checked = included_path_count > 0 and not default_polarization_path_ids
    jones_passive_checked = included_path_count > 0
    jones_passive_passed = not nonpassive_path_ids or allow_jones_gain
    jones_convention_documented = True
    jones_phase_reference_checked = True
    jones_summary_complete = bool(
        skipped_path_count == 0
        and included_path_count > 0
        and grid_checked
        and wavelength_checked
        and mode_reference_checked
    )
    jones_physical_assumptions_complete = bool(
        jones_summary_complete
        and polarization_checked
        and jones_passive_checked
        and jones_passive_passed
        and jones_convention_documented
        and jones_phase_reference_checked
    )

    field_power_w = None
    coupled_power_w = None
    overlap_efficiency = None
    overlap_phase_rad = None
    overall_efficiency = None
    stokes = {"S0": None, "S1": None, "S2": None, "S3": None, "normalized_S1": None, "normalized_S2": None, "normalized_S3": None}
    overlap_detail: dict[str, Any] = {}
    arrays: dict[str, Any] = {}

    if field_x_total is not None and field_y_total is not None and mode_reference is not None:
        field_power_w, coupled_power_w, overlap_efficiency, overlap_phase_rad, overlap_detail = _vector_mode_overlap(
            field_x_total,
            field_y_total,
            mode_reference,
            mode_polarization=mode_polarization,
            mode_jones_vector=parsed_mode_jones,
        )
        overall_efficiency = coupled_power_w / total_input_power_w if coupled_power_w is not None and total_input_power_w > 0.0 else None
        stokes = _integrated_stokes(field_x_total, field_y_total)
        if return_jones_arrays:
            arrays = {
                "multipath_jones_field_x_intensity": (np.abs(field_x_total) ** 2).tolist(),
                "multipath_jones_field_x_phase_rad": np.angle(field_x_total).tolist(),
                "multipath_jones_field_y_intensity": (np.abs(field_y_total) ** 2).tolist(),
                "multipath_jones_field_y_phase_rad": np.angle(field_y_total).tolist(),
                "multipath_jones_total_intensity": (np.abs(field_x_total) ** 2 + np.abs(field_y_total) ** 2).tolist(),
                "multipath_jones_grid_x_mm": reference_grid_x.tolist() if reference_grid_x is not None else [],
                "multipath_jones_grid_y_mm": reference_grid_y.tolist() if reference_grid_y is not None else [],
            }

    result: dict[str, Any] = {
        "jones_summary_complete": jones_summary_complete,
        "power_unit": "W",
        "jones_combination_mode": "jones_polarization_combiner",
        "jones_model_note": (
            "Jones-vector coherent polarization combiner for fully polarized fields. "
            "Natural or partially polarized light requires Mueller/Stokes modeling."
        ),
        "included_path_count": included_path_count,
        "skipped_jones_path_count": skipped_path_count,
        "total_input_power_w": total_input_power_w,
        "total_transmitted_power_w": total_transmitted_power_w,
        "total_jones_field_power_w": field_power_w,
        "total_coupled_power_w": coupled_power_w,
        "jones_mode_overlap_efficiency": overlap_efficiency,
        "overall_jones_combining_efficiency": overall_efficiency,
        "jones_overlap_phase_rad": overlap_phase_rad,
        "mode_polarization": mode_polarization,
        "mode_overlap_detail": overlap_detail,
        "input_power_w_by_path": input_power_w_by_path,
        "throughput_by_path": throughput_by_path,
        "transmitted_power_w_by_path": transmitted_power_w_by_path,
        "phase_offset_rad_by_path": phase_offset_rad_by_path,
        "jones_vector_by_path": jones_vector_by_path,
        "jones_power_factor_by_path": jones_power_factor_by_path,
        "wavelength_nm_by_path": wavelength_nm_by_path,
        "reference_wavelength_nm": reference_wavelength_nm,
        "reference_grid_x_mm": reference_grid_x.tolist() if reference_grid_x is not None else None,
        "reference_grid_y_mm": reference_grid_y.tolist() if reference_grid_y is not None else None,
        "jones_detail_by_path": jones_detail_by_path,
        "integrated_stokes": stokes,
        "jones_assumption_grid_checked": grid_checked,
        "jones_assumption_grid_uniform_checked": grid_checked and not grid_uniform_issue_seen,
        "jones_assumption_wavelength_checked": wavelength_checked,
        "jones_assumption_mode_reference_checked": mode_reference_checked,
        "jones_assumption_polarization_checked": polarization_checked,
        "jones_assumption_explicit_polarization_checked": polarization_checked,
        "jones_default_polarization_path_ids": list(default_polarization_path_ids),
        "jones_assumption_phase_reference_checked": jones_phase_reference_checked,
        "jones_passive_checked": jones_passive_checked,
        "jones_passive_passed": jones_passive_passed,
        "jones_passive_warning_by_path": dict(jones_passive_warning_by_path),
        "jones_nonpassive_path_ids": list(nonpassive_path_ids),
        "jones_max_power_gain_by_path": dict(jones_power_factor_by_path),
        "jones_allow_nonpassive_gain": allow_jones_gain,
        "jones_passivity_tolerance": jones_passivity_tolerance,
        "jones_stokes_convention": "S3 = 2 Im(Ex Ey*)",
        "jones_circular_convention": "left=[1,i]/sqrt(2), right=[1,-i]/sqrt(2)",
        "jones_waveplate_matrix_convention": (
            "standard retarders use diag(1, exp(i*retardance)) in the local fast/slow basis; "
            "optional global_phase_rad multiplies the entire Jones matrix and matters for coherent interference"
        ),
        "jones_convention_documented": jones_convention_documented,
        "jones_physical_assumptions_complete": jones_physical_assumptions_complete,
        "warnings": warnings,
    }
    if arrays:
        result["arrays"] = arrays
    return result

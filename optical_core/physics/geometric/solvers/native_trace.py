# 原生多线程光线追迹内核的 ctypes 绑定与 TraceBundle 组装。
#
# C++ 内核（native/optical_native_core.cpp）逐行复刻
# scalar_raytrace.trace_single_ray_detailed 的语义；本模块负责：
#   1. 懒加载 native/build/optical_native.dll（或 OPTICAL_NATIVE_DLL），
#      失败时 native_available() 返回 False，调用方走原 Python 路径；
#   2. 把 SequentialOpticalSystem/RayBundle/TraceOptions 展平为 C 结构体；
#   3. 把返回数组组装成与 batch_raytrace.trace_ray_batch 完全一致的
#      TraceBundle（含 surface_records、path_points、交互诊断记录）。
# 数值校验见 tests/test_native_raytrace_parity.py。

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Any

import numpy as np

from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.models.representations.ray_bundle import RayBundle
from optical_core.models.representations.trace import PlaneTraceData, TraceBundle
from optical_core.physics.geometric.solvers.trace_options import TraceOptions

__all__ = [
    "NativeTraceError",
    "native_available",
    "native_supports",
    "native_thread_count",
    "trace_ray_batch_native",
]


class NativeTraceError(RuntimeError):
    """Native kernel failure; the caller must fall back to the Python path."""


_STATUS_NAMES = (
    "REACHED_IMAGE",
    "REACHED_LAST_SURFACE",
    "INVALID_INPUT",
    "INTERSECTION_FAILED",
    "APERTURE_CLIPPED",
    "REFLECTION_FAILED",
    "REFRACTION_FAILED",
    "IMAGE_PROPAGATION_FAILED",
)

# 与 C++ kReason* 枚举一一对应；空串表示无终止原因。
_REASON_NAMES = (
    "",
    "invalid input ray",
    "光线方向无效",
    "光线近似平行于局部顶点平面",
    "初值求交失败",
    "交点位于光线反向延长线上",
    "曲面求交未收敛",
    "surface intersection failed",
    "clipped by clear aperture",
    "mirror reflection branch has zero power",
    "total internal reflection or zero transmitted power",
    "cannot propagate to image plane",
    "invalid image propagation distance",
    "全反射或折射方向无效",
)

_DIAG_FIELDS = (
    "input_power",
    "transmitted_power",
    "reflected_power",
    "absorbed_power",
    "scattered_power",
    "specular_survival",
    "coating_Rs",
    "coating_Rp",
    "coating_Ts",
    "coating_Tp",
    "coating_absorption_s",
    "coating_absorption_p",
    "coating_energy_error_s",
    "coating_energy_error_p",
    "energy_accounted_power",
    "energy_error",
    "incident_angle_rad",
    "surface_absorption_fraction",
    "explicit_absorbed_power_estimate",
    "coating_absorbed_power_estimate",
)

_DIAG_COUNT = len(_DIAG_FIELDS)

_MIRROR_TYPES = {"mirror", "reflective", "reflection"}

_PROGRESS_CB = ctypes.CFUNCTYPE(None, ctypes.c_double, ctypes.c_void_p)


class _ONTraceRequest(ctypes.Structure):
    _fields_ = [
        ("surface_count", ctypes.c_int),
        ("radius_mm", ctypes.POINTER(ctypes.c_double)),
        ("conic", ctypes.POINTER(ctypes.c_double)),
        ("asphere_a2", ctypes.POINTER(ctypes.c_double)),
        ("vertex_z", ctypes.POINTER(ctypes.c_double)),
        ("n_before", ctypes.POINTER(ctypes.c_double)),
        ("n_after", ctypes.POINTER(ctypes.c_double)),
        ("clear_aperture", ctypes.POINTER(ctypes.c_double)),
        ("absorption", ctypes.POINTER(ctypes.c_double)),
        ("roughness", ctypes.POINTER(ctypes.c_double)),
        ("pose", ctypes.POINTER(ctypes.c_double)),
        ("kind", ctypes.POINTER(ctypes.c_int)),
        ("asphere_offsets", ctypes.POINTER(ctypes.c_int)),
        ("asphere_coeffs", ctypes.POINTER(ctypes.c_double)),
        ("coating_offsets", ctypes.POINTER(ctypes.c_int)),
        ("coating", ctypes.POINTER(ctypes.c_double)),
        ("image_vertex_z", ctypes.c_double),
        ("image_distance_mm", ctypes.c_double),
        ("n_image", ctypes.c_double),
        ("ray_count", ctypes.c_int),
        ("positions", ctypes.POINTER(ctypes.c_double)),
        ("directions", ctypes.POINTER(ctypes.c_double)),
        ("opl", ctypes.POINTER(ctypes.c_double)),
        ("amplitude", ctypes.POINTER(ctypes.c_double)),
        ("power", ctypes.POINTER(ctypes.c_double)),
        ("quadrature", ctypes.POINTER(ctypes.c_double)),
        ("valid", ctypes.POINTER(ctypes.c_ubyte)),
        ("wavelength_nm", ctypes.c_double),
        ("temperature_c", ctypes.c_double),
        ("max_iterations", ctypes.c_int),
        ("evaluate_apertures", ctypes.c_int),
        ("apply_surface_physics", ctypes.c_int),
        ("polarization_sensitive", ctypes.c_int),
        ("propagate_to_image", ctypes.c_int),
        ("thread_count", ctypes.c_int),
        ("progress_cb", _PROGRESS_CB),
        ("progress_userdata", ctypes.c_void_p),
        ("out_final_positions", ctypes.POINTER(ctypes.c_double)),
        ("out_final_directions", ctypes.POINTER(ctypes.c_double)),
        ("out_opl", ctypes.POINTER(ctypes.c_double)),
        ("out_amplitude", ctypes.POINTER(ctypes.c_double)),
        ("out_power", ctypes.POINTER(ctypes.c_double)),
        ("out_quadrature", ctypes.POINTER(ctypes.c_double)),
        ("out_phase", ctypes.POINTER(ctypes.c_double)),
        ("out_polarization", ctypes.POINTER(ctypes.c_double)),
        ("out_valid", ctypes.POINTER(ctypes.c_ubyte)),
        ("out_status", ctypes.POINTER(ctypes.c_int)),
        ("out_reason", ctypes.POINTER(ctypes.c_int)),
        ("out_seg_counts", ctypes.POINTER(ctypes.c_int)),
        ("out_diag_counts", ctypes.POINTER(ctypes.c_int)),
        ("out_surface_points", ctypes.POINTER(ctypes.c_double)),
        ("out_surface_dirs", ctypes.POINTER(ctypes.c_double)),
        ("out_seg_len", ctypes.POINTER(ctypes.c_double)),
        ("out_seg_n", ctypes.POINTER(ctypes.c_double)),
        ("out_seg_opl", ctypes.POINTER(ctypes.c_double)),
        ("out_seg_cum", ctypes.POINTER(ctypes.c_double)),
        ("out_diag", ctypes.POINTER(ctypes.c_double)),
        ("out_path_points", ctypes.POINTER(ctypes.c_double)),
        ("out_path_surface", ctypes.POINTER(ctypes.c_int)),
    ]


_LIBRARY = None
_LIBRARY_ERROR = ""


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    override = os.environ.get("OPTICAL_NATIVE_DLL")
    if override:
        paths.append(Path(override))
    root = Path(__file__).resolve().parents[4]
    dll_name = "optical_native.dll" if os.name == "nt" else "optical_native.so"
    paths.append(root / "native" / "build" / dll_name)
    return paths


def _load_library():
    global _LIBRARY, _LIBRARY_ERROR
    if _LIBRARY is not None:
        return _LIBRARY
    if _LIBRARY_ERROR:
        return None
    for path in _candidate_paths():
        if not path.exists():
            continue
        try:
            library = ctypes.CDLL(str(path))
            library.on_version.restype = ctypes.c_char_p
            library.on_trace.argtypes = [ctypes.POINTER(_ONTraceRequest)]
            library.on_trace.restype = ctypes.c_int
        except OSError as exc:
            _LIBRARY_ERROR = str(exc)
            return None
        _LIBRARY = library
        return _LIBRARY
    _LIBRARY_ERROR = "native optical core library not found"
    return None


def native_available() -> bool:
    return _load_library() is not None


def native_supports(system: SequentialOpticalSystem, options: TraceOptions) -> str | None:
    """Return a fallback reason, or None when the native kernel can run it."""
    if not native_available():
        return "native library not available"
    if options.include_group_delay:
        return "group delay requires the Python coating audit path"
    for surface in system.surfaces:
        if surface.grating_period_um is not None or surface.grating_orders:
            return "gratings require the branching tracer"
    return None


def native_thread_count() -> int:
    value = os.environ.get("OPTICAL_NATIVE_THREADS", "0")
    try:
        count = int(value)
    except ValueError:
        return 0
    return max(0, count)


def _as_f64(values) -> np.ndarray:
    return np.ascontiguousarray(values, dtype=np.float64)


def _plane_record(
    *,
    plane_z_mm: float,
    positions: np.ndarray,
    directions: np.ndarray,
    optical_paths: np.ndarray,
    field_amplitudes: np.ndarray,
    power_weights: np.ndarray,
    quadrature_weights: np.ndarray,
    valid: np.ndarray,
    ray_ids: np.ndarray,
    status_codes: np.ndarray,
    segment_lengths: np.ndarray | None = None,
    refractive_indices: np.ndarray | None = None,
    segment_opl: np.ndarray | None = None,
    cumulative_opl: np.ndarray | None = None,
    phase_offsets_rad: np.ndarray | None = None,
    polarization_vectors_xyz: np.ndarray | None = None,
) -> PlaneTraceData:
    return PlaneTraceData(
        plane_z_mm=float(plane_z_mm),
        positions_mm=np.asarray(positions, dtype=float),
        directions=np.asarray(directions, dtype=float),
        optical_paths_mm=np.asarray(optical_paths, dtype=float),
        field_amplitudes=np.asarray(field_amplitudes, dtype=float),
        power_weights=np.asarray(power_weights, dtype=float),
        quadrature_weights=np.asarray(quadrature_weights, dtype=float),
        valid_mask=np.asarray(valid, dtype=bool),
        ray_ids=np.asarray(ray_ids, dtype=object),
        status_codes=np.asarray(status_codes, dtype=object),
        segment_lengths_mm=None if segment_lengths is None else np.asarray(segment_lengths, dtype=float),
        refractive_indices=None if refractive_indices is None else np.asarray(refractive_indices, dtype=float),
        segment_opl_mm=None if segment_opl is None else np.asarray(segment_opl, dtype=float),
        cumulative_opl_mm=None if cumulative_opl is None else np.asarray(cumulative_opl, dtype=float),
        phase_offsets_rad=phase_offsets_rad,
        polarization_vectors_xyz=polarization_vectors_xyz,
    )


def trace_ray_batch_native(
    system: SequentialOpticalSystem,
    rays: RayBundle,
    options: TraceOptions,
    *,
    progress_callback=None,
) -> TraceBundle:
    library = _load_library()
    if library is None:
        raise NativeTraceError(_LIBRARY_ERROR or "native library not available")

    n = int(rays.positions_mm.shape[0])
    surfaces = list(system.surfaces)
    surface_count = len(surfaces)
    smax = surface_count + 1
    if n == 0:
        raise NativeTraceError("empty ray bundle")

    wavelength_nm = float(options.wavelength_nm or system.wavelength_nm)
    vertices = list(system.surface_vertex_z_positions())

    radius = np.empty(surface_count)
    conic = np.empty(surface_count)
    a2 = np.empty(surface_count)
    vertex_z = np.empty(surface_count)
    n_before = np.empty(surface_count)
    n_after = np.empty(surface_count)
    clear_aperture = np.empty(surface_count)
    absorption = np.empty(surface_count)
    roughness = np.empty(surface_count)
    pose = np.empty(6 * surface_count)
    kind = np.empty(surface_count, dtype=np.int32)
    asphere_list: list[float] = []
    asphere_offsets = np.zeros(surface_count + 1, dtype=np.int32)
    coating_list: list[float] = []
    coating_offsets = np.zeros(surface_count + 1, dtype=np.int32)

    for index, surface in enumerate(surfaces):
        radius[index] = float(surface.radius_mm) if surface.radius_mm is not None else np.inf
        conic[index] = float(surface.conic)
        a2[index] = float(surface.asphere_a2)
        vertex_z[index] = float(vertices[index]) if index < len(vertices) else 0.0
        n_before[index] = system.material_index(surface.material_before, wavelength_nm)
        n_after[index] = system.material_index(surface.material_after, wavelength_nm)
        clear_aperture[index] = (
            float(surface.clear_aperture_mm)
            if surface.clear_aperture_mm is not None
            else np.nan
        )
        absorption[index] = float(surface.surface_absorption_fraction)
        roughness[index] = float(surface.roughness_rms_nm)
        pose[6 * index : 6 * index + 6] = (
            float(surface.decenter_x_mm),
            float(surface.decenter_y_mm),
            float(surface.tilt_x_deg),
            float(surface.tilt_y_deg),
            float(surface.tilt_z_deg),
            float(surface.cylinder_axis_deg),
        )
        kind[index] = 1 if str(surface.surface_type).strip().lower() in _MIRROR_TYPES else 0
        coefficients = [float(v) for v in surface.asphere_coefficients]
        asphere_list.extend(coefficients)
        asphere_offsets[index + 1] = len(asphere_list)
        for layer in surface.coating_layers:
            coating_list.extend(
                (
                    float(layer.refractive_index),
                    float(layer.extinction_coefficient),
                    float(layer.thickness_nm),
                    float(layer.dn_dt_per_c),
                    float(layer.dk_dt_per_c),
                    float(layer.cte_per_c),
                    float(layer.reference_temperature_c),
                )
            )
        coating_offsets[index + 1] = len(coating_list) // 7

    n_image = (
        system.material_index(surfaces[-1].material_after, wavelength_nm)
        if surfaces
        else 1.0
    )

    # 传给 C 的临时数组必须保持存活到 on_trace 返回，先落为局部引用。
    asphere_arr = np.ascontiguousarray(asphere_list, dtype=np.float64) if asphere_list else None
    coating_arr = np.ascontiguousarray(coating_list, dtype=np.float64) if coating_list else None

    positions = _as_f64(rays.positions_mm)
    directions = _as_f64(rays.directions)
    optical_paths = _as_f64(rays.optical_paths_mm)
    amplitudes = _as_f64(rays.field_amplitudes)
    powers = _as_f64(rays.power_weights)
    quadratures = _as_f64(rays.quadrature_weights)
    valid_input = np.ascontiguousarray(rays.valid_mask, dtype=bool)

    out_positions = np.full((n, 3), np.nan)
    out_directions = np.full((n, 3), np.nan)
    out_opl = np.empty(n)
    out_amplitude = np.empty(n)
    out_power = np.empty(n)
    out_quadrature = np.empty(n)
    out_phase = np.empty(n)
    out_polarization = np.empty(6 * n)
    out_valid = np.zeros(n, dtype=np.uint8)
    out_status = np.full(n, -1, dtype=np.int32)
    out_reason = np.full(n, -1, dtype=np.int32)
    out_seg_counts = np.zeros(n, dtype=np.int32)
    out_diag_counts = np.zeros(n, dtype=np.int32)
    out_surface_points = np.full((n, smax, 3), np.nan)
    out_surface_dirs = np.full((n, smax, 3), np.nan)
    out_seg_len = np.full((n, smax), np.nan)
    out_seg_n = np.full((n, smax), np.nan)
    out_seg_opl = np.full((n, smax), np.nan)
    out_seg_cum = np.full((n, smax), np.nan)
    out_diag = np.full((n, smax, _DIAG_COUNT), np.nan)
    out_path_points = np.full((n, smax + 1, 3), np.nan)
    out_path_surface = np.zeros((n, smax + 1), dtype=np.int32)

    @ctypes.CFUNCTYPE(None, ctypes.c_double, ctypes.c_void_p)
    def _progress_proxy(fraction, _userdata):
        if progress_callback is not None:
            try:
                progress_callback(float(fraction))
            except Exception:
                pass

    request = _ONTraceRequest(
        surface_count=surface_count,
        radius_mm=radius.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        conic=conic.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        asphere_a2=a2.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        vertex_z=vertex_z.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        n_before=n_before.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        n_after=n_after.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        clear_aperture=clear_aperture.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        absorption=absorption.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        roughness=roughness.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        pose=pose.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        kind=kind.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
        asphere_offsets=asphere_offsets.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
        asphere_coeffs=(
            asphere_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double))
            if asphere_arr is not None
            else None
        ),
        coating_offsets=coating_offsets.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
        coating=(
            coating_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double))
            if coating_arr is not None
            else None
        ),
        image_vertex_z=float(vertices[-1]) if vertices else 0.0,
        image_distance_mm=float(system.image_distance_mm),
        n_image=float(n_image),
        ray_count=n,
        positions=positions.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        directions=directions.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        opl=optical_paths.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        amplitude=amplitudes.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        power=powers.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        quadrature=quadratures.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        valid=valid_input.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte)),
        wavelength_nm=wavelength_nm,
        temperature_c=float(options.environment_temperature_c),
        max_iterations=int(options.max_intersection_iterations),
        evaluate_apertures=int(bool(options.evaluate_apertures)),
        apply_surface_physics=int(bool(options.apply_surface_physics)),
        polarization_sensitive=int(bool(options.polarization_sensitive)),
        propagate_to_image=int(bool(options.propagate_to_image)),
        thread_count=native_thread_count(),
        progress_cb=_progress_proxy if progress_callback is not None else _PROGRESS_CB(),
        progress_userdata=None,
        out_final_positions=out_positions.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_final_directions=out_directions.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_opl=out_opl.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_amplitude=out_amplitude.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_power=out_power.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_quadrature=out_quadrature.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_phase=out_phase.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_polarization=out_polarization.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_valid=out_valid.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte)),
        out_status=out_status.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
        out_reason=out_reason.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
        out_seg_counts=out_seg_counts.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
        out_diag_counts=out_diag_counts.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
        out_surface_points=out_surface_points.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_surface_dirs=out_surface_dirs.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_seg_len=out_seg_len.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_seg_n=out_seg_n.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_seg_opl=out_seg_opl.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_seg_cum=out_seg_cum.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_diag=out_diag.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_path_points=out_path_points.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        out_path_surface=out_path_surface.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
    )

    if progress_callback is not None:
        try:
            progress_callback(0.0)
        except Exception:
            pass

    code = library.on_trace(ctypes.byref(request))
    if code != 0:
        raise NativeTraceError("native trace failed; falling back")

    out_polarization = out_polarization.reshape(n, 6)
    polarization = np.empty((n, 3), dtype=np.complex128)
    polarization.real = out_polarization[:, :3]
    polarization.imag = out_polarization[:, 3:]

    status_codes = np.array(
        [_STATUS_NAMES[i] if 0 <= i < len(_STATUS_NAMES) else "UNKNOWN" for i in out_status],
        dtype=object,
    )
    reasons = [
        _REASON_NAMES[i] if 0 <= i < len(_REASON_NAMES) else "unknown failure"
        for i in out_reason
    ]
    ray_ids = np.asarray(rays.ray_ids, dtype=object)
    warnings: list[str] = []
    for i, reason in enumerate(reasons):
        if reason:
            warnings.append(f"ray[{i}] {ray_ids[i]}: {reason}")

    max_segments = int(out_seg_counts.max()) if n else 0
    segment_lengths = out_seg_len[:, :max_segments].copy() if max_segments else None
    segment_indices = out_seg_n[:, :max_segments].copy() if max_segments else None
    segment_opl = out_seg_opl[:, :max_segments].copy() if max_segments else None
    cumulative_opl = out_seg_cum[:, :max_segments].copy() if max_segments else None

    path_counts = out_seg_counts + 1
    offsets = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(path_counts, out=offsets[1:])
    total_points = int(offsets[-1]) if n else 0
    path_points = np.empty((total_points, 3), dtype=float)
    path_surface_indices = np.empty(total_points, dtype=np.int32)
    for i in range(n):
        count = int(path_counts[i])
        if count:
            path_points[offsets[i] : offsets[i] + count] = out_path_points[i, :count]
            path_surface_indices[offsets[i] : offsets[i] + count] = out_path_surface[i, :count]

    input_pupil = _plane_record(
        plane_z_mm=float(np.nanmedian(rays.positions_mm[:, 2])) if n else 0.0,
        positions=positions.copy(),
        directions=directions.copy(),
        optical_paths=optical_paths.copy(),
        field_amplitudes=amplitudes.copy(),
        power_weights=powers.copy(),
        quadrature_weights=quadratures.copy(),
        valid=valid_input.copy(),
        ray_ids=ray_ids,
        status_codes=np.where(valid_input, "INPUT_VALID", "INVALID_INPUT"),
        phase_offsets_rad=np.zeros(n),
        polarization_vectors_xyz=polarization.copy(),
    )

    surface_records: dict[str, PlaneTraceData] = {}
    if options.record_surfaces and max_segments:
        record_vertices = list(vertices)
        if options.propagate_to_image and surfaces:
            record_vertices.append(float(vertices[-1] + system.image_distance_mm))
        for segment_index in range(max_segments):
            has_point = out_seg_counts > segment_index
            plane_z = (
                float(record_vertices[segment_index])
                if segment_index < len(record_vertices)
                else float("nan")
            )
            name = (
                "image"
                if segment_index == len(surfaces)
                else f"surface_{segment_index + 1}"
            )
            surface_records[name] = _plane_record(
                plane_z_mm=plane_z,
                positions=out_surface_points[:, segment_index, :],
                directions=out_surface_dirs[:, segment_index, :],
                optical_paths=out_seg_cum[:, segment_index],
                field_amplitudes=out_amplitude,
                power_weights=out_power,
                quadrature_weights=out_quadrature,
                valid=has_point,
                ray_ids=ray_ids,
                status_codes=status_codes,
                segment_lengths=out_seg_len[:, segment_index],
                refractive_indices=out_seg_n[:, segment_index],
                segment_opl=out_seg_opl[:, segment_index],
                cumulative_opl=out_seg_cum[:, segment_index],
                phase_offsets_rad=out_phase,
                polarization_vectors_xyz=polarization,
            )

    surface_interaction_records: list[list[dict[str, Any]]] = [[] for _ in range(n)]
    # Match the existing compact output contract for ordinary uncoated
    # systems. Dataset labels need the computed powers/fields, but creating
    # thousands of Python audit dictionaries adds avoidable overhead.
    # Full output, coatings and posed systems retain all audit records.
    from optical_core.physics.geometric.solvers.compact_batch_raytrace import compact_trace_support
    include_interaction_records = options.output_level == "full" or not compact_trace_support(system, options).supported
    if options.apply_surface_physics and include_interaction_records:
        for i in range(n):
            count = int(out_diag_counts[i])
            if not count:
                continue
            records: list[dict[str, Any]] = []
            for k in range(count):
                surface = surfaces[k]
                diag = out_diag[i, k]
                entry: dict[str, Any] = {"surface_index": int(surface.index)}
                entry["coating_layer_count"] = len(surface.coating_layers)
                for field_index, field_name in enumerate(_DIAG_FIELDS):
                    entry[field_name] = float(diag[field_index])
                entry["polarization_sensitive"] = bool(options.polarization_sensitive)
                entry["polarization_model"] = (
                    "jones" if options.polarization_sensitive else "scalar_unpolarized"
                )
                entry["surface_pose"] = {
                    "decenter_x_mm": float(surface.decenter_x_mm),
                    "decenter_y_mm": float(surface.decenter_y_mm),
                    "tilt_x_deg": float(surface.tilt_x_deg),
                    "tilt_y_deg": float(surface.tilt_y_deg),
                    "tilt_z_deg": float(surface.tilt_z_deg),
                }
                records.append(entry)
            surface_interaction_records[i] = records

    return TraceBundle(
        final_positions_mm=out_positions,
        final_directions=out_directions,
        optical_paths_mm=out_opl,
        field_amplitudes=out_amplitude,
        valid_mask=out_valid.astype(bool),
        power_weights=out_power,
        quadrature_weights=out_quadrature,
        plane_records={"input_pupil": input_pupil},
        surface_records=surface_records,
        warnings=warnings,
        ray_ids=ray_ids,
        pupil_coordinates_normalized=None
        if rays.pupil_coordinates_normalized is None
        else rays.pupil_coordinates_normalized.copy(),
        status_codes=status_codes,
        termination_reasons=reasons,
        path_points_mm=path_points if total_points else np.empty((0, 3)),
        path_offsets=offsets,
        path_surface_indices=path_surface_indices,
        segment_lengths_mm=segment_lengths,
        segment_refractive_indices=segment_indices,
        segment_opl_mm=segment_opl,
        cumulative_opl_mm=cumulative_opl,
        phase_offsets_rad=out_phase,
        polarization_vectors_xyz=polarization,
        surface_interaction_records=surface_interaction_records,
        surface_physics_applied=bool(options.apply_surface_physics),
    )


from __future__ import annotations

from time import perf_counter
from typing import Any, Mapping
import numpy as np

from optical_runtime.dependency_graph import build_project_dependency_keys


def dependency_keys_for_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    project = payload.get("project") if isinstance(payload.get("project"), Mapping) else {}
    options = payload.get("options") if isinstance(payload.get("options"), Mapping) else {}
    return build_project_dependency_keys(project, options)


def receiver_field_preview(
    cached_result: Mapping[str, Any],
    cached_project: Mapping[str, Any],
    new_payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    started = perf_counter()
    metadata = cached_result.get("metadata") if isinstance(cached_result.get("metadata"), Mapping) else {}
    old_keys = metadata.get("frontend_dependency_keys") if isinstance(metadata.get("frontend_dependency_keys"), Mapping) else None
    new_keys = dependency_keys_for_payload(new_payload)
    if old_keys is None and isinstance(metadata.get("dependency_keys"), Mapping):
        backend_keys = metadata.get("dependency_keys")
        if (
            str(backend_keys.get("receiver_field", "")) == str(new_keys.get("receiver_field", ""))
            and str(backend_keys.get("receiver_passive", "")) == str(new_keys.get("receiver_passive", ""))
        ):
            old_keys = backend_keys
    if old_keys is None:
        old_options = metadata.get("frontend_request_options") if isinstance(metadata.get("frontend_request_options"), Mapping) else {}
        old_keys = build_project_dependency_keys(cached_project, old_options)
    if str(old_keys.get("receiver_field", "")) != str(new_keys.get("receiver_field", "")):
        return None
    if str(old_keys.get("receiver_passive", "")) != str(new_keys.get("receiver_passive", "")):
        return None

    project = new_payload.get("project") if isinstance(new_payload.get("project"), Mapping) else {}
    receiver = project.get("receiver") if isinstance(project.get("receiver"), Mapping) else {}
    old_receiver = cached_project.get("receiver") if isinstance(cached_project.get("receiver"), Mapping) else {}
    mode_model = str(receiver.get("mode_model", "gaussian") or "gaussian").lower()
    if mode_model not in {"gaussian", "gaussian_elliptical"}:
        return None
    if abs(float(receiver.get("axial_offset_z_mm", 0.0) or 0.0) - float(old_receiver.get("axial_offset_z_mm", 0.0) or 0.0)) > 1e-15:
        return None

    arrays = cached_result.get("arrays") if isinstance(cached_result.get("arrays"), Mapping) else {}
    x = np.asarray(arrays.get("coupling_grid_x_mm", ()), dtype=float)
    y = np.asarray(arrays.get("coupling_grid_y_mm", ()), dtype=float)
    real = np.asarray(arrays.get("coupling_field_real", arrays.get("propagated_field_real", ())), dtype=float)
    imag = np.asarray(arrays.get("coupling_field_imag", arrays.get("propagated_field_imag", ())), dtype=float)
    if real.ndim == 2 and imag.shape == real.shape:
        field = real + 1j * imag
    else:
        intensity = np.asarray(arrays.get("coupling_field_intensity", ()), dtype=float)
        phase = np.asarray(arrays.get("coupling_field_phase_rad", ()), dtype=float)
        if intensity.ndim != 2 or phase.shape != intensity.shape:
            return None
        field = np.sqrt(np.maximum(intensity, 0.0)) * np.exp(1j * phase)
    if x.ndim != 1 or y.ndim != 1 or field.shape != (y.size, x.size) or x.size < 2 or y.size < 2:
        return None

    wx = max(float(receiver.get("mode_field_diameter_x_um", 0.0) or 0.0) * 0.5e-3, 1e-12)
    wy = max(float(receiver.get("mode_field_diameter_y_um", 0.0) or 0.0) * 0.5e-3, 1e-12)
    ox = float(receiver.get("offset_x_mm", 0.0) or 0.0)
    oy = float(receiver.get("offset_y_mm", 0.0) or 0.0)
    tx = np.deg2rad(float(receiver.get("tilt_x_deg", 0.0) or 0.0))
    ty = np.deg2rad(float(receiver.get("tilt_y_deg", 0.0) or 0.0))
    wavelength_mm = max(float((project.get("source") or {}).get("wavelength_nm", 780.0)) * 1e-6, 1e-12)
    xx, yy = np.meshgrid(x, y, indexing="xy")
    mode = np.exp(-(((xx - ox) / wx) ** 2 + ((yy - oy) / wy) ** 2)).astype(np.complex128)
    if tx or ty:
        mode *= np.exp(1j * (2.0 * np.pi / wavelength_mm) * (xx * tx + yy * ty))

    weight = abs(float(np.mean(np.diff(x))) * float(np.mean(np.diff(y))))
    field_power = float(np.sum(np.abs(field) ** 2) * weight)
    mode_power = float(np.sum(np.abs(mode) ** 2) * weight)
    if field_power <= 0.0 or mode_power <= 0.0:
        return None
    overlap = np.sum(field * np.conjugate(mode)) * weight / np.sqrt(field_power * mode_power)
    eta = float(np.clip(abs(overlap) ** 2, 0.0, 1.0))
    old_metrics = cached_result.get("metrics") if isinstance(cached_result.get("metrics"), Mapping) else {}
    old_eta = float(old_metrics.get("coupling_efficiency", old_metrics.get("mode_overlap_efficiency", 0.0)) or 0.0)
    old_total = float(old_metrics.get("total_coupling_efficiency", old_eta) or old_eta)
    passive_factor = old_total / old_eta if old_eta > 1e-15 else 1.0
    total = float(np.clip(eta * passive_factor, 0.0, 1.0))
    intensity = np.abs(field) ** 2
    mode_intensity = np.abs(mode) ** 2
    stride = max(1, int(np.ceil(max(field.shape) / 129)))
    rows = slice(None, None, stride); cols = slice(None, None, stride)
    return {
        "status": "running",
        "stage": "frontend.compatible_receiver_preview",
        "metrics": {"coupling_efficiency": eta, "mode_overlap_efficiency": eta, "total_coupling_efficiency": total},
        "preview_result": {
            "status": "completed", "converged": True,
            "metrics": {"coupling_efficiency": eta, "mode_overlap_efficiency": eta, "total_coupling_efficiency": total},
            "arrays": {
                "coupling_field_intensity": intensity[rows, cols].astype(np.float32, copy=False),
                "coupling_mode_intensity": mode_intensity[rows, cols].astype(np.float32, copy=False),
                "coupling_grid_x_mm": x[cols], "coupling_grid_y_mm": y[rows],
            },
            "metadata": {
                "preview_only": True,
                "preview_source": "compatible_cached_receiver_field",
                "dependency_keys": new_keys,
                "preview_elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
            },
        },
    }


__all__ = ["dependency_keys_for_payload", "receiver_field_preview"]

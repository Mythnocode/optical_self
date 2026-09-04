
from __future__ import annotations

from dataclasses import dataclass
from math import exp, pi


@dataclass(frozen=True, slots=True)
class InstantEfficiency:
    system: float
    receiver: float
    mode_overlap: float
    total: float
    source: str = "快速 Gaussian 估计"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _surface_transmission(surface) -> float:
    if not bool(getattr(surface, "enabled", True)):
        return 1.0
    coating = str(getattr(surface, "coating", "无") or "无")
    
    
    if "增透" in coating:
        return 0.995
    if "高反" in coating or "金属" in coating:
        return 0.0
    if "自定义" in coating:
        return 0.985
    return 0.98


def _axis_overlap(
    input_radius_um: float,
    target_radius_um: float,
    offset_um: float,
    tilt_urad: float,
    wavelength_nm: float,
    axial_offset_um: float,
) -> float:
    wi = max(abs(float(input_radius_um)), 1e-9)
    wf = max(abs(float(target_radius_um)), 1e-9)
    denom = wi * wi + wf * wf
    size = 2.0 * wi * wf / denom
    lateral = exp(-2.0 * float(offset_um) ** 2 / denom)

    wavelength_um = max(float(wavelength_nm) * 1e-3, 1e-9)
    theta_rad = float(tilt_urad) * 1e-6
    k = 2.0 * pi / wavelength_um
    angular = exp(-0.5 * (k * theta_rad) ** 2 * (wi * wf) ** 2 / denom)

    rayleigh_um = pi * wi * wi / wavelength_um
    axial = 1.0 / (1.0 + (float(axial_offset_um) / max(rayleigh_um, 1e-9)) ** 2) ** 0.5
    return _clamp01(size * lateral * angular * axial)


def estimate_efficiency(
    project,
    form_state,
    *,
    beam_radius_at_receiver_um: tuple[float, float] | None = None,
) -> InstantEfficiency:

    system = 1.0
    for surface in getattr(project, "surfaces", ()):
        system *= _surface_transmission(surface)
    system = _clamp01(system)

    receiver = form_state.receiver
    propagation_loss_db = (
        max(0.0, float(receiver.attenuation_db_per_km))
        * max(0.0, float(receiver.fiber_length_m))
        / 1000.0
        + max(0.0, float(receiver.connector_loss_db))
    )
    receiver_eff = _clamp01(float(receiver.endface_transmission)) * 10.0 ** (
        -propagation_loss_db / 10.0
    )
    receiver_eff = _clamp01(receiver_eff)

    source = form_state.source
    if beam_radius_at_receiver_um is not None:
        beam_x_um, beam_y_um = beam_radius_at_receiver_um
    else:
        beam_x_um = float(source.waist_x_um)
        beam_y_um = float(source.waist_y_um)
    target_x = max(float(receiver.mode_field_diameter_x_um) / 2.0, 1e-9)
    target_y = max(float(receiver.mode_field_diameter_y_um) / 2.0, 1e-9)
    overlap_x = _axis_overlap(
        beam_x_um,
        target_x,
        receiver.offset_x_um,
        receiver.tilt_x_urad,
        source.wavelength_nm,
        receiver.axial_offset_z_um,
    )
    overlap_y = _axis_overlap(
        beam_y_um,
        target_y,
        receiver.offset_y_um,
        receiver.tilt_y_urad,
        source.wavelength_nm,
        receiver.axial_offset_z_um,
    )
    mode_overlap = _clamp01(overlap_x * overlap_y)
    total = _clamp01(system * receiver_eff * mode_overlap)
    return InstantEfficiency(system, receiver_eff, mode_overlap, total)


__all__ = ["InstantEfficiency", "estimate_efficiency"]

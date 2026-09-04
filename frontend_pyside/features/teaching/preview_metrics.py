from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from frontend_pyside.features.simulation.form_state import (
    ReceiverFormState,
    SimulationFormState,
    SourceFormState,
)
from frontend_pyside.features.simulation.instant_metrics import InstantEfficiency, estimate_efficiency


PREVIEW_EFFICIENCY_LABEL = "与仿真预览同公式（预览级）"


@dataclass(frozen=True, slots=True)
class TeachingPreviewEfficiency:
    system: float
    receiver: float
    mode_overlap: float
    total: float
    source: str = PREVIEW_EFFICIENCY_LABEL


class _DictSurface:
    """Minimal surface view for instant_metrics when only payload dicts exist."""

    __slots__ = ("enabled", "coating")

    def __init__(self, data: dict[str, Any]) -> None:
        self.enabled = bool(data.get("enabled", True))
        coating = data.get("coating")
        self.coating = str(coating if coating is not None else "无") or "无"


class _SurfaceListProject:
    __slots__ = ("surfaces",)

    def __init__(self, surfaces: list[Any]) -> None:
        self.surfaces = surfaces


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number


def _workbench_parameter_state(project_context: Any) -> dict[str, Any]:
    try:
        profile = project_context.research_profile
    except Exception:
        return {}
    if not isinstance(profile, dict):
        return {}
    snapshot = profile.get("workbench_snapshot") or profile.get("shared_snapshot") or {}
    if not isinstance(snapshot, dict):
        return {}
    if str(snapshot.get("source", "")) not in {"formal_workbench", "simulation_workbench"}:
        return {}
    parameter_state = snapshot.get("parameter_state")
    return dict(parameter_state) if isinstance(parameter_state, dict) else {}


def _simulation_project_payload(project_context: Any) -> dict[str, Any]:
    try:
        payload = project_context.simulation_project_payload
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def form_state_from_payload(payload: dict[str, Any]) -> SimulationFormState | None:
    """Rebuild SimulationFormState from a published simulation project payload."""
    if not isinstance(payload, dict):
        return None
    source_payload = dict(payload.get("source") or {})
    receiver_payload = dict(payload.get("receiver") or {})
    if not source_payload and not receiver_payload:
        return None

    wavelength_nm = _finite_positive(source_payload.get("wavelength_nm"))
    waist_x_um = _finite_positive(source_payload.get("waist_x_um"))
    if waist_x_um is None and "waist_x_mm" in source_payload:
        waist_x_um = _finite_positive(float(source_payload["waist_x_mm"]) * 1000.0)
    waist_y_um = _finite_positive(source_payload.get("waist_y_um"))
    if waist_y_um is None and "waist_y_mm" in source_payload:
        waist_y_um = _finite_positive(float(source_payload["waist_y_mm"]) * 1000.0)
    if waist_x_um is None:
        waist_x_um = 893.0
    if waist_y_um is None:
        waist_y_um = waist_x_um

    mfd_x = _finite_positive(receiver_payload.get("mode_field_diameter_x_um"))
    mfd_y = _finite_positive(receiver_payload.get("mode_field_diameter_y_um"))
    if mfd_x is None:
        mfd_x = 5.0
    if mfd_y is None:
        mfd_y = mfd_x

    offset_x_um = 0.0
    if "offset_x_um" in receiver_payload:
        offset_x_um = float(receiver_payload.get("offset_x_um", 0.0) or 0.0)
    elif "offset_x_mm" in receiver_payload:
        offset_x_um = float(receiver_payload.get("offset_x_mm", 0.0) or 0.0) * 1000.0

    offset_y_um = 0.0
    if "offset_y_um" in receiver_payload:
        offset_y_um = float(receiver_payload.get("offset_y_um", 0.0) or 0.0)
    elif "offset_y_mm" in receiver_payload:
        offset_y_um = float(receiver_payload.get("offset_y_mm", 0.0) or 0.0) * 1000.0

    axial_offset_z_um = 0.0
    if "axial_offset_z_um" in receiver_payload:
        axial_offset_z_um = float(receiver_payload.get("axial_offset_z_um", 0.0) or 0.0)
    elif "axial_offset_z_mm" in receiver_payload:
        axial_offset_z_um = float(receiver_payload.get("axial_offset_z_mm", 0.0) or 0.0) * 1000.0

    tilt_x_urad = 0.0
    if "tilt_x_urad" in receiver_payload:
        tilt_x_urad = float(receiver_payload.get("tilt_x_urad", 0.0) or 0.0)
    elif "tilt_x_deg" in receiver_payload:
        tilt_x_urad = math.radians(float(receiver_payload.get("tilt_x_deg", 0.0) or 0.0)) * 1.0e6

    tilt_y_urad = 0.0
    if "tilt_y_urad" in receiver_payload:
        tilt_y_urad = float(receiver_payload.get("tilt_y_urad", 0.0) or 0.0)
    elif "tilt_y_deg" in receiver_payload:
        tilt_y_urad = math.radians(float(receiver_payload.get("tilt_y_deg", 0.0) or 0.0)) * 1.0e6

    source = SourceFormState(
        source_type=str(source_payload.get("source_type", "gaussian") or "gaussian"),
        wavelength_nm=float(wavelength_nm or 780.0),
        waist_x_um=float(waist_x_um),
        waist_y_um=float(waist_y_um),
        waist_position_mm=float(source_payload.get("waist_position_x_mm", source_payload.get("waist_position_mm", 0.0)) or 0.0),
        beam_quality_m2_x=float(source_payload.get("beam_quality_m2_x", source_payload.get("beam_quality_m2", 1.0)) or 1.0),
        beam_quality_m2_y=float(source_payload.get("beam_quality_m2_y", source_payload.get("beam_quality_m2", 1.0)) or 1.0),
        object_na_x=float(source_payload.get("object_na_x", 0.0) or 0.0),
        object_na_y=float(source_payload.get("object_na_y", 0.0) or 0.0),
        field_x_deg=math.degrees(float(source_payload.get("axis_tilt_x_rad", 0.0) or 0.0)),
        field_y_deg=math.degrees(float(source_payload.get("axis_tilt_y_rad", 0.0) or 0.0)),
    )
    receiver = ReceiverFormState(
        receiver_type=str(receiver_payload.get("receiver_type", "single_mode_fiber") or "single_mode_fiber"),
        mode_model=str(receiver_payload.get("mode_model", "gaussian") or "gaussian"),
        mode_field_diameter_x_um=float(mfd_x),
        mode_field_diameter_y_um=float(mfd_y),
        core_diameter_um=float(receiver_payload.get("core_diameter_um", 3.0) or 3.0),
        na_x=float(receiver_payload.get("na_x", 0.13) or 0.13),
        na_y=float(receiver_payload.get("na_y", receiver_payload.get("na_x", 0.13)) or 0.13),
        offset_x_um=offset_x_um,
        offset_y_um=offset_y_um,
        axial_offset_z_um=axial_offset_z_um,
        tilt_x_urad=tilt_x_urad,
        tilt_y_urad=tilt_y_urad,
        endface_transmission=float(receiver_payload.get("endface_transmission", 0.995) or 0.995),
        fiber_length_m=float(receiver_payload.get("fiber_length_m", 0.0) or 0.0),
        attenuation_db_per_km=float(receiver_payload.get("attenuation_db_per_km", 0.0) or 0.0),
        connector_loss_db=float(receiver_payload.get("connector_loss_db", 0.0) or 0.0),
    )
    return SimulationFormState(source=source, receiver=receiver)


def form_state_from_parameter_state(parameter_state: dict[str, Any]) -> SimulationFormState | None:
    if not isinstance(parameter_state, dict):
        return None
    source_payload = dict(parameter_state.get("source") or {})
    receiver_payload = dict(parameter_state.get("receiver") or {})
    if not source_payload and not receiver_payload:
        return None
    return form_state_from_payload({"source": source_payload, "receiver": receiver_payload})


def resolve_preview_surfaces(project_context: Any) -> Any:
    """Prefer shared simulation payload surfaces, then the live project snapshot."""
    project = getattr(project_context, "project", None)
    if project is not None:
        surfaces = list(getattr(project, "surfaces", []) or [])
        if surfaces:
            return project
    payload = _simulation_project_payload(project_context)
    raw = list(payload.get("surfaces") or [])
    if raw:
        converted = [
            item if not isinstance(item, dict) else _DictSurface(item)
            for item in raw
        ]
        return _SurfaceListProject(converted)
    return project


def _resolve_base_form_state(model: Any, project_context: Any | None) -> SimulationFormState:
    if project_context is not None:
        payload_state = form_state_from_payload(_simulation_project_payload(project_context))
        if payload_state is not None:
            return payload_state
        parameter_state = form_state_from_parameter_state(_workbench_parameter_state(project_context))
        if parameter_state is not None:
            return parameter_state

    state = model.beam_state()
    fiber = next((node for node in model.nodes.values() if node.kind == "fiber"), None)
    fiber_params = dict(fiber.params) if fiber is not None else {}
    mfd_um = max(0.4, float(model.receiver_mode_radius_um) * 2.0)
    return SimulationFormState(
        source=SourceFormState(
            wavelength_nm=float(model.wavelength_nm),
            waist_x_um=max(float(state["waist_x_um"]), 1e-9),
            waist_y_um=max(float(state["waist_y_um"]), 1e-9),
        ),
        receiver=ReceiverFormState(
            mode_field_diameter_x_um=mfd_um,
            mode_field_diameter_y_um=mfd_um,
            offset_x_um=float(fiber_params.get("offset_x_um", 0.0)),
            offset_y_um=float(fiber_params.get("offset_y_um", 0.0)),
            axial_offset_z_um=float(fiber_params.get("offset_z_um", 0.0)),
            tilt_x_urad=float(fiber_params.get("pitch_mrad", 0.0)) * 1000.0,
            tilt_y_urad=float(fiber_params.get("yaw_mrad", 0.0)) * 1000.0,
            na_x=float(model.receiver_na),
            na_y=float(model.receiver_na),
        ),
    )


def _overlay_teaching_alignment(model: Any, form_state: SimulationFormState) -> SimulationFormState:
    fiber = next((node for node in model.nodes.values() if node.kind == "fiber"), None)
    if fiber is None:
        return form_state
    fiber_params = dict(fiber.params)
    receiver = replace(
        form_state.receiver,
        offset_x_um=float(fiber_params.get("offset_x_um", form_state.receiver.offset_x_um)),
        offset_y_um=float(fiber_params.get("offset_y_um", form_state.receiver.offset_y_um)),
        axial_offset_z_um=float(fiber_params.get("offset_z_um", form_state.receiver.axial_offset_z_um)),
        tilt_x_urad=float(fiber_params.get("pitch_mrad", 0.0)) * 1000.0,
        tilt_y_urad=float(fiber_params.get("yaw_mrad", 0.0)) * 1000.0,
    )
    source = replace(
        form_state.source,
        wavelength_nm=float(model.wavelength_nm),
    )
    return replace(form_state, source=source, receiver=receiver)


def receiver_beam_radius_um(model: Any, project_context: Any | None) -> tuple[float, float]:
    """Beam 1/e² radius at the receiver plane used for Gaussian overlap."""
    state = model.beam_state()
    plane_x = _finite_positive(state.get("plane_radius_x_um"))
    plane_y = _finite_positive(state.get("plane_radius_y_um"))
    if plane_x is not None and plane_y is not None:
        return plane_x, plane_y

    if project_context is not None:
        project = getattr(project_context, "project", None)
        metrics = dict(getattr(project, "metrics", {}) or {}) if project is not None else {}
        rms_x = _finite_positive(metrics.get("coupling_field_rms_x_um"))
        rms_y = _finite_positive(metrics.get("coupling_field_rms_y_um"))
        if rms_x is not None and rms_y is not None:
            return rms_x, rms_y
        rms = _finite_positive(metrics.get("coupling_field_rms_radius_um"))
        if rms is not None:
            return rms, rms

    waist_x = _finite_positive(state.get("waist_x_um")) or 1e-9
    waist_y = _finite_positive(state.get("waist_y_um")) or waist_x
    return waist_x, waist_y


def beam_radius_from_project_metrics(project: Any) -> tuple[float, float] | None:
    metrics = dict(getattr(project, "metrics", {}) or {})
    rms_x = _finite_positive(metrics.get("coupling_field_rms_x_um"))
    rms_y = _finite_positive(metrics.get("coupling_field_rms_y_um"))
    if rms_x is not None and rms_y is not None:
        return rms_x, rms_y
    rms = _finite_positive(metrics.get("coupling_field_rms_radius_um"))
    if rms is not None:
        return rms, rms
    return None


def teaching_to_preview_form_state(model: Any, project_context: Any | None = None) -> SimulationFormState:
    """Map the teaching scene graph to the same form state used by simulation preview."""
    base = _resolve_base_form_state(model, project_context)
    return _overlay_teaching_alignment(model, base)


def estimate_teaching_preview_efficiency(
    model: Any,
    project_context: Any | None,
) -> TeachingPreviewEfficiency | None:
    """Return preview-level coupling efficiency using simulation instant_metrics."""
    path = model.shortest_path("fiber")
    if not path:
        return None
    if project_context is None:
        return None
    preview_project = resolve_preview_surfaces(project_context)
    if preview_project is None:
        return None
    form_state = teaching_to_preview_form_state(model, project_context)
    beam_radius = receiver_beam_radius_um(model, project_context)
    result: InstantEfficiency = estimate_efficiency(
        preview_project,
        form_state,
        beam_radius_at_receiver_um=beam_radius,
    )
    return TeachingPreviewEfficiency(
        system=result.system,
        receiver=result.receiver,
        mode_overlap=result.mode_overlap,
        total=result.total,
        source=PREVIEW_EFFICIENCY_LABEL,
    )


__all__ = [
    "PREVIEW_EFFICIENCY_LABEL",
    "TeachingPreviewEfficiency",
    "estimate_teaching_preview_efficiency",
    "form_state_from_payload",
    "beam_radius_from_project_metrics",
    "receiver_beam_radius_um",
    "resolve_preview_surfaces",
    "teaching_to_preview_form_state",
]

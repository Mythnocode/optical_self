from __future__ import annotations

from dataclasses import replace

import pytest

from frontend_pyside.core.types import LensSurface, ProjectSnapshot
from frontend_pyside.features.simulation.form_state import ReceiverFormState, SimulationFormState
from frontend_pyside.features.simulation.payloads import build_simulation_payload
from frontend_pyside.presets.demo_780nm_four_lens import (
    DEFAULT_RECEIVER_MFD_UM,
    DEFAULT_WAVELENGTH_NM,
    FOUR_LENS_SURFACES,
    PROJECT_NAME,
)
from optical_runtime import create_optical_simulation_engine
from optical_runtime.request_compiler import compile_simulation_context
from optical_runtime.hybrid_pipeline import _tilt_rad_from_options
from shared_contracts.simulation import SimulationRequest


def _project() -> ProjectSnapshot:
    return ProjectSnapshot(
        name=PROJECT_NAME,
        wavelength_nm=DEFAULT_WAVELENGTH_NM,
        receiver_mfd_um=DEFAULT_RECEIVER_MFD_UM,
        surfaces=[LensSurface(**dict(item)) for item in FOUR_LENS_SURFACES],
    )


def _request_from_gui_tilt_mrad(tilt_mrad: float) -> SimulationRequest:
    state = SimulationFormState(
        receiver=replace(ReceiverFormState(), tilt_x_urad=float(tilt_mrad) * 1000.0)
    )
    payload = build_simulation_payload(
        _project(), state, request_id=f"gui-tilt-{tilt_mrad:g}", random_seed=42
    )
    payload["precision"] = "preview"
    return SimulationRequest.model_validate(payload)


def test_formal_coupling_accepts_gui_serialized_degree_tilt():
    request = _request_from_gui_tilt_mrad(20.0)
    context = compile_simulation_context(request)
    options = context.scene.options["hybrid"]
    # GUI/API project serialization is in degrees.
    assert options["tilt_x_deg"] == pytest.approx(20e-3 * 180.0 / 3.141592653589793)
    # The formal coupling path must convert that degree field back to radians.
    assert _tilt_rad_from_options(options, "tilt_x") == pytest.approx(20e-3)


def test_runtime_tilt_unit_precedence_and_conversion():
    assert _tilt_rad_from_options({"tilt_x_deg": 180.0}, "tilt_x") == pytest.approx(3.141592653589793)
    assert _tilt_rad_from_options({"tilt_x_mrad": 20.0}, "tilt_x") == pytest.approx(20e-3)
    assert _tilt_rad_from_options({"tilt_x_urad": 20_000.0}, "tilt_x") == pytest.approx(20e-3)
    assert _tilt_rad_from_options({"tilt_x_rad": 0.02}, "tilt_x") == pytest.approx(0.02)
    # Explicit runtime radians win over the project-level GUI degree value.
    assert _tilt_rad_from_options({"tilt_x_rad": 0.03, "tilt_x_deg": 90.0}, "tilt_x") == pytest.approx(0.03)


def test_gui_tilt_changes_formal_coupling_monotonically_for_demo_system():
    engine = create_optical_simulation_engine()
    efficiencies = []
    for tilt_mrad in (0.0, 20.0, 40.0, 80.0, 120.0):
        result = engine.evaluate(_request_from_gui_tilt_mrad(tilt_mrad), None, None)
        assert result.status == "completed"
        efficiencies.append(float(result.metrics["coupling_efficiency"]))
    assert efficiencies == sorted(efficiencies, reverse=True)
    assert efficiencies[0] > efficiencies[-1] + 0.2


def test_manual_same_pitch_propagation_flags_under_resolved_single_mode_grid():
    state = SimulationFormState(
        receiver=replace(ReceiverFormState(), tilt_x_urad=80_000.0),
    )
    state = replace(
        state,
        calculation=replace(
            state.calculation,
            propagation_model="band_limited_angular_spectrum",
            analyses=("coupling",),
            only_visible_results=False,
        ),
    )
    payload = build_simulation_payload(
        _project(), state, request_id="manual-under-resolved-mode", random_seed=42
    )
    result = create_optical_simulation_engine().evaluate(
        SimulationRequest.model_validate(payload), None, None
    )
    assert result.status == "completed"
    assert result.metrics["coupling_mode_sampling_pass"] is False
    assert result.metrics["coupling_mode_sampling_points_per_radius_x"] < 1.0
    assert any("under-resolved" in warning for warning in result.warnings)

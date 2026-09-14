from __future__ import annotations

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.explainability.actions import formula_binding_for_feature
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.features.simulation.payloads import build_simulation_payload
from frontend_pyside.presets.demo_780nm_four_lens import REFERENCE_TOTAL_COUPLING_EFFICIENCY
from frontend_pyside.state.project_context import default_project
from optical_runtime import create_optical_simulation_engine
from shared_contracts.simulation import SimulationRequest


def test_780nm_four_asphere_demo_is_a_real_high_total_coupling_prescription() -> None:
    project = default_project()
    serialized = serialize_project(project, SimulationFormState())
    assert all(surface["coating_layers"] for surface in serialized["surfaces"])

    payload = build_simulation_payload(project, SimulationFormState(), request_id="high-coupling-demo")
    result = create_optical_simulation_engine().evaluate(SimulationRequest.model_validate(payload))

    assert result.status == "completed", result.errors
    assert result.metrics["total_coupling_efficiency"] > 0.90
    assert abs(result.metrics["total_coupling_efficiency"] - REFERENCE_TOTAL_COUPLING_EFFICIENCY) < 1.0e-10


def test_structure_features_have_physical_formula_bindings() -> None:
    assert formula_binding_for_feature("surfaces[0].radius_mm")[:2] == ("结构参数", "曲率半径")
    assert formula_binding_for_feature("surfaces[1].thickness_mm")[:2] == ("结构参数", "厚度与间隔")
    assert formula_binding_for_feature("surfaces[0].conic")[:2] == ("结构参数", "圆锥系数")

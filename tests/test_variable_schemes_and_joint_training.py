from __future__ import annotations

from machine_learning.datasets.variable_schemes import resolve_lens_bindings, resolve_variable_scheme
from frontend_pyside.features.machine_learning.dataset_configuration import build_dataset_parameters
from shared_contracts.training import JointTrainingRequest


def _four_lens_project() -> dict:
    surfaces = []
    for index in range(4):
        surfaces.extend([
            {
                "surface_type": "refractive",
                "radius_mm": 10.0 + index,
                "distance_to_next_mm": 3.0 + index,
                "material_before": "AIR",
                "material_after": "N-BK7",
                "clear_aperture_mm": 2.0,
                "conic": -0.1 * index,
            },
            {
                "surface_type": "refractive",
                "radius_mm": -(12.0 + index),
                "distance_to_next_mm": 5.0,
                "material_before": "N-BK7",
                "material_after": "AIR",
                "clear_aperture_mm": 2.0,
                "conic": -0.2 * index,
            },
        ])
    return {"surfaces": surfaces}


def test_presets_resolve_only_effective_surface_variables():
    project = _four_lens_project()
    assert len(resolve_lens_bindings(project)) == 4
    for count in range(1, 5):
        basic = resolve_variable_scheme(project, lens_count=count, include_conic=False)
        asphere = resolve_variable_scheme(project, lens_count=count, include_conic=True)
        assert len(basic.design_variable_paths) == 3 * count
        assert len(asphere.design_variable_paths) == 5 * count


def test_planar_back_surfaces_are_not_fake_design_variables():
    from frontend_pyside.state.project_context import default_project
    from frontend_pyside.api.payloads import serialize_project

    project = serialize_project(default_project())
    scheme = resolve_variable_scheme(project, lens_count=4, include_conic=True)
    assert len(scheme.design_variable_paths) == 12
    assert not any("surfaces[1].radius_mm" in path for path in scheme.design_variable_paths)
    assert not any("surfaces[1].conic" in path for path in scheme.design_variable_paths)


def test_thickness_uses_solid_segment_not_following_air_gap():
    project = _four_lens_project()
    scheme = resolve_variable_scheme(project, lens_count=1, include_conic=False)
    assert "surfaces[0].distance_to_next_mm" in scheme.design_variable_paths
    assert "surfaces[1].distance_to_next_mm" not in scheme.design_variable_paths


def test_explicit_scheme_builds_radius_thickness_and_conic_parameters():
    project = _four_lens_project()
    scheme = resolve_variable_scheme(project, lens_count=2, include_conic=True)
    parameters = build_dataset_parameters(project, explicit_paths=scheme.design_variable_paths)
    assert [row["path"] for row in parameters] == list(scheme.design_variable_paths)
    assert len(parameters) == 10
    assert {row["unit"] for row in parameters} == {"mm", "1"}


def test_joint_training_contract_keeps_model_parameters_separate():
    request = JointTrainingRequest(
        dataset_id="dataset-example",
        random_forest_hyperparameters={"n_estimators": 200},
        xgboost_hyperparameters={"learning_rate": 0.05},
    )
    assert request.random_forest_hyperparameters["n_estimators"] == 200
    assert request.xgboost_hyperparameters["learning_rate"] == 0.05

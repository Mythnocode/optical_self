from __future__ import annotations

from pathlib import Path

import pytest

from frontend_pyside.features.explainability.actions import diagnosis_confidence
from frontend_pyside.features.teaching.applicability import (
    evaluate_scene_applicability,
    lens_prescription,
)
from frontend_pyside.features.teaching.experiment_scene import build_ray_mapping
from frontend_pyside.features.teaching.formal_physics import build_scene_project
from frontend_pyside.features.teaching.spatial_routing_upgrade import (
    FlexibleSpatialExperimentModel,
    FlexibleSpatialGraphicsView,
    FlexibleSpatialTeachingWorkbench,
)


def _lm135c_model() -> FlexibleSpatialExperimentModel:
    model = FlexibleSpatialExperimentModel()
    model.load_layout_preset("lm135c_four_lens_benchmark")
    return model


def test_lm135c_benchmark_compiles_with_explicit_measurement_contract():
    model = _lm135c_model()
    report = evaluate_scene_applicability(model)
    assert report.allowed
    assert report.wavelength_nm == pytest.approx(780.0)
    assert "相机测量" in report.coupling_mode
    assert report.prescription_source == "焦距推导近似"

    compiled = build_scene_project(model)
    assert compiled is not None
    project, image_distance_mm = compiled
    assert project.wavelength_nm == pytest.approx(780.0)
    assert len(project.surfaces) == 8
    assert image_distance_mm == pytest.approx(17.5)
    assert all("处方来源" in surface.note for surface in project.surfaces)

    camera = next(node for node in model.nodes.values() if node.kind == "imaging_camera")
    reading = model.instrument_reading(camera.id)
    assert reading["valid"]
    assert reading["radius_x_1e2_um"] == pytest.approx(2.0 * reading["rms_x_um"])
    assert reading["radius_y_1e2_um"] == pytest.approx(2.0 * reading["rms_y_um"])
    assert reading["radial_rms_um"] == pytest.approx(
        ((reading["rms_x_um"] ** 2 + reading["rms_y_um"] ** 2) / 2.0) ** 0.5
    )
    assert reading["fit_residual"] is None
    assert model.scene_snapshot().efficiency_status == "not_applicable"


def test_formal_trace_is_blocked_by_wavelength_and_mechanical_errors():
    model = _lm135c_model()
    first_lens = next(node for node in model.nodes.values() if node.kind == "lens")
    first_lens.params["coating_max_nm"] = 700.0
    first_lens.params["air_gap_after_mm"] = 0.0
    model.mark_changed()
    report = evaluate_scene_applicability(model)
    assert not report.allowed
    codes = {item.code for item in report.issues if item.level == "error"}
    assert {"coating_band", "mechanical_overlap"} <= codes
    assert build_scene_project(model) is None


def test_mount_flip_uses_the_reversed_surface_prescription():
    model = _lm135c_model()
    lens = next(node for node in model.nodes.values() if node.kind == "lens")
    lens.params.update({
        "front_radius_mm": 25.0,
        "back_radius_mm": -80.0,
        "front_conic": -1.0,
        "back_conic": -0.25,
        "reversed": True,
    })
    prescription = lens_prescription(lens)
    assert prescription["explicit"]
    assert prescription["front_radius_mm"] == pytest.approx(80.0)
    assert prescription["back_radius_mm"] == pytest.approx(-25.0)
    assert prescription["front_conic"] == pytest.approx(-0.25)
    assert prescription["back_conic"] == pytest.approx(-1.0)


def test_formal_ray_mapping_aligns_physical_spacing_with_semantic_scene_icons():
    model = _lm135c_model()
    mapping = build_ray_mapping(model, (((0.0, 0.0, 0.0), (0.0, 0.0, 64.5)),))
    assert mapping is not None
    lenses = sorted((node for node in model.nodes.values() if node.kind == "lens"), key=lambda item: item.x)
    # L1 thickness 3 mm + 7.5 mm air gap puts the next front surface at z=10.5 mm.
    assert mapping.scene_x(10.5) == pytest.approx(lenses[1].x)
    assert mapping.formal_z(lenses[1].x) == pytest.approx(10.5)


def test_shap_reliability_gate_rejects_small_samples_low_r2_and_ood():
    assert diagnosis_confidence({"sample_count": 5, "model_test_r2": 0.95})[0] == "仅探索"
    assert diagnosis_confidence({"sample_count": 100, "model_test_r2": 0.4})[0] == "仅探索"
    assert diagnosis_confidence({"sample_count": 100, "model_test_r2": 0.9, "within_training_domain": False})[0] == "较低"
    confidence, _note = diagnosis_confidence({
        "sample_count": 100,
        "model_test_r2": 0.9,
        "within_training_domain": True,
        "additivity_error": 0.0,
        "targets": [{"sample_shap_values": [{"formal_value": 0.8}]}],
    })
    assert confidence == "较高"


def test_workbench_uses_class_factories_instead_of_global_monkeypatching():
    assert FlexibleSpatialTeachingWorkbench.model_class is FlexibleSpatialExperimentModel
    assert FlexibleSpatialTeachingWorkbench.graphics_view_class is FlexibleSpatialGraphicsView


def test_quick3d_source_keeps_topology_out_of_physical_rays_and_supports_drop():
    root = Path(__file__).resolve().parents[1]
    py_source = (root / "frontend_pyside/features/teaching/unified_quick3d.py").read_text(encoding="utf-8")
    qml_source = (root / "frontend_pyside/resources/qml/unified_teaching_scene_3d.qml").read_text(encoding="utf-8")
    assert "routed_receiver_world_ray" not in py_source
    assert "formal_rays_world_3d" in py_source
    assert "DropArea" in qml_source
    assert "application/x-optical-teaching-component" in qml_source
    assert '["搭建", "观察", "测量", "分析"]' in qml_source

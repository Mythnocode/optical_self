from __future__ import annotations

import json
from pathlib import Path

from scipy.stats import spearmanr

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.state.project_context import default_project
from tools.build_demo_assets import _video_research_options

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = ROOT / "resources" / "demo_assets" / "quick_real_780nm"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_video_demo_preset_matches_recording_system() -> None:
    project = serialize_project(default_project(), SimulationFormState())
    source = project["source"]
    receiver = project["receiver"]
    assert source["wavelength_nm"] == 780.0
    assert source["waist_x_mm"] == 0.893
    assert source["waist_y_mm"] == 1.05
    assert source["beam_quality_m2_x"] == 3.05
    assert source["beam_quality_m2_y"] == 1.33
    assert receiver["mode_field_diameter_x_um"] == 5.0
    assert receiver["mode_field_diameter_y_um"] == 5.0
    assert receiver["na_x"] == 0.13
    assert receiver["endface_transmission"] == 0.995
    assert abs(project["object_distance_mm"] - 18.18244) < 5e-6
    assert abs(project["image_distance_mm"] - 8.97373) < 5e-6
    assert project["pupil_radius_mm"] == 3.0


def test_video_research_options_match_formal_scaled_fresnel_and_do_not_override_design_variables() -> None:
    options = _video_research_options()
    hybrid = options["hybrid"]
    assert hybrid["grid_size"] == 257
    assert hybrid["pupil_sample_count"] == 49
    assert hybrid["propagation_model"] == "scaled_fresnel"
    assert hybrid["zero_padding_factor"] == 2.0
    assert hybrid["output_extent_x_mm"] == 0.024
    assert hybrid["output_extent_y_mm"] == 0.024
    dumped = json.dumps(options, ensure_ascii=False)
    assert "receiver.offset_x_mm" not in dumped
    assert "receiver.axial_offset_z_mm" not in dumped


def test_packaged_video_demo_assets_are_self_consistent() -> None:
    bundle = _load(BUNDLE_DIR / "bundle.json")
    assert bundle["bundle_id"] == "video_demo_780nm_xz_v1"
    assert bundle["dataset_sample_count"] == 139
    assert bundle["sampling_design"] == "128 LHS + 11 formal axial anchors"
    assert bundle["models"] == ["model-63d9d3ea55cf"]
    assert bundle["model_test_metrics"]["r2"] >= 0.90
    ref = bundle["video_flow_reference"]
    assert abs(ref["z0_total_coupling"] - 0.6752702256655362) < 1e-12
    assert abs(ref["z30um_total_coupling"] - 0.5362384844001704) < 1e-12
    assert abs(ref["ml_inverse_target_90_formal_result"] - 0.9001606505980989) < 1e-12

    model_id = bundle["models"][0]
    model_manifest = _load(BUNDLE_DIR / "models" / model_id / "manifest.json")
    assert model_manifest["feature_paths"] == [
        "receiver.offset_x_mm",
        "receiver.axial_offset_z_mm",
    ]
    assert model_manifest["target_names"] == ["coupling_efficiency"]
    assert model_manifest["test_metrics"]["r2"] >= 0.90


def test_packaged_shap_has_physically_expected_xz_direction() -> None:
    bundle = _load(BUNDLE_DIR / "bundle.json")
    shap_files = list((BUNDLE_DIR / "shap").glob("*.json"))
    assert len(shap_files) == 1
    data = _load(shap_files[0])
    top = data["top_features"]
    assert [row["feature"] for row in top[:2]] == [
        "receiver.axial_offset_z_mm",
        "receiver.offset_x_mm",
    ]
    assert top[0]["physical_category"] == "焦面与曲率失配"
    assert top[1]["physical_category"] == "中心位置失配"

    samples = data["targets"][0]["sample_shap_values"]
    for feature, expected_limit in (
        ("receiver.offset_x_mm", -0.85),
        ("receiver.axial_offset_z_mm", -0.75),
    ):
        absolute_parameter = [abs(float(row["feature_values"][feature])) for row in samples]
        contribution = [float(row["shap_values"][feature]) for row in samples]
        rho, p_value = spearmanr(absolute_parameter, contribution)
        assert rho < expected_limit
        assert p_value < 1e-12

    physics = bundle["shap_physics_check"]
    assert physics["spearman_abs_x_vs_shap"] < -0.90
    assert physics["spearman_abs_z_vs_shap"] < -0.80

from __future__ import annotations

from optical_runtime.dependency_graph import build_project_dependency_keys


def test_native_gui_tilt_unit_is_part_of_overlap_dependency_key():
    project = {
        "source": {"wavelength_nm": 780.0},
        "receiver": {"tilt_x_deg": 0.0, "tilt_y_deg": 0.0},
        "surfaces": [],
    }
    key0 = build_project_dependency_keys(project, {"hybrid": {"tilt_x_urad": 0.0}})["overlap"]
    key20 = build_project_dependency_keys(project, {"hybrid": {"tilt_x_urad": 20_000.0}})["overlap"]
    assert key0 != key20


def test_research_tasks_inherit_automatic_scaled_fresnel_numerics():
    from frontend_pyside.features.optimization.numerics import research_simulation_numerics

    precision, options = research_simulation_numerics({
        "automatic": True,
        "precision": "257×257",
        "grid_size": 65,
        "pupil_sample_count": 17,
        "propagation": "带限角谱",
        "padding": 1.0,
        "extent_mm": 1.0,
        "sampling_convergence": True,
    })
    hybrid = options["hybrid"]
    assert precision == "standard"
    assert hybrid["grid_size"] == 257
    assert hybrid["pupil_sample_count"] == 49
    assert hybrid["propagation_model"] == "scaled_fresnel"
    assert hybrid["output_extent_x_mm"] == 0.024
    assert hybrid["output_extent_y_mm"] == 0.024
    assert hybrid["zero_padding_factor"] == 2.0


def test_research_tasks_preserve_explicit_manual_numerics():
    from frontend_pyside.features.optimization.numerics import research_simulation_numerics

    precision, options = research_simulation_numerics({
        "automatic": False,
        "precision": "513×513",
        "grid_size": 513,
        "pupil_sample_count": 65,
        "propagation": "带限角谱",
        "padding": 3.0,
        "extent_mm": 0.032,
        "sampling_convergence": False,
    })
    hybrid = options["hybrid"]
    assert precision == "high"
    assert hybrid["grid_size"] == 513
    assert hybrid["propagation_model"] == "band_limited_angular_spectrum"
    assert hybrid["output_extent_x_mm"] == 0.032
    assert hybrid["zero_padding_factor"] == 3.0
    assert hybrid["sampling_convergence_enabled"] is False

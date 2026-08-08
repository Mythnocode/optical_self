from __future__ import annotations


def base_project() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "frontend-demo",
        "surfaces": [
            {
                "index": 0,
                "surface_type": "spherical",
                "radius_mm": 50.0,
                "distance_to_next_mm": 5.0,
                "material_before": "AIR",
                "material_after": "N-BK7",
                "clear_aperture_mm": 10.0,
                "conic": 0.0,
                "asphere_coefficients": [],
            },
            {
                "index": 1,
                "surface_type": "spherical",
                "radius_mm": -50.0,
                "distance_to_next_mm": 0.0,
                "material_before": "N-BK7",
                "material_after": "AIR",
                "clear_aperture_mm": 10.0,
                "conic": 0.0,
                "asphere_coefficients": [],
            },
        ],
        "object_distance_mm": 100.0,
        "image_distance_mm": 50.0,
        "pupil_radius_mm": 5.0,
        "source": {"wavelength_nm": 550.0},
        "receiver": {
            "na_y": 0.1,
            "na_z": 0.1,
            "mode_field_diameter_y_um": 10.0,
            "mode_field_diameter_z_um": 10.0,
            "offset_y_mm": 0.0,
            "offset_z_mm": 0.0,
            "axial_offset_mm": 0.0,
            "tilt_y_deg": 0.0,
            "tilt_z_deg": 0.0,
        },
        "fingerprint": "frontend-demo-fp",
    }


def simulation_payload(analysis: str) -> dict:
    return {
        "schema_version": "1.0",
        "request_id": f"frontend-simulation-{analysis}",
        "project": base_project(),
        "analyses": [analysis],
        "parameter_changes": [],
        "precision": "preview",
        "random_seed": 42,
        "engine": "headless",
        "options": _analysis_options(analysis),
    }


def dataset_payload(sample_count: int, lower_bound: float, upper_bound: float) -> dict:
    return {
        "dataset_name": "frontend-dataset",
        "base_project": base_project(),
        "parameters": [
            {
                "name": "receiver offset y",
                "path": "receiver.offset_y_mm",
                "unit": "mm",
                "lower_bound": lower_bound,
                "upper_bound": upper_bound,
                "distribution": "uniform",
            }
        ],
        "targets": ["coupling_efficiency"],
        "sample_count": sample_count,
        "sampling_method": "uniform",
        "train_ratio": 0.6,
        "validation_ratio": 0.2,
        "test_ratio": 0.2,
        "random_seed": 42,
        "precision": "preview",
        "engine": "headless",
    }


def _analysis_options(analysis: str) -> dict:
    if analysis in {"diffraction", "psf", "mtf"}:
        return {
            "wave": {
                "wavelength_nm": 532.0,
                "grid_size": 65,
                "extent_mm": 1.0,
                "propagation_distance_mm": 100.0,
                "aperture_diameter_mm": 0.3,
            }
        }
    if analysis == "coupling":
        return {
            "hybrid": {
                "wavelength_nm": 550.0,
                "pupil_sample_count": 25,
                "grid_size": 65,
                "mode_field_diameter_y_um": 10.0,
                "mode_field_diameter_z_um": 10.0,
                "include_breakdown": True,
            }
        }
    return {}

from __future__ import annotations

import csv

from backend.optical_ml_app.application.dataset_registry_service import DatasetRegistryService
from machine_learning.datasets.storage import FileDatasetStore
from machine_learning.features.coupling_physics import PHYSICS_RESIDUAL_FEATURE_PATHS


def test_external_import_normalizes_legacy_paths_and_publishes_closed_loop_metadata(tmp_path):
    columns = [
        "sample_id",
        "surface.0.radius_mm",
        *PHYSICS_RESIDUAL_FEATURE_PATHS,
        "coupling_efficiency",
    ]
    source = tmp_path / "exported_samples.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for index in range(3):
            row = {
                "sample_id": f"sample-{index}",
                "surface.0.radius_mm": 10.0 + index,
                "coupling_efficiency": 0.8 - index * 0.01,
            }
            row.update({path: 0.1 + index for path in PHYSICS_RESIDUAL_FEATURE_PATHS})
            writer.writerow(row)

    registry = DatasetRegistryService(FileDatasetStore(tmp_path / "datasets"))
    entry = registry.import_tabular_file(
        str(source),
        dataset_name="exported_samples.csv",
        target_name="coupling_efficiency",
    )
    manifest = FileDatasetStore(tmp_path / "datasets").load_manifest(entry.dataset_id)

    assert "surfaces[0].radius_mm" in manifest.feature_paths
    assert "surface.0.radius_mm" not in manifest.feature_paths
    assert manifest.design_variable_paths == ["surfaces[0].radius_mm"]
    assert set(manifest.physics_feature_paths) == set(PHYSICS_RESIDUAL_FEATURE_PATHS)
    assert manifest.metadata["closed_loop_compatible"] is True
